const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../templates/rf_map.html"), "utf8");
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const locationCode = script.slice(script.indexOf("let myLocation"), script.indexOf("function redraw"));

function setup({ saved = null, allowed = true, geolocation = true } = {}) {
  const controls = {};
  const positions = [];
  const requests = [];
  const marker = { addTo() { return this; }, bindPopup() { return this; }, setLatLng() {} };
  const browser = geolocation
    ? { getCurrentPosition: (success, fail, options) => requests.push({ success, fail, options }) }
    : undefined;

  vm.runInNewContext(locationCode, {
    $: (id) => controls[id] ??= {},
    document: { permissionsPolicy: { allowsFeature: () => allowed } },
    navigator: { geolocation: browser },
    L: { circleMarker: () => marker },
    map: { getZoom: () => 15, setView: (point, zoom) => positions.push([Array.from(point), zoom]) },
    sessionStorage: { getItem: () => saved, removeItem() {} },
  });
  return { click: controls.myLocation.onclick, controls, positions, requests };
}

test("returns to the location shared on the landing page", () => {
  const app = setup({ saved: '{"latitude":42,"longitude":-76}' });
  app.click();
  assert.deepEqual(app.positions, [[[42, -76], 15], [[42, -76], 15]]);
  assert.equal(app.requests.length, 0);
});

test("retries a timeout once and reuses the successful position", () => {
  const app = setup();
  app.click();
  assert.equal(app.controls.myLocation.disabled, true);
  app.requests[0].fail({ code: 3 });
  assert.equal(app.requests.length, 2);
  assert.equal(app.requests[1].options.enableHighAccuracy, true);
  app.requests[1].success({ coords: { latitude: 0, longitude: 0 } });
  assert.equal(app.controls.myLocation.disabled, false);
  app.click();
  assert.equal(app.requests.length, 2);
  assert.deepEqual(app.positions, [[[0, 0], 15], [[0, 0], 15]]);
});

test("distinguishes denial, an unavailable position, and a second timeout", () => {
  for (const [code, message, attempts] of [
    [1, /blocked/, 1], [2, /couldn’t provide a position/, 2], [3, /timed out/, 2],
  ]) {
    const app = setup();
    app.click();
    app.requests[0].fail({ code });
    if (attempts === 2) app.requests[1].fail({ code });
    assert.equal(app.requests.length, attempts);
    assert.equal(app.controls.myLocation.disabled, false);
    assert.match(app.controls.locationStatus.textContent, message);
    assert.deepEqual(app.positions, []);
  }
});

test("does not request location when browser policy or capability blocks it", () => {
  for (const options of [{ allowed: false }, { geolocation: false }]) {
    const app = setup(options);
    app.click();
    assert.equal(app.requests.length, 0);
    assert.match(app.controls.locationStatus.textContent, /Open the RF map directly/);
  }
});
