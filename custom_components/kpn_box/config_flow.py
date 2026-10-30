"""Config flow for KPN Box."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import DummyCookieJar
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import voluptuous as vol

from .api import KPNBoxApi, KPNBoxAuthError, KPNBoxError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRACK_DEVICES,
    CONF_USE_EVENTS,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class KPNBoxConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KPNBoxOptionsFlow()

    async def _validate(self, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        # Short-lived: closed below, so HA shouldn't also schedule a close for it
        session = async_create_clientsession(self.hass, auto_cleanup=False, cookie_jar=DummyCookieJar())
        api = KPNBoxApi(session, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])
        try:
            await api.login()
            info = await api.device_info()
            await api.logout()
        except KPNBoxAuthError:
            return {}, {"base": "invalid_auth"}
        except KPNBoxError:
            return {}, {"base": "cannot_connect"}
        finally:
            await session.close()
        return info, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            info, errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(info.get("SerialNumber") or user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"KPN Box ({info.get('ProductClass', user_input[CONF_HOST])})",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            _, errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class KPNBoxOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                vol.Required(CONF_TRACK_DEVICES, default=options.get(CONF_TRACK_DEVICES, True)): bool,
                vol.Required(CONF_USE_EVENTS, default=options.get(CONF_USE_EVENTS, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
