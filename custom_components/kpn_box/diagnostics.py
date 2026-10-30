"""Diagnostics download (Settings → Devices → KPN Box → Download diagnostics)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import KPNBoxConfigEntry

REDACT = {
    CONF_PASSWORD,
    "SerialNumber",
    "BaseMAC",
    "MACAddress",
    "IPAddress",
    "ExternalIPAddress",
    "IPv6Address",
    "IPv6DelegatedPrefix",
    "RemoteGateway",
    "PhysAddress",
    "Key",
    "SSID",
    "BSSID",
    "KeyPassPhrase",
    "PreSharedKey",
    "SAEPassphrase",
    "IPv4Address",
    "ID",
    "DestinationIPAddress",
    "UUID",
    "SelfPIN",
    "hosts",
    "directoryNumber",
    "authUserName",
    "authPassword",
    "remoteNumber",
    "remoteName",
    "registrarServer",
    "outboundProxyServer",
    "userAgentDomain",
    "eventSubscribeAuthPassword",
    "eventSubscribeAuthUserName",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: KPNBoxConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = asdict(coordinator.data)
    # These are keyed by MAC address; re-key so the MACs don't leak through the keys
    for key in ("devices", "access_schedules"):
        data[key] = {f"device_{i}": v for i, v in enumerate(data[key].values())}
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "interfaces": coordinator.interfaces,
            "radios": coordinator.radios,
            "data": data,
        },
        REDACT,
    )
