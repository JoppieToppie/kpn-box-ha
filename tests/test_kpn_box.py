"""Load kpn_box in a real HA core against a fake KPN Box (responses modelled on the real box)."""

import asyncio
from datetime import timedelta
import json

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

DOMAIN = "kpn_box"
URL = "http://192.168.2.254/ws/NeMo/Intf/lan:getMIBs"
USER = {CONF_HOST: "192.168.2.254", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}
INFO = {
    "Manufacturer": "Sagemcom",
    "ModelName": "SagemcomFast5359_KPN",
    "ProductClass": "F5359s",
    "SerialNumber": "LK123",
    "SoftwareVersion": "V12.C.26.04.02",
    "HardwareVersion": "1.0",
    "UpTime": 3600,
    "ExternalIPAddress": "77.1.2.3",
}
WAN = {
    "LinkType": "ethernet",
    "LinkState": "up",
    "Protocol": "ppp",
    "ConnectionState": "Connected",
    "IPAddress": "77.1.2.3",
    "RemoteGateway": "195.1.1.1",
    "DNSServers": "195.121.97.202",
    "IPv6Address": "2a02::1",
    "IPv6DelegatedPrefix": "2a02:a46e:2d7::/48",
}
NOT_FOUND = {"status": None, "errors": [{"error": 196618, "description": "Object or parameter not found"}]}
DENIED = {"status": None, "errors": [{"error": 13, "description": "Permission denied"}]}
OK = {"status": True}


def radio(channel, possible, bw, std):
    return {
        "Enable": True,
        "RadioStatus": "Up",
        "Channel": channel,
        "AutoChannelEnable": True,
        "PossibleChannels": possible,
        "OperatingChannelBandwidth": bw,
        "CurrentOperatingChannelBandwidth": bw,
        "OperatingStandards": std,
        "ChannelLoad": 31,
        "Interference": 16,
        "Noise": -91,
        "ActiveAssociatedDevices": 6,
        "MaxChannelBandwidth": bw,
        "OperationalDataTransmitRates": "6,9,12,18,24,36,48,54",
    }


def device(mac, name, active, ip):
    return {
        "Key": mac,
        "PhysAddress": mac,
        "Name": name,
        "Active": active,
        "IPAddress": ip,
        "Layer2Interface": "wl0",
        "SignalStrength": -55,
    }


