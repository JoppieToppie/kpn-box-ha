"""Async client for the KPN Box (prpl/SoftAtHome) sysbus API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import RATES_WITH_11B, RATES_WITHOUT_11B

CONTENT_TYPE = "application/x-sah-ws-4-call+json"
ERROR_PERMISSION_DENIED = 13
ERROR_NOT_FOUND = 196618


class KPNBoxError(Exception):
    """Generic API error."""


class KPNBoxAuthError(KPNBoxError):
    """Login rejected."""


class KPNBoxNotFound(KPNBoxError):
    """Object or method does not exist on this firmware."""


class KPNBoxApi:
    """Minimal client: one session context, re-login when it expires."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        timeout: int = 15,
    ) -> None:
        self._session = session
        self._url = f"http://{host}/ws/NeMo/Intf/lan:getMIBs"
        self._username = username
        self._password = password
        self._timeout = timeout
        self._context: str | None = None
        self._cookie: str | None = None
        self._lock = asyncio.Lock()

    async def _post(
        self, body: dict[str, Any], headers: dict[str, str], timeout: int | None = None
    ) -> tuple[dict, str | None]:
        try:
            async with asyncio.timeout(timeout or self._timeout):
                resp = await self._session.post(self._url, json=body, headers={"Content-Type": CONTENT_TYPE, **headers})
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise KPNBoxError(f"Request to KPN Box failed: {err}") from err
        # The box sets an "<etag>/sessid" cookie that aiohttp's jar rejects; pass it on by hand
        set_cookie = resp.headers.get("Set-Cookie")
        return data, set_cookie.split(";")[0] if set_cookie else None

    async def login(self) -> None:
        data, cookie = await self._post(
            {
                "service": "sah.Device.Information",
                "method": "createContext",
                "parameters": {
                    "applicationName": "webui",
                    "username": self._username,
                    "password": self._password,
                },
            },
            {"Authorization": "X-Sah-Login"},
        )
        context = (data.get("data") or {}).get("contextID")
        if data.get("status") != 0 or not context:
            raise KPNBoxAuthError(f"Login rejected: {data}")
        self._context, self._cookie = context, cookie

    async def logout(self) -> None:
        if not self._context:
            return
        headers = {"Authorization": f"X-Sah-Logout {self._context}"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        try:
            await self._post(
                {
                    "service": "sah.Device.Information",
                    "method": "releaseContext",
                    "parameters": {"applicationName": "webui"},
                },
                headers,
            )
        except KPNBoxError:
            pass
        self._context = self._cookie = None

    async def call(self, service: str, method: str, parameters: dict | None = None) -> dict[str, Any]:
        """Call a sysbus method, logging in (again) when needed."""
        async with self._lock:
            for attempt in range(2):
                if not self._context:
                    await self.login()
                headers = {"Authorization": f"X-Sah {self._context}", "X-Context": self._context}
                if self._cookie:
                    headers["Cookie"] = self._cookie
                data, _ = await self._post(
                    {"service": service, "method": method, "parameters": parameters or {}}, headers
                )
                errors = data.get("errors") or []
                codes = {e.get("error") for e in errors}
                if ERROR_PERMISSION_DENIED in codes and attempt == 0:
                    self._context = None  # context expired, log in again
                    continue
                if ERROR_NOT_FOUND in codes:
                    raise KPNBoxNotFound(f"{service}.{method}: {errors}")
                if errors:
                    raise KPNBoxError(f"{service}.{method}: {errors}")
                return data
        raise KPNBoxError(f"{service}.{method}: permission denied after re-login")

    # --- reads -------------------------------------------------------------

    async def device_info(self) -> dict[str, Any]:
        return (await self.call("DeviceInfo", "get")).get("status") or {}

    async def net_dev_stats(self, intf: str) -> dict[str, Any]:
        return (await self.call(f"NeMo.Intf.{intf}", "getNetDevStats")).get("status") or {}

    async def wan_status(self) -> dict[str, Any]:
        return (await self.call("NMC", "getWANStatus")).get("data") or {}

    async def wifi_status(self) -> dict[str, Any]:
        return (await self.call("NMC.Wifi", "get")).get("status") or {}

    async def radio(self, radio: str) -> dict[str, Any]:
        return (await self.call(f"NeMo.Intf.{radio}", "get")).get("status") or {}

    async def guest_vaps(self) -> dict[str, Any]:
        res = await self.call(
            "NeMo.Intf.brguest",
            "getMIBs",
            {"mibs": "wlanvap", "flag": "!backhaul", "traverse": "one level down"},
        )
        return ((res.get("status") or {}).get("wlanvap")) or {}

    async def guest_settings(self) -> dict[str, Any]:
        return (await self.call("NMC.Guest", "get")).get("status") or {}

    async def guest_timer(self) -> Any:
        return (await self.call("NMC.WlanTimer", "getActivationTimer", {"InterfaceName": "guest"})).get("status")

    async def devices(self, expression: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
        return (await self.call("Devices", "get", {"expression": expression})).get("status") or {}

    async def firewall_level(self) -> str | None:
        return (await self.call("Firewall", "getFirewallLevel")).get("status")

    async def leds(self) -> dict[str, Any]:
        return (await self.call("LEDs.LED", "get")).get("status") or {}

    async def latest_firmware(self) -> dict[str, Any]:
        return (await self.call("WebuiupgradeService", "getLatestVersion")).get("data") or {}

    async def schedules(self, kind: str) -> list[dict[str, Any]]:
        """kind: "ToD" (per-device internet access) or "WLAN" (Wi-Fi on/off schedule)."""
        res = await self.call("Scheduler", "getCompleteSchedules", {"type": kind})
        return ((res.get("data") or {}).get("scheduleInfo")) or []

    async def port_forwards(self, origin: str) -> dict[str, dict[str, Any]]:
        return (await self.call("Firewall", "getPortForwarding", {"origin": origin})).get("status") or {}

    async def pinholes(self) -> dict[str, dict[str, Any]]:
        return (await self.call("Firewall", "getPinhole")).get("status") or {}

    async def dmz(self) -> dict[str, dict[str, Any]]:
        return (await self.call("Firewall", "getDMZ")).get("status") or {}

    async def wps(self, vap: str) -> dict[str, Any]:
        return (await self.call(f"NeMo.Intf.{vap}.WPS", "get")).get("status") or {}

    async def private_vaps(self) -> dict[str, Any]:
        res = await self.call("NeMo.Intf.lan", "getMIBs", {"mibs": "wlanvap", "flag": "!backhaul"})
        return ((res.get("status") or {}).get("wlanvap")) or {}

    async def ping(self, host: str, ip_version: str = "IPv4") -> dict[str, Any]:
        res = await self.call("IPPingDiagnostics", "execDiagnostic", {"ipHost": host, "ProtocolVersion": ip_version})
        return res.get("status") or {}

    # --- writes (same calls as the KPN web UI) ------------------------------

    async def set_wifi(self, enable: bool) -> None:
        await self.call("NMC.Wifi", "set", {"Enable": enable})
        for radio, vap, _ in RADIO_LIST:
            await self.set_radio(radio, vap, enable)

    async def set_radio(self, radio: str, vap: str, enable: bool) -> None:
        await self.call(f"NeMo.Intf.{radio}", "set", {"Enable": enable})
        if enable:
            await self.call(f"NeMo.Intf.{vap}", "set", {"PersistentEnable": True})

    async def set_guest_wifi(self, enable: bool, vaps: tuple[str, ...]) -> None:
        state = {"Enable": enable, "PersistentEnable": enable, "Status": enable}
        await self.call("NeMo.Intf.lan", "setWLANConfig", {"mibs": {"penable": {vap: state for vap in vaps}}})

    async def set_guest_time_limit(self, hours: int) -> None:
        if hours:
            await self.call("NMC.WlanTimer", "setActivationTimer", {"Timeout": hours, "InterfaceName": "guest"})
        else:
            await self.call("NMC.WlanTimer", "disableActivationTimer", {"InterfaceName": "guest"})

    async def set_channel(self, radio: str, channel: int | None, bandwidth: str, standards: str) -> None:
        """channel=None selects automatic channel selection."""
        cfg: dict[str, Any] = {
            "AutoChannelEnable": channel is None,
            "OperatingChannelBandwidth": bandwidth,
            "OperatingStandards": standards,
        }
        if channel is not None:
            cfg["Channel"] = channel
        await self.call(f"NeMo.Intf.{radio}", "setWLANConfig", {"mibs": {"wlanradio": {radio: cfg}}})

    async def set_firewall_level(self, level: str) -> None:
        await self.call("Firewall", "setFirewallLevel", {"level": level})
        await self.call("Firewall", "setFirewallIPv6Level", {"level": level})

    async def set_led_brightness(self, names: list[str], brightness: int) -> None:
        for name in names:
            await self.call(f"LEDs.LED.{name}", "set", {"Brightness": brightness})

    async def reboot(self) -> None:
        # Same call the Livebox integration uses (aiosysbus nmc.async_reboot)
        await self.call("NMC", "reboot")

    async def set_internet_access(self, mac: str, allowed: bool) -> None:
        """Block/allow a device, exactly like the web UI's parental control "Block"/"Allow"."""
        if allowed:
            await self.call("Scheduler", "overrideSchedule", {"type": "ToD", "ID": mac, "override": "Enable"})
            await self.call("Scheduler", "removeSchedules", {"type": "ToD", "ID": [mac]})
        else:
            await self.call(
                "Scheduler",
                "addSchedule",
                {
                    "type": "ToD",
                    "info": {
                        "base": "Weekly",
                        "def": "Enable",
                        "ID": mac,
                        "schedule": [],
                        "enable": True,
                        "override": "Disable",
                    },
                },
            )

    async def set_port_forward(self, rule: dict[str, Any], enable: bool) -> None:
        """Re-send the whole rule with a new enable flag (the web UI's editIPv4Rules)."""
        await self.call(
            "Firewall",
            "setPortForwarding",
            {
                "id": rule["Id"],
                "internalPort": rule.get("InternalPort", ""),
                "externalPort": rule.get("ExternalPort", ""),
                "destinationIPAddress": rule.get("DestinationIPAddress", ""),
                "enable": enable,
                "persistent": True,
                "protocol": rule.get("Protocol", ""),
                "description": rule.get("Description", ""),
                "sourceInterface": "data",
                "origin": "webui",
                "destinationMACAddress": "",
                "sourcePrefix": rule.get("SourcePrefix", ""),
            },
        )

    async def set_pinhole(self, pinhole_id: str, enable: bool) -> None:
        await self.call("Firewall", "setPinhole", {"id": pinhole_id, "enable": enable})

    async def set_dmz(self, ip: str) -> None:
        await self.call(
            "Firewall", "setDMZ", {"id": "webui", "sourceInterface": "data", "destinationIPAddress": ip, "enable": True}
        )

    async def clear_dmz(self) -> None:
        await self.call("Firewall", "deleteDMZ", {"id": "webui"})

    async def set_wifi_schedule(self, enable: bool) -> None:
        await self.call("Scheduler", "enableSchedule", {"type": "WLAN", "ID": "wl0", "enable": enable})

    async def set_wps(self, vaps: tuple[str, ...], enable: bool) -> None:
        for vap in vaps:
            await self.call(f"NeMo.Intf.{vap}.WPS", "set", {"Enable": enable})

    async def start_wps_pairing(self) -> None:
        await self.call("NMC.Wifi", "startPairing", {"clientPIN": ""})

    async def stop_wps_pairing(self) -> None:
        await self.call("NMC.Wifi", "stopPairing")

    async def set_ssid_visible(self, vaps: tuple[str, ...], visible: bool) -> None:
        await self.call(
            "NeMo.Intf.lan",
            "setWLANConfig",
            {"mibs": {"wlanvap": {vap: {"SSIDAdvertisementEnabled": visible} for vap in vaps}}},
        )

    async def set_guest_bandwidth(self, kbps: int) -> None:
        await self.call("NMC.Guest", "set", {"BandwidthLimitation": str(kbps)})

    # --- more reads ----------------------------------------------------------

    async def respond_to_ping(self) -> dict[str, Any]:
        return (await self.call("Firewall", "getRespondToPing", {"sourceInterface": "data"})).get("status") or {}

    async def firewall_settings(self) -> dict[str, Any]:
        return (await self.call("Firewall", "get")).get("status") or {}

    async def custom_rules(self) -> dict[str, dict[str, Any]]:
        return (await self.call("Firewall", "getCustomRule")).get("status") or {}

    async def static_leases(self) -> list[dict[str, Any]]:
        return (await self.call("DHCPv4.Server.Pool.default", "getStaticLeases")).get("status") or []

    async def dhcp_pool(self, pool: str = "default") -> dict[str, Any]:
        res = await self.call("DHCPv4.Server", "getDHCPServerPool", {"id": pool})
        return ((res.get("status") or {}).get(pool)) or {}

    async def netmaster(self) -> dict[str, Any]:
        return (await self.call("NetMaster", "get")).get("status") or {}

    async def dyndns_hosts(self) -> list[dict[str, Any]]:
        return (await self.call("DynDNS", "getHosts")).get("status") or []

    # --- configuration writes (payloads as in the KPN web UI) ---------------

    async def set_wifi_network(
        self, vaps: tuple[str, ...], ssid: str, password: str, security: str, pmf: str, enable: bool | None = None
    ) -> None:
        sec = {"ModeEnabled": security, "KeyPassPhrase": password, "MFPConfig": pmf}
        mibs: dict[str, Any] = {"wlanvap": {vap: {"SSID": ssid, "Security": sec} for vap in vaps}}
        if enable is not None:  # guest/extra networks: the web UI sends the on/off state along
            mibs["penable"] = {vap: {"Enable": enable, "PersistentEnable": enable, "Status": enable} for vap in vaps}
        await self.call("NeMo.Intf.lan", "setWLANConfig", {"mibs": mibs})

    async def set_vap_enabled(self, vaps: tuple[str, ...], enable: bool) -> None:
        state = {"Enable": enable, "PersistentEnable": enable, "Status": enable}
        await self.call("NeMo.Intf.lan", "setWLANConfig", {"mibs": {"penable": {vap: state for vap in vaps}}})

    async def set_schedule(self, kind: str, schedule_id: str, ranges: list[dict[str, Any]]) -> None:
        """kind "ToD" (device, ID = MAC) or "WLAN" (ID wl0). ranges: [{"state": "Disable", "begin", "end"}]."""
        await self.call(
            "Scheduler",
            "addSchedule",
            {
                "type": kind,
                "info": {
                    "base": "Weekly",
                    "def": "Enable",
                    "ID": schedule_id,
                    "schedule": ranges,
                    "enable": True,
                    "override": "",
                },
            },
        )

    async def remove_schedule(self, kind: str, schedule_id: str) -> None:
        await self.call("Scheduler", "removeSchedules", {"type": kind, "ID": [schedule_id]})

    async def add_port_forward(
        self,
        name: str,
        external_port: str,
        internal_port: str,
        ip: str,
        protocol: str,
        enable: bool,
        source_prefix: str = "",
    ) -> None:
        await self.call(
            "Firewall",
            "setPortForwarding",
            {
                "id": name,
                "internalPort": internal_port,
                "externalPort": external_port,
                "destinationIPAddress": ip,
                "enable": enable,
                "persistent": True,
                "protocol": protocol,
                "description": name,
                "sourceInterface": "data",
                "origin": "webui",
                "destinationMACAddress": "",
                "sourcePrefix": source_prefix,
            },
        )

    async def delete_port_forward(self, rule_id: str, ip: str) -> None:
        await self.call(
            "Firewall", "deletePortForwarding", {"id": rule_id, "origin": "webui", "destinationIPAddress": ip}
        )

    async def add_pinhole(self, description: str, port: str, ip: str, protocol: str, enable: bool) -> None:
        await self.call(
            "Firewall",
            "setPinhole",
            {
                "origin": "webui",
                "sourceInterface": "data",
                "sourcePort": "",
                "destinationPort": port,
                "destinationIPAddress": ip,
                "protocol": protocol,
                "ipversion": 6,
                "enable": enable,
                "description": description,
                "persistent": True,
            },
        )

    async def delete_pinhole(self, pinhole_id: str) -> None:
        await self.call("Firewall", "deletePinhole", {"id": pinhole_id, "origin": "webui"})

    async def set_custom_rule(
        self,
        rule_id: str,
        chain: str,
        action: str,
        destination_port: str,
        source_port: str,
        destination: str,
        source: str,
        protocol: str,
        ipversion: int,
        enable: bool,
    ) -> None:
        await self.call(
            "Firewall",
            "setCustomRule",
            {
                "id": rule_id,
                "chain": chain,
                "action": action,
                "destinationPort": destination_port,
                "sourcePort": source_port,
                "destinationPrefix": destination,
                "sourcePrefix": source,
                "protocol": protocol,
                "ipversion": ipversion,
                "enable": enable,
            },
        )

    async def delete_custom_rule(self, rule_id: str, chain: str) -> None:
        await self.call("Firewall", "deleteCustomRule", {"id": rule_id, "chain": chain})

    async def set_chain_policy(self, chain: str, policy: str) -> None:
        await self.call("Firewall", "setChainPolicy", {"chain": chain, "policy": policy})

    async def set_respond_to_ping(self, enable: bool) -> None:
        await self.call(
            "Firewall",
            "setRespondToPing",
            {"sourceInterface": "data", "service_enable": {"enableIPv4": enable, "enableIPv6": enable}},
        )

    async def set_upnp(self, enable: bool) -> None:
        await self.call("Firewall", "set", {"UpnpPortForwardingEnable": enable})

    async def add_static_lease(self, mac: str, ip: str) -> None:
        await self.call("DHCPv4.Server.Pool.default", "addStaticLease", {"MACAddress": mac, "IPAddress": ip})

    async def delete_static_lease(self, mac: str) -> None:
        await self.call("DHCPv4.Server.Pool.default", "deleteStaticLease", {"MACAddress": mac})

    async def set_lan_ipv4(self, bridge: str, settings: dict[str, Any]) -> None:
        """bridge "lan" or "guest"; settings use the web UI's setIPv4 parameter names."""
        await self.call(f"NetMaster.LAN.default.Bridge.{bridge}", "setIPv4", settings)

    async def set_hostname(self, hostname: str) -> None:
        await self.call(
            "NetMaster.LAN.default.Bridge.lan", "setHostName", {"Key": "default", "HostName": hostname, "IPVersion": 0}
        )

    async def set_domain(self, domain: str) -> None:
        await self.call("NetMaster.LAN.default.Bridge.lan", "set", {"DomainName": domain})

    async def set_ipv6_mode(self, mode: str) -> None:
        await self.call("NetMaster", "set", {"EnableIPv6": 1, "IPv6PrefixMode": mode})

    async def dyndns_add(self, service: str, hostname: str, username: str, password: str) -> None:
        await self.call(
            "DynDNS", "addHost", {"service": service, "username": username, "hostname": hostname, "password": password}
        )

    async def dyndns_delete(self, hostname: str) -> None:
        await self.call("DynDNS", "delHost", {"hostname": hostname})

    async def dyndns_enable(self, enable: bool) -> None:
        await self.call("DynDNS", "setGlobalEnable", {"enable": enable})

    async def rename_device(self, mac: str, name: str) -> None:
        await self.call(f"Devices.Device.{mac}", "setName", {"name": name})

    async def set_device_type(self, mac: str, device_type: str) -> None:
        await self.call(f"Devices.Device.{mac}", "setType", {"type": device_type})

    async def remove_device(self, mac: str) -> None:
        await self.call("Devices", "destroyDevice", {"key": mac})

    async def set_mac_filter(self, vaps: tuple[str, ...], whitelist: bool, macs: list[str]) -> None:
        entries = {str(i): {"MACAddress": mac} for i, mac in enumerate(macs, start=1)}
        mode = "WhiteList" if whitelist else "Off"
        await self.call(
            "NeMo.Intf.lan",
            "setWLANConfig",
            {"mibs": {"wlanvap": {vap: {"MACFiltering": {"Mode": mode, "Entry": entries}} for vap in vaps}}},
        )

    async def change_admin_password(self, current: str, new: str) -> None:
        await self.call(
            "UserManagement", "changePasswordSec", {"name": "admin", "password": new, "old_password": current}
        )
        self._password = new

    async def factory_reset(self) -> None:
        await self.call("NMC", "factoryReset")

    async def install_firmware(self) -> None:
        await self.call("WebuiupgradeService", "upgrade")

    # --- generic access: anything the box exposes ----------------------------

    async def describe(self, path: str) -> dict[str, Any]:
        """The box's own description of an object: its functions (with arguments), parameters and children."""
        async with self._lock:
            if not self._context:
                await self.login()
            headers = {"Authorization": f"X-Sah {self._context}", "X-Context": self._context}
            if self._cookie:
                headers["Cookie"] = self._cookie
            url = self._url.split("/ws/")[0] + "/sysbus/" + path.replace(".", "/") + "?_restDepth=0"
            try:
                async with asyncio.timeout(self._timeout):
                    resp = await self._session.get(url, headers=headers)
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise KPNBoxError(f"describe {path} failed: {err}") from err
        if not isinstance(data, dict) or "objectInfo" not in data:
            raise KPNBoxNotFound(f"describe {path}: {data}")
        return {
            "object": data["objectInfo"].get("keyPath", "") + "." + data["objectInfo"].get("key", ""),
            "functions": {f["name"]: [a["name"] for a in f.get("arguments", [])] for f in data.get("functions", [])},
            "parameters": {p["name"]: p.get("value") for p in data.get("parameters", [])},
            "children": [c.get("objectInfo", {}).get("key") for c in data.get("children", [])],
        }

    # --- Wi-Fi radio details, scans ------------------------------------------

    async def scan_results(self, radio: str) -> list[dict[str, Any]]:
        return (await self.call(f"NeMo.Intf.{radio}", "getScanResults")).get("status") or []

    async def spectrum(self, radio: str, update: bool = False) -> list[dict[str, Any]]:
        """update=True makes the radio measure again (as the web UI's refresh does)."""
        return (await self.call(f"NeMo.Intf.{radio}", "getSpectrumInfo", {"update": update})).get("status") or []

    async def set_legacy_rates(self, enable: bool) -> None:
        await self.call(
            "NeMo.Intf.rad2g0", "set", {"OperationalDataTransmitRates": RATES_WITH_11B if enable else RATES_WITHOUT_11B}
        )

    async def steering(self) -> dict[str, Any]:
        return (await self.call("SSW.Steering.MasterConfig", "get")).get("status") or {}

    async def set_steering_sync(self, enable: bool) -> None:
        await self.call("SSW.Steering.MasterConfig", "set", {"SyncEnableField": enable})

    async def set_local_wifi_disabled(self, disabled: bool) -> None:
        await self.call("NMC.Wifi", "set", {"DisableLocalWiFi": disabled})

    async def extenders(self) -> list[dict[str, Any]]:
        res = await self.call(
            "Devices", "get", {"expression": "not interface and not self and ssw", "flags": "alternatives"}
        )
        return res.get("status") or []

    # --- LAN ports, bridges, STP, IPv6 delegation ----------------------------

    async def eth_ports(self) -> dict[str, dict[str, Any]]:
        res = await self.call("NeMo.Intf.lan", "getMIBs", {"mibs": "eth"})
        return ((res.get("status") or {}).get("eth")) or {}

    async def lower_interface(self, port: str) -> str | None:
        res = await self.call(f"NeMo.Intf.{port}", "getMIBs", {"mibs": "base"})
        lower = (((res.get("status") or {}).get("base") or {}).get(port) or {}).get("LLIntf") or {}
        return next(iter(lower), None)

    async def bridge_members(self, bridge: str) -> list[str]:
        return (await self.call(f"NeMo.Intf.{bridge}", "getIntfs", {"traverse": "down"})).get("status") or []

    async def stp(self, bridge: str) -> bool:
        return bool(((await self.call(f"NeMo.Intf.{bridge}", "get")).get("status") or {}).get("STPEnable"))

    async def set_stp(self, bridge: str, enable: bool) -> None:
        await self.call(f"NeMo.Intf.{bridge}", "set", {"STPEnable": enable})

    async def set_port_speed(self, lower: str, speed: int) -> None:
        await self.call(f"NeMo.Intf.{lower}", "set", {"MaxBitRateEnabled": speed})

    async def set_port_duplex(self, lower: str, mode: str) -> None:
        await self.call(f"NeMo.Intf.{lower}", "set", {"DuplexModeEnabled": mode})

    async def set_port_network(self, port: str, network: str) -> None:
        """network: "lan" (home) or "guest". Same remove-then-add as the web UI's guest-port switch."""
        other = "guest" if network == "lan" else "lan"
        await self.call(f"NetMaster.LAN.default.Bridge.{other}", "removeIntf", {"Intf": port})
        await self.call(f"NetMaster.LAN.default.Bridge.{network}", "addIntf", {"Intf": port})

    async def ipv6_delegation(self) -> dict[str, Any]:
        return (await self.call("NetMaster.LAN.default.Bridge.lan.IPv6.lan.DHCPv6", "get")).get("status") or {}

    async def set_ipv6_delegation(self, enable: bool) -> None:
        await self.call(
            "NetMaster.LAN.default.Bridge.lan", "setIPv6Configuration", {"Name": "lan", "DHCPIAPDEnable": enable}
        )

    async def set_ipv6_delegation_length(self, bridge: str, length: int) -> None:
        await self.call(
            f"NetMaster.LAN.default.Bridge.{bridge}.IPv6.{bridge}.DHCPv6", "set", {"IAPDPrefixLength": length}
        )

    # --- telephone -------------------------------------------------------------

    async def voice(self, method: str) -> Any:
        return (await self.call("VoiceService.VoiceApplication", method)).get("status")

    async def sip_conntrack(self) -> dict[str, Any]:
        return (await self.call("Firewall.ConnectionTracking.SIP", "get")).get("status") or {}

    async def set_sip_conntrack(self, enable: bool) -> None:
        await self.call("Firewall.ConnectionTracking.SIP", "set", {"Enable": enable})

    async def ring_phones(self) -> None:
        await self.call("VoiceService.VoiceApplication", "ring")

    async def set_phone_line(
        self, trunk: str, line: str, number: str, user: str, password: str, registrar: str, proxy: str, domain: str
    ) -> None:
        await self.call(
            "VoiceService.VoiceApplication",
            "setTrunk",
            {
                "trunk": {
                    "name": trunk,
                    "enable": "Enabled",
                    "sip": {"registrarServer": registrar, "outboundProxyServer": proxy, "userAgentDomain": domain},
                    "rtp": {},
                    "trunk_lines": [
                        {
                            "name": line,
                            "groupId": f"G{number}",
                            "enable": "Enabled",
                            "directoryNumber": number,
                            "authUserName": user,
                            "authPassword": password,
                        }
                    ],
                }
            },
        )

    async def clear_phone_line(self, trunk: str, line: str) -> None:
        await self.call(
            "VoiceService.VoiceApplication",
            "setTrunk",
            {
                "trunk": {
                    "name": trunk,
                    "enable": "Disabled",
                    "sip": {"registrarServer": "", "outboundProxyServer": "", "userAgentDomain": ""},
                    "rtp": {},
                    "trunk_lines": [
                        {
                            "name": line,
                            "groupId": "",
                            "enable": "Disabled",
                            "directoryNumber": "",
                            "authUserName": "",
                            "authPassword": "",
                        }
                    ],
                }
            },
        )

    async def set_phone_line_enabled(self, trunk: str, line: str, enable: bool) -> None:
        await self.call(
            "VoiceService.VoiceApplication",
            "setTrunk",
            {"trunk": {"name": trunk, "trunk_lines": [{"name": line, "enable": "Enabled" if enable else "Disabled"}]}},
        )

    async def set_incoming_phones(self, group: str, handsets: list[str]) -> None:
        await self.call(
            "VoiceService.VoiceApplication", "setGroups", {"groups": [{"group_id": group, "ep_names": handsets}]}
        )

    async def set_outgoing_line(self, handset: str, number: str, trunk_line: str) -> None:
        await self.call(
            "VoiceService.VoiceApplication",
            "setHandset",
            {"line": {"line": handset, "directoryNumber": number, "outgoingTrunkLine": trunk_line, "name": handset}},
        )

    # --- system extras ---------------------------------------------------------

    async def password_recovery(self) -> dict[str, Any]:
        return (await self.call("PasswordRecovery", "get")).get("status") or {}

    async def start_password_recovery(self) -> None:
        await self.call("PasswordRecovery", "start")

    async def reset_admin_password(self) -> None:
        await self.call("NMC.GroupFunction", "ResetAdminPassword")

    async def wan_modes(self) -> list[str]:
        return [m for m in str((await self.call("NMC", "getWanModeList")).get("status") or "").split(";") if m]

    async def set_wan_mode(self, mode: str, username: str = "", password: str = "") -> None:
        await self.call("NMC", "setWanMode", {"WanMode": mode, "Username": username, "Password": password})

    async def shutdown(self) -> None:
        await self.call("NMC", "shutdown", {"reason": "Home Assistant"})

    # --- event channel (long-poll; deliberately outside the call lock) -----

    def _event_headers(self) -> dict[str, str]:
        if not self._context:
            raise KPNBoxError("Not logged in")
        headers = {"Authorization": f"X-Sah {self._context}", "X-Context": self._context}
        if self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    async def open_event_channel(self, handlers: list[str]) -> int:
        if not self._context:
            await self.call("DeviceInfo", "get")  # logs in
        events = [{"handler": h} for h in handlers]
        data, _ = await self._post(
            {"service": "eventmanager", "method": "open_channel", "parameters": {"events": events}},
            self._event_headers(),
        )
        channel = (data.get("status") or {}).get("channelid")
        if channel is None:
            if any(e.get("error") == ERROR_PERMISSION_DENIED for e in data.get("errors") or []):
                self._context = None
            raise KPNBoxError(f"open_channel failed: {data}")
        # Events only flow after an explicit subscribe
        await self._post(
            {"service": "eventmanager", "method": "subscribe", "parameters": {"channelid": channel, "events": events}},
            self._event_headers(),
        )
        return channel

    async def get_events(self, channel: int, handlers: list[str], timeout: int = 45) -> list[dict[str, Any]]:
        """Waits up to ~30 s on the box side; returns [] when nothing happened."""
        events = [{"handler": h} for h in handlers]
        data, _ = await self._post(
            {
                "events": events,
                "eventsVersionToUse": 1,
                "service": "eventmanager",
                "method": "get_events",
                "parameters": {"channelid": channel, "events": []},
            },
            self._event_headers(),
            timeout,
        )
        if errors := data.get("errors"):
            if any(e.get("error") == ERROR_PERMISSION_DENIED for e in errors):
                self._context = None  # expired; the next call/open logs in again
            raise KPNBoxError(f"get_events: {errors}")
        return (data.get("status") or {}).get("events") or []


RADIO_LIST = (("rad2g0", "vap2g0priv", "2g"), ("rad5g0", "vap5g0priv", "5g"))
