"""Minimal client for the KPN Box 12 (Sagemcom F@st 5359, prpl/SoftAtHome firmware) sysbus API.

Usage:
  Put KPNBOX_PASSWORD=... in .env in the repo root (or you'll be prompted)
  python scripts/kpnbox.py info              # model / firmware (no login needed)
  python scripts/kpnbox.py wan               # WAN status
  python scripts/kpnbox.py devices           # connected hosts
  python scripts/kpnbox.py wifi              # Wi-Fi status
  python scripts/kpnbox.py ethstats          # per-LAN-port traffic counters
  python scripts/kpnbox.py wifi-enable true|false
  python scripts/kpnbox.py call <service> <method> ['{"json": "params"}']
"""

import getpass
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import urllib.request

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_dotenv(path=ENV_FILE):
    """Load KEY=value lines from .env into os.environ (existing variables win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if value:
                os.environ.setdefault(key.strip(), value)


load_dotenv()

HOST = os.environ.get("KPNBOX_HOST", "http://192.168.2.254")
ENDPOINT = f"{HOST}/ws/NeMo/Intf/lan:getMIBs"
CT = "application/x-sah-ws-4-call+json"


class KPNBox:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.context = None

    def _post(self, body, headers):
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": CT, **headers})
        with self.opener.open(req, timeout=15) as r:
            return json.loads(r.read())

    def login(self, password, username="admin"):
        res = self._post(
            {
                "service": "sah.Device.Information",
                "method": "createContext",
                "parameters": {"applicationName": "webui", "username": username, "password": password},
            },
            {"Authorization": "X-Sah-Login"},
        )
        if res.get("status") != 0 or "data" not in res:
            raise RuntimeError(f"Login failed: {res}")
        self.context = res["data"]["contextID"]

    def call(self, service, method, parameters=None):
        headers = {}
        if self.context:
            headers = {"Authorization": f"X-Sah {self.context}", "X-Context": self.context}
        res = self._post({"service": service, "method": method, "parameters": parameters or {}}, headers)
        if res.get("errors"):
            raise RuntimeError(res["errors"])
        return res


def main(argv):
    if not argv:
        print(__doc__)
        return
    box = KPNBox()
    cmd = argv[0]
    if cmd != "info":
        box.login(os.environ.get("KPNBOX_PASSWORD") or getpass.getpass("Router admin password: "))

    if cmd == "info":
        out = box.call("DeviceInfo", "get")
    elif cmd == "wan":
        out = box.call("NMC", "getWANStatus")
    elif cmd == "devices":
        out = box.call("Devices", "get", {"expression": "not interface and not self"})
    elif cmd == "wifi":
        out = box.call("NMC.Wifi", "get")
    elif cmd == "ethstats":
        out = {f"ETH{i}": box.call(f"NeMo.Intf.ETH{i}", "getNetDevStats").get("status") for i in range(4)}
    elif cmd == "wifi-enable":
        out = box.call("NMC.Wifi", "set", {"Enable": argv[1].lower() == "true"})
    elif cmd == "call":
        out = box.call(argv[1], argv[2], json.loads(argv[3]) if len(argv) > 3 else {})
    else:
        sys.exit(f"Unknown command: {cmd}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