class FakeBox:
    def __init__(self):
        self.password = "secret"
        self.contexts = 0
        self.expire_next = False
        self.counters = {"eth4": [1000, 500], "ETH0": [10, 20], "vap2g0priv": [7, 9]}
        self.writes: list[tuple[str, str, dict]] = []
        self.wifi_devices = [
            device("AA:AA:AA:AA:AA:01", "phone", True, "192.168.2.5"),
            device("AA:AA:AA:AA:AA:02", "old-laptop", False, ""),
        ]
        self.eth_devices = [device("BB:BB:BB:BB:BB:01", "TOPNAS", True, "192.168.2.16")]
        self.leds = {
            "PowerGreen": {"Brightness": 255, "CurrentColor": "PlainGreen"},
            "WifiGreen": {"Brightness": 255, "CurrentColor": "PlainGreen"},
        }
        self.firewall = "Medium"
        # Real box: every known device has a ToD entry; blocked ones get override "Disable"
        self.schedules = {
            "AA:AA:AA:AA:AA:01": {
                "ID": "AA:AA:AA:AA:AA:01",
                "enable": False,
                "override": "",
                "value": "Enable",
                "schedule": [],
            }
        }
        self.forwards = {
            "webui_NAS": {
                "Id": "webui_NAS",
                "Origin": "webui",
                "Description": "NAS",
                "Protocol": "6",
                "ExternalPort": "5000",
                "InternalPort": "5000",
                "SourcePrefix": "",
                "DestinationIPAddress": "192.168.2.16",
                "Enable": False,
            }
        }
        self.upnp = {
            "upnp_1": {
                "Id": "upnp_1",
                "Description": "Parsec",
                "Protocol": "17",
                "ExternalPort": "21227",
                "InternalPort": "21227",
                "DestinationIPAddress": "192.168.2.19",
                "Enable": True,
            }
        }
        self.pinholes = {
            "ph1": {
                "Id": "ph1",
                "Description": "web",
                "Protocol": "6",
                "DestinationPort": "443",
                "DestinationIPAddress": "2a02::5",
                "Enable": True,
            }
        }
        self.dmz: dict = {}
        self.events: list = []
        self.event_waits = 0
        self.home_ports = ["ETH0", "ETH1"]
        self.guest_ports: list = []
        self.spectrum_updates = 0

    async def handler(self, method, url, data):
        body = json.loads(data) if isinstance(data, (str, bytes)) else data
        svc, meth, params = body["service"], body["method"], body.get("parameters") or {}
        if svc == "eventmanager":
            return self._resp(await self._events(meth, body, params))
        if meth == "createContext":
            if params["password"] != self.password:
                return self._resp({"status": None, "errors": [{"error": 13}]})
            self.contexts += 1
            return self._resp(
                {"status": 0, "data": {"contextID": f"ctx{self.contexts}"}},
                {"Set-Cookie": "a2724d9c/sessid=abc; path=/"},
            )
        if meth == "releaseContext":
            return self._resp({"status": 0})
        if self.expire_next:
            self.expire_next = False
            return self._resp(DENIED)
        if meth.startswith(
            (
                "set",
                "reboot",
                "disable",
                "add",
                "remove",
                "override",
                "enable",
                "start",
                "stop",
                "delete",
                "del",
                "change",
                "factory",
                "upgrade",
                "destroy",
                "ring",
                "shutdown",
                "Reset",
            )
        ):
            self.writes.append((svc, meth, params))
            self._apply(svc, meth, params)
            return self._resp(OK)
        return self._resp(self._read(svc, meth, params))

    def _apply(self, svc, meth, params):
        if svc == "Firewall" and meth == "setFirewallLevel":
            self.firewall = params["level"]
        elif svc.startswith("LEDs.LED."):
            self.leds[svc.removeprefix("LEDs.LED.")]["Brightness"] = params["Brightness"]
        elif (svc, meth) == ("Scheduler", "addSchedule"):
            info = params["info"]
            self.schedules[info["ID"]] = {**info, "value": info["override"] or "Enable"}
        elif (svc, meth) == ("Scheduler", "overrideSchedule"):
            self.schedules[params["ID"]]["override"] = params["override"]
        elif (svc, meth) == ("Scheduler", "removeSchedules"):
            for mac in params["ID"]:
                self.schedules[mac] = {"ID": mac, "enable": False, "override": "", "value": "Enable", "schedule": []}
        elif (svc, meth) == ("Firewall", "setPortForwarding") and params["id"] in self.forwards:
            self.forwards[params["id"]]["Enable"] = params["enable"]
        elif (svc, meth) == ("Firewall", "setDMZ"):
            self.dmz = {"webui": {"DestinationIPAddress": params["destinationIPAddress"], "Enable": True}}
        elif (svc, meth) == ("Firewall", "deleteDMZ"):
            self.dmz = {}
        elif meth in ("removeIntf", "addIntf"):
            ports = self.home_ports if svc.endswith(".lan") else self.guest_ports
            (ports.remove if meth == "removeIntf" else ports.append)(params["Intf"])

    async def _events(self, meth, body, params):
        if meth == "open_channel":
            return {"status": {"channelid": 7, "events": []}}
        if meth == "subscribe":
            return {"status": True}
        assert body.get("eventsVersionToUse") == 1 and params["channelid"] == 7
        self.event_waits += 1
        if self.events:
            events, self.events = self.events, []
            return {"status": {"channelid": 7, "events": events}}
        await asyncio.sleep(0.05)  # the real box holds the request ~30 s
        return {"status": {"channelid": 7, "events": []}}

    def _read(self, svc, meth, params):
        match (svc, meth):
            case ("DeviceInfo", "get"):
                return {"status": INFO}
            case ("NMC", "getWANStatus"):
                return {"status": True, "data": WAN}
            case ("NMC.Wifi", "get"):
                return {"status": {"Enable": True, "Status": True}}
            case ("NeMo.Intf.rad2g0", "get"):
                return {"status": radio(6, "1,2,3,4,5,6,7,8,9,10,11,12,13", "40MHz", "b,g,n,ax")}
            case ("NeMo.Intf.rad5g0", "get"):
                return {"status": radio(100, "36,40,44,48,100,104", "80MHz", "a,n,ac,ax")}
            case ("NeMo.Intf.brguest", "getMIBs"):
                return {
                    "status": {
                        "wlanvap": {
                            "vap2g0guest": {"VAPStatus": "Down", "SSID": "KPN_Gast"},
                            "vap5g0guest": {"VAPStatus": "Down", "SSID": "KPN_Gast"},
                        }
                    }
                }
            case ("NMC.Guest", "get"):
                return {"status": {"Enable": True, "Status": "Disabled", "Address": "192.168.3.254"}}
            case ("NMC.WlanTimer", "getActivationTimer"):
                return {"status": 0}
            case ("Devices", "get") if isinstance(params.get("expression"), str):  # extenders query
                return {"status": []}
            case ("Devices", "get"):
                return {"status": {"wifi": self.wifi_devices, "eth": self.eth_devices}}
            case ("Firewall", "getFirewallLevel"):
                return {"status": self.firewall}
            case ("LEDs.LED", "get"):
                return {"status": self.leds}
            case ("WebuiupgradeService", "getLatestVersion"):
                return {
                    "status": True,
                    "data": {"updateAvailable": False, "currentVersion": "26.04.02.0", "newVersion": "26.04.02.0"},
                }
            case ("Scheduler", "getCompleteSchedules"):
                info = list(self.schedules.values()) if params["type"] == "ToD" else []
                return {"status": True, "data": {"scheduleInfo": info}}
            case ("Firewall", "getPortForwarding"):
                return {"status": self.forwards if params["origin"] == "webui" else self.upnp}
            case ("Firewall", "getPinhole"):
                return {"status": self.pinholes}
            case ("Firewall", "getDMZ"):
                return {"status": self.dmz}
            case ("NeMo.Intf.vap2g0priv.WPS" | "NeMo.Intf.vap5g0priv.WPS", "get"):
                return {"status": {"Enable": True, "PairingInProgress": False}}
            case ("NeMo.Intf.lan", "getMIBs") if params.get("mibs") == "eth":
                port = {
                    "CurrentBitRate": 1000,
                    "MaxBitRateSupported": 1000,
                    "MaxBitRateEnabled": -1,
                    "CurrentDuplexMode": "Full",
                    "DuplexModeEnabled": "Auto",
                }
                return {"status": {"eth": {"eth0": port, "eth1": {**port, "CurrentBitRate": 100}}}}
            case ("NeMo.Intf.ETH0" | "NeMo.Intf.ETH1", "getMIBs"):
                port = svc.removeprefix("NeMo.Intf.")
                return {"status": {"base": {port: {"LLIntf": {port.lower(): {"Name": port.lower()}}}}}}
            case ("NeMo.Intf.bridge", "getIntfs"):
                return {"status": ["bridge", "vap2g0priv", *self.home_ports]}
            case ("NeMo.Intf.brguest", "getIntfs"):
                return {"status": ["brguest", *self.guest_ports]}
            case ("NeMo.Intf.bridge" | "NeMo.Intf.brguest", "get"):
                return {"status": {"STPEnable": False}}
            case ("NeMo.Intf.rad2g0" | "NeMo.Intf.rad5g0", "getScanResults"):
                return {
                    "status": [
                        {
                            "SSID": "Neighbour",
                            "Channel": 1,
                            "SignalStrength": -70,
                            "SecurityModeEnabled": "WPA2-Personal",
                        },
                        {"SSID": "", "Channel": 6, "SignalStrength": -50},
                    ]
                }
            case ("NeMo.Intf.rad2g0" | "NeMo.Intf.rad5g0", "getSpectrumInfo"):
                self.spectrum_updates += bool(params.get("update"))
                return {
                    "status": [
                        {"channel": 1, "availability": 60, "accesspoints": 3, "isBanned": False},
                        {"channel": 6, "availability": 90, "accesspoints": 1, "isBanned": False},
                        {"channel": 11, "availability": 99, "accesspoints": 0, "isBanned": True},
                    ]
                }
            case ("SSW.Steering.MasterConfig", "get"):
                return {"status": {"SyncEnableField": True}}
            case ("NetMaster.LAN.default.Bridge.lan.IPv6.lan.DHCPv6", "get"):
                return {"status": {"IAPDEnable": True, "IAPDLeasePrefixLength": 56}}
            case ("Firewall.ConnectionTracking.SIP", "get"):
                return {"status": {"Enable": True}}
            case ("PasswordRecovery", "get"):
                return {"status": {"Enable": True, "Status": "Enabled"}}
            case ("NMC", "getWanModeList"):
                return {"status": "Ethernet_PPP;VDSL_PPP;ADSL_PPPOA;Ethernet_DHCP"}
            case ("VoiceService.VoiceApplication", "listTrunks"):
                return {
                    "status": [
                        {
                            "name": "SIP-Trunk1",
                            "trunk_lines": [{"name": "LINE11", "enable": "Disabled", "status": "Disabled"}],
                        }
                    ]
                }
            case ("VoiceService.VoiceApplication", "listHandsets"):
                return {"status": [{"line": "FXS1", "status": "Up"}]}
            case ("VoiceService.VoiceApplication", "listGroups"):
                return {"status": [{"group_id": "Group1", "ep_names": []}]}
            case ("VoiceService.VoiceApplication", "getCallList"):
                return {"status": [{"remoteNumber": "0612345678", "callType": "missed"}]}
            case ("NeMo.Intf.lan", "getMIBs"):
                return {
                    "status": {
                        "wlanvap": {
                            "vap2g0priv": {"SSIDAdvertisementEnabled": True},
                            "vap5g0priv": {"SSIDAdvertisementEnabled": True},
                            "vap2g0ext": {"VAPStatus": "Down"},
                            "vap5g0ext": {"VAPStatus": "Down"},
                        }
                    }
                }
            case ("Firewall", "getRespondToPing"):
                return {"status": {"enableIPv4": True, "enableIPv6": True}}
            case ("Firewall", "get"):
                return {"status": {"UpnpPortForwardingEnable": True}}
            case ("Firewall", "getCustomRule"):
                return {
                    "status": {
                        "ssh": {
                            "Id": "ssh",
                            "Target": "Accept",
                            "IPVersion": 4,
                            "Protocol": "6",
                            "DestinationPort": "22",
                            "SourcePort": "",
                            "DestinationPrefix": "",
                            "SourcePrefix": "",
                            "Enable": True,
                        }
                    }
                }
            case ("DHCPv4.Server.Pool.default", "getStaticLeases"):
                return {"status": [{"MACAddress": "bb:bb:bb:bb:bb:01", "IPAddress": "192.168.2.16"}]}
            case ("DHCPv4.Server", "getDHCPServerPool"):
                pools = {
                    "default": {
                        "Enable": True,
                        "Authoritative": True,
                        "MinAddress": "192.168.2.1",
                        "MaxAddress": "192.168.2.200",
                        "SubnetMask": "255.255.255.0",
                        "IPRouters": "192.168.2.254",
                        "LeaseTime": 86400,
                        "DNSServers": "192.168.2.26,1.1.1.1",
                    },
                    "guest": {
                        "Enable": True,
                        "MinAddress": "192.168.3.1",
                        "MaxAddress": "192.168.3.200",
                        "SubnetMask": "255.255.255.0",
                        "IPRouters": "192.168.3.254",
                        "LeaseTime": 86400,
                        "DNSServers": "",
                    },
                }
                return {"status": {params["id"]: pools[params["id"]]}}
            case ("NetMaster", "get"):
                return {"status": {"EnableIPv6": True, "IPv6PrefixMode": "DHCPv6"}}
            case ("DynDNS", "getHosts"):
                return {"status": []}
            case ("IPPingDiagnostics", "execDiagnostic"):
                return {
                    "status": {
                        "DiagnosticsState": "Success",
                        "ipHost": "8.8.8.8",
                        "packetsSuccess": 10,
                        "packetsFailed": 0,
                        "averageResponseTime": 3,
                        "minimumResponseTime": 2,
                        "maximumResponseTime": 5,
                    }
                }
        if meth == "getNetDevStats":
            intf = svc.removeprefix("NeMo.Intf.")
            if intf in self.counters:
                rx, tx = self.counters[intf]
                return {"status": {"RxBytes": rx, "TxBytes": tx, "RxErrors": 0}}
        return NOT_FOUND

    @staticmethod
    def _resp(payload, headers=None):
        return AiohttpClientMockResponse(
            "POST", URL, json=payload, headers={"Content-Type": "application/json", **(headers or {})}
        )


