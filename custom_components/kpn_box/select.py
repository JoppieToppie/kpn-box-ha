"""Selects: firewall level, Wi-Fi channel per band, guest Wi-Fi time limit."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .const import (
    BANDWIDTHS,
    DUPLEX_MODES,
    FIREWALL_LEVELS,
    GUEST_BANDWIDTH,
    GUEST_TIME_LIMITS,
    IPV6_MODES,
    LAN_PORTS,
    PORT_NETWORKS,
    PORT_SPEEDS,
    RADIOS,
    STANDARDS,
)
from .coordinator import KPNBoxCoordinator
from .entity import KPNBoxEntity

AUTO = "auto"


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [
        FirewallSelect(coordinator, "firewall_level", "Firewall level"),
        GuestTimeLimitSelect(coordinator, "guest_time_limit", "Guest Wi-Fi time limit"),
    ]
    entities += [ChannelSelect(coordinator, key) for key in coordinator.radios]
    entities.append(GuestBandwidthSelect(coordinator, "guest_bandwidth", "Guest Wi-Fi bandwidth limit"))
    entities.append(IPv6ModeSelect(coordinator, "ipv6_mode", "IPv6 on LAN"))
    for key in coordinator.radios:
        entities += [BandwidthSelect(coordinator, key), StandardsSelect(coordinator, key)]
    for n, port in enumerate(LAN_PORTS, start=1):
        if lower := coordinator.port_lower.get(port):
            entities += [PortSpeedSelect(coordinator, n, lower), PortDuplexSelect(coordinator, n, lower)]
        if port in coordinator.data.port_network:
            entities.append(PortNetworkSelect(coordinator, n, port))
    async_add_entities(entities)


class _RadioConfigSelect(KPNBoxEntity, SelectEntity):
    """Channel width / standards go through the same setWLANConfig call as the channel, with the rest kept."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KPNBoxCoordinator, key: str, suffix: str, name: str) -> None:
        super().__init__(coordinator, f"{key}_{suffix}", f"{RADIOS[key][2]} {name}")
        self._key = key

    @property
    def _radio(self) -> dict:
        return self.coordinator.data.radios.get(self._key, {})

    async def _apply(self, bandwidth: str, standards: str) -> None:
        r = self._radio
        channel = None if r.get("AutoChannelEnable") else r.get("Channel")
        await self.coordinator.async_run(
            self.coordinator.api.set_channel(RADIOS[self._key][0], channel, bandwidth, standards)
        )


class BandwidthSelect(_RadioConfigSelect):
    _attr_icon = "mdi:arrow-expand-horizontal"

    def __init__(self, coordinator: KPNBoxCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "channel_width", "channel width")

    @property
    def options(self) -> list[str]:
        maximum = self._radio.get("MaxChannelBandwidth", "160MHz")
        allowed = BANDWIDTHS[: BANDWIDTHS.index(maximum) + 1] if maximum in BANDWIDTHS else BANDWIDTHS
        return allowed

    @property
    def current_option(self) -> str | None:
        value = str(self._radio.get("OperatingChannelBandwidth", ""))
        return "AUTO" if value.lower() == "auto" else (value if value in BANDWIDTHS else None)

    async def async_select_option(self, option: str) -> None:
        await self._apply(option, self._radio.get("OperatingStandards"))


class StandardsSelect(_RadioConfigSelect):
    _attr_icon = "mdi:wifi-star"

    def __init__(self, coordinator: KPNBoxCoordinator, key: str) -> None:
        super().__init__(coordinator, key, "standards", "Wi-Fi standards")

    @property
    def options(self) -> list[str]:
        current = self._radio.get("OperatingStandards")
        options = list(STANDARDS[self._key])
        return options + [current] if current and current not in options else options

    @property
    def current_option(self) -> str | None:
        return self._radio.get("OperatingStandards")

    async def async_select_option(self, option: str) -> None:
        r = self._radio
        await self._apply(r.get("OperatingChannelBandwidth") or r.get("CurrentOperatingChannelBandwidth"), option)


class _PortSelect(KPNBoxEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KPNBoxCoordinator, n: int, key: str, name: str, lower: str) -> None:
        super().__init__(coordinator, f"port{n}_{key}", f"LAN port {n} {name}")
        self._lower = lower

    @property
    def _eth(self) -> dict:
        return self.coordinator.data.eth.get(self._lower, {})


class PortSpeedSelect(_PortSelect):
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: KPNBoxCoordinator, n: int, lower: str) -> None:
        super().__init__(coordinator, n, "speed", "speed", lower)

    @property
    def options(self) -> list[str]:
        maximum = self._eth.get("MaxBitRateSupported") or 1000
        return [k for k, v in PORT_SPEEDS.items() if v <= maximum]

    @property
    def current_option(self) -> str | None:
        return next((k for k, v in PORT_SPEEDS.items() if v == self._eth.get("MaxBitRateEnabled")), None)

    @property
    def extra_state_attributes(self) -> dict:
        return {"current_mbit": self._eth.get("CurrentBitRate"), "max_mbit": self._eth.get("MaxBitRateSupported")}

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_port_speed(self._lower, PORT_SPEEDS[option]))


