"""Actions (services) and the configuration entities added in 0.4.0, against the fake KPN Box."""

from datetime import time as t

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from test_kpn_box import DOMAIN, box, clock, eid, entry  # noqa: F401 (fixtures)

from custom_components.kpn_box.services import week_ranges


async def call(hass, service, data):
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


def test_week_ranges() -> None:
    # Mon 09:00-17:00, and Sun 22:00 -> Mon 07:00 wraps to the start of the week
    assert week_ranges(
        [{"days": ["mon"], "start": t(9), "end": t(17)}, {"days": ["sun"], "start": t(22), "end": t(7)}]
    ) == [
        {"state": "Disable", "begin": 0, "end": 7 * 3600},
        {"state": "Disable", "begin": 9 * 3600, "end": 17 * 3600},
        {"state": "Disable", "begin": 6 * 86400 + 22 * 3600, "end": 7 * 86400},
    ]
    # An end of 00:00 means midnight
    assert week_ranges([{"days": ["tue"], "start": t(20), "end": t(0)}]) == [
        {"state": "Disable", "begin": 86400 + 20 * 3600, "end": 2 * 86400}
    ]


async def test_wifi_and_schedule_actions(hass: HomeAssistant, entry, box) -> None:
    await call(hass, "set_wifi_network", {"network": "main", "ssid": "Home", "password": "supersecret"})
    sec = {"ModeEnabled": "WPA2-WPA3-Personal", "KeyPassPhrase": "supersecret", "MFPConfig": "Optional"}
    assert box.writes == [
        (
            "NeMo.Intf.lan",
            "setWLANConfig",
            {
                "mibs": {
                    "wlanvap": {
                        "vap2g0priv": {"SSID": "Home", "Security": sec},
                        "vap5g0priv": {"SSID": "Home", "Security": sec},
                    }
                }
            },
        )
    ]
    box.writes.clear()
    await call(
        hass,
        "set_wifi_network",
        {"network": "guest", "ssid": "Gast", "password": "welcome123", "security": "WPA2-Personal", "pmf": "Disabled"},
    )
    off = {"Enable": False, "PersistentEnable": False, "Status": False}  # guest is off, so it stays off
    assert box.writes[0][2]["mibs"]["penable"] == {"vap2g0guest": off, "vap5g0guest": off}
    with pytest.raises(Exception):
        await call(hass, "set_wifi_network", {"network": "main", "ssid": "x", "password": "short"})

    box.writes.clear()
    await call(
        hass,
        "set_device_schedule",
        {"mac": "aa:aa:aa:aa:aa:01", "blocked_periods": [{"days": ["mon"], "start": "21:00", "end": "23:00"}]},
    )
    assert box.writes == [
        (
            "Scheduler",
            "addSchedule",
            {
                "type": "ToD",
                "info": {
                    "base": "Weekly",
                    "def": "Enable",
                    "ID": "AA:AA:AA:AA:AA:01",
                    "schedule": [{"state": "Disable", "begin": 21 * 3600, "end": 23 * 3600}],
                    "enable": True,
                    "override": "",
                },
            },
        )
    ]
    box.writes.clear()
    await call(hass, "set_wifi_schedule", {"off_periods": [{"days": ["sat"], "start": "01:00", "end": "06:00"}]})
    assert box.writes[0][2]["type"] == "WLAN" and box.writes[0][2]["info"]["ID"] == "wl0"
    box.writes.clear()
    with pytest.raises(Exception):
        await call(hass, "set_mac_filter", {"enabled": True, "allowed_macs": []})
    await call(hass, "set_mac_filter", {"enabled": True, "allowed_macs": ["aa:aa:aa:aa:aa:01"]})
    flt = {"MACFiltering": {"Mode": "WhiteList", "Entry": {"1": {"MACAddress": "AA:AA:AA:AA:AA:01"}}}}
    assert box.writes == [
        (
            "NeMo.Intf.lan",
            "setWLANConfig",
            {"mibs": {"wlanvap": {"vap2g0priv": flt, "vap5g0priv": flt, "vap2g0ext": flt, "vap5g0ext": flt}}},
        )
    ]