class FakeClock:
    now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def box(aioclient_mock):
    fake = FakeBox()
    aioclient_mock.post(URL, side_effect=fake.handler)
    return fake


@pytest.fixture
def clock(monkeypatch):
    from custom_components.kpn_box import coordinator

    fake = FakeClock()
    monkeypatch.setattr(coordinator, "time", fake)
    return fake


@pytest.fixture
async def entry(hass: HomeAssistant, box, clock):
    entry = MockConfigEntry(domain=DOMAIN, data=USER, unique_id="LK123")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def eid(hass, platform, key):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"LK123_{key}")


async def tick(hass, clock, seconds=31):
    clock.now += seconds
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_config_and_options_flow(hass: HomeAssistant, box) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {**USER, CONF_PASSWORD: "wrong"})
    assert bad["errors"] == {"base": "invalid_auth"}
    ok = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert ok["type"] is FlowResultType.CREATE_ENTRY
    assert ok["title"] == "KPN Box (F5359s)"
    entry = ok["result"]
    await hass.async_block_till_done()

    opts = await hass.config_entries.options.async_init(entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        opts["flow_id"], {"scan_interval": 60, "track_devices": False}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == timedelta(seconds=60)
    assert not [
        e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) if e.domain == "device_tracker"
    ]


async def test_entities_created(hass: HomeAssistant, entry) -> None:
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    by_domain: dict[str, int] = {}
    for e in entities:
        by_domain[e.domain] = by_domain.get(e.domain, 0) + 1
    # sensors: 14 system + 2 radios x (5 health + 2 scan) + 2 port links + 3 interfaces x 4 traffic
    # switches: 8 fixed + 2 bands + 2 extra networks + 2 STP + SIP + IPv6 delegation + extender sync
    #           + local Wi-Fi off + 802.11b + 2 device internet access + 1 port forward + 1 pinhole
    #           + 1 custom firewall rule + 1 phone line
    # selects: 6 + 2 radios x 2 + 2 ports x (speed, duplex, network)
    assert by_domain == {
        "sensor": 42,
        "binary_sensor": 3,
        "switch": 25,
        "select": 16,
        "button": 5,
        "light": 1,
        "update": 1,
        "device_tracker": 2,
    }


