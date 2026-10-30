# Contributing

Issues and pull requests are welcome, especially reports from other KPN boxes and firmware versions.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate     # Python 3.14; on Windows use WSL
pip install -r requirements_dev.txt
pytest
ruff check && ruff format --check
```

## How the box's API works

The box runs SoftAtHome / prpl firmware. Everything goes through one endpoint:

```http
POST http://192.168.2.254/ws/NeMo/Intf/lan:getMIBs
Content-Type: application/x-sah-ws-4-call+json
Authorization: X-Sah <contextID>

{"service": "NMC", "method": "getWANStatus", "parameters": {}}
```

`KPNBoxApi.login()` gets the context ID; `KPNBoxApi.call()` logs in again by itself when the session expires.

## Adding a box function

1. Find the call. Either watch the web UI's network tab while you change the setting, or explore with the
   `kpn_box.describe` action (or `python scripts/kpnbox.py call <service> <method>`).
2. Add a method to `custom_components/kpn_box/api.py` that sends the same payload as the web UI.
3. Read it in `coordinator.py` if it's state, and add an entity, or add an action in `services.py`.
   Actions are described once in `tools/gen_services.py`; run `python tools/gen_services.py` to regenerate
   `services.yaml` and the texts in `strings.json` / `translations/en.json`.
4. Teach `FakeBox` in `tests/test_kpn_box.py` the new call and add a test that checks the exact payload.
5. If you have the box, check reads against it with `python scripts/live_check.py` (read-only).

Please don't paste passwords, serial numbers, public IPs or MAC addresses in issues or tests.
