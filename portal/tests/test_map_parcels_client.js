const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class E{
 constructor(tag='DIV'){this.tagName=tag;this.events={};this.children=[];this.value='';this.open=false;this.options=[{}];this.dataset={};}
 addEventListener(k,fn){(this.events[k]||=[]).push(fn);} emit(k,e={}){(this.events[k]||[]).forEach(fn=>fn(e));} append(e){this.children.push(e);e.parentElement=this;} replaceChildren(){this.children=[];} setAttribute(){} insertAdjacentHTML(){} closest(){return this.owner||null;}
}
const settle=()=>new Promise(r=>setImmediate(r));
function fixture(browser=true){
 const nodes={},get=s=>nodes[s]||=(new E()),tools=new E('DETAILS'),details=get('.parcel-search');details.tagName='DETAILS';details.parentElement=tools;
 const form=get('[data-parcel-search]'),host=new E();host.querySelector=get;host.closest=()=>tools;form.querySelector=get;form.querySelectorAll=()=>['gemarkung','flur','zaehler','nenner','kennzeichen'].map(k=>get('[name="'+k+'"]'));details.querySelector=get;
 get('[data-parcel-click]').checked=true;get('[data-parcel-click]').owner=new E('LABEL');get('[data-parcel-scope]').value='preferred';
 const info=new E();info.querySelector=get;const listeners={},sources={},layers={},calls=[],pending=[];
 const map={on:(k,fn)=>(listeners[k]||=[]).push(fn),isStyleLoaded:()=>true,getSource:k=>sources[k],addSource:(k,v)=>sources[k]={data:v.data,setData(d){this.data=d;}},addLayer:l=>layers[l.id]=l,getLayer:k=>layers[k],setLayoutProperty(){},fitBounds(){}};
 const window={},context={window,MapKit:{esc:s=>String(s??''),parcelLabels:()=>({update(){}})},maplibregl:{LngLatBounds:class{extend(){}}},AbortController,URLSearchParams,Date,setTimeout,clearTimeout,document:{createElement:t=>new E(t)},fetch:async u=>{calls.push(u);if(u.includes('/options?'))return {ok:true,json:async()=>({gemarkungen:[],fluren:[],nummern:[],complete:false})};return new Promise(resolve=>pending.push(data=>resolve({ok:true,json:async()=>data})));}};
 vm.runInNewContext(fs.readFileSync('portal/app/static/map-parcels.js','utf8'),context);
 const api=window.MapParcels.create(map,host,{browserMode:browser,infoHost:browser?info:null});
 return {api,host,nodes,get,tools,details,map,sources,calls,pending,click(){(listeners.click||[]).forEach(fn=>fn({lngLat:{lng:7.7,lat:49.5}}));}};
}
const parcel={type:'Feature',id:'a',geometry:{type:'Polygon',coordinates:[[[7,49],[8,49],[8,50],[7,49]]]},properties:{gemarkung:'Otterbach',flstkennz:'a',flstnrzae:123,flaeche:123},retrieved_at:'2026-10-09T00:00:00Z'};
(async()=>{
 const f=fixture();f.get('[name="zaehler"]').value='1144/2';f.get('[name="zaehler"]').emit('input');assert.equal(f.get('[name="zaehler"]').value,'1144');assert.equal(f.get('[name="nenner"]').value,'2','Number suggestions populate both numerator and denominator');f.click();assert.equal(f.calls.length,0,'Parcel lookup stays inactive until its tool is opened');
 f.tools.open=true;f.details.open=true;f.details.emit('toggle');await settle();f.click();assert.equal(f.calls.filter(u=>!u.includes('/options?')).length,1);
 f.pending.shift()({features:[parcel],fields:{gemarkung:'Gemarkung'}});await settle();await settle();
 assert.equal(f.api.active().id,'a');assert.equal(f.api.features().length,0,'Inspecting must never add a parcel to the persistent collection');
 const highlighted=Object.values(f.sources)[0].data.features;assert.equal(highlighted.length,1);assert.equal(highlighted[0].properties._active,1);
 f.get('[data-active-add]').emit('click');assert.equal(f.api.features().length,1);
 f.get('[data-active-add]').emit('click');assert.equal(f.api.features().length,1,'Explicit collection cannot contain duplicate parcels');
 f.details.open=false;f.details.emit('toggle');assert.equal(f.api.active(),null);assert.equal(f.api.features().length,1,'Closing keeps saved collection');
 f.click();assert.equal(f.calls.filter(u=>!u.includes('/options?')).length,1);
 f.details.open=true;f.click();const first=f.pending.shift();f.click();const second=f.pending.shift();second({features:[{...parcel,id:'b',properties:{...parcel.properties,flstkennz:'b'}}],fields:{}});await settle();first({features:[parcel],fields:{}});await settle();assert.equal(f.api.active().id,'b','Late responses cannot overwrite the current parcel');
 f.tools.open=false;f.click();assert.equal(f.calls.filter(u=>!u.includes('/options?')).length,3,'Collapsed parent toolbox disables parcel querying');
 const legacy=fixture(false);legacy.click();assert.equal(legacy.calls.length,1,'Form parcel mode retains the original click behavior');
 console.log('Parcel mode activation, separate inspection/collection, race protection and form compatibility passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
// Parcel numbers are zoom gated, collision limited and cleaned up without remote fonts.
{
 const listeners={},live=new Set();let zoom=15;
 const map={on(k,fn){(listeners[k]||=[]).push(fn);},off(k,fn){listeners[k]=(listeners[k]||[]).filter(f=>f!==fn);},getZoom:()=>zoom,getBounds:()=>({contains:()=>true}),project:p=>({x:p[0]*100,y:p[1]*100})};
 const context={window:{},document:{createElement:()=>new E()},maplibregl:{Marker:class{constructor(o){this.options=o;}setLngLat(){return this;}addTo(){live.add(this);return this;}remove(){live.delete(this);}}}};
 vm.runInNewContext(fs.readFileSync('portal/app/static/map-core.js','utf8'),context);
 const labels=context.window.MapKit.parcelLabels(map);labels.update([parcel,{...parcel,id:'second'}],true);assert.equal(live.size,0);
 zoom=16;listeners.moveend[0]();assert.equal(live.size,1,'Nearby duplicate labels are suppressed');assert.equal([...live][0].options.element.textContent,'123');
 labels.update([parcel],false);assert.equal(live.size,0);labels.update([parcel],true);assert.equal(live.size,1);labels.destroy();assert.equal(live.size,0);assert.equal(listeners.moveend.length,0);
}
