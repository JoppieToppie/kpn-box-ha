"""Base entity for KPN Box."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KPNBoxCoordinator, KPNBoxData


def add_dynamic_entities(
    entry: ConfigEntry,
    coordinator: KPNBoxCoordinator,
    keys: Callable[[KPNBoxData], Iterable[str]],
    factory: Callable[[str], Entity],
    async_add_entities: Callable[[Iterable[Entity]], None],
) -> None:
    """Add one entity per key now, and for keys that show up in later updates."""
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [k for k in keys(coordinator.data) if k not in known]
        known.update(new)
        if new:
            async_add_entities(factory(k) for k in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class KPNBoxEntity(CoordinatorEntity[KPNBoxCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KPNBoxCoordinator, key: str, name: str | None = None) -> None:
        super().__init__(coordinator)
        info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.serial}_{key}"
        if name is not None:
            self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            manufacturer=info.get("Manufacturer", "Sagemcom"),
            model=info.get("ModelName") or info.get("ProductClass"),
            name=f"KPN Box ({info.get('ProductClass', 'gateway')})",
            sw_version=info.get("SoftwareVersion"),
            hw_version=info.get("HardwareVersion"),
            serial_number=info.get("SerialNumber"),
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
        )
