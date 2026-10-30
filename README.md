<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/kpn_box/brand/dark_logo.png">
    <img alt="KPN Box" src="custom_components/kpn_box/brand/logo.png" height="96">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img alt="HACS Custom" src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg"></a>
  <a href="https://github.com/JoppieToppie/kpn-box-ha/releases"><img alt="Release" src="https://img.shields.io/github/v/release/JoppieToppie/kpn-box-ha"></a>
  <a href="https://github.com/JoppieToppie/kpn-box-ha/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/JoppieToppie/kpn-box-ha/actions/workflows/tests.yml/badge.svg"></a>
  <a href="https://github.com/JoppieToppie/kpn-box-ha/actions/workflows/validate.yml"><img alt="Validate" src="https://github.com/JoppieToppie/kpn-box-ha/actions/workflows/validate.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/JoppieToppie/kpn-box-ha"></a>
</p>

# KPN Box for Home Assistant

A local Home Assistant integration for the **KPN Box 12** (Sagemcom F@st 5359). It covers everything the
KPN web UI can do, adds monitoring the web UI doesn't show, and has generic `call` / `describe` actions that
reach every function the box exposes, including ones its web UI never uses.

- **Fully local:** talks to the box's own API on your network; no cloud and no extra Python packages.
- **Instant updates:** listens on the box's event channel, so a device joining or a setting changing shows up
  within seconds. 30-second polling stays on as a fallback.
- **Same calls as the web UI:** every switch, select and action sends exactly the payload the KPN web UI sends.

> [!NOTE]
> This is a community project. It is not made, supported or endorsed by KPN or Sagemcom.
> "KPN" and the box picture belong to their owners and are only used to identify the device.

## Contents

