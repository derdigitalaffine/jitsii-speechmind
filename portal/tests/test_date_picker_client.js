'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/static/date-picker.js'), 'utf8');
const dates = require('../app/static/date-picker.js');
assert.deepEqual(dates.parse('29.02.2024', 'date'), { value: '2024-02-29', error: '' });
for (const bad of ['29.02.2023', '29.02.1900', '31.04.2026', '00.01.2026', '01.13.2026', '01.01.0000', '2026-01-01', '1.1.26']) assert.ok(dates.parse(bad, 'date').error, bad);
assert.equal(dates.parse('29.02.2000', 'date').value, '2000-02-29');
assert.equal(dates.parse(' 9.10.2026, 8:05 ', 'datetime-local').value, '2026-10-09T08:05');
assert.equal(dates.parse('9.10.2026 08:05:12', 'datetime-local').value, '2026-10-09T08:05:12');
for (const bad of ['9.10.2026', '9.10.2026, 24:00', '9.10.2026, 10:60', '9.10.2026, 10:00:99']) assert.ok(dates.parse(bad, 'datetime-local').error, bad);
assert.equal(dates.parse('7:05', 'time').value, '07:05');
assert.equal(dates.format('2026-10-09T08:05', 'datetime-local'), '09.10.2026, 08:05');
assert.ok(dates.constraint('', { required: true }));
assert.equal(dates.constraint('', { required: false }), '');
assert.ok(dates.constraint('2026-10-08', { min: '2026-10-09' }));
assert.equal(dates.constraint('2026-10-09', { min: '2026-10-09', max: '2026-10-09' }), '');
assert.ok(dates.constraint('2026-10-08', { start: '2026-10-09' }));
assert.equal(dates.constraint('08:00', { type: 'time', min: '08:00:00' }), '');
assert.equal(dates.constraint('23:00', { type: 'time', min: '22:00', max: '02:00' }), '');
assert.ok(dates.constraint('12:00', { type: 'time', min: '22:00', max: '02:00' }));

