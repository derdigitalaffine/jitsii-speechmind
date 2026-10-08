"""OGC interoperability, public cadastral information and durable geometry snapshots."""
import json
from urllib.parse import parse_qs, urlparse
import pytest
from app import maps, parcels, forms
from app.db import UserMap, Group
from conftest import client, login, csrf_of, settings
from test_circulations import actors


def test_wms_capability_endpoint_inheritance_and_query_format():
    body=b'''<WMS_Capabilities version="1.3.0"><Capability><Request><GetMap><DCPType><HTTP><Get><OnlineResource xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.org/ows?map=rp"/></Get></HTTP></DCPType></GetMap><GetFeatureInfo><Format>text/html</Format><Format>application/json</Format></GetFeatureInfo></Request><Layer queryable="1"><CRS>EPSG:3857</CRS><Dimension name="time" default="2025">2024,2025</Dimension><Layer><Name>rp_lika</Name><Title>LiKa</Title></Layer></Layer></Capability></WMS_Capabilities>'''
    caps=maps.parse_capabilities(body,'wms');l=caps['layers'][0]
    assert caps['url']=='https://example.org/ows?map=rp'
    assert l['supported'] and l['queryable'] and l['times']==['2024','2025']
    assert l['service']['info_format']=='application/json'
    spec={'kind':'wms','url':caps['url'],'layers':l['name'],'service':l['service']}
    q=parse_qs(urlparse(maps.upstream_url(spec,'info',{'bbox':'0,0,10,10','i':17,'j':200,'time':'2024'})).query)
    assert q['map']==['rp'] and q['I']==['17'] and q['J']==['200'] and q['TIME']==['2024']
    assert q['QUERY_LAYERS']==['rp_lika']


def test_wmts_real_matrix_identifiers_and_unsupported_grid():
    template='''<Capabilities><OperationsMetadata><Operation name="GetTile"><DCP><HTTP><Get xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.org/wmts?key=public"/></HTTP></DCP></Operation></OperationsMetadata><Contents><Layer><Identifier>base</Identifier><Format>image/png</Format><Style isDefault="true"><Identifier>normal</Identifier></Style><TileMatrixSetLink><TileMatrixSet>merc</TileMatrixSet></TileMatrixSetLink></Layer><TileMatrixSet><Identifier>merc</Identifier><SupportedCRS>{crs}</SupportedCRS><TileMatrix><Identifier>EPSG:3857:0</Identifier><ScaleDenominator>559082264.0287178</ScaleDenominator><TopLeftCorner>-20037508.342789244 20037508.342789244</TopLeftCorner><TileWidth>256</TileWidth><TileHeight>256</TileHeight><MatrixWidth>1</MatrixWidth><MatrixHeight>1</MatrixHeight></TileMatrix></TileMatrixSet></Contents></Capabilities>'''
    caps=maps.parse_capabilities(template.format(crs='urn:ogc:def:crs:EPSG::3857').encode(),'xyz');l=caps['layers'][0]
    assert caps['type']=='wmts' and l['supported'] and l['service']['matrices']=={'0':'EPSG:3857:0'}
    spec={'kind':'wmts','url':l['template'],'layers':'base','styles':l['styles'],'service':l['service']}
    q=parse_qs(urlparse(maps.upstream_url(spec,'tile',{'z':0,'x':0,'y':0,'time':'2025'})).query)
    assert q['TILEMATRIX']==['EPSG:3857:0'] and q['STYLE']==['normal'] and q['TIME']==['2025'] and q['key']==['public']
    assert maps.upstream_url(spec,'tile',{'z':1,'x':0,'y':0}) is None
    spec['url']='https://example.org/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}/{Style}.png'
    assert '/merc/EPSG:3857:0/0/0/normal.png' in maps.upstream_url(spec,'tile',{'z':0,'x':0,'y':0})
    assert not maps.parse_capabilities(template.format(crs='EPSG:25832').encode(),'wmts')['layers'][0]['supported']


