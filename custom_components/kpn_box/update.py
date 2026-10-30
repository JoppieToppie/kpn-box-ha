"""Update entity: KPN firmware availability, with install (same call as the web UI's upgrade)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .api import KPNBoxError
from .entity import KPNBoxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([FirmwareUpdate(entry.runtime_data, "firmware", "Firmware")])


class FirmwareUpdate(KPNBoxEntity, UpdateEntity):
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        return data.info.get("SoftwareVersion") or data.firmware.get("currentVersion")

    @property
    def latest_version(self) -> str | None:
        fw = self.coordinator.data.firmware
        if not fw:
            return None
        # The box reports versions as "26.04.02.0"; show the full SoftwareVersion unless an update exists
        return fw.get("newVersion") if fw.get("updateAvailable") else self.installed_version

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        try:
            await self.coordinator.api.install_firmware()
        except KPNBoxError:
            pass  # the box restarts while upgrading and may drop the connection
