"""Sensors: per-interface traffic, WAN/system info, Wi-Fi radio health and device counts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .const import INTERFACES, LAN_PORTS, PROTOCOLS, RADIOS
from .coordinator import KPNBoxCoordinator, KPNBoxData
from .entity import KPNBoxEntity

TRAFFIC_ATTRS = ("RxPackets", "TxPackets", "RxErrors", "TxErrors", "RxDropped", "TxDropped")


@dataclass(frozen=True, kw_only=True)
class KPNSensorDescription(SensorEntityDescription):
    value_fn: Callable[[KPNBoxData], Any]
    attrs_fn: Callable[[KPNBoxData], dict[str, Any] | None] = lambda d: None


def _active(data: KPNBoxData, link: str | None = None) -> int:
    return sum(1 for d in data.devices.values() if d.get("Active") and (link is None or d["_link"] == link))


SYSTEM_SENSORS = (
    KPNSensorDescription(
        key="last_boot",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_boot,
    ),
    KPNSensorDescription(
        key="public_ipv4",
        name="Public IPv4",
        icon="mdi:ip-network",
        value_fn=lambda d: d.wan.get("IPAddress") or None,
        attrs_fn=lambda d: {
            "gateway": d.wan.get("RemoteGateway"),
            "dns_servers": d.wan.get("DNSServers"),
            "protocol": d.wan.get("Protocol"),
            "link_type": d.wan.get("LinkType"),
        },
    ),
    KPNSensorDescription(
        key="ipv6_prefix",
        name="IPv6 prefix",
        icon="mdi:ip-network-outline",
        value_fn=lambda d: d.wan.get("IPv6DelegatedPrefix") or None,
        attrs_fn=lambda d: {"wan_ipv6_address": d.wan.get("IPv6Address")},
    ),
    KPNSensorDescription(
        key="wan_state",
        name="WAN connection",
        icon="mdi:wan",
        value_fn=lambda d: d.wan.get("ConnectionState"),
        attrs_fn=lambda d: {"link_state": d.wan.get("LinkState"), "last_error": d.wan.get("LastConnectionError")},
    ),
    KPNSensorDescription(
        key="devices_connected",
        name="Connected devices",
        icon="mdi:devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_active,
    ),
    KPNSensorDescription(
        key="devices_wifi",
        name="Wi-Fi devices",
        icon="mdi:wifi",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _active(d, "wifi"),
    ),
    KPNSensorDescription(
        key="devices_wired",
        name="Wired devices",
        icon="mdi:ethernet",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _active(d, "eth"),
    ),
    KPNSensorDescription(
        key="upnp_forwards",
        name="UPnP port forwards",
        icon="mdi:router-network-wireless",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.upnp_forwards),
        attrs_fn=lambda d: {
            "rules": [
                f"{r.get('Description')} {PROTOCOLS.get(str(r.get('Protocol')), r.get('Protocol'))} "
                f"{r.get('ExternalPort')} -> {r.get('DestinationIPAddress')}:{r.get('InternalPort')}"
                for r in d.upnp_forwards.values()
            ]
        },
    ),
    KPNSensorDescription(
        key="dhcp",
        name="DHCP range",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: f"{d.dhcp.get('MinAddress')} - {d.dhcp.get('MaxAddress')}" if d.dhcp else None,
        attrs_fn=lambda d: {
            "router_ip": d.dhcp.get("IPRouters"),
            "subnet_mask": d.dhcp.get("SubnetMask"),
            "dns_servers": d.dhcp.get("DNSServers"),
            "lease_time_s": d.dhcp.get("LeaseTime"),
            "dhcp_enabled": d.dhcp.get("Enable"),
            "authoritative": d.dhcp.get("Authoritative"),
            "guest_range": f"{d.guest_dhcp.get('MinAddress')} - {d.guest_dhcp.get('MaxAddress')}"
            if d.guest_dhcp
            else None,
        },
    ),
    KPNSensorDescription(
        key="static_leases",
        name="Fixed IP addresses",
        icon="mdi:ip-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.static_leases),
        attrs_fn=lambda d: {"leases": {lease.get("MACAddress"): lease.get("IPAddress") for lease in d.static_leases}},
    ),
    KPNSensorDescription(
        key="dyndns",
        name="DynDNS hosts",
        icon="mdi:dns",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.dyndns),
        attrs_fn=lambda d: {"hosts": [{k: v for k, v in h.items() if "pass" not in k.lower()} for h in d.dyndns]},
    ),
    KPNSensorDescription(
        key="blocked_devices",
        name="Blocked devices",
        icon="mdi:web-cancel",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(1 for s in d.access_schedules.values() if s.get("override") == "Disable"),
    ),
)


def _radio_sensors(key: str) -> tuple[KPNSensorDescription, ...]:
    name = RADIOS[key][2]

    def r(field: str) -> Callable[[KPNBoxData], Any]:
        return lambda d: d.radios.get(key, {}).get(field)

    return (
        KPNSensorDescription(
            key=f"{key}_channel",
            name=f"{name} channel",
            icon="mdi:wifi-cog",
            value_fn=r("Channel"),
            attrs_fn=lambda d: {
                "bandwidth": d.radios.get(key, {}).get("CurrentOperatingChannelBandwidth"),
                "standards": d.radios.get(key, {}).get("OperatingStandards"),
                "auto_channel": d.radios.get(key, {}).get("AutoChannelEnable"),
                "channels_in_use": d.radios.get(key, {}).get("ChannelsInUse"),
                "change_reason": d.radios.get(key, {}).get("ChannelChangeReason"),
            },
        ),
        KPNSensorDescription(
            key=f"{key}_channel_load",
            name=f"{name} channel load",
            icon="mdi:gauge",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=r("ChannelLoad"),
        ),
        KPNSensorDescription(
            key=f"{key}_interference",
            name=f"{name} interference",
            icon="mdi:sine-wave",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=r("Interference"),
        ),
        KPNSensorDescription(
            key=f"{key}_noise",
            name=f"{name} noise",
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=r("Noise"),
        ),
        KPNSensorDescription(
            key=f"{key}_clients",
            name=f"{name} clients",
            icon="mdi:account-multiple",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=r("ActiveAssociatedDevices"),
        ),
    )


EXTRA_SENSORS = (
    KPNSensorDescription(
        key="phone_calls",
        name="Phone calls",
        icon="mdi:phone-log",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.calls),
        attrs_fn=lambda d: {"recent": d.calls[:10]},
    ),
    KPNSensorDescription(
        key="extenders",
        name="Wi-Fi extenders",
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.extenders),
        attrs_fn=lambda d: {
            "extenders": [
                {"name": e.get("Name"), "ip": e.get("IPAddress"), "active": e.get("Active")} for e in d.extenders
            ]
        },
    ),
)


def _scan_sensors(key: str) -> tuple[KPNSensorDescription, ...]:
    name = RADIOS[key][2]

    def neighbours(d: KPNBoxData) -> list[dict[str, Any]]:
        return sorted(d.scan.get(key, []), key=lambda n: n.get("SignalStrength") or -200, reverse=True)

    def best(d: KPNBoxData) -> dict[str, Any]:
        usable = [c for c in d.spectrum.get(key, []) if not c.get("isBanned")]
        return max(usable, key=lambda c: c.get("availability") or 0, default={})

    return (
        KPNSensorDescription(
            key=f"{key}_neighbours",
            name=f"{name} nearby networks",
            icon="mdi:wifi-marker",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d: len(d.scan.get(key, [])),
            attrs_fn=lambda d: {
                "networks": [
                    {
                        "ssid": n.get("SSID") or "(hidden)",
                        "channel": n.get("Channel"),
                        "signal": n.get("SignalStrength"),
                        "security": n.get("SecurityModeEnabled"),
                    }
                    for n in neighbours(d)[:25]
                ]
            },
        ),
        KPNSensorDescription(
            key=f"{key}_best_channel",
            name=f"{name} least busy channel",
            icon="mdi:wifi-check",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d: best(d).get("channel"),
            attrs_fn=lambda d: {
                "availability_pct": best(d).get("availability"),
                "channels": [
                    {
                        "channel": c.get("channel"),
                        "availability": c.get("availability"),
                        "access_points": c.get("accesspoints"),
                        "noise": c.get("noiselevel"),
                    }
                    for c in d.spectrum.get(key, [])
                ],
            },
        ),
    )


def _port_sensor(n: int, lower: str) -> KPNSensorDescription:
    return KPNSensorDescription(
        key=f"port{n}_link",
        name=f"LAN port {n} link speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.eth.get(lower, {}).get("CurrentBitRate") or None,
        attrs_fn=lambda d: {"duplex": d.eth.get(lower, {}).get("CurrentDuplexMode")},
    )


def _traffic_sensors(intf: str) -> tuple[KPNSensorDescription, ...]:
    name, is_wan = INTERFACES[intf]
    labels = (
        ("download", "upload", "download speed", "upload speed")
        if is_wan
        else ("received", "sent", "receive speed", "send speed")
    )
    out = []
    for field, label in zip(("RxBytes", "TxBytes", "rx_rate", "tx_rate"), labels, strict=True):
        rate = field.endswith("rate")
        out.append(
            KPNSensorDescription(
                key=f"{intf}_{field}",
                name=f"{name} {label}",
                device_class=SensorDeviceClass.DATA_RATE if rate else SensorDeviceClass.DATA_SIZE,
                state_class=SensorStateClass.MEASUREMENT if rate else SensorStateClass.TOTAL_INCREASING,
                native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND if rate else UnitOfInformation.BYTES,
                suggested_unit_of_measurement=None if rate else UnitOfInformation.GIGABYTES,
                suggested_display_precision=2,
                value_fn=lambda d, i=intf, f=field: d.traffic.get(i, {}).get(f),
                attrs_fn=None
                if rate
                else (
                    lambda d, i=intf: (
                        {k: v for k, v in d.traffic.get(i, {}).items() if k in TRAFFIC_ATTRS} | {"interface": i}
                    )
                ),
            )
        )
    return tuple(out)


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    descriptions = [*SYSTEM_SENSORS, *EXTRA_SENSORS]
    for key in coordinator.radios:
        descriptions += _radio_sensors(key)
        descriptions += _scan_sensors(key)
    for n, port in enumerate(LAN_PORTS, start=1):
        if lower := coordinator.port_lower.get(port):
            descriptions.append(_port_sensor(n, lower))
    for intf in coordinator.interfaces:
        descriptions += _traffic_sensors(intf)
    async_add_entities(KPNBoxSensor(coordinator, d) for d in descriptions)


class KPNBoxSensor(KPNBoxEntity, SensorEntity):
    entity_description: KPNSensorDescription

    def __init__(self, coordinator: KPNBoxCoordinator, description: KPNSensorDescription) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