def test_gml_axes_and_unknown_crs_are_explicit():
    body=b'''<FeatureCollection xmlns:gml="http://www.opengis.net/gml" xmlns:x="urn:test"><gml:featureMember><x:parcel><x:name>Test</x:name><x:geometry><gml:Point srsName="urn:ogc:def:crs:EPSG::4326"><gml:pos>49.48 7.73</gml:pos></gml:Point></x:geometry></x:parcel></gml:featureMember></FeatureCollection>'''
    f=maps.normalize_features(body)['features'][0]
    assert f['geometry']['coordinates']==[7.73,49.48]
    with pytest.raises(ValueError):maps.normalize_features(body.replace(b'4326',b'25832'))
    assert maps.exception_text(b'<ServiceExceptionReport><ServiceException>bad layer</ServiceException></ServiceExceptionReport>')=='bad layer'


def shape():
    return {'type':'Polygon','coordinates':[[[7,49],[8,49],[8,50],[7,50],[7,49]],[[7.2,49.2],[7.8,49.2],[7.8,49.8],[7.2,49.8],[7.2,49.2]]]}


def test_parcel_snapshot_preserves_holes_in_maps_and_form_exports():
    g=shape();f={'type':'Feature','id':'07492600001144______','geometry':g,'properties':{'flstkennz':'07492600001144______','gemarkung':'Otterbach','flaeche':5730,'owner':'must disappear'},'retrieved_at':'2026-10-08T12:00:00Z'}
    snap=parcels.clean_selection([f])[0]
    assert len(snap['geometry']['coordinates'])==2 and 'owner' not in snap['properties']
    assert parcels.contains(g,(7.1,49.1)) and not parcels.contains(g,(7.5,49.5))
    assert maps.clean_geometry(g,max_points=4) is None # never silently truncate cadastral boundaries
    raw={'type':'FeatureCollection','features':[{'geometry':g,'properties':{'parcel':{k:v for k,v in snap.items() if k!='geometry'}}}]}
    value,error=forms.parse_geo({'geometries':['polygon'],'max_features':1,'allow_parcels':True},json.dumps(raw))
    assert not error and value['features'][0]['parcel']['properties']['flstkennz']==f['id']
    assert value['features'][0]['area'] < forms.parse_shape(json.dumps({'type':'Polygon','coordinates':g['coordinates'][:1]}),'polygon')['area']
    rebuilt=forms.geo_features(value)[0]
    assert len(rebuilt['geometry']['coordinates'])==2 and rebuilt['properties']['parcel']['source']==parcels.SOURCE


def test_public_parcel_search_uses_post_filter_and_whitelists(monkeypatch):
    calls=[]
    def fetch(url,**kw):
        calls.append((url,kw))
        return 200,json.dumps({'type':'FeatureCollection','features':[{'geometry':shape(),'properties':{'flstkennz':'07492600001144______','gemarkung':'Otterbach','owner':'private'}}]}).encode(),'application/json'
    monkeypatch.setattr(maps,'fetch',fetch);settings(module_maps='1')
    r=client().get('/map/parcels',params={'gemarkung':'Otterbach','flur':'0','zaehler':'1144'})
    assert r.status_code==200 and 'owner' not in r.json()['features'][0]['properties']
    assert calls[0][0]==parcels.SOURCE and calls[0][1]['guard']
    assert b'Flur 0' in calls[0][1]['content'] and b'1144' in calls[0][1]['content']
    assert client().get('/map/parcels',params={'gemarkung':'*'}).status_code==422
    assert client().get('/map/parcels',params={'lon':7.7}).status_code==422
    assert client().get('/map/parcels',params={'lon':0,'lat':0}).status_code==422
    assert 'A&amp;B' in parcels.filter_xml({'gemarkung':'A&B'})


