"""Public RLP cadastral information; no ownership records or privileged service access."""
import math
import re
import json
import time
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from . import maps as mp

SOURCE = 'https://www.geoportal.rlp.de/registry/wfs/519'
BOUNDARIES = 'https://geo5.service24.rlp.de/wfs/verwaltungsgrenzen_rp.fcgi'
_lookup_cache = OrderedDict()
_lookup_lock = threading.RLock()
LOOKUP_LIMIT = 100


def preference(cfg):
    return {'preferred_code': cfg.get('map_parcel_vg_code', '33510'),
            'preferred_label': cfg.get('map_parcel_vg_label', 'VG Otterbach-Otterberg')}


def _name(value, minimum=0):
    value = str(value or '').strip()
    if len(value) < minimum or len(value) > 100 or any(c in value for c in '*?!\\\x00'):
        raise ValueError('Bitte mindestens zwei Zeichen und keine Platzhalter eingeben.')
    return value


def _eq(field, value):
    return '<fes:PropertyIsEqualTo><fes:ValueReference>'+field+'</fes:ValueReference><fes:Literal>'+escape(value)+'</fes:Literal></fes:PropertyIsEqualTo>'


def _like(field, value):
    return '<fes:PropertyIsLike wildCard="*" singleChar="?" escapeChar="!" matchCase="false"><fes:ValueReference>'+field+'</fes:ValueReference><fes:Literal>'+escape(value)+'*</fes:Literal></fes:PropertyIsLike>'


def _query(url, typename, properties, terms, *, start=0, count=LOOKUP_LIMIT+1, json_format=False):
    """Fixed trusted endpoints, property-only requests, bounded pages; no server next-URL following."""
    key = (url, typename, tuple(properties), tuple(terms), start, count, json_format)
    with _lookup_lock:
        cached = _lookup_cache.get(key)
        if cached and cached[0] > time.monotonic():
            _lookup_cache.move_to_end(key)
            return json.loads(cached[1])
        filt = '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0">'+ ('<fes:And>'+''.join(terms)+'</fes:And>' if len(terms)>1 else ''.join(terms))+'</fes:Filter>' if terms else ''
        namespace = 'https://www.vermkv.rlp.de' if typename.startswith('vermkv:') else 'http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0'
        prefix = typename.split(':')[0]
        output = ' outputFormat="application/json; subtype=geojson"' if json_format else ''
        body = ('<wfs:GetFeature xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:'+prefix+'="'+namespace+'" service="WFS" version="2.0.0" count="'+str(count)+'" startIndex="'+str(start)+'"'+output+'><wfs:Query typeNames="'+typename+'">'+''.join('<wfs:PropertyName>'+p+'</wfs:PropertyName>' for p in properties)+filt+'</wfs:Query></wfs:GetFeature>').encode()
        status, body, _ = mp.fetch(url, guard=True, accept='application/json' if json_format else 'application/xml', content=body)
        if status >= 400 or mp.exception_text(body):
            raise ValueError('Die amtlichen Suchvorschläge sind derzeit nicht erreichbar. Die freie Eingabe bleibt möglich.')
        if json_format:
            data=json.loads(body); rows=[f.get('properties') or {} for f in data.get('features', [])[:count]]
            total=data.get('numberMatched'); returned=len(rows)
        else:
            root=mp.ET.fromstring(body)
            rows=[]
            for member in root.iter():
                if member.tag.split('}')[-1] == 'member' and len(member):
                    rows.append({e.tag.split('}')[-1]: ''.join(e.itertext()).strip()[:200] for e in member[0] if e.tag.split('}')[-1] in properties})
            total=root.get('numberMatched'); returned=int(root.get('numberReturned',len(rows)))
        complete = returned < count
        if str(total).isdigit(): complete = start+returned >= int(total)
        elif not json_format and root.get('next'): complete = False
        result={'rows':rows[:count], 'complete':complete, 'start':start, 'returned':returned}
        _lookup_cache[key]=(time.monotonic()+3600, json.dumps(result))
        while len(_lookup_cache)>256: _lookup_cache.popitem(last=False)
        return result


def vg_options(query):
    query=_name(query,2)
    data=_query(BOUNDARIES,'vermkv:verbandsgemeinde_rlp',['vgnr','vgname'],[_like('vgname',query)])
    return {'items':[{'code':r['vgnr'],'name':r['vgname']} for r in data['rows'][:LOOKUP_LIMIT] if re.fullmatch(r'\d{5}',r.get('vgnr',''))], 'complete':data['complete'] and len(data['rows'])<=LOOKUP_LIMIT}


