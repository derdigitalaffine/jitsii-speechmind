const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag) {this.tagName=tag;this.children=[];this.value='';this.dataset={};this.events={};this.classList={remove(){},toggle(){}};}
  append(...children) {children.forEach(c=>{this.children.push(c);c.parentElement=this;});}
  replaceChildren(...children) {this.children=[];this.append(...children);}
  addEventListener(name,fn) {(this.events[name] ||= []).push(fn);}
  dispatchEvent(event) {(this.events[event.type]||[]).forEach(fn=>fn(event));}
  click() {if(this.onclick){this.onclick();}this.dispatchEvent({type:'click'});}
  remove() {this.parentElement.children=this.parentElement.children.filter(c=>c!==this);}
  focus() {}
}
const settle = () => new Promise(resolve=>setImmediate(resolve));
(async function(){
  const timers=[], fields={}, form=new Element('form'), hidden=new Element('input'), holder=new Element('div'), total=new Element('div'), add=new Element('button'), map=new Element('div'), created=[], requests=[];
  const box={dataset:{value:'',max:'10',required:'1',return:'1',deviation:'1'},querySelector:s=>({'.js-route-value':hidden,'.js-route-legs':holder,'.js-route-total':total,'.js-route-add':add,'.js-route-map':map})[s],closest:s=>s==='form'?form:null};
  const document={querySelectorAll:()=>[box],querySelector:()=>({content:'csrf'}),getElementById:()=>null,createElement:tag=>{const e=new Element(tag);created.push(e);return e;}};
  const context={document,window:{},Event:class{constructor(type){this.type=type;}},GeoSearch:{policy:Promise.resolve({public_only:true}),bind:()=>()=>{}},setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:()=>{},fetch:async(url,options)=>({ok:true,json:async()=>{
    if(url==='/geo/locations'){return {locations:[{id:1,name:'Rathaus',label:'Rathaus',city:'Otterberg',lat:49,lon:7,public:true},{id:2,name:'Kita',label:'Kita',city:'Otterbach',lat:50,lon:8,public:true}],categories:{private_car:'Privat-Pkw'},public_routing:{car:true},routing_auto:true};}
    const body=JSON.parse(options.body);requests.push(body);return {points:body.points,category:body.category,meters:1000,geometry:{coordinates:[]}};
  }})};
  vm.runInNewContext(fs.readFileSync('portal/app/static/form-route.js','utf8'),context);await settle();
  const points=holder.children[0].children.find(e=>e.className==='d-grid gap-2');
  points.children.forEach((row,i)=>{const select=row.children[0].children[1];select.value=String(i+1);select.dispatchEvent({type:'change'});});
  timers.at(-1)();await settle();
  assert.equal(requests.length,1);assert.equal(requests[0].public_points,true);assert.equal(JSON.parse(hidden.value).legs.length,1);
  created.find(e=>e.textContent==='Rückfahrt ergänzen').click();timers.at(-1)();await settle();
  assert.equal(requests.length,2);assert.equal(requests[1].points[0].label,'Kita');assert.equal(requests[1].points[1].label,'Rathaus');assert.equal(JSON.parse(hidden.value).legs.length,2);
  assert.equal(created.filter(e=>e.type==='checkbox').length,0);
  // Postal-code lookup starts after completion and preserves typed city values.
  const zip=new Element('input'), city=new Element('input'), choices=new Element('div'), info=new Element('div'), district=new Element('input'), lat=new Element('input'), lon=new Element('input'), postcodeTimers=[];
  const address={dataset:{name:'q_addr'},querySelector:s=>s.includes('__zip')?zip:s.includes('__city')?city:s.includes('__district')?district:s.includes('__lat')?lat:s.includes('__lon')?lon:({'.js-addr-info':info,'.js-addr-city-choices':choices})[s]||null,closest:()=>null};
  const addrContext={window:{},document:{querySelectorAll:()=>[address],getElementById:()=>null,createElement:tag=>new Element(tag)},GeoSearch:{policy:Promise.resolve({public_only:true})},Event:context.Event,setTimeout:fn=>{postcodeTimers.push(fn);return fn;},clearTimeout:()=>{},fetch:async()=>({ok:true,json:async()=>({results:[{city:'Heiligenmoschel'},{city:'Schneckenhausen'}]})})};
  vm.runInNewContext(fs.readFileSync('portal/app/static/form-address.js','utf8'),addrContext);await settle();
  zip.value='6769';zip.dispatchEvent({type:'input'});assert.equal(postcodeTimers.length,0);
  zip.value='67699';city.value='Eigene Eingabe';zip.dispatchEvent({type:'input'});postcodeTimers.at(-1)();await settle();
  assert.equal(city.value,'Eigene Eingabe');assert.equal(choices.children.length,2);
  choices.children[0].click();assert.equal(city.value,'Heiligenmoschel');assert.equal(choices.children.length,0);
  console.log('Automatic routes, separate return trips and one-click postcode choices passed.');
}()).catch(e=>{console.error(e);process.exitCode=1;});
