"""Buttons: restart, start/stop WPS pairing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .api import KPNBoxError
from .coordinator import KPNBoxCoordinator
from .entity import KPNBoxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(
        [
            RebootButton(c, "reboot", "Restart"),
            ActionButton(c, "wps_start", "Start WPS pairing", "mdi:wifi-plus", c.api.start_wps_pairing),
            ActionButton(c, "wps_stop", "Stop WPS pairing", "mdi:wifi-cancel", c.api.stop_wps_pairing),
            ActionButton(c, "wifi_rescan", "Scan Wi-Fi channels", "mdi:radar", c.async_rescan_wifi, refresh=False),
            ActionButton(c, "ring_phones", "Test ring phones", "mdi:phone-ring", c.api.ring_phones),
        ]
    )


class RebootButton(KPNBoxEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.reboot()
        except KPNBoxError:
            # The box often drops the connection while it goes down; that's expected
            pass


class ActionButton(KPNBoxEntity, ButtonEntity):
    def __init__(
        self,
        c: KPNBoxCoordinator,
        key: str,
        name: str,
        icon: str,
        action: Callable[[], Awaitable[None]],
        refresh: bool = True,
    ) -> None:
        super().__init__(c, key, name)
        self._attr_icon = icon
        self._action, self._refresh = action, refresh

    async def async_press(self) -> None:
        if self._refresh:
            await self.coordinator.async_run(self._action())
        else:  # the action refreshes by itself
            try:
                await self._action()
            except KPNBoxError as err:
                raise HomeAssistantError(f"KPN Box rejected the request: {err}") from err
