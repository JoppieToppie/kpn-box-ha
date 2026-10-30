"""KPN Box: monitoring and full control of KPN Box 12 / prpl-based KPN gateways."""

from __future__ import annotations

from aiohttp import DummyCookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import KPNBoxApi
from .const import CONF_USE_EVENTS, DOMAIN
from .coordinator import KPNBoxCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type KPNBoxConfigEntry = ConfigEntry[KPNBoxCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    from .services import async_setup_services

    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KPNBoxConfigEntry) -> bool:
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    api = KPNBoxApi(session, entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = KPNBoxCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if entry.options.get(CONF_USE_EVENTS, True):
        # Cancelled automatically when the entry unloads
        entry.async_create_background_task(hass, coordinator.async_listen_events(), "kpn_box events")
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: KPNBoxConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KPNBoxConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # The box only allows a few contexts at once; free ours
        await entry.runtime_data.api.logout()
    return unloaded
