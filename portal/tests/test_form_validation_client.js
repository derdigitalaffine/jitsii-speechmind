/* Exercise actual rule update logic with a minimal DOM contract. */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('portal/app/static/form-fill.js', 'utf8');
const start = source.indexOf('  function updateDateRules(scope)');
const end = source.indexOf("  form.addEventListener('input', function() {updateDateRules(form);});", start);
assert(start >= 0 && end > start);
const rules = {min:'2026-06-01',max:'2026-06-30',date_reference:'start',date_gap_min:2,date_gap_max:5};
const reference = {value:'2026-05-10'};
const input = {dataset:{dateRules:JSON.stringify(rules)},type:'date',value:'2026-05-12',
  closest:()=>({dataset:{qid:'end'}}),setCustomValidity(message){this.message=message;},dispatchEvent(){}};
const scope = {querySelectorAll:()=>[input]};
const context = {originalDates:{start:'2026-05-10',end:'2026-05-12'},
  form:{querySelector:()=>reference}, CustomEvent:function(){}, scope};
vm.createContext(context);
vm.runInContext(source.slice(start,end), context);
context.updateDateRules(scope);
assert.equal(input.min,'');assert.equal(input.max,'');assert.equal(input.message,'');
reference.value='2026-05-11';context.updateDateRules(scope);
assert.equal(input.min,'2026-05-13');assert(input.message); // Changed start validates unchanged end.
input.value='2026-06-12';context.updateDateRules(scope);
assert.equal(input.min,'2026-06-01');assert.equal(input.max,'2026-05-16');assert(input.message);
context.originalDates={};reference.value='';input.value='2026-05-12';context.updateDateRules(scope);
assert.equal(input.min,'2026-06-01');assert(input.message); // New/profile prefills get full constraints.
context.originalDates={start:'2026-05-10',end:'2026-05-12'};
context.form.querySelector=()=>null;input.value='2026-05-11';
input.dataset.dateRules=JSON.stringify({date_reference:'start',date_gap_min:2});
context.updateDateRules(scope);assert.equal(input.min,'2026-05-12');assert(input.message); // Reference need not be reopened.
console.log('Form validation client tests passed');