async def test_sensor_values(hass: HomeAssistant, entry) -> None:
    assert hass.states.get(eid(hass, "sensor", "public_ipv4")).state == "77.1.2.3"
    assert hass.states.get(eid(hass, "sensor", "ipv6_prefix")).state == "2a02:a46e:2d7::/48"
    assert hass.states.get(eid(hass, "sensor", "wan_state")).state == "Connected"
    assert hass.states.get(eid(hass, "sensor", "5g_channel")).state == "100"
    assert hass.states.get(eid(hass, "sensor", "5g_channel_load")).state == "31"
    assert hass.states.get(eid(hass, "sensor", "5g_noise")).state == "-91"
    assert hass.states.get(eid(hass, "sensor", "5g_clients")).state == "6"
    assert hass.states.get(eid(hass, "sensor", "devices_connected")).state == "2"
    assert hass.states.get(eid(hass, "sensor", "devices_wifi")).state == "1"
    assert hass.states.get(eid(hass, "sensor", "devices_wired")).state == "1"
    boot = dt_util.parse_datetime(hass.states.get(eid(hass, "sensor", "last_boot")).state)
    assert abs((dt_util.utcnow() - boot).total_seconds() - 3600) < 5
    assert hass.states.get(eid(hass, "binary_sensor", "internet")).state == "on"
    fw = hass.states.get(eid(hass, "update", "firmware"))
    assert fw.state == "off" and fw.attributes["installed_version"] == "V12.C.26.04.02"


