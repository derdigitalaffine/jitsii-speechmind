/* Meaningful file-picker checks without requiring a browser or client-side dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let onChange;
const picker = { files: [], validity: '', attributes: {},
  addEventListener(name, fn) { if (name === 'change') onChange = fn; },
  setCustomValidity(value) { this.validity = value; },
  setAttribute(name, value) { this.attributes[name] = value; }
};
const feedback = {textContent: '', classList: {toggle() {}}};
const list = {children: [], replaceChildren() {this.children = [];}, appendChild(item) {this.children.push(item);}};
const document = {
  getElementById(id) {return {'task-initial-files':picker,'task-file-feedback':feedback,'task-file-list':list}[id];},
  createElement() {return {textContent: '', set innerHTML(value) {throw new Error('Unsafe filename rendering');}};}
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/static/task-create.js'),'utf8'),{document});
const select = files => {picker.files = files; onChange();};
select([{name:'<img src=x onerror=alert(1)>.txt',size:4}]);
assert.equal(picker.validity,'');
assert.equal(list.children[0].textContent,'<img src=x onerror=alert(1)>.txt');
assert.match(feedback.textContent,/1 Datei ausgewählt/);
select(Array.from({length:11},(_,i)=>({name:`${i}.txt`,size:1})));
assert.match(picker.validity,/höchstens 10/);
select([{name:'gross.bin',size:20*1024*1024+1}]);
assert.match(picker.validity,/größer als 20/);
select(Array.from({length:6},()=>({name:'gross.bin',size:20*1024*1024})));
assert.match(picker.validity,/zusammen größer als 100/);
select([]);
assert.equal(picker.validity,'');
assert.equal(feedback.textContent,'');
assert.equal(picker.attributes['aria-invalid'],'false');
assert.equal(list.children.length,0);
console.log('Task file picker checks passed.');
