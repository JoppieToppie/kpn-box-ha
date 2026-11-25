// Dashboard card for the KPN Box integration: every device on the network in one sortable, searchable table.
// No build step and no dependencies; Home Assistant loads it automatically once the integration is set up.

const COLUMNS = [
  ["name", "Name"],
  ["ip", "IP address"],
  ["mac", "MAC address"],
  ["link", "Connection"],
  ["signal", "Signal"],
];

// Device names come from the devices themselves, so never put them into HTML unescaped
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const ipKey = (ip) => (ip || "").split(".").map((n) => n.padStart(3, "0")).join(".");

class KpnBoxCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "KPN Box", show_offline: false, ...config };
    this._sort = { key: "name", dir: 1 };
    this._search = "";
    this._sig = null;
  }

  static getStubConfig() {
    return {};
  }

  getCardSize() {
    return 8;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._build();
    this._update();
  }

  devices() {
    const hass = this._hass;
    return Object.values(hass.entities || {})
      .filter((e) => e.platform === "kpn_box" && e.entity_id.startsWith("device_tracker."))
      .map((e) => hass.states[e.entity_id])
      .filter(Boolean)
      .map((s) => {
        const a = s.attributes;
        const wifi = a.connection === "wifi";
        return {
          id: s.entity_id,
          name: a.friendly_name || s.entity_id,
          online: s.state === "home",
          ip: a.ip || "",
          mac: a.mac || "",
          link: wifi ? `Wi-Fi${a.band ? ` ${a.band}` : ""}` : a.connection ? "Ethernet" : "",
          signal: wifi && a.signal_strength != null ? a.signal_strength : null,
        };
      });
  }

  rebootButton() {
    // The integration's restart button; only admins get to press it from here
    const hass = this._hass;
    if (!hass.user?.is_admin) return null;
    const e = Object.values(hass.entities || {}).find(
      (e) =>
        e.platform === "kpn_box" &&
        e.entity_id.startsWith("button.") &&
        hass.states[e.entity_id]?.attributes.device_class === "restart",
    );
    return e?.entity_id ?? null;
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
        .head h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; }
        .count { color: var(--secondary-text-color); }
        input { width: 100%; box-sizing: border-box; padding: 8px; margin-bottom: 8px; border-radius: 4px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        button { cursor: pointer; border: none; border-radius: 4px; padding: 6px 12px;
          background: var(--error-color, #db4437); color: #fff; }
        .wrap { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th { text-align: left; cursor: pointer; user-select: none; color: var(--secondary-text-color); font-weight: 500; }
        th, td { padding: 6px 8px; white-space: nowrap; }
        tbody tr { cursor: pointer; border-top: 1px solid var(--divider-color); }
        tbody tr:hover { background: var(--secondary-background-color); }
        .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px;
          background: var(--disabled-text-color, #999); }
        .on .dot { background: var(--success-color, #43a047); }
        tr:not(.on) td { color: var(--secondary-text-color); }
        .empty { color: var(--secondary-text-color); padding: 8px; }
      </style>
      <ha-card>
        <div class="head"><h1></h1><span class="count"></span><button hidden>Restart</button></div>
        <input type="search" placeholder="Search name, IP or MAC">
        <div class="wrap"><table>
          <thead><tr>${COLUMNS.map(([k, l]) => `<th data-key="${k}">${l}</th>`).join("")}</tr></thead>
          <tbody></tbody>
        </table></div>
      </ha-card>`;
    root.querySelector("h1").textContent = this._config.title;
    root.querySelector("input").addEventListener("input", (ev) => {
      this._search = ev.target.value.toLowerCase();
      this._update(true);
    });
    root.querySelector("thead").addEventListener("click", (ev) => {
      const key = ev.target.closest("th")?.dataset.key;
      if (!key) return;
      this._sort = { key, dir: this._sort.key === key ? -this._sort.dir : 1 };
      this._update(true);
    });
    root.querySelector("tbody").addEventListener("click", (ev) => {
      const entityId = ev.target.closest("tr")?.dataset.id;
      if (entityId) this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
    });
    root.querySelector("button").addEventListener("click", () => {
      const id = this.rebootButton();
      if (id && confirm("Restart the KPN Box? The internet is down for a few minutes.")) {
        this._hass.callService("button", "press", { entity_id: id });
      }
    });
  }

  _update(force = false) {
    const root = this.shadowRoot;
    const all = this.devices();
    const reboot = this.rebootButton();
    // hass updates arrive for every state change in HA; only redraw when this card's data changed
    const sig = JSON.stringify([all, reboot]);
    if (!force && sig === this._sig) return;
    this._sig = sig;

    const online = all.filter((d) => d.online).length;
    root.querySelector(".count").textContent = `${online} online / ${all.length}`;
    root.querySelector("button").hidden = !reboot;

    const { key, dir } = this._sort;
    const val = (d) => (key === "ip" ? ipKey(d.ip) : key === "signal" ? (d.signal ?? -999) : String(d[key]).toLowerCase());
    const rows = all
      .filter((d) => this._config.show_offline || d.online)
      .filter((d) => !this._search || [d.name, d.ip, d.mac].some((v) => v.toLowerCase().includes(this._search)))
      .sort((a, b) => b.online - a.online || (val(a) > val(b) ? dir : val(a) < val(b) ? -dir : 0));

    root.querySelectorAll("th").forEach((th) => {
      const label = COLUMNS.find(([k]) => k === th.dataset.key)[1];
      th.textContent = th.dataset.key === key ? `${label} ${dir > 0 ? "▲" : "▼"}` : label;
    });
    root.querySelector("tbody").innerHTML = rows.length
      ? rows
          .map(
            (d) => `<tr class="${d.online ? "on" : ""}" data-id="${esc(d.id)}">
              <td><span class="dot"></span>${esc(d.name)}</td><td>${esc(d.ip)}</td><td>${esc(d.mac)}</td>
              <td>${esc(d.link)}</td><td>${d.signal == null ? "" : `${esc(d.signal)} dBm`}</td></tr>`,
          )
          .join("")
      : `<tr><td class="empty" colspan="${COLUMNS.length}">No devices</td></tr>`;
  }
}

customElements.define("kpn-box-card", KpnBoxCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "kpn-box-card",
  name: "KPN Box devices",
  description: "Every device on your KPN Box network: name, IP, MAC, connection and signal.",
});