async def test_traffic_rates_relogin_and_reset(hass: HomeAssistant, entry, box, clock) -> None:
    download = eid(hass, "sensor", "eth4_RxBytes")
    speed = eid(hass, "sensor", "eth4_rx_rate")
    assert hass.states.get(download).name == "KPN Box (F5359s) WAN download"
    assert hass.states.get(speed).state == "unknown"

    box.counters["eth4"][0] += 1_250_000  # 10 Mbit over 30 s
    await tick(hass, clock, 30)
    assert 0.3 < float(hass.states.get(speed).state) < 0.35

    box.expire_next = True
    await tick(hass, clock, 30)
    assert hass.states.get(download).state != "unavailable"
    assert box.contexts == 2

    box.counters["eth4"][0] = 5
    await tick(hass, clock, 30)
    assert hass.states.get(speed).state == "unknown"


async def test_wifi_switches(hass: HomeAssistant, entry, box) -> None:
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid(hass, "switch", "wifi")}, blocking=True)
    assert box.writes[:3] == [
        ("NMC.Wifi", "set", {"Enable": False}),
        ("NeMo.Intf.rad2g0", "set", {"Enable": False}),
        ("NeMo.Intf.rad5g0", "set", {"Enable": False}),
    ]
    box.writes.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid(hass, "switch", "5g_radio")}, blocking=True)
    assert box.writes == [
        ("NeMo.Intf.rad5g0", "set", {"Enable": True}),
        ("NeMo.Intf.vap5g0priv", "set", {"PersistentEnable": True}),
    ]
    box.writes.clear()
    guest = eid(hass, "switch", "guest_wifi")
    assert hass.states.get(guest).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": guest}, blocking=True)
    on = {"Enable": True, "PersistentEnable": True, "Status": True}
    assert box.writes == [
        ("NeMo.Intf.lan", "setWLANConfig", {"mibs": {"penable": {"vap2g0guest": on, "vap5g0guest": on}}})
    ]