async def test_rule_and_device_actions(hass: HomeAssistant, entry, box) -> None:
    await call(
        hass,
        "add_port_forward",
        {"name": "Minecraft", "external_port": 25565, "ip_address": "192.168.2.16", "protocol": "both"},
    )
    assert box.writes == [
        (
            "Firewall",
            "setPortForwarding",
            {
                "id": "Minecraft",
                "internalPort": "25565",
                "externalPort": "25565",
                "destinationIPAddress": "192.168.2.16",
                "enable": True,
                "persistent": True,
                "protocol": "6,17",
                "description": "Minecraft",
                "sourceInterface": "data",
                "origin": "webui",
                "destinationMACAddress": "",
                "sourcePrefix": "",
            },
        )
    ]
    box.writes.clear()
    await call(hass, "remove_port_forward", {"name": "NAS"})
    assert box.writes == [
        (
            "Firewall",
            "deletePortForwarding",
            {"id": "webui_NAS", "origin": "webui", "destinationIPAddress": "192.168.2.16"},
        )
    ]
    box.writes.clear()
    await call(hass, "add_ipv6_pinhole", {"name": "web", "port": "443", "ip_address": "2a02::5"})
    assert box.writes[0][1] == "setPinhole" and box.writes[0][2]["ipversion"] == 6
    await call(hass, "remove_ipv6_pinhole", {"id": "ph1"})
    assert box.writes[1] == ("Firewall", "deletePinhole", {"id": "ph1", "origin": "webui"})
    box.writes.clear()
    await call(
        hass, "add_firewall_rule", {"id": "rdp", "action": "Drop", "destination_port": "3389", "ip_version": "4"}
    )
    assert box.writes == [
        (
            "Firewall",
            "setCustomRule",
            {
                "id": "rdp",
                "chain": "Custom",
                "action": "Drop",
                "destinationPort": "3389",
                "sourcePort": "",
                "destinationPrefix": "",
                "sourcePrefix": "",
                "protocol": "6",
                "ipversion": 4,
                "enable": True,
            },
        )
    ]
    # Firewall-rule switches start disabled; enable one like a user would
    rule = eid(hass, "switch", "fwrule_ssh")
    assert er.async_get(hass).async_get(rule).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    er.async_get(hass).async_update_entity(rule, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    box.writes.clear()
    await hass.services.async_call("switch", "turn_off", {"entity_id": rule}, blocking=True)
    assert box.writes[0][2]["enable"] is False and box.writes[0][2]["destinationPort"] == "22"
    box.writes.clear()
    await call(hass, "add_static_lease", {"mac": "aa:aa:aa:aa:aa:01", "ip_address": "192.168.2.50"})
    await call(hass, "remove_static_lease", {"mac": "aa:aa:aa:aa:aa:01"})
    await call(hass, "rename_device", {"mac": "aa:aa:aa:aa:aa:01", "name": "Phone"})
    await call(hass, "set_device_type", {"mac": "aa:aa:aa:aa:aa:01", "type": "Mobile"})
    await call(hass, "remove_device", {"mac": "aa:aa:aa:aa:aa:02"})
    assert box.writes == [
        (
            "DHCPv4.Server.Pool.default",
            "addStaticLease",
            {"MACAddress": "AA:AA:AA:AA:AA:01", "IPAddress": "192.168.2.50"},
        ),
        ("DHCPv4.Server.Pool.default", "deleteStaticLease", {"MACAddress": "AA:AA:AA:AA:AA:01"}),
        ("Devices.Device.AA:AA:AA:AA:AA:01", "setName", {"name": "Phone"}),
        ("Devices.Device.AA:AA:AA:AA:AA:01", "setType", {"type": "Mobile"}),
        ("Devices", "destroyDevice", {"key": "AA:AA:AA:AA:AA:02"}),
    ]


async def test_lan_and_network_actions(hass: HomeAssistant, entry, box) -> None:
    await call(hass, "set_lan", {"dhcp_end": "192.168.2.150", "dns_servers": ["1.1.1.1"]})
    assert box.writes == [
        (
            "NetMaster.LAN.default.Bridge.lan",
            "setIPv4",
            {
                "Address": "192.168.2.254",
                "PrefixLength": "24",
                "DHCPEnable": True,
                "DHCPMinAddress": "192.168.2.1",
                "DHCPMaxAddress": "192.168.2.150",
                "LeaseTime": "86400",
                "DHCPAuthoritative": "true",
                "DNSServers": "1.1.1.1",
            },
        )
    ]
    box.writes.clear()
    await call(hass, "set_guest_lan", {"lease_time": 3600})
    assert box.writes[0][0] == "NetMaster.LAN.default.Bridge.guest" and box.writes[0][2]["LeaseTime"] == "3600"
    box.writes.clear()
    await call(hass, "set_hostname", {"hostname": "kpnbox", "domain": "lan"})
    assert box.writes == [
        ("NetMaster.LAN.default.Bridge.lan", "setHostName", {"Key": "default", "HostName": "kpnbox", "IPVersion": 0}),
        ("NetMaster.LAN.default.Bridge.lan", "set", {"DomainName": "lan"}),
    ]
    box.writes.clear()
    await call(
        hass, "add_dyndns_host", {"service": "No-IP", "hostname": "me.ddns.net", "username": "u", "password": "p"}
    )
    await call(hass, "set_dyndns_enabled", {"enabled": True})
    await call(hass, "remove_dyndns_host", {"hostname": "me.ddns.net"})
    assert [w[1] for w in box.writes] == ["addHost", "setGlobalEnable", "delHost"]
    box.writes.clear()
    await hass.services.async_call(
        "select", "select_option", {"entity_id": eid(hass, "select", "ipv6_mode"), "option": "enabled"}, blocking=True
    )
    assert box.writes == [("NetMaster", "set", {"EnableIPv6": 1, "IPv6PrefixMode": "RA"})]
    box.writes.clear()
    for key in ("respond_to_ping", "upnp"):
        await hass.services.async_call("switch", "turn_off", {"entity_id": eid(hass, "switch", key)}, blocking=True)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": eid(hass, "switch", "extra_vap5g0ext")}, blocking=True
    )
    assert box.writes == [
        (
            "Firewall",
            "setRespondToPing",
            {"sourceInterface": "data", "service_enable": {"enableIPv4": False, "enableIPv6": False}},
        ),
        ("Firewall", "set", {"UpnpPortForwardingEnable": False}),
        (
            "NeMo.Intf.lan",
            "setWLANConfig",
            {"mibs": {"penable": {"vap5g0ext": {"Enable": True, "PersistentEnable": True, "Status": True}}}},
        ),
    ]
    dhcp = hass.states.get(eid(hass, "sensor", "dhcp"))
    assert dhcp.state == "192.168.2.1 - 192.168.2.200"
    assert dhcp.attributes["dns_servers"] == "192.168.2.26,1.1.1.1"


