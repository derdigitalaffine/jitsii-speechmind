/* Reusable periods, repeating rows, derived values and drawn signatures. */
(function () {
  'use strict';
  var form = document.querySelector('form.js-fill');
  if (!form) { return; }
  function value(raw, fallback) { try { var v = JSON.parse(raw || 'null'); if (typeof v === 'string') { v = JSON.parse(v); } return v || fallback; } catch (e) { return fallback; } }
  function changed(hidden, data) { hidden.value = JSON.stringify(data); hidden.dispatchEvent(new Event('input', { bubbles: true })); }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  form.querySelectorAll('.js-period').forEach(function (box) {
    var initial = value(box.dataset.value, {}), start = box.querySelector('[name$="__start"]'), end = box.querySelector('[name$="__end"]'), hidden = box.querySelector('.js-structured-value');
    function sync() { end.min = start.value; end.setCustomValidity(start.value && end.value && end.value < start.value ? 'Das Ende darf nicht vor dem Anfang liegen.' : ''); changed(hidden, {start:start.value, end:end.value}); }
    start.value = initial.start || ''; end.value = initial.end || '';
    start.addEventListener('input', sync); end.addEventListener('input', sync);
    hidden.addEventListener('change', function () { var restored = value(hidden.value, {}); start.value = restored.start || ''; end.value = restored.end || ''; sync(); });
    sync();
  });
  form.querySelectorAll('.js-table').forEach(function (box) {
    var cols = value(box.dataset.columns, []), initial = value(box.dataset.value, []), area = box.querySelector('.js-table-rows'), hidden = box.querySelector('.js-structured-value'), add = box.querySelector('.js-table-add');
    var max = Number(box.dataset.max) || 30, min = Math.max(Number(box.dataset.min) || 0, box.dataset.required ? 1 : 0), sequence = 0;
    function sync() {
      var rows = [];
      area.querySelectorAll('.structured-row').forEach(function (row, index) {
        var obj = {}; row.querySelector('.js-row-number').textContent = 'Position ' + (index+1);
        row.querySelectorAll('[data-cell]').forEach(function (el) { obj[el.dataset.cell] = el.type === 'checkbox' ? el.checked : el.value; }); rows.push(obj);
      });
      add.disabled = rows.length >= max;
      add.setCustomValidity(rows.length < Math.max(Number(box.dataset.min) || 0, box.dataset.required ? 1 : 0) ? 'Bitte mindestens ' + min + ' Position(en) erfassen.' : '');
      changed(hidden, rows);
    }
    function append(data, focus) {
      if (area.children.length >= max) { return; }
      var row = document.createElement('div'); row.className = 'structured-row border rounded p-3';
      var number = ++sequence;
      row.innerHTML = '<div class="d-flex justify-content-between mb-2"><strong class="js-row-number"></strong><button type="button" class="btn btn-sm btn-outline-danger js-row-remove" aria-label="Position entfernen">Entfernen</button></div><div class="row g-2">' + cols.map(function (c) {
        var id = box.dataset.name + '-row-' + number + '-' + c.id, val = data[c.id];
        var attrs = ' id="' + esc(id) + '" data-cell="' + esc(c.id) + '"' + (c.required ? ' required' : '');
        var input;
        if (c.type === 'select') { input = '<select class="form-select"' + attrs + '><option value="">Bitte wählen …</option>' + (c.options || []).map(function (o) { return '<option value="' + esc(o) + '"' + (val === o ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>'; }
        else if (c.type === 'checkbox') { input = '<input class="form-check-input" type="checkbox"' + attrs + (val === true ? ' checked' : '') + '>'; }
        else { var type = c.type === 'amount' || c.type === 'number' ? 'number' : c.type === 'datetime' ? 'datetime-local' : c.type;
          input = '<input class="form-control" type="' + esc(type) + '"' + attrs + ' value="' + esc(val == null ? '' : val) + '"' + (type === 'number' ? ' step="' + (c.type === 'amount' ? '0.01' : 'any') + '" inputmode="decimal"' : ' maxlength="2000"') + (c.min != null ? ' min="' + esc(c.min) + '"' : '') + (c.max != null ? ' max="' + esc(c.max) + '"' : '') + '>'; }
        return '<div class="col-12 col-md-6"><label class="form-label small" for="' + esc(id) + '">' + esc(c.label) + '</label>' + input + '</div>';
      }).join('') + '</div>';
      area.appendChild(row); row.addEventListener('input', sync); row.addEventListener('change', sync);
      row.querySelector('.js-row-remove').addEventListener('click', function () { row.remove(); sync(); add.focus(); });
      sync(); if (focus) { row.querySelector('input, select').focus(); }
    }
    add.addEventListener('click', function () { append({}, true); });
    if (!Array.isArray(initial)) { initial = []; }
    initial.forEach(function (row) { append(row, false); });
    while (area.children.length < min) { append({}, false); }
    hidden.addEventListener('change', function () { area.innerHTML = ''; value(hidden.value, []).forEach(function (row) { append(row, false); }); sync(); });
    form.addEventListener('submit', function (ev) { if (!hidden.disabled && area.children.length < Math.max(Number(box.dataset.min) || 0, box.dataset.required ? 1 : 0)) { ev.preventDefault(); add.reportValidity(); } });
    sync();
  });
  var calcs = Array.from(form.querySelectorAll('.js-calculation'));
  function recalculate() {
    var visiting = [], computed = {};
    function calc(box) {
      if (Object.prototype.hasOwnProperty.call(computed, box.dataset.name)) { return computed[box.dataset.name]; }
      if (visiting.indexOf(box) >= 0) { return NaN; }
      visiting.push(box);
      var nums = [], sources = value(box.dataset.sources, []);
      sources.forEach(function (id) {
        var name = 'q_' + id, sourceCalc = calcs.find(function (x) { return x.dataset.name === name; });
        var source = form.querySelector('[name="' + CSS.escape(name) + '"]');
        if (sourceCalc) { nums.push(calc(sourceCalc)); }
        else if (box.dataset.operation === 'table_total') {
          var rows = value(source && !source.disabled ? source.value : '[]', []);
          if (Array.isArray(rows)) { rows.forEach(function (r) { nums.push(Number(String(r[box.dataset.column] || 0).replace(',', '.')) * (box.dataset.quantity ? Number(r[box.dataset.quantity] || 0) : 1)); }); }
        } else { nums.push(Number(String(source && !source.disabled ? source.value || 0 : 0).replace(',', '.'))); }
      });
      var result = box.dataset.operation === 'product' ? nums.reduce(function (a,b) { return a*b; }, nums.length ? 1 : 0) : box.dataset.operation === 'difference' ? (nums[0] || 0) - nums.slice(1).reduce(function (a,b) { return a+b; },0) : nums.reduce(function (a,b) { return a+b; },0);
      computed[box.dataset.name] = result; visiting.pop();
      box.querySelector('output').textContent = Number.isFinite(result) ? result.toLocaleString('de-DE', {minimumFractionDigits:Number(box.dataset.precision), maximumFractionDigits:Number(box.dataset.precision)}) : 'Bitte Angaben prüfen';
      return result;
    }
    calcs.forEach(calc);
  }
  form.addEventListener('input', recalculate); form.addEventListener('change', recalculate); recalculate();
  form.querySelectorAll('.js-signature').forEach(function (box) {
    var initial = value(box.dataset.value, {}), strokes = initial.strokes || [], canvas = box.querySelector('canvas'), ctx = canvas.getContext('2d'), name = box.querySelector('.js-sign-name'), hidden = box.querySelector('.js-structured-value'), stroke = null;
    name.value = initial.name || '';
    function sync() { name.setCustomValidity(box.dataset.required && !strokes.some(function (s) { return s.length >= 2; }) ? 'Bitte unterschreiben.' : ''); changed(hidden, {name:name.value, strokes:strokes}); }
    function draw() { ctx.clearRect(0,0,canvas.width,canvas.height); ctx.strokeStyle = '#182b44'; ctx.lineWidth = 2; strokes.forEach(function (s) { ctx.beginPath(); s.forEach(function (p,i) { if (i) { ctx.lineTo(p[0]*canvas.width,p[1]*canvas.height); } else { ctx.moveTo(p[0]*canvas.width,p[1]*canvas.height); } }); ctx.stroke(); }); }
    function point(ev) { var r=canvas.getBoundingClientRect(); return [Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height))]; }
    canvas.tabIndex = 0;
    var cursor = [.5, .5];
    canvas.addEventListener('keydown', function (ev) {
      if (ev.key === ' ') { ev.preventDefault(); if (stroke) {finish();} else {stroke=[cursor.slice()]; strokes.push(stroke);} }
      if (ev.key === 'Escape' || ev.key === 'Enter') {finish();}
      if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].indexOf(ev.key)>=0) {ev.preventDefault(); cursor[0]=Math.max(0,Math.min(1,cursor[0]+(ev.key==='ArrowLeft'?-.01:ev.key==='ArrowRight'?.01:0)));cursor[1]=Math.max(0,Math.min(1,cursor[1]+(ev.key==='ArrowUp'?-.01:ev.key==='ArrowDown'?.01:0))); if(stroke){stroke.push(cursor.slice());draw();}}
    });
    canvas.addEventListener('pointerdown', function (ev) { if (hidden.disabled || strokes.length >= 100) { return; } ev.preventDefault(); stroke=[point(ev)]; strokes.push(stroke); canvas.setPointerCapture(ev.pointerId); });
    canvas.addEventListener('pointermove', function (ev) { if (!stroke || strokes.reduce(function (n,s) { return n+s.length; },0) >= 5000) { return; } stroke.push(point(ev)); draw(); });
    function finish() { stroke=null; sync(); }
    canvas.addEventListener('pointerup', finish); canvas.addEventListener('pointercancel', finish);
    box.querySelector('.js-sign-clear').addEventListener('click', function () { strokes=[]; draw(); sync(); });
    name.addEventListener('input', sync);
    // Signatures are never silently restored from a saved draft.
    draw(); sync();
  });
})();
