"""Read-only live check of every read the integration's API client makes (no writes)."""

import asyncio
import importlib
import os
from pathlib import Path
import sys
import types

import aiohttp
import kpnbox  # noqa: F401  (loads KPNBOX_PASSWORD from .env)

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kpn_box"


# Load const/api as a package without running __init__.py (that one needs Home Assistant)
pkg = types.ModuleType("kpn_box")
pkg.__path__ = [str(ROOT)]
sys.modules["kpn_box"] = pkg
const = importlib.import_module("kpn_box.const")
api_mod = importlib.import_module("kpn_box.api")


async def main():
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        api = api_mod.KPNBoxApi(session, const.DEFAULT_HOST, "admin", os.environ["KPNBOX_PASSWORD"])
        info = await api.device_info()
        print(f"Box: {info['ModelName']} {info['SoftwareVersion']}, up {info['UpTime'] / 86400:.1f} days")
        wan = await api.wan_status()
        print(
            f"WAN: {wan.get('ConnectionState')} / link {wan.get('LinkState')}, IPv6 prefix {wan.get('IPv6DelegatedPrefix')}"
        )
        print(f"Wi-Fi enabled: {(await api.wifi_status()).get('Enable')}")
        for radio, _, name in const.RADIOS.values():
            r = await api.radio(radio)
            print(
                f"{name}: on={r.get('Enable')} ch={r.get('Channel')} auto={r.get('AutoChannelEnable')} "
                f"bw={r.get('OperatingChannelBandwidth')} load={r.get('ChannelLoad')}% "
                f"interf={r.get('Interference')}% noise={r.get('Noise')} clients={r.get('ActiveAssociatedDevices')}"
            )
        print(
            "Guest VAPs:",
            {k: v.get("VAPStatus") for k, v in (await api.guest_vaps()).items()},
            "timer:",
            await api.guest_timer(),
        )
        devs = await api.devices(const.DEVICE_EXPRESSION)
        for link, items in devs.items():
            print(f"Devices {link}: {sum(1 for d in items if d.get('Active'))} online / {len(items)} known")
        print("Firewall:", await api.firewall_level())
        print("LEDs:", {k: v.get("Brightness") for k, v in (await api.leds()).items()})
        print("Firmware:", await api.latest_firmware())
        print("Ping:", await api.ping("1.1.1.1"))
        tod = await api.schedules("ToD")
        print(f"Device access schedules: {len(tod)}, blocked: {sum(1 for s in tod if s.get('override') == 'Disable')}")
        print("Wi-Fi schedule:", await api.schedules("WLAN") or "none")
        print("Port forwards:", {k: v.get("Enable") for k, v in (await api.port_forwards("webui")).items()})
        print("UPnP forwards:", len(await api.port_forwards("upnp")))
        print("Pinholes:", await api.pinholes(), "DMZ:", await api.dmz())
        for vap in ("vap2g0priv", "vap5g0priv"):
            w = await api.wps(vap)
            print(f"WPS {vap}: enable={w.get('Enable')} pairing={w.get('PairingInProgress')}")
        print(
            "SSID visible:",
            {k: v.get("SSIDAdvertisementEnabled") for k, v in (await api.private_vaps()).items() if "priv" in k},
        )
        print("Guest bandwidth:", (await api.guest_settings()).get("BandwidthLimitation"))
        print(
            "Respond to ping:",
            await api.respond_to_ping(),
            "UPnP:",
            (await api.firewall_settings()).get("UpnpPortForwardingEnable"),
        )
        print("Custom firewall rules:", {k: v.get("Enable") for k, v in (await api.custom_rules()).items()})
        print("Fixed IPs:", len(await api.static_leases()))
        for pool in ("default", "guest"):
            p = await api.dhcp_pool(pool)
            print(
                f"DHCP {pool}: {p.get('MinAddress')} - {p.get('MaxAddress')}, router {p.get('IPRouters')}, "
                f"lease {p.get('LeaseTime')}s"
            )
        print("IPv6 mode:", (await api.netmaster()).get("IPv6PrefixMode"), "| DynDNS hosts:", await api.dyndns_hosts())
        for radio, _, name in const.RADIOS.values():
            scan, spec = await api.scan_results(radio), await api.spectrum(radio)
            best = max((c for c in spec if not c.get("isBanned")), key=lambda c: c.get("availability", 0), default={})
            print(
                f"{name}: {len(scan)} nearby networks, least busy channel {best.get('channel')} "
                f"({best.get('availability')}% free)"
            )
        lowers = {p: await api.lower_interface(p) for p in const.LAN_PORTS}
        eth = await api.eth_ports()
        print(
            "LAN ports:",
            {
                p: (lo, eth.get(lo, {}).get("CurrentBitRate"), eth.get(lo, {}).get("DuplexModeEnabled"))
                for p, lo in lowers.items()
            },
        )
        print(
            "Home ports:",
            [p for p in await api.bridge_members("bridge") if p in const.LAN_PORTS],
            "guest ports:",
            [p for p in await api.bridge_members("brguest") if p in const.LAN_PORTS],
        )
        print(
            "STP:",
            await api.stp("bridge"),
            await api.stp("brguest"),
            "| IPv6 delegation:",
            (await api.ipv6_delegation()).get("IAPDEnable"),
        )
        print(
            "Steering sync:",
            (await api.steering()).get("SyncEnableField"),
            "| SIP conntrack:",
            (await api.sip_conntrack()).get("Enable"),
            "| password recovery:",
            await api.password_recovery(),
        )
        print(
            "Phone lines:",
            [(t["name"], [ln["name"] for ln in t.get("trunk_lines", [])]) for t in await api.voice("listTrunks")],
            "| calls:",
            len(await api.voice("getCallList") or []),
        )
        print("Extenders:", len(await api.extenders()), "| WAN modes:", await api.wan_modes())
        d = await api.describe("NMC.Wifi")
        print(f"describe NMC.Wifi: {len(d['functions'])} functions, e.g. {list(d['functions'])[:5]}")
        res = await api.call("NMC", "getWANStatus")
        print("generic call NMC.getWANStatus:", (res.get("data") or {}).get("ConnectionState"))
        channel = await api.open_event_channel(const.EVENT_HANDLERS)
        events = await api.get_events(channel, const.EVENT_HANDLERS)
        print(f"Event channel {channel}: {len(events)} event(s) in one wait")
        await api.logout()
        print("All reads OK, logged out.")


asyncio.run(main())
