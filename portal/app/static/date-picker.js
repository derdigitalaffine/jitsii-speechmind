/* Local German date entry. Original native inputs remain the ISO integration surface. */
(function (root) {
  'use strict';
  var months = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  function pad(n) { return String(n).padStart(2, '0'); }
  function dateISO(y, m, d) { return String(y).padStart(4, '0') + '-' + pad(m) + '-' + pad(d); }
  function validDate(y, m, d) {
    if (y < 1 || y > 9999 || m < 1 || m > 12 || d < 1) return false;
    var leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
    return d <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
  }
  function parse(text, type) {
    text = String(text || '').trim();
    if (!text) return { value: '', error: '' };
    var m, date, time;
    if (type !== 'time') {
      m = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*[,T]?\s+(.*))?$/);
      if (!m || !validDate(+m[3], +m[2], +m[1])) return { value: '', error: 'Bitte ein gültiges Datum im Format TT.MM.JJJJ eingeben.' };
      date = dateISO(+m[3], +m[2], +m[1]);
      if (type === 'date') return m[4] ? { value: '', error: 'Bitte nur das Datum eingeben.' } : { value: date, error: '' };
      time = m[4];
    } else time = text;
    m = String(time || '').match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
    if (!m || +m[1] > 23 || +m[2] > 59 || (m[3] && +m[3] > 59)) return { value: '', error: type === 'time' ? 'Bitte eine gültige Uhrzeit im Format HH:MM eingeben.' : 'Bitte Datum und Uhrzeit im Format TT.MM.JJJJ, HH:MM eingeben.' };
    time = pad(+m[1]) + ':' + m[2] + (m[3] ? ':' + m[3] : '');
    return { value: (type === 'time' ? '' : date + 'T') + time, error: '' };
  }
  function format(value, type) {
    if (!value) return '';
    if (type === 'time') return value;
    var parts = value.split('T'), date = parts[0].split('-');
    return date[2] + '.' + date[1] + '.' + date[0] + (type === 'datetime-local' ? ', ' + (parts[1] || '') : '');
  }
  function constraint(value, options) {
    if (!value) return options.required ? 'Bitte dieses Feld ausfüllen.' : '';
    var type = options.type || 'date';
    function comparable(v) { return v && ((type === 'time' && v.length === 5) || (type === 'datetime-local' && v.length === 16)) ? v + ':00' : v; }
    var compared = comparable(value), min = comparable(options.min), max = comparable(options.max), start = comparable(options.start);
    // Native time controls also support a range crossing midnight.
    if (type === 'time' && min && max && min > max) {
      if (compared < min && compared > max) return 'Bitte eine Uhrzeit im erlaubten Zeitraum wählen.';
    } else {
      if (min && compared < min) return 'Frühestens ' + format(options.min, type) + ' möglich.';
      if (max && compared > max) return 'Spätestens ' + format(options.max, type) + ' möglich.';
    }
    if (start && compared < start) return 'Das Ende darf nicht vor dem Beginn liegen (' + format(options.start, type) + ').';
    return '';
  }
  var api = { parse: parse, format: format, constraint: constraint, validDate: validDate };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (!root.document) return;
  var doc = root.document, states = new WeakMap(), all = new Set(), active = null, serial = 0;
  var selector = 'input[type="date"],input[type="datetime-local"],input[type="time"]';
  function today() { var d = new Date(); return dateISO(d.getFullYear(), d.getMonth() + 1, d.getDate()); }
  function el(tag, cls, text) { var node = doc.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
  function button(label, icon) {
    var b = el('button', 'btn btn-sm btn-outline-secondary'); b.type = 'button'; b.setAttribute('aria-label', label); b.title = label;
    if (icon) { var i = el('i', 'fa-solid ' + icon); i.setAttribute('aria-hidden', 'true'); b.appendChild(i); } else b.textContent = label;
    return b;
  }
  function startFor(s) {
    var original = s.original, scope = original.form || doc, explicit = original.dataset.dateStart;
    if (explicit) { var target = doc.getElementById(explicit); return target && target.type === s.type ? target : null; }
    var name = original.name || original.dataset.k || original.dataset.h || original.id || '', partner = '';
    if (/__end$/.test(name)) partner = name.replace(/__end$/, '__start');
    else if (/^(end|end_at|end_date|end_time|ends_at|date_to|time_to|date_end|time_end|valid_until|to)$/.test(name)) partner = ({ end: 'start', end_at: 'start_at', end_date: 'start_date', end_time: 'start_time', ends_at: 'starts_at', date_to: 'date_from', time_to: 'time_from', date_end: 'date_start', time_end: 'time_start', valid_until: 'valid_from', to: 'from' })[name];
    else if (/[-_]end$/.test(name)) partner = name.replace(/end$/, 'start');
    else if (/[-_]to$/.test(name)) partner = name.replace(/to$/, 'from');
    if (!partner) return null;
    // Repeated anonymous rows must never get paired with another row's beginning.
    var row = original.closest('[data-date-range], [data-poll-option], [data-term], [data-i], .poll-option, [data-d]');
    var pool = (row || scope).querySelectorAll(selector);
    var candidates = Array.from(pool).filter(function (p) { return (p.name || p.dataset.k || p.dataset.h || p.id) === partner && p.type === s.type; });
    return candidates.length === 1 ? candidates[0] : null;
  }
  function options(s) {
    var start = startFor(s);
    return { type: s.type, required: s.required, min: s.original.min, max: s.original.max, start: start && start.value };
  }
  function message(s, error, show) {
    s.proxy.setCustomValidity(error);
    s.proxy.setAttribute('aria-invalid', (show && error) || s.serverInvalid ? 'true' : 'false');
    s.proxy.classList.toggle('is-invalid', !!((show && error) || s.serverInvalid));
    s.error.textContent = show ? error : ''; s.error.hidden = !(show && error);
  }
  function write(s, value, dispatch) {
    s.set(value); s.last = s.original.value;
    if (dispatch) { s.syncing = true; s.original.dispatchEvent(new Event('input', { bubbles: true })); if (dispatch !== 'input') s.original.dispatchEvent(new Event('change', { bubbles: true })); s.syncing = false; }
  }
  function commit(s, show, dispatch) {
    if (s.proxy.disabled || s.original.disabled) return true;
    s.serverInvalid = false;
    var parsed = parse(s.proxy.value, s.type), error = parsed.error || constraint(parsed.value, options(s));
    // Keep invalid human input visible, but do not leak a stale canonical value to JS or submission.
    write(s, error ? '' : parsed.value, dispatch);
    // Conditional forms may update min/max while handling the native input event.
    error = parsed.error || constraint(parsed.value, options(s));
    if (error) write(s, '', false);
    if (!error && parsed.value && s.original.validity.stepMismatch) { error = 'Bitte einen Wert passend zur vorgegebenen Schrittweite wählen.'; write(s, '', dispatch); }
    message(s, error, show); s.edited = true;
    if (!error && show) s.proxy.value = format(s.original.value, s.type);
    return !error;
  }
  function sync(s) {
    s.proxy.value = format(s.original.value, s.type); s.last = s.original.value; s.edited = false;
    s.proxy.disabled = s.original.disabled; s.proxy.readOnly = s.original.readOnly; s.toggle.disabled = s.original.disabled || s.original.readOnly;
    s.proxy.required = s.required;
    if (s.original.getAttribute('aria-label')) s.proxy.setAttribute('aria-label', s.original.getAttribute('aria-label'));
    var error = constraint(s.original.value, options(s)); message(s, error, false);
  }
  function close(focus) {
    if (!active) return;
    var old = active; active = null; old.panel.remove(); old.state.toggle.setAttribute('aria-expanded', 'false');
    if (focus) old.state.proxy.focus();
  }
  function position() {
    if (!active) return;
    var r = active.state.wrap.getBoundingClientRect(), p = active.panel;
    if (r.bottom < 0 || r.top > root.innerHeight) { close(false); return; }
    p.style.left = Math.max(8, Math.min(r.left, root.innerWidth - p.offsetWidth - 8)) + 'px';
    p.style.top = (r.bottom + p.offsetHeight + 8 > root.innerHeight && r.top > p.offsetHeight ? r.top - p.offsetHeight - 6 : Math.min(r.bottom + 6, Math.max(8, root.innerHeight - p.offsetHeight - 8))) + 'px';
  }
  function setPicked(s, value) { s.proxy.value = format(value, s.type); commit(s, true, true); if (active) renderCalendar(); }
  function dateAllowed(s, iso) {
    var o = options(s), lower = [o.min, o.start].filter(Boolean).sort().pop(), upper = o.max;
    // A date containing a permitted time remains selectable; exact times are checked on confirmation.
    return !(lower && iso < lower.slice(0, 10)) && !(upper && iso > upper.slice(0, 10));
  }
  function shifted(iso, amount) {
    var p = iso.split('-'), d = new Date(0); d.setFullYear(+p[0], +p[1] - 1, +p[2]); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + amount);
    return dateISO(d.getFullYear(), d.getMonth() + 1, d.getDate());
  }
  function renderCalendar(focusDate, focusControl) {
    if (!active || active.state.type === 'time') return;
    var a = active, s = a.state, panel = a.panel; panel.replaceChildren();
    var controls = el('div', 'portal-date-heading'), prev = button('Vorheriger Monat', 'fa-chevron-left'), next = button('Nächster Monat', 'fa-chevron-right');
    prev.classList.add('portal-date-prev'); next.classList.add('portal-date-next');
    prev.disabled = a.year === 1 && a.month === 0; next.disabled = a.year === 9999 && a.month === 11;
    var month = el('select', 'form-select form-select-sm portal-date-month'); month.setAttribute('aria-label', 'Monat');
    months.forEach(function (name, i) { var op = el('option', '', name); op.value = i; month.appendChild(op); }); month.value = a.month;
    var year = el('input', 'form-control form-control-sm portal-date-year'); year.type = 'number'; year.min = '1'; year.max = '9999'; year.value = a.year; year.setAttribute('aria-label', 'Jahr');
    function shiftMonth(delta, control) { a.month += delta; if (a.month < 0) { a.month = 11; a.year--; } if (a.month > 11) { a.month = 0; a.year++; } a.year = Math.max(1, Math.min(9999, a.year)); renderCalendar(null, control); }
    prev.addEventListener('click', function () { shiftMonth(-1, 'portal-date-prev'); }); next.addEventListener('click', function () { shiftMonth(1, 'portal-date-next'); });
    month.addEventListener('change', function () { a.month = +month.value; renderCalendar(null, 'portal-date-month'); });
    year.addEventListener('change', function () { if (+year.value >= 1 && +year.value <= 9999) { a.year = +year.value; renderCalendar(null, 'portal-date-year'); } else year.value = a.year; });
    controls.append(prev, month, year, next); panel.appendChild(controls);
    var title = el('div', 'visually-hidden', months[a.month] + ' ' + a.year); title.id = 'portal-date-month-' + s.id; title.setAttribute('aria-live', 'polite'); panel.appendChild(title);
    var grid = el('div', 'portal-date-grid'); grid.setAttribute('role', 'grid'); grid.setAttribute('aria-labelledby', title.id);
    var heads = el('div', 'portal-date-row'); heads.setAttribute('role', 'row');
    ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].forEach(function (day) { var h = el('span', 'portal-date-weekday', day); h.setAttribute('role', 'columnheader'); heads.appendChild(h); }); grid.appendChild(heads);
    var first = new Date(0); first.setFullYear(a.year, a.month, 1); first.setHours(12, 0, 0, 0);
    var offset = (first.getDay() + 6) % 7, length = 28; while (validDate(a.year, a.month + 1, length + 1)) length++;
    var current = s.original.value.slice(0, 10), start = startFor(s), startValue = start && start.value.slice(0, 10), selected = focusDate || a.focus || current || today();
    if (selected.slice(0, 7) !== dateISO(a.year, a.month + 1, 1).slice(0, 7)) selected = dateISO(a.year, a.month + 1, 1);
    var focusButton = null, firstEnabled = null;
    for (var index = 0; index < Math.ceil((offset + length) / 7) * 7; index++) {
      if (index % 7 === 0) { var row = el('div', 'portal-date-row'); row.setAttribute('role', 'row'); grid.appendChild(row); }
      var day = index - offset + 1;
      if (day < 1 || day > length) { var empty = el('span'); empty.setAttribute('role', 'gridcell'); row.appendChild(empty); continue; }
      var iso = dateISO(a.year, a.month + 1, day), b = button(format(iso, 'date')); b.className = 'portal-date-day'; b.textContent = day; b.dataset.iso = iso; b.setAttribute('role', 'gridcell'); b.tabIndex = -1;
      b.disabled = !dateAllowed(s, iso); b.setAttribute('aria-selected', iso === current ? 'true' : 'false');
      if (iso === today()) { b.classList.add('is-today'); b.setAttribute('aria-current', 'date'); }
      if (iso === current) b.classList.add('is-selected');
      if (startValue && current && iso >= startValue && iso <= current) b.classList.add('is-range');
      if (!b.disabled && !firstEnabled) firstEnabled = b;
      if (!b.disabled && iso === selected) focusButton = b;
      b.addEventListener('click', function (event) { pickDay(event.currentTarget.dataset.iso); });
      b.addEventListener('keydown', function (event) {
        var move = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key], target;
        if (move) target = shifted(event.currentTarget.dataset.iso, move);
        else if (event.key === 'Home') { var d = new Date(event.currentTarget.dataset.iso + 'T12:00:00'); target = shifted(event.currentTarget.dataset.iso, -((d.getDay() + 6) % 7)); }
        else if (event.key === 'End') { var e = new Date(event.currentTarget.dataset.iso + 'T12:00:00'); target = shifted(event.currentTarget.dataset.iso, 6 - ((e.getDay() + 6) % 7)); }
        else if (event.key === 'PageUp' || event.key === 'PageDown') {
          var p = event.currentTarget.dataset.iso.split('-').map(Number), shift = event.key === 'PageUp' ? -1 : 1;
          if (event.shiftKey) p[0] += shift; else { p[1] += shift; if (p[1] === 0) { p[0]--; p[1] = 12; } if (p[1] === 13) { p[0]++; p[1] = 1; } }
          while (p[2] > 1 && !validDate(p[0], p[1], p[2])) p[2]--; target = dateISO(p[0], p[1], p[2]);
        }
        if (target && +target.split('-')[0] >= 1 && +target.split('-')[0] <= 9999) { event.preventDefault(); if (!dateAllowed(s, target)) return; a.focus = target; a.year = +target.slice(0, 4); a.month = +target.slice(5, 7) - 1; renderCalendar(target); }
      });
      row.appendChild(b);
    }
    (focusButton || firstEnabled || {}).tabIndex = 0; panel.appendChild(grid);
    if (s.type === 'datetime-local') {
      var timeLabel = el('label', 'portal-date-time', 'Uhrzeit'), ti = el('input', 'form-control form-control-sm'); ti.type = 'time'; ti.value = a.time; ti.step = s.original.step || '60'; ti.setAttribute('aria-label', 'Uhrzeit zum ausgewählten Datum');
      ti.addEventListener('change', function () { a.time = ti.value; if (s.original.value) setPicked(s, s.original.value.slice(0, 10) + 'T' + a.time); }); timeLabel.appendChild(ti); panel.appendChild(timeLabel);
    }
    var actions = el('div', 'portal-date-actions'), now = button('Heute'), done = button('Fertig'); now.disabled = !dateAllowed(s, today()); now.addEventListener('click', function () { pickDay(today()); }); actions.appendChild(now);
    if (!s.required) { var clear = button('Leeren'); clear.addEventListener('click', function () { setPicked(s, ''); close(true); }); actions.appendChild(clear); }
    done.addEventListener('click', function () { close(true); }); actions.appendChild(done); panel.appendChild(actions); position();
    if (focusDate && (focusButton || firstEnabled)) (focusButton || firstEnabled).focus();
    else if (focusControl) panel.querySelector('.' + focusControl).focus();
  }
  function pickDay(iso) {
    var a = active, s = a.state, time = a.time || '00:00';
    if (s.type === 'datetime-local') {
      var o = options(s), candidate = iso + 'T' + time, lower = [o.min, o.start].filter(Boolean).sort().pop();
      if (lower && candidate < lower && lower.slice(0, 10) === iso) time = lower.split('T')[1];
      if (o.max && iso + 'T' + time > o.max && o.max.slice(0, 10) === iso) time = o.max.split('T')[1];
      a.time = time;
    }
    setPicked(s, iso + (s.type === 'datetime-local' ? 'T' + time : '')); a.focus = iso;
    if (s.type === 'date') close(true);
    else { var ti = a.panel.querySelector('input[type="time"]'); if (ti) ti.focus(); }
  }
  function open(s) {
    if (active && active.state === s) { close(true); return; } close(false);
    var panel = el('div', 'portal-date-panel'); panel.id = 'portal-date-panel-' + s.id; panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', s.type === 'time' ? 'Uhrzeit auswählen' : 'Datum auswählen'); panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(true); } });
    (s.original.closest('.modal') || doc.body).appendChild(panel); s.toggle.setAttribute('aria-expanded', 'true'); s.toggle.setAttribute('aria-controls', panel.id);
    var iso = s.original.value || (s.type === 'time' ? '09:00' : today());
    if (!s.original.value && s.type !== 'time') { var o = options(s), lower = [o.min, o.start].filter(Boolean).sort().pop(); if (lower && iso < lower.slice(0, 10)) iso = lower; if (o.max && iso.slice(0, 10) > o.max.slice(0, 10)) iso = o.max; }
    var d = iso.slice(0, 10).split('-'); active = { state: s, panel: panel, year: +d[0], month: +d[1] - 1, time: iso.split('T')[1] || '09:00' };
    if (s.type !== 'time') { renderCalendar(); var selected = panel.querySelector('.portal-date-day[tabindex="0"]'); if (selected) selected.focus(); return; }
    var label = el('label', 'portal-date-time', 'Uhrzeit'), input = el('input', 'form-control'); input.type = 'time'; input.value = s.original.value || '09:00'; input.step = s.original.step || '60'; input.min = s.original.min; input.max = s.original.max; label.appendChild(input); panel.appendChild(label);
    var actions = el('div', 'portal-date-actions'), apply = button('Übernehmen'); apply.addEventListener('click', function () { if (!input.reportValidity()) return; setPicked(s, input.value); if (s.proxy.validity.valid) close(true); }); actions.appendChild(apply);
    if (!s.required) { var clear = button('Leeren'); clear.addEventListener('click', function () { setPicked(s, ''); close(true); }); actions.appendChild(clear); }
    panel.appendChild(actions); position(); input.focus();
  }
  function enhance(original) {
    if (states.has(original) || original.dataset.dateNative === '1' || original.closest('.portal-date-panel') || original.hidden || original.type === 'hidden') return;
    var type = original.type, id = ++serial, wrap = el('div', 'portal-date-field'), group = el('div', 'portal-date-entry'), proxy = el('input', 'form-control'), toggle = button(type === 'time' ? 'Uhrzeit auswählen' : 'Kalender öffnen', type === 'time' ? 'fa-clock' : 'fa-calendar-days'), error = el('div', 'invalid-feedback d-block');
    proxy.type = 'text'; proxy.id = (original.id || 'portal-date-' + id) + '-display'; proxy.autocomplete = 'off'; proxy.placeholder = type === 'time' ? 'HH:MM' : type === 'date' ? 'TT.MM.JJJJ' : 'TT.MM.JJJJ, HH:MM';
    if (original.hasAttribute('form')) proxy.setAttribute('form', original.getAttribute('form'));
    proxy.inputMode = 'text'; proxy.spellcheck = false;
    if (original.classList.contains('form-control-sm')) proxy.classList.add('form-control-sm');
    if (original.classList.contains('form-control-lg')) proxy.classList.add('form-control-lg');
    error.id = 'portal-date-error-' + id; error.hidden = true; error.setAttribute('aria-live', 'polite');
    proxy.setAttribute('aria-describedby', [original.getAttribute('aria-describedby'), error.id].filter(Boolean).join(' '));
    toggle.classList.add('portal-date-toggle'); toggle.setAttribute('aria-haspopup', 'dialog'); toggle.setAttribute('aria-expanded', 'false');
    if (original.style.maxWidth) wrap.style.maxWidth = original.style.maxWidth;
    original.before(wrap); group.append(proxy, toggle); wrap.append(group, error, original);
    var nativeDescriptor = Object.getOwnPropertyDescriptor(root.HTMLInputElement.prototype, 'value');
    var s = { original: original, proxy: proxy, toggle: toggle, wrap: wrap, error: error, type: type, id: id, required: original.required, syncing: false, edited: false, serverInvalid: original.classList.contains('is-invalid'), set: function (value) { nativeDescriptor.set.call(original, value); } };
    states.set(original, s); all.add(s); original.hidden = true; original.dataset.dateEnhanced = '1';
    if (original.id) Array.from(doc.querySelectorAll('label')).filter(function (l) { return l.htmlFor === original.id; }).forEach(function (l) { l.htmlFor = proxy.id; });
    if (original.getAttribute('aria-labelledby')) proxy.setAttribute('aria-labelledby', original.getAttribute('aria-labelledby'));
    // Existing calendars / calculations often assign .value without dispatching an event.
    Object.defineProperty(original, 'value', { configurable: true, get: function () { return nativeDescriptor.get.call(original); }, set: function (value) { nativeDescriptor.set.call(original, value); s.serverInvalid = false; sync(s); } });
    original.addEventListener('input', function () { if (!s.syncing) sync(s); }); original.addEventListener('change', function () { if (!s.syncing) sync(s); all.forEach(function (other) { if (other !== s && startFor(other) === original) { var parsed = parse(other.proxy.value, other.type); message(other, parsed.error || constraint(parsed.value, options(other)), other.edited); } }); });
    original.addEventListener('invalid', function (e) { e.preventDefault(); commit(s, true, false); proxy.focus(); });
    original.addEventListener('dateconstraintschange', function () { if (!s.syncing) commit(s, s.edited, false); });
    proxy.addEventListener('input', function () { commit(s, false, 'input'); }); proxy.addEventListener('blur', function () { commit(s, true, true); });
    proxy.addEventListener('keydown', function (e) { if (e.key === 'ArrowDown' && e.altKey) { e.preventDefault(); open(s); } else if (e.key === 'Escape') close(true); });
    toggle.addEventListener('click', function () { open(s); });
    new MutationObserver(function (mutations) {
      s.required = original.required;
      // Do not erase an unfinished or invalid typed value when a limit changes.
      proxy.disabled = original.disabled; proxy.readOnly = original.readOnly; proxy.required = s.required; toggle.disabled = original.disabled || original.readOnly;
      if (s.edited) commit(s, false, false); else sync(s);
    }).observe(original, { attributes: true, attributeFilter: ['value', 'min', 'max', 'step', 'disabled', 'readonly', 'required', 'aria-label'] });
    sync(s);
  }
  function scan(scope) { if (scope.matches && scope.matches(selector)) enhance(scope); if (scope.querySelectorAll) scope.querySelectorAll(selector).forEach(enhance); }
  function init() {
    scan(doc);
    new MutationObserver(function (mutations) { mutations.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) scan(n); }); }); all.forEach(function (s) { if (!s.original.isConnected) { if (active && active.state === s) close(false); all.delete(s); } }); }).observe(doc.body, { childList: true, subtree: true });
    doc.addEventListener('submit', function (e) {
      // Draft/delete/waitlist actions and modules with their own wizard validation keep their existing contract.
      if (e.target.noValidate || (e.submitter && e.submitter.formNoValidate)) return;
      var invalid = null; all.forEach(function (s) { if (s.original.form === e.target && !commit(s, true, false) && !invalid) invalid = s; });
      if (invalid) { e.preventDefault(); e.stopImmediatePropagation(); invalid.proxy.focus(); invalid.proxy.reportValidity(); }
    }, true);
    // The browser fires invalid before submit; reveal a clear inline error there too.
    doc.addEventListener('invalid', function (e) { all.forEach(function (s) { if (s.proxy === e.target) commit(s, true, false); }); }, true);
    doc.addEventListener('reset', function (e) { root.setTimeout(function () { all.forEach(function (s) { if (s.original.form === e.target) sync(s); }); }, 0); });
    doc.addEventListener('pointerdown', function (e) { if (active && !active.panel.contains(e.target) && !active.state.wrap.contains(e.target)) close(false); });
    doc.addEventListener('focusin', function (e) { if (active && !active.panel.contains(e.target) && !active.state.wrap.contains(e.target)) close(false); });
    root.addEventListener('resize', position); root.addEventListener('scroll', position, true);
    if (root.visualViewport) { root.visualViewport.addEventListener('resize', position); root.visualViewport.addEventListener('scroll', position); }
  }
  api.enhance = scan; root.PortalDatePicker = api;
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init); else init();
})(typeof window !== 'undefined' ? window : globalThis);
