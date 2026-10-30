"""v0.5.0: radio details, scans, LAN ports, STP, IPv6 delegation, telephone, system extras, generic call/describe."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from test_kpn_box import DOMAIN, URL, box, clock, eid, entry  # noqa: F401 (fixtures)


async def svc(hass, domain, service, data, **kw):
    return await hass.services.async_call(domain, service, data, blocking=True, **kw)


async def test_radio_selects_and_switches(hass: HomeAssistant, entry, box) -> None:
    width = eid(hass, "select", "5g_channel_width")
    state = hass.states.get(width)
    assert state.state == "80MHz" and state.attributes["options"] == ["AUTO", "20MHz", "40MHz", "80MHz"]
    await svc(hass, "select", "select_option", {"entity_id": width, "option": "40MHz"})
    # Channel stays automatic, standards unchanged
    assert box.writes == [
        (
            "NeMo.Intf.rad5g0",
            "setWLANConfig",
            {
                "mibs": {
                    "wlanradio": {
                        "rad5g0": {
                            "AutoChannelEnable": True,
                            "OperatingChannelBandwidth": "40MHz",
                            "OperatingStandards": "a,n,ac,ax",
                        }
                    }
                }
            },
        )
    ]
    box.writes.clear()
    await svc(hass, "select", "select_option", {"entity_id": eid(hass, "select", "2g_standards"), "option": "g,n,ax"})
    assert box.writes[0][2]["mibs"]["wlanradio"]["rad2g0"]["OperatingStandards"] == "g,n,ax"
    box.writes.clear()
    legacy = eid(hass, "switch", "legacy_11b")
    assert hass.states.get(legacy).state == "off"
    await svc(hass, "switch", "turn_on", {"entity_id": legacy})
    assert box.writes == [
        ("NeMo.Intf.rad2g0", "set", {"OperationalDataTransmitRates": "1,2,5.5,6,9,11,12,18,24,36,48,54"})
    ]
    # Extender-only switches start disabled
    reg = er.async_get(hass)
    assert reg.async_get(eid(hass, "switch", "extender_sync")).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert reg.async_get(eid(hass, "switch", "local_wifi_off")).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_scan_sensors_and_rescan(hass: HomeAssistant, entry, box) -> None:
    near = hass.states.get(eid(hass, "sensor", "2g_neighbours"))
    assert near.state == "2"
    assert near.attributes["networks"][0] == {"ssid": "(hidden)", "channel": 6, "signal": -50, "security": None}
    best = hass.states.get(eid(hass, "sensor", "5g_best_channel"))
    assert best.state == "6"  # 11 is more free but banned
    await svc(hass, "button", "press", {"entity_id": eid(hass, "button", "wifi_rescan")})
    assert box.spectrum_updates == 2  # both bands measured again


async def test_lan_ports(hass: HomeAssistant, entry, box) -> None:
    assert hass.states.get(eid(hass, "sensor", "port2_link")).state == "100"
    speed = eid(hass, "select", "port1_speed")
    assert hass.states.get(speed).state == "auto"
    assert hass.states.get(speed).attributes["options"] == ["auto", "10 Mbit/s", "100 Mbit/s", "1 Gbit/s"]
    await svc(hass, "select", "select_option", {"entity_id": speed, "option": "100 Mbit/s"})
    await svc(hass, "select", "select_option", {"entity_id": eid(hass, "select", "port1_duplex"), "option": "Full"})
    assert box.writes == [
        ("NeMo.Intf.eth0", "set", {"MaxBitRateEnabled": 100}),
        ("NeMo.Intf.eth0", "set", {"DuplexModeEnabled": "Full"}),
    ]
    box.writes.clear()
    net = eid(hass, "select", "port2_network")
    assert hass.states.get(net).state == "home"
    await svc(hass, "select", "select_option", {"entity_id": net, "option": "guest"})
    assert box.writes == [
        ("NetMaster.LAN.default.Bridge.lan", "removeIntf", {"Intf": "ETH1"}),
        ("NetMaster.LAN.default.Bridge.guest", "addIntf", {"Intf": "ETH1"}),
    ]
    assert hass.states.get(net).state == "guest"
    box.writes.clear()
    await svc(hass, "switch", "turn_on", {"entity_id": eid(hass, "switch", "stp_bridge")})
    await svc(hass, "switch", "turn_off", {"entity_id": eid(hass, "switch", "ipv6_prefix_delegation")})
    await svc(hass, DOMAIN, "set_ipv6_delegation_length", {"length": 60})
    assert box.writes == [
        ("NeMo.Intf.bridge", "set", {"STPEnable": True}),
        ("NetMaster.LAN.default.Bridge.lan", "setIPv6Configuration", {"Name": "lan", "DHCPIAPDEnable": False}),
        ("NetMaster.LAN.default.Bridge.lan.IPv6.lan.DHCPv6", "set", {"IAPDPrefixLength": 60}),
    ]


async def test_telephone(hass: HomeAssistant, entry, box) -> None:
    calls = hass.states.get(eid(hass, "sensor", "phone_calls"))
    assert calls.state == "1"
    line = eid(hass, "switch", "phone_SIP-Trunk1_LINE11")
    # Not set up (no number) -> created disabled; enable it like a user would
    assert er.async_get(hass).async_get(line).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    er.async_get(hass).async_update_entity(line, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(line).state == "off"
    await svc(hass, "switch", "turn_on", {"entity_id": line})
    await svc(hass, "button", "press", {"entity_id": eid(hass, "button", "ring_phones")})
    await svc(
        hass,
        DOMAIN,
        "set_phone_line",
        {"number": "0201234567", "username": "u", "password": "p", "registrar": "sip.example.nl"},
    )
    await svc(hass, DOMAIN, "set_incoming_phones", {"handsets": ["FXS1"]})
    await svc(hass, DOMAIN, "set_outgoing_line", {"handset": "FXS1", "line": "LINE11"})
    await svc(hass, DOMAIN, "clear_phone_line", {})
    await svc(hass, "switch", "turn_off", {"entity_id": eid(hass, "switch", "sip_conntrack")})
    assert box.writes[0] == (
        "VoiceService.VoiceApplication",
        "setTrunk",
        {"trunk": {"name": "SIP-Trunk1", "trunk_lines": [{"name": "LINE11", "enable": "Enabled"}]}},
    )
    assert box.writes[1] == ("VoiceService.VoiceApplication", "ring", {})
    assert box.writes[2][2]["trunk"]["trunk_lines"][0]["directoryNumber"] == "0201234567"
    assert box.writes[3] == (
        "VoiceService.VoiceApplication",
        "setGroups",
        {"groups": [{"group_id": "Group1", "ep_names": ["FXS1"]}]},
    )
    assert box.writes[4] == (
        "VoiceService.VoiceApplication",
        "setHandset",
        {"line": {"line": "FXS1", "directoryNumber": "", "outgoingTrunkLine": "LINE11", "name": "FXS1"}},
    )
    assert box.writes[5][2]["trunk"]["enable"] == "Disabled"
    assert box.writes[6] == ("Firewall.ConnectionTracking.SIP", "set", {"Enable": False})


async def test_system_extras(hass: HomeAssistant, entry, box) -> None:
    for service, data in (
        ("reset_admin_password", {"confirm": "no"}),
        ("shutdown", {"confirm": "no"}),
        ("set_wan_mode", {"mode": "Ethernet_DHCP", "confirm": "no"}),
    ):
        with pytest.raises(Exception):
            await svc(hass, DOMAIN, service, data)
    with pytest.raises(Exception):  # not a mode this box offers
        await svc(hass, DOMAIN, "set_wan_mode", {"mode": "Cable", "confirm": "change wan mode"})
    assert box.writes == []
    await svc(hass, DOMAIN, "start_password_recovery", {})
    await svc(hass, DOMAIN, "set_wan_mode", {"mode": "Ethernet_DHCP", "confirm": "change wan mode"})
    await svc(hass, DOMAIN, "reset_admin_password", {"confirm": "reset password"})
    await svc(hass, DOMAIN, "shutdown", {"confirm": "shut down"})
    assert box.writes == [
        ("PasswordRecovery", "start", {}),
        ("NMC", "setWanMode", {"WanMode": "Ethernet_DHCP", "Username": "", "Password": ""}),
        ("NMC.GroupFunction", "ResetAdminPassword", {}),
        ("NMC", "shutdown", {"reason": "Home Assistant"}),
    ]


async def test_generic_call_and_describe(hass: HomeAssistant, entry, box, aioclient_mock) -> None:
    res = await svc(hass, DOMAIN, "call", {"service": "NMC", "method": "getWANStatus"}, return_response=True)
    assert res["data"]["ConnectionState"] == "Connected"
    await svc(
        hass,
        DOMAIN,
        "call",
        {"service": "NMC.Wifi", "method": "setEnable", "parameters": {"value": True}},
        return_response=True,
    )
    assert box.writes[-1] == ("NMC.Wifi", "setEnable", {"value": True})
    with pytest.raises(Exception):
        await svc(hass, DOMAIN, "call", {"service": "NMC", "method": "doesNotExist"}, return_response=True)

    aioclient_mock.get(
        URL.split("/ws/")[0] + "/sysbus/NMC/Wifi?_restDepth=0",
        json={
            "objectInfo": {"keyPath": "NMC", "key": "Wifi"},
            "functions": [{"name": "startPairing", "arguments": [{"name": "clientPIN"}]}],
            "parameters": [{"name": "Enable", "value": True}],
            "children": [{"objectInfo": {"key": "Stats"}}],
        },
    )
    res = await svc(hass, DOMAIN, "describe", {"object": "NMC.Wifi"}, return_response=True)
    assert res == {
        "object": "NMC.Wifi",
        "functions": {"startPairing": ["clientPIN"]},
        "parameters": {"Enable": True},
        "children": ["Stats"],
    }
