const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("WiGLE status follows visibility, display mode, and clearing", async () => {
  const html = fs.readFileSync(path.join(__dirname, "../templates/rf_map.html"), "utf8");
  const start = html.indexOf("function parseWigleCSV");
  const code = html.slice(start, html.indexOf('map.on("click", (e)', start));
  const handlers = {};
  const fileInput = { files: [], set value(value) { if (!value) this.files = []; } };
  const controls = { wigleFile: fileInput, wigleLayer: { checked: true }, wigleMode: { value: "density" } };
  for (const [id, control] of Object.entries(controls)) {
    control.addEventListener = (event, callback) => { handlers[id] = callback; };
  }
  const bounds = { extend() {}, contains() { return true; } };
  let popup;
  const marker = { bindTooltip() { return this; }, bindPopup(content) { popup = content; return this; }, addTo() {} };
  let zoom = 15;
  const page = {};
  vm.runInNewContext(code, {
    window: page,
    $: (id) => id === "surveySyncStatus" ? null : controls[id] ??= {},
    wigle: { clearLayers() {}, addTo() {} },
    map: { on: (event, callback) => { handlers[event] = callback; }, getZoom: () => zoom, getBounds: () => bounds, fitBounds() {} },
    L: { latLngBounds: () => bounds, rectangle: () => marker, circleMarker: () => marker },
    splitCSVRow: (row) => row.split(","),
    saveLayerSettings() {},
    safe: (value) => value,
  });

  const csv = "SSID,CurrentLatitude,CurrentLongitude,Type\nTest network,42,-76,WIFI";
  fileInput.files = [{ text: async () => csv }];
  await fileInput.onchange({ target: fileInput });
  assert.match(controls.wigleStatus.textContent, /reception areas/);

  controls.wigleLayer.checked = false;
  handlers.wigleLayer();
  assert.match(controls.wigleStatus.textContent, /Turn on WiGLE/);
  controls.wigleMode.value = "pins";
  handlers.wigleMode();
  assert.match(controls.wigleStatus.textContent, /Turn on WiGLE/);

  controls.wigleLayer.checked = true;
  handlers.wigleLayer();
  assert.match(controls.wigleStatus.textContent, /1 Wi-Fi reception locations in view/);
  zoom = 10;
  handlers.moveend();
  assert.match(controls.wigleStatus.textContent, /Zoom in/);

  let finishRead;
  fileInput.files = [{ text: () => new Promise((resolve) => { finishRead = resolve; }) }];
  const pending = fileInput.onchange({ target: fileInput });
  controls.clearWigle.onclick();
  finishRead(csv);
  await pending;
  handlers.moveend();
  assert.equal(controls.wigleStatus.textContent, "");

  zoom = 15;
  assert.equal(page.ghostEmImportWigleCsv(csv), 1);
  assert.match(controls.wigleStatus.textContent, /1 Wi-Fi reception locations in view/);
  const combined = csv + "\nSecond network,42,-76,WIFI";
  assert.equal(page.ghostEmImportWigleCsv(combined), 2);
  assert.match(controls.wigleStatus.textContent, /1 Wi-Fi reception locations in view/);
  assert.match(popup, /Test network/);
  assert.match(popup, /Second network/);
  assert.throws(() => page.ghostEmImportWigleCsv("SSID,lat,lon\nNo fix,,"), /valid coordinates/);
});
