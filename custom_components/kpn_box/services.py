"""Actions (services) for settings that don't fit an entity: Wi-Fi setup, schedules, rules, LAN, system."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import time as dtime
import ipaddress
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .api import KPNBoxError
from .const import (
    DAYS,
    DOMAIN,
    PMF_MODES,
    PROTOCOL_CODES,
    SECURITY_MODES,
    WIFI_NETWORKS,
)
from .coordinator import KPNBoxCoordinator

ENTRY = vol.Optional("config_entry_id")
MAC = vol.All(cv.string, vol.Match(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$"), lambda v: v.upper())
IPV4 = vol.All(cv.string, lambda v: str(ipaddress.IPv4Address(v)))
IPV6 = vol.All(cv.string, lambda v: str(ipaddress.IPv6Address(v)))
PORT = vol.All(vol.Coerce(str), vol.Match(r"^\d{1,5}(-\d{1,5})?$"))
PROTOCOL = vol.All(vol.Lower, vol.In(PROTOCOL_CODES))
BLOCKS = vol.All(
    cv.ensure_list,
    [
        vol.Schema(
            {
                vol.Required("days"): vol.All(cv.ensure_list, [vol.All(vol.Lower, vol.In(DAYS))]),
                vol.Required("start"): cv.time,
                vol.Required("end"): cv.time,
            }
        )
    ],
)


def _schema(fields: dict) -> vol.Schema:
    return vol.Schema({**fields, ENTRY: cv.string})


def week_ranges(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn [{days, start, end}] into the scheduler's weekly ranges (seconds from Monday 00:00).

    A block whose end is before its start runs past midnight into the next day.
    """

    def secs(t: dtime) -> int:
        return t.hour * 3600 + t.minute * 60

    week = 7 * 86400
    ranges: list[tuple[int, int]] = []
    for block in blocks:
        start, end = secs(block["start"]), secs(block["end"]) or 86400
        for day in dict.fromkeys(block["days"]):
            base = DAYS.index(day) * 86400
            if end > start:
                ranges.append((base + start, base + end))
            else:  # overnight
                ranges.append((base + start, base + 86400))
                nxt = (base + 86400) % week
                ranges.append((nxt, nxt + end))
    return [{"state": "Disable", "begin": b, "end": e} for b, e in sorted(ranges)]


def _prefix_len(mask: str) -> int:
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> KPNBoxCoordinator:
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and call.data.get("config_entry_id", e.entry_id) == e.entry_id
    ]
    if not entries:
        raise ServiceValidationError("No loaded KPN Box found")
    return entries[0].runtime_data


