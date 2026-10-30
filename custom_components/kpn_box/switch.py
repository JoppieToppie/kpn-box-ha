"""Switches: Wi-Fi, bands, guest Wi-Fi, SSID visibility, WPS, Wi-Fi schedule,
per-device internet access, port forwarding rules and IPv6 pinholes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .const import EXTRA_NETWORKS, PROTOCOLS, RADIOS
from .coordinator import KPNBoxCoordinator, KPNBoxData
from .entity import KPNBoxEntity, add_dynamic_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    priv = tuple(RADIOS[k][1] for k in c.radios)
    entities: list[SwitchEntity] = [
        WifiSwitch(c, "wifi", "Wi-Fi"),
        GuestWifiSwitch(c, "guest_wifi", "Guest Wi-Fi"),
        SimpleSwitch(
            c,
            "ssid_visible",
            "Wi-Fi network visible",
            "mdi:eye",
            is_on=lambda d: any(d.private_vaps.get(v, {}).get("SSIDAdvertisementEnabled") for v in priv),
            set_fn=lambda on: c.api.set_ssid_visible(priv, on),
            category=EntityCategory.CONFIG,
        ),
        SimpleSwitch(
            c,
            "guest_ssid_visible",
            "Guest Wi-Fi network visible",
            "mdi:eye-outline",
            is_on=lambda d: any(v.get("SSIDAdvertisementEnabled") for v in d.guest_vaps.values()),
            set_fn=lambda on: c.api.set_ssid_visible(c.guest_vap_names, on),
            category=EntityCategory.CONFIG,
        ),
        SimpleSwitch(
            c,
            "wps",
            "WPS",
            "mdi:wifi-lock-open",
            is_on=lambda d: any(w.get("Enable") for w in d.wps.values()),
            set_fn=lambda on: c.api.set_wps(priv, on),
            category=EntityCategory.CONFIG,
        ),
        WifiScheduleSwitch(c, "wifi_schedule", "Wi-Fi schedule"),
        SimpleSwitch(
            c,
            "respond_to_ping",
            "Respond to ping from internet",
            "mdi:access-point-network",
            is_on=lambda d: bool(d.respond_to_ping.get("enableIPv4")),
            set_fn=c.api.set_respond_to_ping,
            category=EntityCategory.CONFIG,
        ),
        SimpleSwitch(
            c,
            "upnp",
            "UPnP port forwarding",
            "mdi:router-network-wireless",
            is_on=lambda d: bool(d.firewall.get("UpnpPortForwardingEnable")),
            set_fn=c.api.set_upnp,
            category=EntityCategory.CONFIG,
        ),
    ]
    entities += [RadioSwitch(c, key) for key in c.radios]
    for vap, name in EXTRA_NETWORKS.items():
        if vap in c.data.private_vaps:
            entities.append(
                SimpleSwitch(
                    c,
                    f"extra_{vap}",
                    name,
                    "mdi:wifi-plus",
                    is_on=lambda d, v=vap: d.private_vaps.get(v, {}).get("VAPStatus") == "Up",
                    set_fn=lambda on, v=vap: c.api.set_vap_enabled((v,), on),
                )
            )
    entities += [
        SimpleSwitch(
            c,
            f"stp_{nemo}",
            f"STP ({name})",
            "mdi:lan",
            category=EntityCategory.CONFIG,
            is_on=lambda d, b=nemo: bool(d.stp.get(b)),
            set_fn=lambda on, b=nemo: c.api.set_stp(b, on),
        )
        for nemo, name in (("bridge", "home network"), ("brguest", "guest network"))
    ]
    entities += [
        SimpleSwitch(
            c,
            "sip_conntrack",
            "SIP connection tracking",
            "mdi:phone-settings",
            category=EntityCategory.CONFIG,
            is_on=lambda d: bool(d.sip_conntrack.get("Enable")),
            set_fn=c.api.set_sip_conntrack,
        ),
        SimpleSwitch(
            c,
            "ipv6_prefix_delegation",
            "IPv6 prefix delegation",
            "mdi:ip-network-outline",
            category=EntityCategory.CONFIG,
            is_on=lambda d: bool(d.ipv6_delegation.get("IAPDEnable")),
            set_fn=c.api.set_ipv6_delegation,
        ),
        SimpleSwitch(
            c,
            "extender_sync",
            "Sync Wi-Fi settings to extenders",
            "mdi:sync",
            category=EntityCategory.CONFIG,
            enabled_default=False,
            is_on=lambda d: bool(d.steering.get("SyncEnableField")),
            set_fn=c.api.set_steering_sync,
        ),
        SimpleSwitch(
            c,
            "local_wifi_off",
            "Box Wi-Fi off (extenders stay on)",
            "mdi:wifi-off",
            category=EntityCategory.CONFIG,
            enabled_default=False,
            is_on=lambda d: bool(d.wifi.get("DisableLocalWiFi")),
            set_fn=c.api.set_local_wifi_disabled,
        ),
    ]
    if "2g" in c.radios:
        entities.append(
            SimpleSwitch(
                c,
                "legacy_11b",
                "Wi-Fi 2.4 GHz 802.11b compatibility",
                "mdi:wifi-strength-1",
                category=EntityCategory.CONFIG,
                is_on=lambda d: "5.5" in str(d.radios.get("2g", {}).get("OperationalDataTransmitRates", "")),
                set_fn=c.api.set_legacy_rates,
            )
        )
    async_add_entities(entities)
    add_dynamic_entities(
        entry, c, lambda d: list(d.custom_rules), lambda rid: CustomRuleSwitch(c, rid), async_add_entities
    )
    add_dynamic_entities(
        entry,
        c,
        lambda d: [f"{t['name']}|{ln['name']}" for t in d.trunks for ln in t.get("trunk_lines", [])],
        lambda key: PhoneLineSwitch(c, *key.split("|")),
        async_add_entities,
    )

    if c.track_devices:
        # Same device set as the trackers (seen online), plus anything already blocked
        add_dynamic_entities(
            entry,
            c,
            lambda d: [m for m, dev in d.devices.items() if dev.get("Active") or _blocked(d.access_schedules.get(m))],
            lambda mac: InternetAccessSwitch(c, mac),
            async_add_entities,
        )
    add_dynamic_entities(
        entry, c, lambda d: list(d.port_forwards), lambda rid: PortForwardSwitch(c, rid), async_add_entities
    )
    add_dynamic_entities(entry, c, lambda d: list(d.pinholes), lambda pid: PinholeSwitch(c, pid), async_add_entities)


def _blocked(schedule: dict[str, Any] | None) -> bool:
    return bool(schedule) and (schedule.get("override") == "Disable" or schedule.get("value") == "Disable")


class SimpleSwitch(KPNBoxEntity, SwitchEntity):
    def __init__(
        self,
        c: KPNBoxCoordinator,
        key: str,
        name: str,
        icon: str,
        *,
        is_on: Callable[[KPNBoxData], bool],
        set_fn: Callable[[bool], Awaitable[None]],
        category: EntityCategory | None = None,
        enabled_default: bool = True,
    ) -> None:
        super().__init__(c, key, name)
        self._attr_icon = icon
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled_default
        self._is_on, self._set = is_on, set_fn

    @property
    def is_on(self) -> bool:
        return bool(self._is_on(self.coordinator.data))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self._set(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self._set(False))


class WifiSwitch(KPNBoxEntity, SwitchEntity):
    _attr_icon = "mdi:wifi"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.wifi.get("Enable") is True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_wifi(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_wifi(False))


class RadioSwitch(KPNBoxEntity, SwitchEntity):
    _attr_icon = "mdi:wifi-settings"

    def __init__(self, coordinator: KPNBoxCoordinator, key: str) -> None:
        radio, vap, name = RADIOS[key]
        super().__init__(coordinator, f"{key}_radio", name)
        self._key, self._radio, self._vap = key, radio, vap

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.radios.get(self._key, {}).get("Enable") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"radio_status": self.coordinator.data.radios.get(self._key, {}).get("RadioStatus")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_radio(self._radio, self._vap, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_radio(self._radio, self._vap, False))


class GuestWifiSwitch(KPNBoxEntity, SwitchEntity):
    _attr_icon = "mdi:account-group"

    @property
    def is_on(self) -> bool:
        return any(v.get("VAPStatus") == "Up" for v in self.coordinator.data.guest_vaps.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        ssid = next((v.get("SSID") for v in data.guest_vaps.values() if v.get("SSID")), None)
        return {
            "ssid": ssid,
            "network": data.guest.get("Address"),
            "bandwidth_limit_kbps": data.guest.get("BandwidthLimitation"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_guest_wifi(True, self.coordinator.guest_vap_names))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_guest_wifi(False, self.coordinator.guest_vap_names))


class WifiScheduleSwitch(KPNBoxEntity, SwitchEntity):
    """Turns the Wi-Fi on/off schedule made in the KPN web UI on or off."""

    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        # Nothing to switch until a schedule has been created in the web UI
        return super().available and self.coordinator.data.wifi_schedule is not None

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data.wifi_schedule or {}).get("enable"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"schedule": (self.coordinator.data.wifi_schedule or {}).get("schedule")}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_wifi_schedule(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_wifi_schedule(False))


class InternetAccessSwitch(KPNBoxEntity, SwitchEntity):
    """On = device may use the internet. Off = blocked (the web UI's parental control "Block")."""

    _attr_icon = "mdi:web"

    def __init__(self, coordinator: KPNBoxCoordinator, mac: str) -> None:
        dev = coordinator.data.devices.get(mac, {})
        super().__init__(coordinator, f"internet_{mac.lower()}", f"{dev.get('Name') or mac} internet access")
        self._mac = mac

    @property
    def _schedule(self) -> dict[str, Any] | None:
        return self.coordinator.data.access_schedules.get(self._mac)

    @property
    def is_on(self) -> bool:
        return not _blocked(self._schedule)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._schedule or {}
        dev = self.coordinator.data.devices.get(self._mac, {})
        return {
            "mac": self._mac,
            "ip": dev.get("IPAddress"),
            "online": dev.get("Active"),
            "weekly_schedule": bool(s.get("schedule")),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Like the web UI's "Allow": also removes a weekly schedule set there
        await self.coordinator.async_run(self.coordinator.api.set_internet_access(self._mac, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_internet_access(self._mac, False))


class PortForwardSwitch(KPNBoxEntity, SwitchEntity):
    _attr_icon = "mdi:router-network"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KPNBoxCoordinator, rule_id: str) -> None:
        rule = coordinator.data.port_forwards.get(rule_id, {})
        super().__init__(coordinator, f"portforward_{rule_id}", f"Port forward {rule.get('Description') or rule_id}")
        self._id = rule_id

    @property
    def _rule(self) -> dict[str, Any]:
        return self.coordinator.data.port_forwards.get(self._id, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._rule)  # rule deleted in the web UI

    @property
    def is_on(self) -> bool:
        return self._rule.get("Enable") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._rule
        return {
            "protocol": PROTOCOLS.get(str(r.get("Protocol")), r.get("Protocol")),
            "external_port": r.get("ExternalPort"),
            "internal_port": r.get("InternalPort"),
            "destination": r.get("DestinationIPAddress"),
            "source_prefix": r.get("SourcePrefix") or None,
            "status": r.get("Status"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_port_forward(self._rule, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_port_forward(self._rule, False))


class PinholeSwitch(KPNBoxEntity, SwitchEntity):
    """IPv6 'open port' rule."""

    _attr_icon = "mdi:ip-network-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KPNBoxCoordinator, pinhole_id: str) -> None:
        p = coordinator.data.pinholes.get(pinhole_id, {})
        super().__init__(coordinator, f"pinhole_{pinhole_id}", f"IPv6 open port {p.get('Description') or pinhole_id}")
        self._id = pinhole_id

    @property
    def _p(self) -> dict[str, Any]:
        return self.coordinator.data.pinholes.get(self._id, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._p)

    @property
    def is_on(self) -> bool:
        return self._p.get("Enable") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._p
        return {
            "id": self._id,
            "protocol": PROTOCOLS.get(str(p.get("Protocol")), p.get("Protocol")),
            "port": p.get("DestinationPort"),
            "destination": p.get("DestinationIPAddress"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_pinhole(self._id, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_pinhole(self._id, False))


class CustomRuleSwitch(KPNBoxEntity, SwitchEntity):
    """Custom firewall rule (web UI: Security → firewall → custom).

    The box ships ~37 of these (ssh, http, CommTV...), so they start disabled; enable the ones you need.
    """

    _attr_icon = "mdi:wall-fire"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KPNBoxCoordinator, rule_id: str) -> None:
        r = coordinator.data.custom_rules.get(rule_id, {})
        super().__init__(coordinator, f"fwrule_{rule_id}", f"Firewall rule {r.get('Description') or rule_id}")
        self._id = rule_id

    @property
    def _r(self) -> dict[str, Any]:
        return self.coordinator.data.custom_rules.get(self._id, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._r)

    @property
    def is_on(self) -> bool:
        return self._r.get("Enable") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._r
        return {
            "id": self._id,
            "action": r.get("Target"),
            "protocol": PROTOCOLS.get(str(r.get("Protocol")), r.get("Protocol")),
            "destination_port": r.get("DestinationPort"),
            "source_port": r.get("SourcePort") or None,
            "destination": r.get("DestinationPrefix") or None,
            "source": r.get("SourcePrefix") or None,
            "ip_version": r.get("IPVersion"),
        }

    async def _set(self, enable: bool) -> None:
        r = self._r
        await self.coordinator.async_run(
            self.coordinator.api.set_custom_rule(
                self._id,
                "Custom",
                r.get("Target", "Accept"),
                r.get("DestinationPort", ""),
                r.get("SourcePort", ""),
                r.get("DestinationPrefix", ""),
                r.get("SourcePrefix", ""),
                r.get("Protocol", ""),
                r.get("IPVersion", 4),
                enable,
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class PhoneLineSwitch(KPNBoxEntity, SwitchEntity):
    """A telephone line (SIP trunk line). Set it up with the set_phone_line action."""

    _attr_icon = "mdi:phone"

    def __init__(self, coordinator: KPNBoxCoordinator, trunk: str, line: str) -> None:
        super().__init__(coordinator, f"phone_{trunk}_{line}", f"Phone line {line}")
        self._trunk, self._line = trunk, line
        # The box always has 4 lines; only show the ones that are set up
        self._attr_entity_registry_enabled_default = bool(self._l.get("directoryNumber"))

    @property
    def _l(self) -> dict[str, Any]:
        for t in self.coordinator.data.trunks:
            if t.get("name") == self._trunk:
                return next((ln for ln in t.get("trunk_lines", []) if ln.get("name") == self._line), {})
        return {}

    @property
    def is_on(self) -> bool:
        return self._l.get("enable") == "Enabled"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ln = self._l
        return {
            "trunk": self._trunk,
            "status": ln.get("status"),
            "number": ln.get("directoryNumber") or None,
            "status_info": ln.get("statusInfo") or None,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_phone_line_enabled(self._trunk, self._line, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_phone_line_enabled(self._trunk, self._line, False))