async def test_router_ip_change_moves_entry(hass: HomeAssistant, entry, box, aioclient_mock) -> None:
    await call(hass, "set_lan", {"router_ip": "192.168.2.254"})  # same IP: entry untouched
    assert entry.data[CONF_HOST] == "192.168.2.254"
    # The box now answers on its new address
    aioclient_mock.post("http://192.168.10.1/ws/NeMo/Intf/lan:getMIBs", side_effect=box.handler)
    await call(hass, "set_lan", {"router_ip": "192.168.10.1"})
    await hass.async_block_till_done()
    assert entry.data[CONF_HOST] == "192.168.10.1"
    assert entry.state is ConfigEntryState.LOADED  # reloaded against the new IP


async def test_admin_password(hass: HomeAssistant, entry, box) -> None:
    with pytest.raises(Exception):
        await call(hass, "change_admin_password", {"current_password": "wrong", "new_password": "newsecret1"})
    box.password = "newsecret1"  # what the real box does once the change goes through
    await call(hass, "change_admin_password", {"current_password": "secret", "new_password": "newsecret1"})
    await hass.async_block_till_done()
    assert box.writes == [
        ("UserManagement", "changePasswordSec", {"name": "admin", "password": "newsecret1", "old_password": "secret"})
    ]
    assert entry.data[CONF_PASSWORD] == "newsecret1"
    assert entry.state is ConfigEntryState.LOADED  # reloaded and logged in with the new password


async def test_factory_reset_and_firmware_install(hass: HomeAssistant, entry, box) -> None:
    with pytest.raises(Exception):
        await call(hass, "factory_reset", {"confirm": "yes"})
    assert box.writes == []
    # HA only allows install when an update is offered
    coordinator = entry.runtime_data
    coordinator._firmware = {"updateAvailable": True, "currentVersion": "26.04.02.0", "newVersion": "26.10.01.0"}
    await coordinator.async_refresh()
    fw = eid(hass, "update", "firmware")
    assert hass.states.get(fw).state == "on" and hass.states.get(fw).attributes["latest_version"] == "26.10.01.0"
    await hass.services.async_call("update", "install", {"entity_id": fw}, blocking=True)
    await call(hass, "factory_reset", {"confirm": "factory reset"})
    assert box.writes == [("WebuiupgradeService", "upgrade", {}), ("NMC", "factoryReset", {})]