async def test_selects(hass: HomeAssistant, entry, box) -> None:
    fw = eid(hass, "select", "firewall_level")
    assert hass.states.get(fw).state == "Medium"
    await hass.services.async_call("select", "select_option", {"entity_id": fw, "option": "High"}, blocking=True)
    assert box.writes == [
        ("Firewall", "setFirewallLevel", {"level": "High"}),
        ("Firewall", "setFirewallIPv6Level", {"level": "High"}),
    ]
    assert hass.states.get(fw).state == "High"

    box.writes.clear()
    ch = eid(hass, "select", "5g_channel_select")
    state = hass.states.get(ch)
    assert state.state == "auto" and state.attributes["options"] == ["auto", "36", "40", "44", "48", "100", "104"]
    await hass.services.async_call("select", "select_option", {"entity_id": ch, "option": "44"}, blocking=True)
    assert box.writes == [
        (
            "NeMo.Intf.rad5g0",
            "setWLANConfig",
            {
                "mibs": {
                    "wlanradio": {
                        "rad5g0": {
                            "AutoChannelEnable": False,
                            "OperatingChannelBandwidth": "80MHz",
                            "OperatingStandards": "a,n,ac,ax",
                            "Channel": 44,
                        }
                    }
                }
            },
        )
    ]

    box.writes.clear()
    gt = eid(hass, "select", "guest_time_limit")
    assert hass.states.get(gt).state == "unlimited"
    await hass.services.async_call("select", "select_option", {"entity_id": gt, "option": "4h"}, blocking=True)
    assert box.writes == [("NMC.WlanTimer", "setActivationTimer", {"Timeout": 4, "InterfaceName": "guest"})]
    assert hass.states.get(gt).state == "4h"


