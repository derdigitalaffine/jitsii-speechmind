(() => {
 const action=document.getElementById('rule-action');
 const sync=()=>document.querySelectorAll('[data-rule-fields]').forEach(el=>{el.hidden=!el.dataset.ruleFields.split(' ').includes(action.value)});
 if(action){action.addEventListener('change',sync);sync()}
})();
