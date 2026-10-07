const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
(async function () {
  for (const publicOnly of [true, false]) {
    const calls = [], timers = [], pending = [];
    const context = {window: {}, clearTimeout: function (timer) {if (timer) {timer.cancelled = true;}}, setTimeout: function (run, delay) {const timer = {run, delay}; timers.push(timer); return timer;}, fetch: function (url) {
      calls.push(url);
      if (url === '/geo/info') {return Promise.resolve({ok: true, json: async () => ({public_only: publicOnly, delay_ms: publicOnly ? 1000 : 300, search_mode: 'auto'})});}
      if (url === '/geo/locations') {return Promise.resolve({ok: true, json: async () => ({locations: [{label: 'Rathaus Otterberg', lat: 49, lon: 7}]})});}
      return new Promise(resolve => pending.push(function (label) {resolve({ok: true, json: async () => ({results: [{label}]})});}));
    }};
    vm.runInNewContext(fs.readFileSync('portal/app/static/geo-search.js', 'utf8'), context);
    const events = {}, input = {value: '', addEventListener: (name, fn) => {events[name] = fn;}}, shown = [];
    const run = context.window.GeoSearch.bind(input, (items, live) => shown.push({items, live}), e => {throw e;});
    await new Promise(resolve => setImmediate(resolve));
    input.value = 'Rathaus'; events.input();
    assert.equal(timers.at(-1).delay, publicOnly ? 1000 : 300);
    timers.at(-1).run();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(calls.at(-1), /live=1/);
    input.value = 'Otterberg'; events.input();
    pending.shift()('Obsolete result');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(shown.at(-1).items.length, 0, 'ignore old response after changed input');
    run();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(calls.at(-1), /live=0/);
    pending.shift()('Remote Otterberg');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(shown.at(-1).items[0].label, 'Rathaus Otterberg');
    assert.equal(shown.at(-1).items[1].label, 'Remote Otterberg');
  }
  console.log('Search intervals, stale responses, explicit requests and POI suggestions passed.');
}()).catch(e => {console.error(e); process.exitCode = 1;});