- [Supported devices](#supported-devices)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Actions](#actions)
- [Examples](#examples)
- [Cautions](#cautions)
- [What has been tested](#what-has-been-tested)
- [Development](#development)

## Supported devices

| Box | Status |
|-----|--------|
| KPN Box 12 (Sagemcom F@st 5359, `F5359s`), firmware `V12.C.26.04.02` | Developed and tested on |
| Other KPN boxes on SoftAtHome / prpl firmware (Box 14, …) | Untested. Will likely partly work; [open an issue](https://github.com/JoppieToppie/kpn-box-ha/issues) with your diagnostics |

Requires Home Assistant **2025.2** or newer. The integration's icon and logo need **2026.3** or newer, which
reads them from the integration's own `brand/` folder; older versions show a generic icon.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JoppieToppie&repository=kpn-box-ha&category=integration)

Or by hand:

1. HACS → ⋮ → **Custom repositories**: add `https://github.com/JoppieToppie/kpn-box-ha`, type **Integration**.
2. Search for **KPN Box**, download it, and restart Home Assistant.

### Manual

1. Download `kpn_box.zip` from the [latest release](https://github.com/JoppieToppie/kpn-box-ha/releases/latest).
2. Unzip it into `/config/custom_components/kpn_box/`, so that `/config/custom_components/kpn_box/manifest.json` exists.
3. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up KPN Box.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kpn_box)

Settings → Devices & services → **Add integration** → **KPN Box**. Enter the box address (default
`192.168.2.254`) and the admin password from the sticker or the one you set. If the password changes later,
Home Assistant asks for the new one.

**Options** (Configure on the integration):

| Option | Default |
|--------|---------|
| Update interval | 30 s |
| Device trackers and per-device internet switches | On |
| Instant updates (event channel) | On |

**Diagnostics:** download them from the device page. IPs, MACs, the serial number, SSIDs and passwords are redacted.

## Entities

| Type | Entities |
|------|----------|
| **Sensors: traffic** (per interface) | Total received/sent (GB, `total_increasing`) and live speed (Mbit/s) for WAN (`eth4`, includes KPN TV), Internet (PPP, internet only), LAN ports 1–4, Wi-Fi 2.4/5 GHz, guest Wi-Fi 2.4/5 GHz |
| **Sensors: Wi-Fi radios** (per band) | Channel (bandwidth, standards and auto-channel as attributes), channel load %, interference %, noise dBm, connected clients, nearby networks (count plus a list of SSID/channel/signal), least busy channel (with per-channel availability). Scans refresh every 5 min |
| **Sensors: network** | Public IPv4 (gateway and DNS as attributes), IPv6 prefix, WAN connection state, last boot, connected / Wi-Fi / wired device counts, UPnP port forwards, blocked devices, DHCP range (router IP, DNS servers, lease time, guest range), fixed IP addresses, DynDNS hosts, LAN port 1–4 link speed and duplex, phone calls (with recent calls), Wi-Fi extenders |
| **Binary sensors** | Internet (connectivity), DMZ active, WPS pairing in progress |
| **Switches: Wi-Fi** | Wi-Fi (all bands), Wi-Fi 2.4 GHz, Wi-Fi 5 GHz, guest Wi-Fi, extra 2.4 / 5 GHz networks, network visible, guest network visible, WPS, Wi-Fi schedule (unavailable until a schedule exists), 2.4 GHz 802.11b compatibility. For extenders (disabled by default): sync Wi-Fi settings to extenders, box Wi-Fi off while extenders stay on |
| **Switches: per device** | "&lt;device&gt; internet access" for every device seen online. Off means blocked, like Block in the web UI's parental control |
| **Switches: security** | One per port-forwarding rule, one per IPv6 open port, respond to ping from the internet, UPnP port forwarding, one per custom firewall rule. The box ships about 37 firewall rules, so those switches are **disabled** by default; enable the ones you want |
| **Switches: network and phone** | STP (home / guest network), IPv6 prefix delegation, SIP connection tracking, one per phone line (disabled unless the line is set up) |
| **Selects** | Firewall level; per band: channel (auto or fixed), channel width (AUTO/20/40/80/160 MHz up to the band's maximum), Wi-Fi standards; guest Wi-Fi time limit and bandwidth limit; IPv6 on LAN; per LAN port: speed, duplex and network (home / guest) |
| **Light** | Status LEDs (brightness of all front LEDs; off means dark) |
| **Buttons** | Restart, start WPS pairing, stop WPS pairing, scan Wi-Fi channels, test-ring phones |
| **Update** | Firmware: shows when KPN offers a newer version, and **Install** runs the upgrade (the box restarts) |
| **Device trackers** | One per device seen online since setup, with IP, interface, band, signal and link rates as attributes |

## Actions

All actions take an optional `config_entry_id`, which is only needed with more than one box. Write MAC addresses
as `AA:BB:CC:DD:EE:FF`.

| Area | Actions |
|------|---------|
| Diagnostics | `ping` (returns the result) |
| Wi-Fi | `set_wifi_network` (main / guest / extra_2g / extra_5g: name, password, WPA mode, PMF), `set_wifi_schedule`, `clear_wifi_schedule`, `set_mac_filter` (allow-list; refuses an empty list) |
| Devices | `set_device_schedule` (weekly no-internet periods), `clear_device_schedule`, `rename_device`, `set_device_type`, `remove_device`, `add_static_lease`, `remove_static_lease` |
| Port forwarding and firewall | `add_port_forward`, `remove_port_forward`, `add_ipv6_pinhole`, `remove_ipv6_pinhole`, `add_firewall_rule`, `remove_firewall_rule`, `set_firewall_policy`, `set_dmz`, `clear_dmz` |
| Network | `set_lan` (router IP, mask, DHCP on/off/range/lease, DNS servers, authoritative; only the fields you give change, and a new router IP moves the integration along), `set_guest_lan`, `set_hostname` (hostname and/or domain), `add_dyndns_host`, `remove_dyndns_host`, `set_dyndns_enabled`, `set_ipv6_delegation_length` |
| Telephone | `set_phone_line`, `clear_phone_line`, `set_incoming_phones`, `set_outgoing_line` |
| System | `change_admin_password` (the current password must match; the integration switches to the new one), `start_password_recovery`, `reset_admin_password`, `set_wan_mode`, `shutdown` (switch the box on by hand afterwards), `factory_reset` |
| Anything else | `describe` (lists an object's functions, settings and children) and `call` (runs any function and returns the answer, with no safety checks) |

The destructive system actions only run with a confirmation phrase:

| Action | `confirm` |
|--------|-----------|
| `factory_reset` | `factory reset` |
| `reset_admin_password` | `reset password` |
| `set_wan_mode` | `change wan mode` |
| `shutdown` | `shut down` |

## Examples

Block internet for a device on school nights. An end before the start runs past midnight:

```yaml
action: kpn_box.set_device_schedule
data:
  mac: "AA:BB:CC:DD:EE:FF"
  blocked_periods:
    - days: [mon, tue, wed, thu, sun]
      start: "21:30"
      end: "07:00"
    - days: [fri, sat]
      start: "23:30"
      end: "08:00"
```

Ping from the box:

```yaml
action: kpn_box.ping
data:
  host: 8.8.8.8
response_variable: ping
# -> {state: Success, packets_received: 10, packets_lost: 0, avg_ms: 3, min_ms: 3, max_ms: 4, ...}
```

Explore what the box can do, for example its config backup, extra admin users or a paired extender:

```yaml
action: kpn_box.describe
data:
  object: NMC            # -> functions: backup, restore, export, import, setLANIP, getVoIPConfig, ...
response_variable: nmc
```

Run a function on a paired extender:

```yaml
action: kpn_box.call
data:
  service: Devices.Device.AA:BB:CC:DD:EE:FF.SSW
  method: execAPI
  parameters: {service: LEDs.LED.Root, method: set, parameters: {Brightness: 0}}
response_variable: result
```

## Cautions

- `set_wifi_network`, `set_mac_filter`, `set_lan`, the Wi-Fi switches and `factory_reset` can cut devices off,
  including Home Assistant itself if it's on Wi-Fi or the LAN settings change.
- `call` has no safety checks. It can do anything the web UI's admin user can.
- "Received/sent" on LAN and Wi-Fi is from the router's point of view: received means devices uploading.
- The ETH0 → "LAN port 1" mapping is assumed; check it against the port labels on your box.
- Turning a device's internet access back on also removes its weekly schedule, like Allow in the web UI.
- The router-side speed test only exists on the KPN Box 14. Use Home Assistant's Speedtest.net integration instead.
- Extenders get a status sensor and the two extender switches; per-extender settings go through `call` with
  `execAPI`, as in the example above. 4G backup / hybrid internet is reachable via `call`.
- `setSeparateWifi` (`NMC.Wifi` `ConfigurationMode`) exists in the web UI's code but is never used there and its
  meaning isn't documented, so it's only reachable via `call`.

## What has been tested

On a real KPN Box 12 with firmware `V12.C.26.04.02`:

- Every read (all sensors, states and attributes), the event channel, `describe`, and a read via `call`.
- The box's own function list confirms the system calls used (factory reset, firmware upgrade, scheduler,
  admin password).
- Accepted with the current value (no change): LED brightness, firewall level, a port-forward rule, guest
  bandwidth, SSID visibility, WPS on/off.
- Done for real and undone: blocking and unblocking an offline device, starting and stopping WPS pairing.
- The schedule time format (seconds from Monday 00:00, box local time): a block period around the current time
  made the box report the device as blocked, and one two hours later as allowed.

Everything else that changes settings sends exactly the web UI's payloads and is covered by the test suite
against a simulated box, but hasn't been tried on a real box. Reports either way are welcome.

## Development

```bash
python -m venv .venv && . .venv/bin/activate     # Python 3.14
pip install -r requirements_dev.txt
pytest
ruff check && ruff format --check
```

On Windows, run the tests in WSL; Home Assistant's test harness imports Unix-only modules.

| Path | What it is |
|------|------------|
| `custom_components/kpn_box/` | The integration |
| `tests/` | Tests against a simulated box (`FakeBox` in `tests/test_kpn_box.py`) |
| `scripts/kpnbox.py` | Command-line client: `info`, `wan`, `devices`, `wifi`, `ethstats`, `call <service> <method> '{json}'` |
| `scripts/live_check.py` | Read-only check of everything the integration reads, against your real box |
| `tools/gen_services.py` | Regenerates `services.yaml` and the action texts in `strings.json` / `translations/en.json` |
| `tools/make_brand.py` | Rebuilds the icon and logo in `brand/` from the box photo in the KPN web UI |

The scripts read the router password from `.env` in the repo root (copy `.env.example`); `.env` is git-ignored.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to find a new box function and add it.

## License

[MIT](LICENSE)