def validate_vg(code):
    if not re.fullmatch(r'\d{5}',str(code)): raise ValueError('Bitte eine Verbandsgemeinde aus den Suchvorschlägen wählen.')
    data=_query(BOUNDARIES,'vermkv:verbandsgemeinde_rlp',['vgnr','vgname'],[_eq('vgnr',code)])
    row=next((r for r in data['rows'] if r.get('vgnr')==code),None)
    if not row: raise ValueError('Die Verbandsgemeinde wurde in den amtlichen Daten nicht gefunden.')
    return row.get('vgname') or code


def lookup(params, cfg):
    scope=params.get('scope','preferred')
    if scope not in ('preferred','rlp'): raise ValueError('Bitte Suchgebiet prüfen.')
    name=_name(params.get('gemarkung',''),2 if scope=='rlp' else 0)
    pref=preference(cfg); terms=[]
    if scope=='preferred':
        if not re.fullmatch(r'\d{5}',pref['preferred_code']): raise ValueError('Das bevorzugte Suchgebiet ist noch nicht eingerichtet.')
        terms.append(_eq('vgnr',pref['preferred_code']))
    if name: terms.append(_like('gemarkung',name))
    data=_query(BOUNDARIES,'vermkv:gemarkungen_rlp',['gemarkung','gmkgnr'],terms)
    result={'gemarkungen': sorted([{'name':r['gemarkung'],'code':r.get('gmkgnr','')} for r in data['rows'][:LOOKUP_LIMIT] if r.get('gemarkung')],key=lambda r:r['name'].casefold()),'fluren':[], 'nummern':[], 'complete':data['complete'] and len(data['rows'])<=LOOKUP_LIMIT, **pref, 'source':BOUNDARIES,'attribution':ATTRIBUTION}
    selected=[r for r in result['gemarkungen'] if r['name'].casefold()==name.casefold()]
    if len(selected)==1:
        flurs=_query(BOUNDARIES,'vermkv:fluren_rlp',['flur'],[_eq('gmkgnr',selected[0]['code'])])
        result['fluren']=sorted({str(int(r['flur'])) for r in flurs['rows'][:LOOKUP_LIMIT] if re.fullmatch(r'\d{1,5}',r.get('flur',''))},key=int)
        result['complete'] = result['complete'] and flurs['complete'] and len(flurs['rows'])<=LOOKUP_LIMIT
        flur=str(params.get('flur','')).strip(); zaehler=str(params.get('zaehler','')).strip()
        if flur:
            if not re.fullmatch(r'\d{1,5}',flur) or (zaehler and not re.fullmatch(r'\d{1,5}',zaehler)): raise ValueError('Flur und Zähler bitte als Zahlen eingeben.')
            filters=[_like('flstkennz',selected[0]['code']),_eq('flur','Flur '+str(int(flur)))]
            if zaehler: filters.append(_eq('flstnrzae',str(int(zaehler))))
            numbers=_query(SOURCE,'ave:Flurstueck',['flstnrzae','flstnrnen'],filters,json_format=True)
            pairs={(str(r.get('flstnrzae','')),str(r.get('flstnrnen') or '0')) for r in numbers['rows'][:LOOKUP_LIMIT] if str(r.get('flstnrzae','')).isdigit()}
            result['nummern']=[{'zaehler':a,'nenner':b,'label':a+('/'+b if b!='0' else '')} for a,b in sorted(pairs,key=lambda p:(int(p[0]),int(p[1]) if p[1].isdigit() else 0))]
            result['complete']=result['complete'] and numbers['complete'] and len(numbers['rows'])<=LOOKUP_LIMIT
    result['message']='Amtliche Suchvorschläge. Freie Eingabe ist weiterhin möglich.' if result['complete'] else 'Nur ein Teil der amtlichen Treffer wird vorgeschlagen. Bitte die Eingabe genauer eingrenzen; freie Eingabe ist möglich.'
    return result