async def test_leds_and_reboot(hass: HomeAssistant, entry, box) -> None:
    leds = eid(hass, "light", "leds")
    assert hass.states.get(leds).state == "on"
    await hass.services.async_call("light", "turn_on", {"entity_id": leds, "brightness": 64}, blocking=True)
    assert box.writes == [
        ("LEDs.LED.PowerGreen", "set", {"Brightness": 64}),
        ("LEDs.LED.WifiGreen", "set", {"Brightness": 64}),
    ]
    assert hass.states.get(leds).attributes["brightness"] == 64
    await hass.services.async_call("light", "turn_off", {"entity_id": leds}, blocking=True)
    assert hass.states.get(leds).state == "off"

    box.writes.clear()
    await hass.services.async_call("button", "press", {"entity_id": eid(hass, "button", "reboot")}, blocking=True)
    assert box.writes == [("NMC", "reboot", {})]


async def test_device_trackers(hass: HomeAssistant, entry, box, clock) -> None:
    reg = er.async_get(hass)
    phone = reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:01")
    assert hass.states.get(phone).state == "home"
    assert hass.states.get(phone).attributes["ip"] == "192.168.2.5"
    # Never-active device isn't tracked until it shows up
    assert reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:02") is None
    box.wifi_devices[0]["Active"] = False
    box.wifi_devices[1]["Active"] = True
    await tick(hass, clock)
    assert hass.states.get(phone).state == "not_home"
    laptop = reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:02")
    assert hass.states.get(laptop).state == "home"


async def test_ping_service(hass: HomeAssistant, entry) -> None:
    res = await hass.services.async_call(DOMAIN, "ping", {"host": "8.8.8.8"}, blocking=True, return_response=True)
    assert res == {
        "state": "Success",
        "host": "8.8.8.8",
        "packets_received": 10,
        "packets_lost": 0,
        "avg_ms": 3,
        "min_ms": 2,
        "max_ms": 5,
    }


async def test_diagnostics_redacted(hass: HomeAssistant, entry) -> None:
    from custom_components.kpn_box.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, default=str)
    assert "secret" not in text and "77.1.2.3" not in text and "AA:AA:AA:AA:AA:01" not in text
    assert diag["data"]["radios"]["5g"]["Channel"] == 100


async def test_unload_releases_context(hass: HomeAssistant, entry, box, aioclient_mock) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_internet_access(hass: HomeAssistant, entry, box) -> None:
    sw = eid(hass, "switch", "internet_aa:aa:aa:aa:aa:01")
    assert hass.states.get(sw).name == "KPN Box (F5359s) phone internet access"
    assert hass.states.get(sw).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": sw}, blocking=True)
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
                    "schedule": [],
                    "enable": True,
                    "override": "Disable",
                },
            },
        )
    ]
    assert hass.states.get(sw).state == "off"
    assert hass.states.get(eid(hass, "sensor", "blocked_devices")).state == "1"
    box.writes.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": sw}, blocking=True)
    assert box.writes == [
        ("Scheduler", "overrideSchedule", {"type": "ToD", "ID": "AA:AA:AA:AA:AA:01", "override": "Enable"}),
        ("Scheduler", "removeSchedules", {"type": "ToD", "ID": ["AA:AA:AA:AA:AA:01"]}),
    ]
    assert hass.states.get(sw).state == "on"


