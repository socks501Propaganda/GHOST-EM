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
  const controls = { wigleFile: fileInput, wigleLayer: { checked: true }, bluetoothLayer: { checked: true }, wigleMode: { value: "density" } };
  for (const [id, control] of Object.entries(controls)) {
    control.addEventListener = (event, callback) => { handlers[id] = callback; };
  }
  const bounds = { extend() {}, contains() { return true; }, isValid() { return true; } };
  const markers = [];
  function marker(position, options) {
    return { bindTooltip() { return this; }, on(event, tap) { markers.push({ position, options, tap }); return this; }, addTo() {} };
  }
  let zoom = 15;
  const page = {};
  vm.runInNewContext(code, {
    window: page,
    $: (id) => id === "surveySyncStatus" ? null : controls[id] ??= {},
    wigle: { clearLayers() { markers.length = 0; }, addTo() {} },
    map: { on: (event, callback) => { handlers[event] = callback; }, getZoom: () => zoom, getBounds: () => bounds, fitBounds() {}, distance: (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) * 100000, latLngToLayerPoint: ([lat, lon]) => ({ x: lon * 1000, y: lat * 1000 }), layerPointToLatLng: ({ x, y }) => [y / 1000, x / 1000] },
    L: { latLngBounds: () => bounds, circleMarker: marker, point: (x, y) => ({ x, y }), polyline: () => ({ addTo() {} }) },
    splitCSVRow: (row) => row.split(","),
    saveLayerSettings() {},
    safe: (value) => value,
  });

  const csv = "SSID,CurrentLatitude,CurrentLongitude,Type\nTest network,42,-76,WIFI";
  fileInput.files = [{ text: async () => csv }];
  await fileInput.onchange({ target: fileInput });
  assert.match(controls.wigleStatus.textContent, /reception areas/);

  controls.wigleLayer.checked = false;
  controls.bluetoothLayer.checked = false;
  handlers.wigleLayer();
  assert.match(controls.wigleStatus.textContent, /Turn on Wi-Fi or Bluetooth/);
  controls.wigleMode.value = "pins";
  handlers.wigleMode();
  assert.match(controls.wigleStatus.textContent, /Turn on Wi-Fi or Bluetooth/);

  controls.wigleLayer.checked = true;
  handlers.wigleLayer();
  assert.match(controls.wigleStatus.textContent, /1 individual devices in view/);
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
  assert.match(controls.wigleStatus.textContent, /1 individual devices in view/);
  const combined = csv + "\nSecond network,42,-76,WIFI";
  assert.equal(page.ghostEmImportWigleCsv(combined), 2);
  assert.match(controls.wigleStatus.textContent, /2 individual devices in view/);
  assert.notDeepEqual(markers[0].position, markers[1].position);
  assert.equal(markers[0].options.fillColor, "#f02c38");
  markers[0].tap();
  assert.equal(controls.wifiDetails.hidden, false);
  assert.match(controls.wifiDetailsContent.innerHTML, /Test network/);
  assert.doesNotMatch(controls.wifiDetailsContent.innerHTML, /Second network/);
  markers[1].tap();
  assert.match(controls.wifiDetailsContent.innerHTML, /Second network/);
  handlers.moveend();
  assert.equal(controls.wifiDetails.hidden, false);
  controls.closeWifiDetails.onclick();
  assert.equal(controls.wifiDetails.hidden, true);
  controls.bluetoothLayer.checked = true;
  const mixed = "SSID,MAC,lat,lon,RSSI,Type\nOne,02:00:00:00:00:01,42,-76,-40,WIFI" +
    "\nOne,02:00:00:00:00:01,42.001,-76,-70,WIFI\nOne,02:00:00:00:00:01,42,-76.001,-80,WIFI" +
    "\nBeacon,02:00:00:00:00:01,42,-76,-60,BLE";
  page.ghostEmImportWigleCsv(mixed, { sync: false });
  assert.equal(markers.length, 2);
  assert.equal(markers[1].options.fillColor, "#219efa");
  markers[0].tap();
  assert.match(controls.wifiDetailsContent.innerHTML, /Estimated access point/);
  assert.match(controls.wifiDetailsContent.innerHTML, /from 3 signal readings/);
  markers[1].tap();
  assert.match(controls.wifiDetailsContent.innerHTML, /Bluetooth address: 02:00/);
  assert.throws(() => page.ghostEmImportWigleCsv("SSID,lat,lon\nNo fix,,"), /valid coordinates/);
});