ATTRIBUTION = f'©GeoBasis-DE / LVermGeoRP {datetime.now(timezone.utc).year}, dl-de/by-2-0, www.lvermgeo.rlp.de'
FIELDS = {'gemarkung':'Gemarkung','gemeinde':'Gemeinde','flur':'Flur','flstnrzae':'Zähler','flstnrnen':'Nenner','flstkennz':'Flurstückskennzeichen','flaeche':'Amtliche Fläche (m²)','lagebeztxt':'Lagebezeichnung','tntxt':'Tatsächliche Nutzung','aktualit':'Datenstand'}
CATALOG = {
 'dtk5':dict(name='DTK5 RP – farbig',url='https://www.geoportal.rlp.de/mapbender/php/wms.php?layer_id=24142&withChilds=1',layer='rp_dtk5'),
 'dtk5-gray':dict(name='DTK5 RP – grau',url='https://www.geoportal.rlp.de/mapbender/php/wms.php?layer_id=24142&withChilds=1',layer='rp_dtk5_grau'),
 'lika':dict(name='Liegenschaftskarte RP – tagesaktuell',url='https://www.geoportal.rlp.de/mapbender/php/wms.php?layer_id=61688&withChilds=1',layer='rp_lika'),
 'lika-info':dict(name='Flurstücksauskunft RP',url='https://www.geoportal.rlp.de/mapbender/php/wms.php?layer_id=61688&withChilds=1',layer='rp_lika_info'),
 'parcels':dict(name='ALKIS RP – Flurstücke',url=SOURCE,layer='ave:Flurstueck',kind='wfs'),
 'boundaries':dict(name='Verwaltungs-, Gemarkungs- und Flurgrenzen RP',url='https://www.geoportal.rlp.de/mapbender/php/wms.php?layer_id=48936&withChilds=1',layer=''),
 'plans-otterbach':dict(attribution='Bebauungspläne Otterbach / GeoPortal Rheinland-Pfalz; Nutzungsbedingungen des Herausgebers beachten',name='Bebauungspläne Otterbach',url='https://komserv4gdi.service24.rlp.de/ows/wms/07335034_Otterbach?',layer=''),
 'plans-otterberg':dict(attribution='Bebauungspläne Otterberg / GeoPortal Rheinland-Pfalz; Nutzungsbedingungen des Herausgebers beachten',name='Bebauungspläne Otterberg',url='https://komserv4gdi.service24.rlp.de/ows/wms/07335035_Otterberg?',layer=''),
}


def filter_xml(params):
    terms=[]
    def eq(field, value):
        terms.append('<fes:PropertyIsEqualTo><fes:ValueReference>'+field+'</fes:ValueReference><fes:Literal>'+escape(value)+'</fes:Literal></fes:PropertyIsEqualTo>')
    name=str(params.get('gemarkung','')).strip()[:100]
    code=str(params.get('kennzeichen','')).strip().upper()[:40]
    if code:
        if not re.fullmatch(r'[A-Z0-9_/-]{8,40}',code): raise ValueError('Bitte ein gültiges Flurstückskennzeichen eingeben.')
        eq('flstkennz',code)
    else:
        if len(name)<2:raise ValueError('Bitte mindestens zwei Zeichen der Gemarkung eingeben.')
        if any(c in name for c in '*?!\\'):raise ValueError('Bitte die Gemarkung ohne Platzhalter eingeben.')
        terms.append('<fes:PropertyIsLike wildCard="*" singleChar="?" escapeChar="!" matchCase="false"><fes:ValueReference>gemarkung</fes:ValueReference><fes:Literal>'+escape(name)+'*</fes:Literal></fes:PropertyIsLike>')
        for key,field in [('zaehler','flstnrzae'),('nenner','flstnrnen'),('flur','flur')]:
            value=str(params.get(key,'')).strip()
            if value:
                if not re.fullmatch(r'\d{1,5}',value):raise ValueError('Flur, Zähler und Nenner bitte als Zahlen eingeben.')
                eq(field,('Flur ' if key=='flur' else '')+str(int(value)))
    return '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0">'+('<fes:And>'+''.join(terms)+'</fes:And>' if len(terms)>1 else terms[0])+'</fes:Filter>'


