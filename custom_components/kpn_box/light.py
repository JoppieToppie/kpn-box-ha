"""Light: brightness of the status LEDs on the front of the box."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KPNBoxConfigEntry
from .entity import KPNBoxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KPNBoxConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.data.leds:
        async_add_entities([StatusLeds(coordinator, "leds", "Status LEDs")])


class StatusLeds(KPNBoxEntity, LightEntity):
    _attr_icon = "mdi:led-on"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def brightness(self) -> int | None:
        values = [
            led.get("Brightness")
            for led in self.coordinator.data.leds.values()
            if isinstance(led.get("Brightness"), int)
        ]
        return max(values) if values else None

    @property
    def is_on(self) -> bool:
        return bool(self.brightness)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {name: led.get("CurrentColor") for name, led in self.coordinator.data.leds.items()}

    async def _set(self, brightness: int) -> None:
        await self.coordinator.async_run(
            self.coordinator.api.set_led_brightness(list(self.coordinator.data.leds), brightness)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(kwargs.get(ATTR_BRIGHTNESS, 255))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(0)
