"""Binary sensors: internet connectivity, DMZ active, WPS pairing in progress."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .entity import KPNBoxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            KPNBoxInternet(c, "internet", "Internet"),
            DMZActive(c, "dmz", "DMZ"),
            WPSPairing(c, "wps_pairing", "WPS pairing"),
        ]
    )


class KPNBoxInternet(KPNBoxEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        wan = self.coordinator.data.wan
        return wan.get("ConnectionState") == "Connected" and wan.get("LinkState") == "up"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        wan = self.coordinator.data.wan
        return {"ip_address": wan.get("IPAddress"), "link_type": wan.get("LinkType"), "protocol": wan.get("Protocol")}


class DMZActive(KPNBoxEntity, BinarySensorEntity):
    """On when a device is exposed as DMZ host. Set/clear with the kpn_box.set_dmz / clear_dmz actions."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY  # on = unsafe
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return any(d.get("Enable", True) for d in self.coordinator.data.dmz.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hosts = [d.get("DestinationIPAddress") for d in self.coordinator.data.dmz.values()]
        return {"hosts": hosts}


class WPSPairing(KPNBoxEntity, BinarySensorEntity):
    _attr_icon = "mdi:wifi-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return any(w.get("PairingInProgress") for w in self.coordinator.data.wps.values())