class PortDuplexSelect(_PortSelect):
    _attr_icon = "mdi:swap-horizontal"
    _attr_options = DUPLEX_MODES

    def __init__(self, coordinator: KPNBoxCoordinator, n: int, lower: str) -> None:
        super().__init__(coordinator, n, "duplex", "duplex", lower)

    @property
    def current_option(self) -> str | None:
        return self._eth.get("DuplexModeEnabled")

    @property
    def extra_state_attributes(self) -> dict:
        return {"current": self._eth.get("CurrentDuplexMode")}

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_port_duplex(self._lower, option))


class PortNetworkSelect(KPNBoxEntity, SelectEntity):
    """Put a LAN port on the home or the guest network (the web UI's guest-port switch)."""

    _attr_icon = "mdi:ethernet"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(PORT_NETWORKS)

    def __init__(self, coordinator: KPNBoxCoordinator, n: int, port: str) -> None:
        super().__init__(coordinator, f"port{n}_network", f"LAN port {n} network")
        self._port = port

    @property
    def current_option(self) -> str | None:
        bridge = self.coordinator.data.port_network.get(self._port)
        return next((k for k, v in PORT_NETWORKS.items() if v == bridge), None)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_port_network(self._port, PORT_NETWORKS[option]))


class IPv6ModeSelect(KPNBoxEntity, SelectEntity):
    """The web UI's 'IPv6 prefix delegation' choice: enabled (RA), enabled with DHCPv6, or disabled."""

    _attr_icon = "mdi:ip-network-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(IPV6_MODES)

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.data.netmaster.get("IPv6PrefixMode")
        return next((k for k, v in IPV6_MODES.items() if v == mode), None)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_ipv6_mode(IPV6_MODES[option]))


class GuestBandwidthSelect(KPNBoxEntity, SelectEntity):
    _attr_icon = "mdi:speedometer-slow"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(GUEST_BANDWIDTH)

    @property
    def current_option(self) -> str | None:
        try:
            value = int(self.coordinator.data.guest.get("BandwidthLimitation", 0))
        except (TypeError, ValueError):
            return None
        return next((k for k, v in GUEST_BANDWIDTH.items() if v == value), None)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_guest_bandwidth(GUEST_BANDWIDTH[option]))


class FirewallSelect(KPNBoxEntity, SelectEntity):
    _attr_icon = "mdi:wall-fire"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = FIREWALL_LEVELS

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.firewall_level

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_run(self.coordinator.api.set_firewall_level(option))


class ChannelSelect(KPNBoxEntity, SelectEntity):
    _attr_icon = "mdi:wifi-cog"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: KPNBoxCoordinator, key: str) -> None:
        super().__init__(coordinator, f"{key}_channel_select", f"{RADIOS[key][2]} channel selection")
        self._key = key

    @property
    def _radio(self) -> dict:
        return self.coordinator.data.radios.get(self._key, {})

    @property
    def options(self) -> list[str]:
        channels = [c.strip() for c in str(self._radio.get("PossibleChannels", "")).split(",") if c.strip()]
        return [AUTO, *channels]

    @property
    def current_option(self) -> str | None:
        if self._radio.get("AutoChannelEnable"):
            return AUTO
        return str(self._radio.get("Channel")) if self._radio.get("Channel") is not None else None

    async def async_select_option(self, option: str) -> None:
        radio = self._radio
        await self.coordinator.async_run(
            self.coordinator.api.set_channel(
                RADIOS[self._key][0],
                None if option == AUTO else int(option),
                radio.get("OperatingChannelBandwidth") or radio.get("CurrentOperatingChannelBandwidth"),
                radio.get("OperatingStandards"),
            )
        )


class GuestTimeLimitSelect(KPNBoxEntity, SelectEntity):
    """Auto-off timer for guest Wi-Fi, same choices as the KPN web UI."""

    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(GUEST_TIME_LIMITS)

    def __init__(self, coordinator: KPNBoxCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key, name)
        self._chosen: str | None = None

    @property
    def current_option(self) -> str | None:
        # The box reports 0 when no timer is set; otherwise prefer what was chosen here
        if self._chosen is not None:
            return self._chosen
        timer = self.coordinator.data.guest_timer
        if not timer:
            return "unlimited"
        return next((k for k, v in GUEST_TIME_LIMITS.items() if v == timer), None)

    async def async_select_option(self, option: str) -> None:
        previous, self._chosen = self._chosen, option
        try:
            await self.coordinator.async_run(self.coordinator.api.set_guest_time_limit(GUEST_TIME_LIMITS[option]))
        except Exception:
            self._chosen = previous
            raise