async def test_port_forward_pinhole_dmz(hass: HomeAssistant, entry, box) -> None:
    pf = eid(hass, "switch", "portforward_webui_NAS")
    state = hass.states.get(pf)
    assert state.state == "off" and state.attributes["protocol"] == "TCP"
    await hass.services.async_call("switch", "turn_on", {"entity_id": pf}, blocking=True)
    assert box.writes == [
        (
            "Firewall",
            "setPortForwarding",
            {
                "id": "webui_NAS",
                "internalPort": "5000",
                "externalPort": "5000",
                "destinationIPAddress": "192.168.2.16",
                "enable": True,
                "persistent": True,
                "protocol": "6",
                "description": "NAS",
                "sourceInterface": "data",
                "origin": "webui",
                "destinationMACAddress": "",
                "sourcePrefix": "",
            },
        )
    ]
    assert hass.states.get(pf).state == "on"

    box.writes.clear()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": eid(hass, "switch", "pinhole_ph1")}, blocking=True
    )
    assert box.writes == [("Firewall", "setPinhole", {"id": "ph1", "enable": False})]

    upnp = hass.states.get(eid(hass, "sensor", "upnp_forwards"))
    assert upnp.state == "1" and upnp.attributes["rules"] == ["Parsec UDP 21227 -> 192.168.2.19:21227"]

    dmz = eid(hass, "binary_sensor", "dmz")
    assert hass.states.get(dmz).state == "off"
    await hass.services.async_call(DOMAIN, "set_dmz", {"ip_address": "192.168.2.16"}, blocking=True)
    assert hass.states.get(dmz).state == "on"
    await hass.services.async_call(DOMAIN, "clear_dmz", {}, blocking=True)
    assert hass.states.get(dmz).state == "off"
    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "set_dmz", {"ip_address": "not-an-ip"}, blocking=True)


async def test_wifi_extras(hass: HomeAssistant, entry, box) -> None:
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": eid(hass, "switch", "ssid_visible")}, blocking=True
    )
    assert box.writes == [
        (
            "NeMo.Intf.lan",
            "setWLANConfig",
            {
                "mibs": {
                    "wlanvap": {
                        "vap2g0priv": {"SSIDAdvertisementEnabled": False},
                        "vap5g0priv": {"SSIDAdvertisementEnabled": False},
                    }
                }
            },
        )
    ]
    box.writes.clear()
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid(hass, "switch", "wps")}, blocking=True)
    assert box.writes == [
        ("NeMo.Intf.vap2g0priv.WPS", "set", {"Enable": False}),
        ("NeMo.Intf.vap5g0priv.WPS", "set", {"Enable": False}),
    ]
    box.writes.clear()
    await hass.services.async_call("button", "press", {"entity_id": eid(hass, "button", "wps_start")}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": eid(hass, "button", "wps_stop")}, blocking=True)
    assert box.writes == [("NMC.Wifi", "startPairing", {"clientPIN": ""}), ("NMC.Wifi", "stopPairing", {})]
    box.writes.clear()
    bw = eid(hass, "select", "guest_bandwidth")
    assert hass.states.get(bw).state == "unlimited"
    await hass.services.async_call("select", "select_option", {"entity_id": bw, "option": "20 Mbit/s"}, blocking=True)
    assert box.writes == [("NMC.Guest", "set", {"BandwidthLimitation": "20000"})]
    # No Wi-Fi schedule made in the web UI -> nothing to switch
    assert hass.states.get(eid(hass, "switch", "wifi_schedule")).state == "unavailable"


async def test_events_refresh_immediately(hass: HomeAssistant, entry, box) -> None:
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:02") is None
    for _ in range(100):  # wait for the listener to be polling
        if box.event_waits:
            break
        await asyncio.sleep(0.01)
    box.wifi_devices[1]["Active"] = True
    box.events = [
        {
            "data": {
                "handler": "Devices.Device.AA:AA:AA:AA:AA:02",
                "object": {"reason": "changed", "attributes": {"Active": "1"}},
            }
        }
    ]
    for _ in range(300):  # no clock tick: only the event can cause this refresh
        await asyncio.sleep(0.01)
        await hass.async_block_till_done()
        if reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:02"):
            break
    laptop = reg.async_get_entity_id("device_tracker", DOMAIN, "aa:aa:aa:aa:aa:02")
    assert laptop and hass.states.get(laptop).state == "home"
