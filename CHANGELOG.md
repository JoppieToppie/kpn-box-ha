# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-10-30

First public release.

### Added

- Icon and logo for light and dark themes in `custom_components/kpn_box/brand` (shown on Home Assistant 2026.3+).
- HACS support, CI (hassfest, HACS validation, Ruff, pytest) and release zips.

### Changed

- Renamed from "KPN Box Stats" (`kpnbox_stats`) to **KPN Box** (`kpn_box`); actions are now `kpn_box.*`.
  If you installed the old version: remove that integration, delete `custom_components/kpnbox_stats`, then
  install this one.

## [0.5.0]

- Wi-Fi radio details and neighbour scans, LAN port speed/duplex/network, STP, IPv6 prefix delegation,
  telephone lines and calls, Wi-Fi extenders, WAN mode, password recovery, generic `call` and `describe` actions.

## [0.4.0] and earlier

- Traffic sensors, Wi-Fi and guest Wi-Fi control, device trackers and per-device internet access, schedules,
  port forwarding, IPv6 pinholes, firewall, DMZ, DHCP and static leases, DynDNS, status LEDs, firmware updates,
  the event channel for instant updates, diagnostics.

[0.6.0]: https://github.com/JoppieToppie/kpn-box-ha/releases/tag/v0.6.0