def fetch(params=None, point=None, cfg=None):
    query=dict(SERVICE='WFS',REQUEST='GetFeature',VERSION='2.0.0',TYPENAMES='ave:Flurstueck',COUNT='21',OUTPUTFORMAT='application/json; subtype=geojson',SRSNAME='urn:ogc:def:crs:EPSG::4326')
    if point:
        lon,lat=point
        if not (5.5<=lon<=9 and 48.5<=lat<=51.5):raise ValueError('Die öffentliche Flurstücksauskunft ist für Rheinland-Pfalz verfügbar.')
        x=6378137*math.radians(lon);y=6378137*math.log(math.tan(math.pi/4+math.radians(lat)/2))
        query['BBOX']=','.join(str(v) for v in (x-2,y-2,x+2,y+2))+',urn:ogc:def:crs:EPSG::3857'
    else:
        params=params or {}
        query['FILTER']=filter_xml(params)
        if params.get('scope') == 'preferred':
            available=lookup({'scope':'preferred'},cfg or {})
            if not available['complete']: raise ValueError('Das bevorzugte Suchgebiet konnte nicht vollständig geladen werden. Bitte Rheinland-Pfalz als Suchgebiet wählen.')
            codes=[g['code'] for g in available['gemarkungen'] if re.fullmatch(r'\d{6}',g.get('code',''))]
            if not codes: raise ValueError('Keine Gemarkungen für das bevorzugte Suchgebiet gefunden.')
            old=query['FILTER'].split('>',1)[1].rsplit('</fes:Filter>',1)[0]
            query['FILTER']='<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0"><fes:And>'+old+'<fes:Or>'+''.join(_like('flstkennz',code) for code in codes)+'</fes:Or></fes:And></fes:Filter>'
        elif params.get('scope') not in (None,'','rlp'):
            raise ValueError('Bitte Suchgebiet prüfen.')
    if point:
        status,body,_=mp.fetch(mp._with_params(SOURCE,query),guard=True,accept='application/json')
    else:
        # Geoportal's proxy rejects XML filters in GET URLs; the standard WFS POST works.
        body=('<wfs:GetFeature xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ave="http://repository.gdi-de.org/schemas/adv/produkt/alkis-vereinfacht/2.0" service="WFS" version="2.0.0" count="21" outputFormat="application/json; subtype=geojson"><wfs:Query typeNames="ave:Flurstueck" srsName="urn:ogc:def:crs:EPSG::4326">'+query['FILTER']+'</wfs:Query></wfs:GetFeature>').encode()
        status,body,_=mp.fetch(SOURCE,guard=True,accept='application/json',content=body)
    if status>=400:raise ValueError('Die amtliche Flurstücksauskunft ist derzeit nicht erreichbar.')
    data=mp.normalize_features(body)
    now=datetime.now(timezone.utc).isoformat()
    features=[]
    for feature in data['features'][:20]:
        p=feature.get('properties') or {}; safe={k:p[k] for k in FIELDS if k in p and isinstance(p[k],(str,int,float,type(None)))}
        if point and not contains(feature.get('geometry'),point):continue
        features.append(dict(type='Feature',id=p.get('flstkennz') or feature.get('id'),geometry=feature.get('geometry'),properties=safe,
            source=SOURCE,retrieved_at=now,attribution=ATTRIBUTION))
    return dict(type='FeatureCollection',features=features,truncated=len(data['features'])>20,source=SOURCE,retrieved_at=now,fields=FIELDS,attribution=ATTRIBUTION)


def contains(geometry,point):
    def ring(r):
        x,y=point;inside=False
        for a,b in zip(r,r[1:]+r[:1]):
            if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
        return inside
    if not geometry:return False
    polys=[geometry['coordinates']] if geometry['type']=='Polygon' else geometry['coordinates'] if geometry['type']=='MultiPolygon' else []
    return any(ring(poly[0]) and not any(ring(hole) for hole in poly[1:]) for poly in polys if poly)


def clean_selection(raw):
    if not isinstance(raw,list):return []
    result=[]
    for f in raw[:50]:
        if not isinstance(f,dict) or not isinstance(f.get('properties'),dict):continue
        g=f.get('geometry'); geom=mp.clean_geometry(g)
        if not geom and isinstance(g,dict) and g.get('type')=='MultiPolygon':
            parts=[mp.clean_geometry({'type':'Polygon','coordinates':p}) for p in g.get('coordinates',[])[:20]]
            if parts and all(parts):geom={'type':'MultiPolygon','coordinates':[p['coordinates'] for p in parts]}
        if not geom:continue
        props={k:(str(v)[:4000] if isinstance(v,str) else v) for k,v in f['properties'].items() if k in FIELDS and isinstance(v,(str,int,float,type(None)))}
        if not props.get('flstkennz'):continue
        result.append(dict(type='Feature',id=str(props['flstkennz'])[:40],geometry=geom,properties=props,source=SOURCE,retrieved_at=str(f.get('retrieved_at',''))[:60],attribution=ATTRIBUTION))
    return result