// Small dependency-free DOM harness exercises the integration contract, not browser drawing.
class Node {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.dataset = {}; this.style = {}; this.listeners = {}; this.hidden = false; this.disabled = false; this.readOnly = false; this.required = false; this.className = ''; this.classList = { contains: c => this.className.split(' ').includes(c), add: c => { if (!this.classList.contains(c)) this.className += ' ' + c; }, toggle: (c, on) => { this.className = this.className.split(' ').filter(x => x !== c).join(' '); if (on) this.classList.add(c); } }; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'id') this.id = v; }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  hasAttribute(k) { return this.attrs[k] !== undefined; }
  addEventListener(k, f) { (this.listeners[k] ||= []).push(f); }
  dispatchEvent(e) { e.target ||= this; e.currentTarget = this; for (const f of this.listeners[e.type] || []) f(e); if (e.bubbles && this.parentNode) this.parentNode.dispatchEvent(e); return !e.defaultPrevented; }
  appendChild(n) { if (n.parentNode) n.remove(); n.parentNode = this; this.children.push(n); return n; }
  append(...nodes) { nodes.forEach(n => this.appendChild(n)); }
  before(n) { const p = this.parentNode; n.parentNode = p; p.children.splice(p.children.indexOf(this), 0, n); }
  remove() { if (this.parentNode) { const p = this.parentNode; p.children.splice(p.children.indexOf(this), 1); this.parentNode = null; } }
  replaceChildren(...nodes) { this.children.forEach(n => n.parentNode = null); this.children = []; this.append(...nodes); }
  get form() { if (this.attrs.form) return document.getElementById(this.attrs.form); for (let p = this.parentNode; p; p = p.parentNode) if (p.tagName === 'FORM') return p; return null; }
  get isConnected() { return !!this.parentNode; }
  matches(selector) { return selector.split(',').some(s => { const m = s.match(/^input\[type="([^"]+)"\]$/); return m ? this.tagName === 'INPUT' && this.type === m[1] : s === 'label' ? this.tagName === 'LABEL' : s.startsWith('.') ? this.classList.contains(s.slice(1)) : false; }); }
  closest(selector) { for (let p = this; p; p = p.parentNode) if (p.matches(selector)) return p; return null; }
  querySelectorAll(selector) { const result = []; const walk = p => p.children.forEach(n => { if (n.matches(selector)) result.push(n); walk(n); }); walk(this); return result; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { document.focused = this; }
  getBoundingClientRect() { return { left: 0, top: 0, bottom: 40 }; }
  get offsetWidth() { return 300; }
  get offsetHeight() { return 300; }
}
class Input extends Node {
  constructor() { super('input'); this.type = 'text'; this._value = ''; this.min = ''; this.max = ''; this.step = ''; this.validationMessage = ''; }
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  setCustomValidity(v) { this.validationMessage = v; }
  get validity() { return { valid: !this.validationMessage && !(this.required && !this.value), stepMismatch: false }; }
  reportValidity() { return this.validity.valid; }
}
class BrowserEvent { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } preventDefault() { this.defaultPrevented = true; } stopImmediatePropagation() { this.stopped = true; } }
const document = new Node('document'); document.body = new Node('body'); document.appendChild(document.body); document.readyState = 'complete'; document.createElement = t => t === 'input' ? new Input() : new Node(t);
document.getElementById = id => { let found; const walk = n => { if (n.id === id) found = n; n.children.forEach(walk); }; walk(document); return found; };
const observers = []; class Observer { constructor(fn) { this.fn = fn; observers.push(this); } observe(n, options) { this.node = n; this.options = options; } }
const window = new Node('window'); Object.assign(window, { document, HTMLInputElement: Input, innerWidth: 1000, innerHeight: 800, setTimeout: fn => fn() });
function field(name, type = 'date', value = '', required = false, parent) { const f = new Input(); Object.assign(f, { name, id: name, type, value, required }); (parent || form).appendChild(f); return f; }
const form = new Node('form'); form.id = 'booking'; document.body.appendChild(form);
const original = field('date', 'date', '2026-10-09', true); const label = new Node('label'); label.htmlFor = original.id; form.appendChild(label);
const start = field('date_from', 'date', '2026-10-09'); const end = field('date_to', 'date', '2026-10-10');
vm.runInNewContext(source, { window, document, MutationObserver: Observer, Event: BrowserEvent, HTMLInputElement: Input, console });
const proxy = document.getElementById('date-display');
assert.equal(original.type, 'date'); assert.equal(original.name, 'date'); assert.equal(original.hidden, true); assert.equal(original.required, true);
assert.equal(proxy.placeholder, 'TT.MM.JJJJ'); assert.equal(proxy.value, '09.10.2026'); assert.equal(proxy.name, undefined); assert.equal(label.htmlFor, proxy.id);
let inputs = 0, changes = 0; original.addEventListener('input', () => ++inputs); original.addEventListener('change', () => ++changes);
proxy.value = '11.10.2026'; proxy.dispatchEvent(new BrowserEvent('input')); assert.equal(original.value, '2026-10-11'); assert.equal(inputs, 1); assert.equal(changes, 0, 'Typing must not cause change-driven rerenders.');
proxy.value = '31.02.2026'; proxy.dispatchEvent(new BrowserEvent('input')); assert.equal(original.value, ''); assert.equal(proxy.value, '31.02.2026'); assert.equal(proxy.attrs['aria-invalid'], 'false');
proxy.dispatchEvent(new BrowserEvent('blur')); assert.equal(proxy.attrs['aria-invalid'], 'true'); assert.match(proxy.validationMessage, /gültiges Datum/); assert.equal(proxy.value, '31.02.2026', 'Invalid user input must stay visible.');
original.value = '2027-01-02'; assert.equal(proxy.value, '02.01.2027'); assert.equal(proxy.validationMessage, '');
const endProxy = document.getElementById('date_to-display'); endProxy.value = '08.10.2026'; endProxy.dispatchEvent(new BrowserEvent('blur')); assert.equal(end.value, ''); assert.match(endProxy.validationMessage, /Ende.*Beginn/);
endProxy.value = '10.10.2026'; endProxy.dispatchEvent(new BrowserEvent('blur')); start.value = '2026-10-12'; start.dispatchEvent(new BrowserEvent('change')); assert.match(endProxy.validationMessage, /Ende.*Beginn/);
original.min = '2027-02-01'; original.dispatchEvent(new BrowserEvent('dateconstraintschange')); assert.match(proxy.validationMessage, /Frühestens/);
const late = field('external', 'datetime-local', '2026-10-09T10:15', false, document.body); late.setAttribute('form', 'booking'); window.PortalDatePicker.enhance(late);
assert.equal(document.getElementById('external-display').form, form, 'External form association must be preserved.');
late.value = '2026-10-10T09:30'; assert.equal(document.getElementById('external-display').value, '10.10.2026, 09:30');
const dynamic = field('dynamic', 'time', '08:00'); const documentObserver = observers.find(o => o.node === document.body); documentObserver.fn([{ addedNodes: [Object.assign(dynamic, { nodeType: 1 })] }]);
assert.equal(document.getElementById('dynamic-display').placeholder, 'HH:MM');
original.disabled = true; observers.find(o => o.node === original).fn([{ attributeName: 'disabled' }]); assert.equal(proxy.disabled, true);
original.required = false; observers.find(o => o.node === original).fn([{ attributeName: 'required' }]); assert.equal(proxy.required, false);
original.disabled = false; observers.find(o => o.node === original).fn([{ attributeName: 'disabled' }]);
original.value = '2027-02-02'; const toggle = original.parentNode.querySelector('.portal-date-toggle'); toggle.dispatchEvent(new BrowserEvent('click'));
let panel = document.body.querySelector('.portal-date-panel'); assert.equal(panel.attrs.role, 'dialog');
const day3 = panel.querySelectorAll('.portal-date-day').find(n => n.dataset.iso === '2027-02-03'); day3.dispatchEvent(new BrowserEvent('click'));
assert.equal(original.value, '2027-02-03'); assert.equal(proxy.value, '03.02.2027'); assert.equal(document.body.querySelector('.portal-date-panel'), null); assert.equal(document.focused, proxy);
toggle.dispatchEvent(new BrowserEvent('click')); panel = document.body.querySelector('.portal-date-panel');
const selected = panel.querySelectorAll('.portal-date-day').find(n => n.dataset.iso === '2027-02-03'); selected.dispatchEvent(new BrowserEvent('keydown', { key: 'ArrowRight' })); assert.equal(document.focused.dataset.iso, '2027-02-04');
panel = document.body.querySelector('.portal-date-panel'); panel.querySelectorAll('.btn').find(n => n.textContent === 'Leeren').dispatchEvent(new BrowserEvent('click')); assert.equal(original.value, ''); assert.equal(proxy.value, '');
const requiredDate = field('must_date', 'date', '2026-10-09', true); window.PortalDatePicker.enhance(requiredDate); requiredDate.parentNode.querySelector('.portal-date-toggle').dispatchEvent(new BrowserEvent('click')); panel = document.body.querySelector('.portal-date-panel'); assert.equal(panel.querySelectorAll('.btn').some(n => n.textContent === 'Leeren'), false);
panel.dispatchEvent(new BrowserEvent('keydown', { key: 'Escape' })); assert.equal(document.body.querySelector('.portal-date-panel'), null);
const portalToday = field('portal_today', 'date', ''); portalToday.dataset.dateRules = JSON.stringify({today:'2030-02-03'});
window.PortalDatePicker.enhance(portalToday); portalToday.parentNode.querySelector('.portal-date-toggle').dispatchEvent(new BrowserEvent('click'));
panel = document.body.querySelector('.portal-date-panel'); panel.querySelectorAll('.btn').find(n => n.textContent === 'Heute').dispatchEvent(new BrowserEvent('click'));
assert.equal(portalToday.value, '2030-02-03', 'Today must follow the portal day for constrained form fields.');
const invalidSubmit = new BrowserEvent('submit', { target: form }); document.dispatchEvent(invalidSubmit); assert.equal(invalidSubmit.defaultPrevented, true);
const deleteSubmit = new BrowserEvent('submit', { target: form, submitter: { formNoValidate: true } }); document.dispatchEvent(deleteSubmit); assert.equal(deleteSubmit.defaultPrevented, undefined, 'Non-validating delete/draft actions must remain usable.');
form.noValidate = true; const wizardSubmit = new BrowserEvent('submit', { target: form }); document.dispatchEvent(wizardSubmit); assert.equal(wizardSubmit.defaultPrevented, undefined, 'Modules with custom wizard validation retain control.');
console.log('German date parsing, leap years, ranges, ISO/proxy events, dynamic fields, constraints and form association passed.');