def test_portal_member_saved_maps_internal_sharing_and_guest_restrictions(db,actors,monkeypatch):
    settings(module_maps='1')
    owner=login(actors[1].email,'passwort-test-123');page=owner.get('/karte')
    assert page.status_code==200 and 'Layer hinzufügen' in page.text
    assert client().get('/karte').status_code==200 and 'id="add-layer"' not in client().get('/karte').text
    saved=owner.post('/maps/save',data={'csrf':csrf_of(page.text),'title':'Interne Karte','state':'{}'}).json();mid=saved['id']
    outsider=login(actors[3].email,'passwort-test-123')
    assert outsider.get(f'/maps/{mid}').status_code==404
    group=Group(name='GIS test');group.members.append(actors[3]);db.add(group);db.commit()
    share=owner.post(f'/maps/{mid}/share',data={'csrf':csrf_of(page.text),'groups':group.id})
    assert share.status_code==303 and outsider.get(f'/maps/{mid}').status_code==200
    listing=outsider.get('/maps');assert listing.status_code==200 and 'Für Sie freigegeben' in listing.text
    assert outsider.post(f'/maps/{mid}/share',data={'csrf':csrf_of(listing.text)}).status_code==404
    assert outsider.post(f'/maps/{mid}/public',data={'csrf':csrf_of(listing.text)}).status_code==404
    assert client().get(f'/maps/{mid}').status_code in (401,403,303)
    owner.post(f'/maps/{mid}/share',data={'csrf':csrf_of(page.text)})
    assert outsider.get(f'/maps/{mid}').status_code==404
    db.delete(db.get(UserMap,mid));db.delete(group);db.commit()


def test_legacy_capabilities_repair_cached_without_mutating_spec(monkeypatch):
    url='https://example.org/ows?request=GetCapabilities';calls=[]
    monkeypatch.setattr(maps,'query_service',lambda *a:(calls.append(a) or {'url':'https://example.org/map?key=x','layers':[{'name':'lika','service':{'info_format':'application/json'}}]}))
    maps._capability_specs.clear();spec={'kind':'wms','url':url,'layers':'lika','service':{}}
    for _ in range(2):
        fixed=maps.resolve_capability_spec(spec)
        assert fixed['url'].endswith('key=x') and fixed['service']['info_format']=='application/json'
    assert len(calls)==1 and spec['url']==url


def test_internal_layer_not_exposed_through_form_flag(db):
    from app.db import MapLayer
    from app.routes_maps import visible_layers
    l=MapLayer(name='Internal',kind='xyz',role='base',url='https://example.org/{z}/{x}/{y}.png',enabled=True,public=False,in_forms=True,proxy=True)
    db.add(l);db.commit();settings(module_maps='1')
    assert l.id not in [v.id for v in visible_layers(db,None,'forms')]
    assert client().get(f'/map/l/{l.id}/10/1/1').status_code==404
    db.delete(l);db.commit()


def test_http_200_service_exception_is_reported(db,monkeypatch):
    from app.db import MapLayer
    l=MapLayer(name='Broken WMS',kind='wms',url='https://example.org/wms',layers='bad',public=True,enabled=True,proxy=True)
    db.add(l);db.commit()
    monkeypatch.setattr(maps,'fetch',lambda *a,**k:(200,b'<ServiceExceptionReport><ServiceException>Layer unavailable</ServiceException></ServiceExceptionReport>','text/xml'))
    r=client().get(f'/map/l/{l.id}/wms',params={'bbox':'0,0,10,10'},headers={'Accept':'application/json'})
    assert r.status_code==502 and 'Layer unavailable' in r.json()['detail']
    db.delete(l);db.commit()


def test_geojson_mercator_and_invalid_coordinates():
    raw={'type':'FeatureCollection','crs':{'type':'name','properties':{'name':'EPSG:3857'}},'features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[111319.49079327358,0]},'properties':{}}]}
    d=maps.normalize_features(json.dumps(raw).encode());assert d['features'][0]['geometry']['coordinates']==pytest.approx([1,0])
    raw['crs']['properties']['name']='EPSG:25832'
    with pytest.raises(ValueError): maps.normalize_features(json.dumps(raw).encode())
    raw.pop('crs')
    with pytest.raises(ValueError): maps.normalize_features(json.dumps(raw).encode())
