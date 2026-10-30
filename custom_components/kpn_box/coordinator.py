"""Polling coordinator: reads everything the integration shows in one pass."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import KPNBoxApi, KPNBoxAuthError, KPNBoxError, KPNBoxNotFound
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRACK_DEVICES,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_EXPRESSION,
    DOMAIN,
    EVENT_HANDLERS,
    FIRMWARE_CHECK_INTERVAL,
    GUEST_VAPS,
    INTERFACES,
    LAN_PORTS,
    RADIOS,
    SLOW_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class KPNBoxData:
    traffic: dict[str, dict[str, Any]] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)
    wan: dict[str, Any] = field(default_factory=dict)
    wifi: dict[str, Any] = field(default_factory=dict)
    radios: dict[str, dict[str, Any]] = field(default_factory=dict)
    guest_vaps: dict[str, Any] = field(default_factory=dict)
    guest: dict[str, Any] = field(default_factory=dict)
    guest_timer: Any = None
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)  # MAC -> device, with "_link" wifi/eth
    firewall_level: str | None = None
    leds: dict[str, Any] = field(default_factory=dict)
    firmware: dict[str, Any] = field(default_factory=dict)
    last_boot: datetime | None = None
    access_schedules: dict[str, dict[str, Any]] = field(default_factory=dict)  # MAC -> ToD schedule
    wifi_schedule: dict[str, Any] | None = None
    port_forwards: dict[str, dict[str, Any]] = field(default_factory=dict)
    upnp_forwards: dict[str, dict[str, Any]] = field(default_factory=dict)
    pinholes: dict[str, dict[str, Any]] = field(default_factory=dict)
    dmz: dict[str, dict[str, Any]] = field(default_factory=dict)
    wps: dict[str, dict[str, Any]] = field(default_factory=dict)  # vap -> WPS object
    private_vaps: dict[str, Any] = field(default_factory=dict)
    respond_to_ping: dict[str, Any] = field(default_factory=dict)
    firewall: dict[str, Any] = field(default_factory=dict)
    custom_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    static_leases: list[dict[str, Any]] = field(default_factory=list)
    dhcp: dict[str, Any] = field(default_factory=dict)
    guest_dhcp: dict[str, Any] = field(default_factory=dict)
    netmaster: dict[str, Any] = field(default_factory=dict)
    dyndns: list[dict[str, Any]] = field(default_factory=list)
    eth: dict[str, dict[str, Any]] = field(default_factory=dict)  # lower interface (eth0..) -> link settings
    port_network: dict[str, str] = field(default_factory=dict)  # ETH0.. -> "lan" / "guest"
    stp: dict[str, bool] = field(default_factory=dict)  # bridge -> STP on
    steering: dict[str, Any] = field(default_factory=dict)
    ipv6_delegation: dict[str, Any] = field(default_factory=dict)
    sip_conntrack: dict[str, Any] = field(default_factory=dict)
    password_recovery: dict[str, Any] = field(default_factory=dict)
    # refreshed every SLOW_POLL_INTERVAL
    scan: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # band -> neighbouring networks
    spectrum: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # band -> per-channel availability
    trunks: list[dict[str, Any]] = field(default_factory=list)
    handsets: list[dict[str, Any]] = field(default_factory=list)
    phone_groups: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    extenders: list[dict[str, Any]] = field(default_factory=list)
    wan_modes: list[str] = field(default_factory=list)


class KPNBoxCoordinator(DataUpdateCoordinator[KPNBoxData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: KPNBoxApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.api = api
        self.track_devices: bool = entry.options.get(CONF_TRACK_DEVICES, True)
        self.device_info: dict[str, Any] = {}
        self.interfaces: list[str] = []
        self.radios: list[str] = []
        self.serial: str = entry.unique_id or entry.entry_id
        self._last: dict[str, tuple[float, int, int]] = {}
        self._firmware: dict[str, Any] = {}
        self._firmware_checked = 0.0
        self._last_boot: datetime | None = None
        self.port_lower: dict[str, str] = {}  # ETH0 -> eth0 (where speed/duplex live)
        self._slow: dict[str, Any] = {}
        self._slow_checked = 0.0

    async def _async_setup(self) -> None:
        """Read device info and find which interfaces/radios this firmware exposes."""
        try:
            self.device_info = await self.api.device_info()
            self.serial = self.device_info.get("SerialNumber") or self.serial
            for intf in INTERFACES:
                try:
                    await self.api.net_dev_stats(intf)
                    self.interfaces.append(intf)
                except KPNBoxNotFound:
                    _LOGGER.debug("Interface %s not available", intf)
            for key, (radio, _, _) in RADIOS.items():
                try:
                    await self.api.radio(radio)
                    self.radios.append(key)
                except KPNBoxNotFound:
                    _LOGGER.debug("Radio %s not available", radio)
            for port in LAN_PORTS:
                lower = await self._optional(self.api.lower_interface(port))
                if lower:
                    self.port_lower[port] = lower
        except KPNBoxAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except KPNBoxError as err:
            raise UpdateFailed(err) from err

    async def _optional(self, coro, default=None):
        """Data that some firmwares lack shouldn't fail the whole update."""
        try:
            return await coro
        except KPNBoxNotFound:
            return default

    async def _async_update_data(self) -> KPNBoxData:
        api = self.api
        data = KPNBoxData()
        try:
            for intf in self.interfaces:
                data.traffic[intf] = self._with_rates(intf, await api.net_dev_stats(intf))
            data.info = await api.device_info()
            data.wan = await api.wan_status()
            data.wifi = await self._optional(api.wifi_status(), {})
            for key in self.radios:
                data.radios[key] = await api.radio(RADIOS[key][0])
            data.guest_vaps = await self._optional(api.guest_vaps(), {})
            data.guest = await self._optional(api.guest_settings(), {})
            data.guest_timer = await self._optional(api.guest_timer())
            data.firewall_level = await self._optional(api.firewall_level())
            data.leds = await self._optional(api.leds(), {})
            for link, devices in (await self._optional(api.devices(DEVICE_EXPRESSION), {})).items():
                for dev in devices or []:
                    if mac := (dev.get("PhysAddress") or dev.get("Key") or "").upper():
                        data.devices[mac] = {**dev, "_link": link}
            data.access_schedules = {
                s["ID"].upper(): s for s in await self._optional(api.schedules("ToD"), []) if s.get("ID")
            }
            data.wifi_schedule = next(iter(await self._optional(api.schedules("WLAN"), [])), None)
            data.port_forwards = await self._optional(api.port_forwards("webui"), {})
            data.upnp_forwards = await self._optional(api.port_forwards("upnp"), {})
            data.pinholes = await self._optional(api.pinholes(), {})
            data.dmz = await self._optional(api.dmz(), {})
            data.private_vaps = await self._optional(api.private_vaps(), {})
            for key in self.radios:
                vap = RADIOS[key][1]
                data.wps[vap] = await self._optional(api.wps(vap), {})
            data.respond_to_ping = await self._optional(api.respond_to_ping(), {})
            data.firewall = await self._optional(api.firewall_settings(), {})
            data.custom_rules = await self._optional(api.custom_rules(), {})
            data.static_leases = await self._optional(api.static_leases(), [])
            data.dhcp = await self._optional(api.dhcp_pool("default"), {})
            data.guest_dhcp = await self._optional(api.dhcp_pool("guest"), {})
            data.netmaster = await self._optional(api.netmaster(), {})
            data.dyndns = await self._optional(api.dyndns_hosts(), [])
            data.eth = await self._optional(api.eth_ports(), {})
            for bridge in ("lan", "guest"):
                nemo = "bridge" if bridge == "lan" else "brguest"
                members = await self._optional(api.bridge_members(nemo), [])
                data.port_network.update({p: bridge for p in members if p in LAN_PORTS})
                data.stp[nemo] = await self._optional(api.stp(nemo), False)
            data.steering = await self._optional(api.steering(), {})
            data.ipv6_delegation = await self._optional(api.ipv6_delegation(), {})
            data.sip_conntrack = await self._optional(api.sip_conntrack(), {})
            data.password_recovery = await self._optional(api.password_recovery(), {})
            await self._slow_poll(data)
            if time.monotonic() - self._firmware_checked > FIRMWARE_CHECK_INTERVAL or not self._firmware_checked:
                self._firmware = await self._optional(api.latest_firmware(), {})
                self._firmware_checked = time.monotonic()
            data.firmware = self._firmware
        except KPNBoxAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except KPNBoxError as err:
            raise UpdateFailed(err) from err

        data.last_boot = self._boot_time(data.info.get("UpTime"))
        return data

    async def _slow_poll(self, data: KPNBoxData, force: bool = False) -> None:
        """Things that change slowly or cost the box more: neighbour scan, spectrum, telephone, extenders."""
        api = self.api
        if force or not self._slow_checked or time.monotonic() - self._slow_checked > SLOW_POLL_INTERVAL:
            slow: dict[str, Any] = {"scan": {}, "spectrum": {}}
            for key in self.radios:
                radio = RADIOS[key][0]
                slow["scan"][key] = await self._optional(api.scan_results(radio), [])
                slow["spectrum"][key] = await self._optional(api.spectrum(radio), [])
            slow["trunks"] = await self._optional(api.voice("listTrunks"), []) or []
            slow["handsets"] = await self._optional(api.voice("listHandsets"), []) or []
            slow["phone_groups"] = await self._optional(api.voice("listGroups"), []) or []
            slow["calls"] = await self._optional(api.voice("getCallList"), []) or []
            slow["extenders"] = await self._optional(api.extenders(), []) or []
            slow["wan_modes"] = await self._optional(api.wan_modes(), []) or []
            self._slow, self._slow_checked = slow, time.monotonic()
        for key, value in self._slow.items():
            setattr(data, key, value)

    async def async_rescan_wifi(self) -> None:
        """Measure the spectrum again (like the web UI's refresh) and re-read everything slow."""
        for key in self.radios:
            await self.api.spectrum(RADIOS[key][0], update=True)
        self._slow_checked = 0.0
        await self.async_refresh()

    def _boot_time(self, uptime: int | None) -> datetime | None:
        if uptime is None:
            return None
        boot = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(microsecond=0)
        # Keep the timestamp stable between polls; only move it on a real reboot (or > 1 min drift)
        if self._last_boot is None or abs((boot - self._last_boot).total_seconds()) > 60:
            self._last_boot = boot
        return self._last_boot

    def _with_rates(self, intf: str, stats: dict[str, Any]) -> dict[str, Any]:
        now = time.monotonic()
        rx, tx = stats.get("RxBytes"), stats.get("TxBytes")
        rx_rate = tx_rate = None
        if (prev := self._last.get(intf)) and rx is not None and tx is not None:
            dt = now - prev[0]
            # A drop means the counter reset (reboot); skip the rate for that poll
            if dt > 0 and rx >= prev[1] and tx >= prev[2]:
                rx_rate = (rx - prev[1]) * 8 / dt / 1_000_000
                tx_rate = (tx - prev[2]) * 8 / dt / 1_000_000
        if rx is not None and tx is not None:
            self._last[intf] = (now, rx, tx)
        return {**stats, "rx_rate": rx_rate, "tx_rate": tx_rate}

    async def async_listen_events(self) -> None:
        """Long-poll the box's event channel; refresh right away when devices, schedules etc. change.

        Polling keeps running as a fallback, so a broken channel only costs speed.
        """
        while True:
            try:
                channel = await self.api.open_event_channel(EVENT_HANDLERS)
                _LOGGER.debug("Event channel %s open", channel)
                while True:
                    events = await self.api.get_events(channel, EVENT_HANDLERS)
                    if events:
                        _LOGGER.debug("Box events: %s", events)
                        await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep listening whatever the box does
                _LOGGER.debug("Event channel error, reconnecting in 30 s: %s", err)
                await asyncio.sleep(30)

    @property
    def guest_vap_names(self) -> tuple[str, ...]:
        return tuple(v for v in GUEST_VAPS if v in (self.data.guest_vaps if self.data else {})) or GUEST_VAPS

    async def async_run(self, coro) -> None:
        """Run a write call, then refresh so entities show the new state."""
        try:
            await coro
        except KPNBoxError as err:
            raise HomeAssistantError(f"KPN Box rejected the change: {err}") from err
        # Not the debounced request_refresh: back-to-back changes must show their result right away
        await self.async_refresh()
