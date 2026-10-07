/* Pure selection reconciliation shared by the editor and client regression tests. */
(function (root) {
  'use strict';
  function reconcileDocuments(entries, selection) {
    var additions = [], occupied = new Set(entries.filter(function(e) {return e.existing && ['law','form','dms'].includes(e.item.kind);}).map(function(e) {return e.item.kind+':'+e.item.id;}));
    selection.objects.forEach(function(entry) {occupied.add(entry.ref);additions.push(entry);});
    selection.bundles.forEach(function(pick) {
      (pick.bundle.items || []).forEach(function(item) {
        var portal = ['law','form','dms'].includes(item.kind), ref = item.kind+':'+item.id;
        if (portal && occupied.has(ref)) return;
        if (portal) occupied.add(ref);
        additions.push({ref:'bundle:'+pick.id+':'+item.key,item:Object.assign({},item,{bundle_title:pick.bundle.title}),box:pick.box,bundle:true});
      });
    });
    selection.uploads.forEach(function(file,index) {additions.push({ref:'upload:'+index,item:{title:file.name,kind:file.name.toLowerCase().endsWith('.md')?'markdown':'file',mime:file.type,size:file.size},upload:index});});
    if (selection.markdown) additions.push({ref:'markdown:new',item:{title:selection.markdown.title || 'Textdokument',kind:'markdown'}});
    var byRef = new Map(additions.map(function(entry) {return [entry.ref,entry];}));
    var result = entries.filter(function(e) {return e.existing || byRef.has(e.ref);}).map(function(e) {return e.existing?e:byRef.get(e.ref);});
    var known = new Set(result.map(function(e) {return e.ref;}));
    return result.concat(additions.filter(function(e) {return !known.has(e.ref);}));
  }
  var api = {reconcileDocuments:reconcileDocuments};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.CirculationEditorState=api;
})(typeof window !== 'undefined'?window:globalThis);
