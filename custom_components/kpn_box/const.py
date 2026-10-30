"""Constants for KPN Box."""

DOMAIN = "kpn_box"
DEFAULT_HOST = "192.168.2.254"
DEFAULT_USERNAME = "admin"
DEFAULT_SCAN_INTERVAL = 30
FIRMWARE_CHECK_INTERVAL = 6 * 3600

CONF_SCAN_INTERVAL = "scan_interval"
CONF_TRACK_DEVICES = "track_devices"
CONF_USE_EVENTS = "use_events"

# Event-channel handlers: changes under these trigger an immediate refresh
EVENT_HANDLERS = [
    "Devices.Device",
    "Scheduler",
    "Firewall",
    "LEDs",
    "NMC",
    "NeMo.Intf.vap2g0priv.WPS",
    "NeMo.Intf.vap5g0priv.WPS",
]

# NeMo interface name -> (display name, is WAN). Interfaces the box doesn't have are skipped at setup.
INTERFACES: dict[str, tuple[str, bool]] = {
    "eth4": ("WAN", True),
    "ppp_vdata": ("Internet (PPP)", True),
    "ETH0": ("LAN port 1", False),
    "ETH1": ("LAN port 2", False),
    "ETH2": ("LAN port 3", False),
    "ETH3": ("LAN port 4", False),
    "vap2g0priv": ("Wi-Fi 2.4 GHz", False),
    "vap5g0priv": ("Wi-Fi 5 GHz", False),
    "vap2g0guest": ("Guest Wi-Fi 2.4 GHz", False),
    "vap5g0guest": ("Guest Wi-Fi 5 GHz", False),
}

# Radio key -> (NeMo radio, private VAP, display name)
RADIOS: dict[str, tuple[str, str, str]] = {
    "2g": ("rad2g0", "vap2g0priv", "Wi-Fi 2.4 GHz"),
    "5g": ("rad5g0", "vap5g0priv", "Wi-Fi 5 GHz"),
}
GUEST_VAPS = ("vap2g0guest", "vap5g0guest")

FIREWALL_LEVELS = ["Low", "Medium", "High", "Custom"]
# Same choices as the KPN web UI (value is passed to NMC.WlanTimer as-is)
GUEST_TIME_LIMITS = {"unlimited": 0, "1h": 1, "2h": 2, "4h": 4, "24h": 24, "48h": 48}
# Same choices as the KPN web UI; the box takes kbit/s
GUEST_BANDWIDTH = {
    "unlimited": 0,
    "10 Mbit/s": 10000,
    "20 Mbit/s": 20000,
    "30 Mbit/s": 30000,
    "40 Mbit/s": 40000,
    "50 Mbit/s": 50000,
}
PROTOCOLS = {"6": "TCP", "17": "UDP", "6,17": "TCP/UDP"}

DEVICE_EXPRESSION = {
    "wifi": 'wifi && (edev || hnid) and .PhysAddress!=""',
    "eth": 'eth && (edev || hnid) and .PhysAddress!=""',
}

# Optional extra Wi-Fi networks the web UI offers (separate SSIDs per band)
EXTRA_NETWORKS = {"vap2g0ext": "Extra Wi-Fi 2.4 GHz", "vap5g0ext": "Extra Wi-Fi 5 GHz"}
# Network name used in actions -> VAPs it covers
WIFI_NETWORKS = {
    "main": ("vap2g0priv", "vap5g0priv"),
    "guest": ("vap2g0guest", "vap5g0guest"),
    "extra_2g": ("vap2g0ext",),
    "extra_5g": ("vap5g0ext",),
}
SECURITY_MODES = ["WPA2-Personal", "WPA3-Personal", "WPA2-WPA3-Personal"]
PMF_MODES = ["Disabled", "Optional", "Required"]
IPV6_MODES = {"enabled": "RA", "enabled_with_dhcpv6": "RAandDHCPv6", "disabled": "DHCPv6"}
PROTOCOL_CODES = {"tcp": "6", "udp": "17", "both": "6,17"}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

SLOW_POLL_INTERVAL = 300  # scan results, spectrum, telephone, extenders
LAN_PORTS = ("ETH0", "ETH1", "ETH2", "ETH3")
BANDWIDTHS = ["AUTO", "20MHz", "40MHz", "80MHz", "160MHz"]
# Wi-Fi standard combinations the web UI offers on a Box 12 ("v12")
STANDARDS = {
    "2g": ["g,n,ax", "g,n", "b,g,n", "n,ax", "b,g,n,ax"],
    "5g": ["a,n,ac,ax", "a,n,ac", "a,n", "n,ac,ax", "ac,ax", "ax"],
}
RATES_WITH_11B = "1,2,5.5,6,9,11,12,18,24,36,48,54"
RATES_WITHOUT_11B = "6,9,12,18,24,36,48,54"
PORT_SPEEDS = {
    "auto": -1,
    "10 Mbit/s": 10,
    "100 Mbit/s": 100,
    "1 Gbit/s": 1000,
    "2.5 Gbit/s": 2500,
    "5 Gbit/s": 5000,
    "10 Gbit/s": 10000,
}
DUPLEX_MODES = ["Auto", "Half", "Full"]
PORT_NETWORKS = {"home": "lan", "guest": "guest"}
