"""Generate services.yaml and the services section of strings.json / translations/en.json from one spec.

Run from the repo root: python tools/gen_services.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kpn_box"

TXT = {"text": {}}
BOOL = {"boolean": {}}
PWD = {"text": {"type": "password"}}
OBJ = {"object": {}}
NUM_LEASE = {"number": {"min": 120, "max": 2592000, "mode": "box"}}


def sel(*opts):
    return {"select": {"options": list(opts)}}


MAC = ("Device MAC", "MAC address of the device, e.g. AA:BB:CC:DD:EE:FF.", True, TXT, "AA:BB:CC:DD:EE:FF")
PROTO = ("Protocol", "tcp, udp or both.", False, sel("tcp", "udp", "both"), None)
BLOCKS_EX = '[{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "22:00", "end": "07:00"}]'
LAN = {
    "router_ip": ("Router IP", "The box's own address.", False, TXT, None),
    "subnet_mask": ("Subnet mask", "e.g. 255.255.255.0.", False, TXT, None),
    "dhcp_enabled": ("DHCP server", "Hand out addresses.", False, BOOL, None),
    "dhcp_start": ("DHCP start", "First address handed out.", False, TXT, None),
    "dhcp_end": ("DHCP end", "Last address handed out.", False, TXT, None),
    "lease_time": ("Lease time", "Seconds.", False, NUM_LEASE, None),
    "dns_servers": ("DNS servers", "List of IPv4 addresses handed to devices.", False, OBJ, '["1.1.1.1", "8.8.8.8"]'),
}

SERVICES = {
    "ping": (
        "Ping from router",
        "Let the KPN Box ping a host and return the result.",
        {
            "host": ("Host", "Hostname or IP address to ping.", True, TXT, "8.8.8.8"),
            "ip_version": ("IP version", "IPv4 or IPv6.", False, sel("IPv4", "IPv6"), None),
        },
    ),
    "set_wifi_network": (
        "Set Wi-Fi network",
        "Change name, password and security of a Wi-Fi network. Devices on it must reconnect.",
        {
            "network": (
                "Network",
                "main, guest, extra_2g or extra_5g.",
                True,
                sel("main", "guest", "extra_2g", "extra_5g"),
                None,
            ),
            "ssid": ("Network name", "1-32 characters.", True, TXT, None),
            "password": ("Password", "8-63 characters.", True, PWD, None),
            "security": (
                "Security",
                "WPA mode.",
                False,
                sel("WPA2-Personal", "WPA3-Personal", "WPA2-WPA3-Personal"),
                None,
            ),
            "pmf": (
                "Protected management frames",
                "Disabled, Optional or Required.",
                False,
                sel("Disabled", "Optional", "Required"),
                None,
            ),
        },
    ),
    "set_wifi_schedule": (
        "Set Wi-Fi schedule",
        "Weekly periods during which Wi-Fi is off. Replaces the existing schedule.",
        {
            "off_periods": (
                "Off periods",
                "List of periods, each with days, start and end; an end before the start runs past midnight.",
                True,
                OBJ,
                BLOCKS_EX,
            )
        },
    ),
    "clear_wifi_schedule": ("Clear Wi-Fi schedule", "Remove the Wi-Fi schedule.", {}),
    "set_mac_filter": (
        "Set Wi-Fi MAC filter",
        "Only allow listed devices on Wi-Fi, or turn the filter off.",
        {
            "enabled": ("Enabled", "On = only the listed MACs may join.", True, BOOL, None),
            "allowed_macs": (
                "Allowed MACs",
                "MAC addresses allowed when enabled.",
                False,
                OBJ,
                '["AA:BB:CC:DD:EE:FF"]',
            ),
        },
    ),
    "set_device_schedule": (
        "Set device internet schedule",
        "Weekly periods during which a device has no internet (parental control). Replaces its schedule.",
        {
            "mac": MAC,
            "blocked_periods": (
                "Blocked periods",
                "List of periods, each with days, start and end.",
                True,
                OBJ,
                BLOCKS_EX,
            ),
        },
    ),
    "clear_device_schedule": (
        "Clear device schedule",
        "Remove a device's internet schedule (and block).",
        {"mac": MAC},
    ),
    "rename_device": (
        "Rename device",
        "Change a device's name on the KPN Box.",
        {"mac": MAC, "name": ("Name", "New name.", True, TXT, None)},
    ),
    "set_device_type": (
        "Set device type",
        "Set the device type/icon, e.g. Desktop, Mobile, Tablet, Laptop, Game Console, Set-top Box.",
        {"mac": MAC, "type": ("Type", "Device type.", True, TXT, "Mobile")},
    ),
    "remove_device": ("Remove device", "Delete a device from the box's device list.", {"mac": MAC}),
    "add_static_lease": (
        "Add fixed IP address",
        "Always give a device the same IP address.",
        {"mac": MAC, "ip_address": ("IP address", "Address in the LAN range.", True, TXT, "192.168.2.50")},
    ),
    "remove_static_lease": ("Remove fixed IP address", "Remove a device's fixed IP address.", {"mac": MAC}),
    "add_port_forward": (
        "Add port forward",
        "Create (or overwrite) a port-forwarding rule.",
        {
            "name": ("Name", "Rule name.", True, TXT, "Minecraft"),
            "external_port": ("External port", "Port or range, e.g. 25565 or 5000-5010.", True, TXT, "25565"),
            "internal_port": ("Internal port", "Defaults to the external port.", False, TXT, None),
            "ip_address": ("Device IP", "Local IPv4 address.", True, TXT, "192.168.2.16"),
            "protocol": PROTO,
            "enabled": ("Enabled", "Start enabled.", False, BOOL, None),
            "source_prefix": ("Source", "Only allow this source address/prefix (optional).", False, TXT, None),
        },
    ),
    "remove_port_forward": (
        "Remove port forward",
        "Delete a port-forwarding rule by name.",
        {"name": ("Name", "Rule name as shown in Home Assistant / the web UI.", True, TXT, None)},
    ),
    "add_ipv6_pinhole": (
        "Add IPv6 open port",
        "Open a port to a device over IPv6.",
        {
            "name": ("Name", "Description.", True, TXT, None),
            "port": ("Port", "Port or range.", True, TXT, "443"),
            "ip_address": ("Device IPv6", "Global IPv6 address of the device.", True, TXT, None),
            "protocol": PROTO,
            "enabled": ("Enabled", "Start enabled.", False, BOOL, None),
        },
    ),
    "remove_ipv6_pinhole": (
        "Remove IPv6 open port",
        "Delete an IPv6 open port by its ID.",
        {"id": ("ID", "Pinhole ID (shown as the switch's 'id' attribute).", True, TXT, None)},
    ),
    "add_firewall_rule": (
        "Add firewall rule",
        "Create (or overwrite) a custom firewall rule. Used with firewall level Custom.",
        {
            "id": ("ID", "Letters, digits, - and _.", True, TXT, "ssh"),
            "chain": ("Chain", "Custom (IPv4) or Custom_V6Out.", False, sel("Custom", "Custom_V6Out"), None),
            "action": ("Action", "Accept, Drop or Reject.", False, sel("Accept", "Drop", "Reject"), None),
            "protocol": PROTO,
            "destination_port": ("Destination port", "Port or range.", False, TXT, None),
            "source_port": ("Source port", "Port or range.", False, TXT, None),
            "destination": ("Destination", "Address/prefix.", False, TXT, None),
            "source": ("Source", "Address/prefix.", False, TXT, None),
            "ip_version": ("IP version", "4 or 6.", False, sel("4", "6"), None),
            "enabled": ("Enabled", "Start enabled.", False, BOOL, None),
        },
    ),
    "remove_firewall_rule": (
        "Remove firewall rule",
        "Delete a custom firewall rule.",
        {
            "id": ("ID", "Rule ID.", True, TXT, None),
            "chain": ("Chain", "Custom or Custom_V6Out.", False, sel("Custom", "Custom_V6Out"), None),
        },
    ),
    "set_firewall_policy": (
        "Set firewall chain policy",
        "Default action of a firewall chain (advanced).",
        {
            "chain": ("Chain", "Chain name, e.g. Custom.", True, TXT, None),
            "policy": ("Policy", "Accept, Drop or Reject.", True, sel("Accept", "Drop", "Reject"), None),
        },
    ),
    "set_dmz": (
        "Set DMZ host",
        "Expose one device fully to the internet (all ports forwarded). Use with care.",
        {"ip_address": ("IP address", "Local IPv4 address of the device.", True, TXT, "192.168.2.16")},
    ),
    "clear_dmz": ("Clear DMZ", "Remove the DMZ host.", {}),
    "set_lan": (
        "Set LAN / DHCP",
        "Change the home network. Only the fields you give change. "
        "Changing the router IP moves the box (and this integration follows).",
        {**LAN, "authoritative": ("Authoritative", "DHCP authoritative mode.", False, BOOL, None)},
    ),
    "set_guest_lan": ("Set guest network / DHCP", "Change the guest network. Only the fields you give change.", LAN),
    "set_hostname": (
        "Set hostname / domain",
        "The box's hostname and local domain.",
        {
            "hostname": ("Hostname", "Letters, digits and -.", False, TXT, None),
            "domain": ("Domain", "Local domain, e.g. home.", False, TXT, "home"),
        },
    ),
    "add_dyndns_host": (
        "Add DynDNS host",
        "Keep a dynamic DNS name pointed at your public IP.",
        {
            "service": (
                "Service",
                "Which DynDNS provider.",
                True,
                sel("dyndns", "No-IP", "ChangeIP", "GnuDIP", "AfraidFreeDNS", "Infomaniak", "OVH-dynhost"),
                None,
            ),
            "hostname": ("Hostname", "Your DynDNS name.", True, TXT, None),
            "username": ("Username", "Account at the service.", True, TXT, None),
            "password": ("Password", "Account password.", True, PWD, None),
        },
    ),
    "remove_dyndns_host": (
        "Remove DynDNS host",
        "Remove a DynDNS host.",
        {"hostname": ("Hostname", "DynDNS name.", True, TXT, None)},
    ),
    "set_dyndns_enabled": (
        "Enable/disable DynDNS",
        "Turn DynDNS updates on or off.",
        {"enabled": ("Enabled", "On or off.", True, BOOL, None)},
    ),
    "change_admin_password": (
        "Change admin password",
        "Change the KPN Box admin password; the integration keeps working with the new one.",
        {
            "current_password": ("Current password", "Current admin password.", True, PWD, None),
            "new_password": ("New password", "At least 8 characters.", True, PWD, None),
        },
    ),
    "set_ipv6_delegation_length": (
        "Set IPv6 delegated prefix length",
        "Prefix size handed to routers behind the box (the web UI uses 56).",
        {
            "network": ("Network", "home or guest.", False, sel("home", "guest"), None),
            "length": ("Length", "48-64.", True, {"number": {"min": 48, "max": 64}}, "56"),
        },
    ),
    "set_phone_line": (
        "Set up phone line",
        "Configure a SIP phone line (VoIP account details from your provider).",
        {
            "trunk": ("Trunk", "SIP-Trunk1 or SIP-Trunk2.", False, TXT, "SIP-Trunk1"),
            "line": ("Line", "LINE11 (trunk 1) or LINE21 (trunk 2).", False, TXT, "LINE11"),
            "number": ("Phone number", "Your number.", True, TXT, None),
            "username": ("SIP username", "Authentication user name.", True, TXT, None),
            "password": ("SIP password", "Authentication password.", True, PWD, None),
            "registrar": ("Registrar", "SIP registrar server.", True, TXT, None),
            "outbound_proxy": ("Outbound proxy", "Optional.", False, TXT, None),
            "domain": ("Domain", "User agent domain (optional).", False, TXT, None),
        },
    ),
    "clear_phone_line": (
        "Clear phone line",
        "Remove a phone line's configuration.",
        {
            "trunk": ("Trunk", "SIP-Trunk1 or SIP-Trunk2.", False, TXT, "SIP-Trunk1"),
            "line": ("Line", "LINE11 or LINE21.", False, TXT, "LINE11"),
        },
    ),
    "set_incoming_phones": (
        "Set phones for incoming calls",
        "Which phone ports ring for a line group.",
        {
            "group": ("Group", "Line group, e.g. Group1.", False, TXT, "Group1"),
            "handsets": ("Phones", "Phone ports, e.g. FXS1, FXS2.", True, OBJ, '["FXS1", "FXS2"]'),
        },
    ),
    "set_outgoing_line": (
        "Set outgoing line",
        "Which line a phone port calls out on.",
        {
            "handset": ("Phone", "Phone port, e.g. FXS1.", True, TXT, "FXS1"),
            "line": ("Line", "Trunk line, e.g. LINE11.", True, TXT, "LINE11"),
            "number": ("Internal number", "e.g. **1 (optional).", False, TXT, None),
        },
    ),
    "start_password_recovery": (
        "Start password recovery",
        "Start the box's 'forgot password' procedure (then follow the box's instructions).",
        {},
    ),
    "reset_admin_password": (
        "Reset admin password",
        "Reset the admin password to the default on the box's sticker. The integration then asks for the new password.",
        {"confirm": ("Confirm", "Type: reset password", True, TXT, "reset password")},
    ),
    "set_wan_mode": (
        "Set WAN mode",
        "Change how the box connects to the internet. A wrong mode cuts the internet.",
        {
            "mode": (
                "Mode",
                "Ethernet_PPP, VDSL_PPP, ADSL_PPPOA or Ethernet_DHCP.",
                True,
                sel("Ethernet_PPP", "VDSL_PPP", "ADSL_PPPOA", "Ethernet_DHCP"),
                None,
            ),
            "username": ("PPP username", "Optional.", False, TXT, None),
            "password": ("PPP password", "Optional.", False, PWD, None),
            "confirm": ("Confirm", "Type: change wan mode", True, TXT, "change wan mode"),
        },
    ),
    "shutdown": (
        "Shut down",
        "Turn the KPN Box off. It must be switched on again by hand.",
        {"confirm": ("Confirm", "Type: shut down", True, TXT, "shut down")},
    ),
    "call": (
        "Call any box function",
        "Run any function the KPN Box exposes and return its answer. Use 'describe' to find functions. "
        "No safety checks: you can break your connection with this.",
        {
            "service": ("Object", "e.g. NMC.Wifi or Devices.Device.AA:BB:CC:DD:EE:FF.", True, TXT, "NMC.Wifi"),
            "method": ("Function", "e.g. get.", True, TXT, "get"),
            "parameters": ("Parameters", "Arguments as a mapping.", False, OBJ, "{}"),
        },
    ),
    "describe": (
        "Describe box object",
        "List the functions (with arguments), settings and children of an object.",
        {"object": ("Object", "e.g. NMC, NMC.Wifi, NeMo.Intf.rad5g0, Firewall.", True, TXT, "NMC.Wifi")},
    ),
    "factory_reset": (
        "Factory reset",
        "Reset the KPN Box to factory settings. All settings are lost and the box restarts.",
        {"confirm": ("Confirm", "Type: factory reset", True, TXT, "factory reset")},
    ),
}
ENTRY = (
    "KPN Box",
    "Which box to use (only needed with more than one).",
    False,
    {"config_entry": {"integration": "kpn_box"}},
    None,
)


def main() -> None:
    lines, strings = [], {}
    for svc, (name, desc, fields) in SERVICES.items():
        fields = {**fields, "config_entry_id": ENTRY}
        lines += [f"{svc}:", "  fields:"]
        field_strings = {}
        for field, (fname, fdesc, required, selector, example) in fields.items():
            lines.append(f"    {field}:")
            if required:
                lines.append("      required: true")
            if example:
                lines.append(f"      example: {json.dumps(example)}")
            kind, opts = next(iter(selector.items()))
            lines += ["      selector:", f"        {kind}:"]
            lines += [f"          {k}: {json.dumps(v)}" for k, v in opts.items()]
            field_strings[field] = {"name": fname, "description": fdesc}
        lines.append("")
        strings[svc] = {"name": name, "description": desc, "fields": field_strings}
    (ROOT / "services.yaml").write_text("\n".join(lines), encoding="utf-8")
    for path in (ROOT / "strings.json", ROOT / "translations" / "en.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["services"] = strings
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(SERVICES)} services written")


if __name__ == "__main__":
    main()
