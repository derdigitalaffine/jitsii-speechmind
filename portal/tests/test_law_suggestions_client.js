const assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const timers=[], calls=[], pending=[], events={}, list={children:[],style:{},classList:{add(){},toggle(){}},setAttribute(){},addEventListener(){},appendChild(e){this.children.push(e);},querySelectorAll(){return this.children;}};
Object.defineProperty(list,'innerHTML',{set(){this.children=[];}});
const wrap={style:{},appendChild(){},contains(){return true;}}, input={value:'',dataset:{suggest:'/recht-embed/suche.json?catalog=1&bereich=ort&thema=Friedhof%20%26%20Bestattung&ebene=42'},closest(){return wrap;},setAttribute(){},addEventListener(name,fn){events[name]=fn;}};
const mobilePanel={open:true};
const context={document:{querySelector(s){return s==='[data-catalog-filters]'?mobilePanel:null;},getElementById(){return null;},querySelectorAll(s){return s==='input[data-suggest]'?[input]:[];},createElement(tag){return tag==='div'?list:{setAttribute(){}};},addEventListener(){}},window:{matchMedia(){return {matches:true};}},localStorage:{getItem(){return null;}},location:{href:'https://portal.example.org/recht-embed'},URL,setTimeout(fn){timers.push(fn);},clearTimeout(){},fetch(url){calls.push(url);return new Promise(resolve=>pending.push(items=>resolve({json:async()=>items})));}};
vm.runInNewContext(fs.readFileSync('portal/app/static/laws.js','utf8'),context);
assert.equal(mobilePanel.open,false,'keep mobile results accessible with collapsed filter panel');
(async()=>{
 input.value='Friedhof';events.input();timers.at(-1)();
 const url=new URL(calls[0]);assert.equal(url.pathname,'/recht-embed/suche.json');assert.equal(url.searchParams.get('thema'),'Friedhof & Bestattung');assert.equal(url.searchParams.get('ebene'),'42');assert.equal(url.searchParams.get('q'),'Friedhof');
 input.value='Garten';events.input();pending.shift()([{label:'Obsolete',url:'/recht-embed/old'}]);await new Promise(resolve=>setImmediate(resolve));assert.equal(list.children.length,0);
 timers.at(-1)();pending.shift()([{label:'Aktueller Treffer',url:'/recht-embed/now'}]);await new Promise(resolve=>setImmediate(resolve));assert.equal(list.children[0].textContent,'Aktueller Treffer');assert.equal(list.children[0].href,'/recht-embed/now');
 console.log('Filtered embedded suggestions and stale response rejection passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
