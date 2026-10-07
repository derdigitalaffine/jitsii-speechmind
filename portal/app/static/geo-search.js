/* One search policy for address fields, trips, POIs and the map browser. */
(function () {
  'use strict';
  function get(url) { return fetch(url, {credentials: 'same-origin', cache: 'no-store'}).then(function (r) { if (!r.ok) { throw Error('Adressdienst nicht erreichbar.'); } return r.json(); }); }
  var policy = get('/geo/info');
  var places = get('/geo/locations').then(function (d) { return d.locations || []; }).catch(function () { return []; });
  function search(q, live) {
    q = q.trim();
    if (q.length < 3) { return Promise.resolve([]); }
    return Promise.all([get('/geo/search?public_place=1&live=' + (live ? '1' : '0') + '&q=' + encodeURIComponent(q)).catch(function(e){return {results:[],error:e};}), places]).then(function (values) {
      var words = q.toLocaleLowerCase('de').split(/\s+/);
      var local = values[1].filter(function (p) { return words.every(function (w) { return p.label.toLocaleLowerCase('de').includes(w); }); }).slice(0, 6).map(function(p){var match=(p.street||'').match(/^(.*?)\s+(\d+\s?[a-zA-Z]?(?:[-/]\d+[a-zA-Z]?)?)$/);return match?Object.assign({},p,{street:match[1],house_no:match[2]}):p;});
      if (!local.length && values[0].error) { throw values[0].error; }
      return local.concat(values[0].results || []).filter(function (p, i, all) { return all.findIndex(function (v) { return v.label === p.label; }) === i; }).slice(0, 10);
    });
  }
  function bind(input, show, error) {
    var timer, version = 0, currentPolicy;
    policy.then(function (p) { currentPolicy = p; }).catch(error || function () {});
    function run(live) {
      clearTimeout(timer);
      var q = input.value.trim(), request = ++version;
      if (!currentPolicy || q.length < 3) { show([], live); return; }
      search(q, live).then(function (results) { if (version === request && input.value.trim() === q) { show(results, live); } }).catch(function (e) { if (version === request && error) { error(e); } });
    }
    input.addEventListener('input', function () {
      ++version; clearTimeout(timer); show([], true);
      if (currentPolicy && currentPolicy.search_mode !== 'manual' && input.value.trim().length >= 3) { timer = setTimeout(function () { run(true); }, currentPolicy.delay_ms); }
    });
    return function () { run(false); };
  }
  window.GeoSearch = {policy: policy, search: search, bind: bind};
}());
