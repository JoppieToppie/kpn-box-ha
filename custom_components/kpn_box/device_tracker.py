"""Device trackers for devices connected to the box (Wi-Fi and wired)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KPNBoxConfigEntry
from .coordinator import KPNBoxCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if not coordinator.track_devices:
        # Tracking switched off in the options: drop trackers created earlier
        registry = er.async_get(hass)
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg_entry.domain == "device_tracker":
                registry.async_remove(reg_entry.entity_id)
        return
    tracked: set[str] = set()

    @callback
    def add_new() -> None:
        # Only devices seen online since setup, so years of stale history don't become entities
        new = [mac for mac, dev in coordinator.data.devices.items() if dev.get("Active") and mac not in tracked]
        tracked.update(new)
        if new:
            async_add_entities(KPNBoxTracker(coordinator, mac) for mac in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class KPNBoxTracker(CoordinatorEntity[KPNBoxCoordinator], ScannerEntity):
    """HA's ScannerEntity uses the MAC as unique ID and links to an existing device with that MAC."""

    def __init__(self, coordinator: KPNBoxCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = format_mac(mac)
        self._key = mac
        self._attr_name = self._dev.get("Name") or self._mac

    @property
    def _dev(self) -> dict[str, Any]:
        return self.coordinator.data.devices.get(self._key, {})

    @property
    def entity_registry_enabled_default(self) -> bool:
        # Only devices seen online get a tracker, so enable them even without a matching HA device
        return True

    @property
    def is_connected(self) -> bool:
        return bool(self._dev.get("Active"))

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def ip_address(self) -> str | None:
        return self._dev.get("IPAddress") or None

    @property
    def hostname(self) -> str | None:
        return self._dev.get("Name") or None

    @property
    def icon(self) -> str:
        return "mdi:wifi" if self._dev.get("_link") == "wifi" else "mdi:ethernet"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self._dev
        attrs = {
            "connection": dev.get("_link"),
            "interface": dev.get("Layer2Interface"),
            "band": dev.get("OperatingFrequencyBand"),
            "signal_strength": dev.get("SignalStrength"),
            "signal_noise_ratio": dev.get("SignalNoiseRatio"),
            "downlink_rate_kbps": dev.get("LastDataDownlinkRate"),
            "uplink_rate_kbps": dev.get("LastDataUplinkRate"),
            "standard": dev.get("OperatingStandard"),
            "device_type": dev.get("DeviceType"),
            "last_connection": dev.get("LastConnection"),
            "first_seen": dev.get("FirstSeen"),
        }
        return {k: v for k, v in attrs.items() if v not in (None, "", 0)}
