"""Public RLP cadastral information; no ownership records or privileged service access."""
import math
import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from . import maps as mp

SOURCE = 'https://www.geoportal.rlp.de/registry/wfs/519'
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


def fetch(params=None, point=None):
    query=dict(SERVICE='WFS',REQUEST='GetFeature',VERSION='2.0.0',TYPENAMES='ave:Flurstueck',COUNT='21',OUTPUTFORMAT='application/json; subtype=geojson',SRSNAME='urn:ogc:def:crs:EPSG::4326')
    if point:
        lon,lat=point
        if not (5.5<=lon<=9 and 48.5<=lat<=51.5):raise ValueError('Die öffentliche Flurstücksauskunft ist für Rheinland-Pfalz verfügbar.')
        x=6378137*math.radians(lon);y=6378137*math.log(math.tan(math.pi/4+math.radians(lat)/2))
        query['BBOX']=','.join(str(v) for v in (x-2,y-2,x+2,y+2))+',urn:ogc:def:crs:EPSG::3857'
    else:query['FILTER']=filter_xml(params or {})
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