def async_setup_services(hass: HomeAssistant) -> None:
    def run(fn: Callable[[KPNBoxCoordinator, dict[str, Any]], Awaitable[None]]):
        async def handler(call: ServiceCall) -> None:
            c = _coordinator(hass, call)
            await c.async_run(fn(c, call.data))

        return handler

    # --- diagnostics ---------------------------------------------------------

    async def ping(call: ServiceCall) -> ServiceResponse:
        try:
            r = await _coordinator(hass, call).api.ping(call.data["host"], call.data["ip_version"])
        except KPNBoxError as err:
            raise HomeAssistantError(f"Ping failed: {err}") from err
        return {
            "state": r.get("DiagnosticsState"),
            "host": r.get("ipHost"),
            "packets_received": r.get("packetsSuccess"),
            "packets_lost": r.get("packetsFailed"),
            "avg_ms": r.get("averageResponseTime"),
            "min_ms": r.get("minimumResponseTime"),
            "max_ms": r.get("maximumResponseTime"),
        }

    hass.services.async_register(
        DOMAIN,
        "ping",
        ping,
        supports_response=SupportsResponse.ONLY,
        schema=_schema(
            {vol.Required("host"): cv.string, vol.Optional("ip_version", default="IPv4"): vol.In(["IPv4", "IPv6"])}
        ),
    )

    # --- Wi-Fi ---------------------------------------------------------------

    async def set_wifi_network(c: KPNBoxCoordinator, d: dict) -> None:
        vaps = WIFI_NETWORKS[d["network"]]
        if d["network"] == "guest":
            enable = any(v.get("VAPStatus") == "Up" for v in c.data.guest_vaps.values())
        elif d["network"].startswith("extra"):
            enable = c.data.private_vaps.get(vaps[0], {}).get("VAPStatus") == "Up"
        else:
            enable = None
        await c.api.set_wifi_network(vaps, d["ssid"], d["password"], d["security"], d["pmf"], enable)

    async def set_wifi_schedule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_schedule("WLAN", "wl0", week_ranges(d["off_periods"]))

    async def clear_wifi_schedule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.remove_schedule("WLAN", "wl0")

    async def set_mac_filter(c: KPNBoxCoordinator, d: dict) -> None:
        if d["enabled"] and not d["allowed_macs"]:
            raise ServiceValidationError("An empty allow-list would lock every device out of Wi-Fi")
        vaps = tuple(v for v in ("vap2g0priv", "vap5g0priv", "vap2g0ext", "vap5g0ext") if v in c.data.private_vaps)
        await c.api.set_mac_filter(vaps, d["enabled"], d["allowed_macs"])

    hass.services.async_register(
        DOMAIN,
        "set_wifi_network",
        run(set_wifi_network),
        schema=_schema(
            {
                vol.Required("network"): vol.In(list(WIFI_NETWORKS)),
                vol.Required("ssid"): vol.All(cv.string, vol.Length(min=1, max=32)),
                vol.Required("password"): vol.All(cv.string, vol.Length(min=8, max=63)),
                vol.Optional("security", default="WPA2-WPA3-Personal"): vol.In(SECURITY_MODES),
                vol.Optional("pmf", default="Optional"): vol.In(PMF_MODES),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, "set_wifi_schedule", run(set_wifi_schedule), schema=_schema({vol.Required("off_periods"): BLOCKS})
    )
    hass.services.async_register(DOMAIN, "clear_wifi_schedule", run(clear_wifi_schedule), schema=_schema({}))
    hass.services.async_register(
        DOMAIN,
        "set_mac_filter",
        run(set_mac_filter),
        schema=_schema(
            {
                vol.Required("enabled"): cv.boolean,
                vol.Optional("allowed_macs", default=[]): vol.All(cv.ensure_list, [MAC]),
            }
        ),
    )

    # --- devices -------------------------------------------------------------

    async def set_device_schedule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_schedule("ToD", d["mac"], week_ranges(d["blocked_periods"]))

    async def clear_device_schedule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.remove_schedule("ToD", d["mac"])

    async def rename_device(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.rename_device(d["mac"], d["name"])

    async def set_device_type(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_device_type(d["mac"], d["type"])

    async def remove_device(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.remove_device(d["mac"])

    async def add_static_lease(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.add_static_lease(d["mac"], d["ip_address"])

    async def remove_static_lease(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.delete_static_lease(d["mac"])

    hass.services.async_register(
        DOMAIN,
        "set_device_schedule",
        run(set_device_schedule),
        schema=_schema({vol.Required("mac"): MAC, vol.Required("blocked_periods"): BLOCKS}),
    )
    hass.services.async_register(
        DOMAIN, "clear_device_schedule", run(clear_device_schedule), schema=_schema({vol.Required("mac"): MAC})
    )
    hass.services.async_register(
        DOMAIN,
        "rename_device",
        run(rename_device),
        schema=_schema({vol.Required("mac"): MAC, vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=64))}),
    )
    hass.services.async_register(
        DOMAIN,
        "set_device_type",
        run(set_device_type),
        schema=_schema({vol.Required("mac"): MAC, vol.Required("type"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "remove_device", run(remove_device), schema=_schema({vol.Required("mac"): MAC})
    )
    hass.services.async_register(
        DOMAIN,
        "add_static_lease",
        run(add_static_lease),
        schema=_schema({vol.Required("mac"): MAC, vol.Required("ip_address"): IPV4}),
    )
    hass.services.async_register(
        DOMAIN, "remove_static_lease", run(remove_static_lease), schema=_schema({vol.Required("mac"): MAC})
    )

    # --- port forwarding, pinholes, firewall, DMZ ----------------------------

    async def add_port_forward(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.add_port_forward(
            d["name"],
            d["external_port"],
            d.get("internal_port") or d["external_port"],
            d["ip_address"],
            PROTOCOL_CODES[d["protocol"]],
            d["enabled"],
            d.get("source_prefix", ""),
        )

    async def remove_port_forward(c: KPNBoxCoordinator, d: dict) -> None:
        rule_id = d["name"] if d["name"] in c.data.port_forwards else f"webui_{d['name']}"
        rule = c.data.port_forwards.get(rule_id)
        if rule is None:
            raise ServiceValidationError(f"No port forward named {d['name']}")
        await c.api.delete_port_forward(rule_id, rule.get("DestinationIPAddress", ""))

    async def add_ipv6_pinhole(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.add_pinhole(d["name"], d["port"], d["ip_address"], PROTOCOL_CODES[d["protocol"]], d["enabled"])

    async def remove_ipv6_pinhole(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.delete_pinhole(d["id"])

    async def add_firewall_rule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_custom_rule(
            d["id"],
            d["chain"],
            d["action"],
            d.get("destination_port", ""),
            d.get("source_port", ""),
            d.get("destination", ""),
            d.get("source", ""),
            PROTOCOL_CODES[d["protocol"]],
            d["ip_version"],
            d["enabled"],
        )

    async def remove_firewall_rule(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.delete_custom_rule(d["id"], d["chain"])

    async def set_firewall_policy(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_chain_policy(d["chain"], d["policy"])

    async def set_dmz(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_dmz(d["ip_address"])

    async def clear_dmz(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.clear_dmz()

    hass.services.async_register(
        DOMAIN,
        "add_port_forward",
        run(add_port_forward),
        schema=_schema(
            {
                vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=64)),
                vol.Required("external_port"): PORT,
                vol.Optional("internal_port"): PORT,
                vol.Required("ip_address"): IPV4,
                vol.Optional("protocol", default="tcp"): PROTOCOL,
                vol.Optional("enabled", default=True): cv.boolean,
                vol.Optional("source_prefix", default=""): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, "remove_port_forward", run(remove_port_forward), schema=_schema({vol.Required("name"): cv.string})
    )
    hass.services.async_register(
        DOMAIN,
        "add_ipv6_pinhole",
        run(add_ipv6_pinhole),
        schema=_schema(
            {
                vol.Required("name"): cv.string,
                vol.Required("port"): PORT,
                vol.Required("ip_address"): IPV6,
                vol.Optional("protocol", default="tcp"): PROTOCOL,
                vol.Optional("enabled", default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, "remove_ipv6_pinhole", run(remove_ipv6_pinhole), schema=_schema({vol.Required("id"): cv.string})
    )
    hass.services.async_register(
        DOMAIN,
        "add_firewall_rule",
        run(add_firewall_rule),
        schema=_schema(
            {
                vol.Required("id"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_-]+$")),
                vol.Optional("chain", default="Custom"): vol.In(["Custom", "Custom_V6Out"]),
                vol.Optional("action", default="Accept"): vol.In(["Accept", "Drop", "Reject"]),
                vol.Optional("protocol", default="tcp"): PROTOCOL,
                vol.Optional("destination_port", default=""): vol.Any("", PORT),
                vol.Optional("source_port", default=""): vol.Any("", PORT),
                vol.Optional("destination", default=""): cv.string,
                vol.Optional("source", default=""): cv.string,
                vol.Optional("ip_version", default=4): vol.All(vol.Coerce(int), vol.In([4, 6])),
                vol.Optional("enabled", default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "remove_firewall_rule",
        run(remove_firewall_rule),
        schema=_schema(
            {
                vol.Required("id"): cv.string,
                vol.Optional("chain", default="Custom"): vol.In(["Custom", "Custom_V6Out"]),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_firewall_policy",
        run(set_firewall_policy),
        schema=_schema(
            {
                vol.Required("chain"): cv.string,
                vol.Required("policy"): vol.In(["Accept", "Drop", "Reject"]),
            }
        ),
    )
    hass.services.async_register(DOMAIN, "set_dmz", run(set_dmz), schema=_schema({vol.Required("ip_address"): IPV4}))
    hass.services.async_register(DOMAIN, "clear_dmz", run(clear_dmz), schema=_schema({}))

    # --- LAN / DNS / DynDNS --------------------------------------------------

    async def set_lan(c: KPNBoxCoordinator, d: dict) -> None:
        cur = c.data.dhcp
        if not cur:
            raise ServiceValidationError("Current LAN settings unknown; try again after the next update")
        mask = d.get("subnet_mask", cur.get("SubnetMask", "255.255.255.0"))
        dns = d.get("dns_servers")
        settings = {
            "Address": d.get("router_ip", cur.get("IPRouters")),
            "PrefixLength": str(_prefix_len(mask)),
            "DHCPEnable": d.get("dhcp_enabled", bool(cur.get("Enable"))),
            "DHCPMinAddress": d.get("dhcp_start", cur.get("MinAddress")),
            "DHCPMaxAddress": d.get("dhcp_end", cur.get("MaxAddress")),
            "LeaseTime": str(d.get("lease_time", cur.get("LeaseTime"))),
            "DHCPAuthoritative": str(d.get("authoritative", bool(cur.get("Authoritative")))).lower(),
            "DNSServers": ",".join(dns) if dns is not None else cur.get("DNSServers", ""),
        }
        await c.api.set_lan_ipv4("lan", settings)
        if "router_ip" in d and d["router_ip"] != c.config_entry.data[CONF_HOST]:
            # The box moves; follow it (this reloads the integration)
            hass.config_entries.async_update_entry(
                c.config_entry, data={**c.config_entry.data, CONF_HOST: d["router_ip"]}
            )

    async def set_guest_lan(c: KPNBoxCoordinator, d: dict) -> None:
        cur = c.data.guest_dhcp
        if not cur:
            raise ServiceValidationError("Current guest network settings unknown")
        mask = d.get("subnet_mask", cur.get("SubnetMask", "255.255.255.0"))
        dns = d.get("dns_servers")
        settings = {
            "Address": d.get("router_ip", cur.get("IPRouters")),
            "PrefixLength": str(_prefix_len(mask)),
            "DHCPMinAddress": d.get("dhcp_start", cur.get("MinAddress")),
            "DHCPMaxAddress": d.get("dhcp_end", cur.get("MaxAddress")),
            "DHCPEnable": str(d.get("dhcp_enabled", bool(cur.get("Enable")))).lower(),
            "LeaseTime": str(d.get("lease_time", cur.get("LeaseTime"))),
            "DNSServers": ",".join(dns) if dns is not None else cur.get("DNSServers", ""),
        }
        await c.api.set_lan_ipv4("guest", settings)

    async def set_hostname(c: KPNBoxCoordinator, d: dict) -> None:
        if "hostname" in d:
            await c.api.set_hostname(d["hostname"])
        if "domain" in d:
            await c.api.set_domain(d["domain"])

    async def add_dyndns(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.dyndns_add(d["service"], d["hostname"], d["username"], d["password"])

    async def remove_dyndns(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.dyndns_delete(d["hostname"])

    async def set_dyndns_enabled(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.dyndns_enable(d["enabled"])

    lan_fields = {
        vol.Optional("router_ip"): IPV4,
        vol.Optional("subnet_mask"): IPV4,
        vol.Optional("dhcp_enabled"): cv.boolean,
        vol.Optional("dhcp_start"): IPV4,
        vol.Optional("dhcp_end"): IPV4,
        vol.Optional("lease_time"): vol.All(vol.Coerce(int), vol.Range(min=120)),
        vol.Optional("dns_servers"): vol.All(cv.ensure_list, [IPV4]),
    }
    hass.services.async_register(
        DOMAIN, "set_lan", run(set_lan), schema=_schema({**lan_fields, vol.Optional("authoritative"): cv.boolean})
    )
    hass.services.async_register(DOMAIN, "set_guest_lan", run(set_guest_lan), schema=_schema(lan_fields))
    hass.services.async_register(
        DOMAIN,
        "set_hostname",
        run(set_hostname),
        schema=vol.All(
            _schema(
                {
                    vol.Optional("hostname"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9-]{1,63}$")),
                    vol.Optional("domain"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9.-]{1,253}$")),
                }
            ),
            cv.has_at_least_one_key("hostname", "domain"),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "add_dyndns_host",
        run(add_dyndns),
        schema=_schema(
            {
                vol.Required("service"): cv.string,
                vol.Required("hostname"): cv.string,
                vol.Required("username"): cv.string,
                vol.Required("password"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, "remove_dyndns_host", run(remove_dyndns), schema=_schema({vol.Required("hostname"): cv.string})
    )
    hass.services.async_register(
        DOMAIN, "set_dyndns_enabled", run(set_dyndns_enabled), schema=_schema({vol.Required("enabled"): cv.boolean})
    )

    # --- system --------------------------------------------------------------

    async def change_admin_password(call: ServiceCall) -> None:
        c = _coordinator(hass, call)
        if call.data["current_password"] != c.config_entry.data[CONF_PASSWORD]:
            raise ServiceValidationError("Current password doesn't match the one this integration uses")
        await c.async_run(c.api.change_admin_password(call.data["current_password"], call.data["new_password"]))
        # Keep logging in after the change (this reloads the integration)
        hass.config_entries.async_update_entry(
            c.config_entry, data={**c.config_entry.data, CONF_PASSWORD: call.data["new_password"]}
        )

    async def factory_reset(call: ServiceCall) -> None:
        if call.data["confirm"] != "factory reset":
            raise ServiceValidationError('Type "factory reset" in confirm to reset the KPN Box')
        try:
            await _coordinator(hass, call).api.factory_reset()
        except KPNBoxError:
            pass  # the box goes down right away

    def confirmed(call: ServiceCall, phrase: str) -> None:
        if call.data["confirm"] != phrase:
            raise ServiceValidationError(f'Type "{phrase}" in confirm to do this')

    async def start_password_recovery(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        await coordinator.async_run(coordinator.api.start_password_recovery())

    async def reset_admin_password(call: ServiceCall) -> None:
        confirmed(call, "reset password")
        # After this the integration can't log in until you enter the new password (reauth)
        await _coordinator(hass, call).api.reset_admin_password()

    async def set_wan_mode(call: ServiceCall) -> None:
        confirmed(call, "change wan mode")
        coordinator = _coordinator(hass, call)
        if coordinator.data.wan_modes and call.data["mode"] not in coordinator.data.wan_modes:
            raise ServiceValidationError(f"Mode must be one of {', '.join(coordinator.data.wan_modes)}")
        await coordinator.async_run(
            coordinator.api.set_wan_mode(
                call.data["mode"], call.data.get("username", ""), call.data.get("password", "")
            )
        )

    async def shutdown(call: ServiceCall) -> None:
        confirmed(call, "shut down")
        try:
            await _coordinator(hass, call).api.shutdown()
        except KPNBoxError:
            pass  # goes down right away; it has to be switched on by hand

    hass.services.async_register(DOMAIN, "start_password_recovery", start_password_recovery, schema=_schema({}))
    hass.services.async_register(
        DOMAIN, "reset_admin_password", reset_admin_password, schema=_schema({vol.Required("confirm"): cv.string})
    )
    hass.services.async_register(
        DOMAIN,
        "set_wan_mode",
        set_wan_mode,
        schema=_schema(
            {
                vol.Required("mode"): cv.string,
                vol.Optional("username"): cv.string,
                vol.Optional("password"): cv.string,
                vol.Required("confirm"): cv.string,
            }
        ),
    )
    hass.services.async_register(DOMAIN, "shutdown", shutdown, schema=_schema({vol.Required("confirm"): cv.string}))

    # --- telephone -------------------------------------------------------------

    async def set_phone_line(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_phone_line(
            d["trunk"],
            d["line"],
            d["number"],
            d["username"],
            d["password"],
            d["registrar"],
            d.get("outbound_proxy", ""),
            d.get("domain", ""),
        )

    async def clear_phone_line(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.clear_phone_line(d["trunk"], d["line"])

    async def set_incoming_phones(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_incoming_phones(d["group"], d["handsets"])

    async def set_outgoing_line(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_outgoing_line(d["handset"], d.get("number", ""), d["line"])

    trunk = {vol.Optional("trunk", default="SIP-Trunk1"): cv.string, vol.Optional("line", default="LINE11"): cv.string}
    hass.services.async_register(
        DOMAIN,
        "set_phone_line",
        run(set_phone_line),
        schema=_schema(
            {
                **trunk,
                vol.Required("number"): cv.string,
                vol.Required("username"): cv.string,
                vol.Required("password"): cv.string,
                vol.Required("registrar"): cv.string,
                vol.Optional("outbound_proxy"): cv.string,
                vol.Optional("domain"): cv.string,
            }
        ),
    )
    hass.services.async_register(DOMAIN, "clear_phone_line", run(clear_phone_line), schema=_schema(trunk))
    hass.services.async_register(
        DOMAIN,
        "set_incoming_phones",
        run(set_incoming_phones),
        schema=_schema(
            {
                vol.Optional("group", default="Group1"): cv.string,
                vol.Required("handsets"): vol.All(cv.ensure_list, [cv.string]),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_outgoing_line",
        run(set_outgoing_line),
        schema=_schema(
            {
                vol.Required("handset"): cv.string,
                vol.Required("line"): cv.string,
                vol.Optional("number"): cv.string,
            }
        ),
    )

    async def set_ipv6_delegation_length(c: KPNBoxCoordinator, d: dict) -> None:
        await c.api.set_ipv6_delegation_length("lan" if d["network"] == "home" else "guest", d["length"])

    hass.services.async_register(
        DOMAIN,
        "set_ipv6_delegation_length",
        run(set_ipv6_delegation_length),
        schema=_schema(
            {
                vol.Optional("network", default="home"): vol.In(["home", "guest"]),
                vol.Required("length"): vol.All(vol.Coerce(int), vol.Range(min=48, max=64)),
            }
        ),
    )

    # --- generic: anything the box exposes -------------------------------------

    async def raw_call(call: ServiceCall) -> ServiceResponse:
        c = _coordinator(hass, call)
        try:
            result = await c.api.call(call.data["service"], call.data["method"], call.data.get("parameters") or {})
        except KPNBoxError as err:
            raise HomeAssistantError(f"{call.data['service']}.{call.data['method']} failed: {err}") from err
        await c.async_request_refresh()
        return {"status": result.get("status"), "data": result.get("data")}

    async def describe(call: ServiceCall) -> ServiceResponse:
        try:
            return await _coordinator(hass, call).api.describe(call.data["object"])
        except KPNBoxError as err:
            raise HomeAssistantError(f"describe {call.data['object']} failed: {err}") from err

    hass.services.async_register(
        DOMAIN,
        "call",
        raw_call,
        supports_response=SupportsResponse.ONLY,
        schema=_schema(
            {
                vol.Required("service"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_.:${}-]+$")),
                vol.Required("method"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_]+$")),
                vol.Optional("parameters"): dict,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "describe",
        describe,
        supports_response=SupportsResponse.ONLY,
        schema=_schema({vol.Required("object"): vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_.-]+$"))}),
    )

    hass.services.async_register(
        DOMAIN,
        "change_admin_password",
        change_admin_password,
        schema=_schema(
            {
                vol.Required("current_password"): cv.string,
                vol.Required("new_password"): vol.All(cv.string, vol.Length(min=8)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, "factory_reset", factory_reset, schema=_schema({vol.Required("confirm"): cv.string})
    )
