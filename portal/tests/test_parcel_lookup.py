"""Bounded official cadastral suggestions, geographical scope and safe administration."""
import json
from xml.sax.saxutils import escape
import pytest
from app import maps, parcels
from conftest import client, login, csrf_of, settings


def collection(rows, total=None, next_url=None):
    attrs=' numberMatched="'+str(len(rows) if total is None else total)+'" numberReturned="'+str(len(rows))+'"'
    if next_url: attrs+=' next="'+escape(next_url, {'"':'&quot;'})+'"'
    return ('<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:x="urn:test"'+attrs+'>'+''.join('<wfs:member><x:item>'+''.join('<x:'+k+'>'+escape(str(v))+'</x:'+k+'>' for k,v in row.items())+'</x:item></wfs:member>' for row in rows)+'</wfs:FeatureCollection>').encode()


@pytest.fixture
def lookup_network(monkeypatch):
    parcels._lookup_cache.clear(); calls=[]
    def fetch(url, **kw):
        calls.append((url,kw)); body=kw['content'].decode()
        assert kw['guard'] is True
        assert url in (parcels.SOURCE,parcels.BOUNDARIES)
        if 'count="21"' not in body:
            assert 'count="101"' in body and 'startIndex="0"' in body
        assert 'msGeometry' not in body
        if 'verbandsgemeinde_rlp' in body:
            return 200,collection([{'vgnr':'33510','vgname':'Otterbach-Otterberg (33510)'}]),'application/xml'
        if 'gemarkungen_rlp' in body:
            return 200,collection([{'gemarkung':'Otterbach','gmkgnr':'074926'}]),'application/xml'
        if 'fluren_rlp' in body:
            return 200,collection([{'flur':'0'},{'flur':'2'},{'flur':'12'}]),'application/xml'
        return 200,json.dumps({'type':'FeatureCollection','numberMatched':2,'features':[{'properties':{'flstnrzae':'1144','flstnrnen':'0','owner':'private'}},{'properties':{'flstnrzae':'1144','flstnrnen':'2'}}]}).encode(),'application/json'
    monkeypatch.setattr(maps,'fetch',fetch)
    yield calls
    parcels._lookup_cache.clear()


def test_guided_lookup_uses_small_boundary_catalog_and_cached_public_properties(lookup_network):
    d=parcels.lookup({'scope':'preferred','gemarkung':'Otterbach','flur':'0'}, {})
    assert d['gemarkungen']==[{'name':'Otterbach','code':'074926'}]
    assert d['fluren']==['0','2','12']
    assert d['nummern']==[{'zaehler':'1144','nenner':'0','label':'1144'},{'zaehler':'1144','nenner':'2','label':'1144/2'}]
    assert d['complete'] and 'owner' not in json.dumps(d)
    assert len(lookup_network)==3
    assert '<fes:Literal>33510</fes:Literal>' in lookup_network[0][1]['content'].decode()
    assert '<fes:Literal>074926</fes:Literal>' in lookup_network[1][1]['content'].decode()
    again=parcels.lookup({'scope':'preferred','gemarkung':'Otterbach','flur':'0'}, {})
    again['gemarkungen'][0]['name']='must not poison cache'
    assert parcels.lookup({'scope':'preferred','gemarkung':'Otterbach','flur':'0'}, {})['gemarkungen'][0]['name']=='Otterbach'
    assert len(lookup_network)==3


def test_partial_suggestions_never_claim_complete_catalog(monkeypatch):
    parcels._lookup_cache.clear()
    rows=[{'gemarkung':'Test '+str(i),'gmkgnr':'074926'} for i in range(101)]
    monkeypatch.setattr(maps,'fetch',lambda *a,**kw:(200,collection(rows,total=500),'application/xml'))
    d=parcels.lookup({'scope':'rlp','gemarkung':'Te'}, {})
    assert len(d['gemarkungen'])==100 and not d['complete'] and 'Teil' in d['message']
    parcels._lookup_cache.clear()
    monkeypatch.setattr(maps,'fetch',lambda *a,**kw:(200,collection(rows[:2],total='unknown',next_url='http://127.0.0.1/private'),'application/xml'))
    assert not parcels.lookup({'scope':'rlp','gemarkung':'Te'}, {})['complete']
    parcels._lookup_cache.clear()


def test_public_options_validate_before_network_and_gate_disabled_module(lookup_network):
    settings(module_maps='1')
    c=client()
    for params in ({'scope':'rlp','gemarkung':'A'},{'scope':'preferred','gemarkung':'*'},{'scope':'invalid'},{'flur':'1 OR 1'}):
        assert c.get('/map/parcels/options',params=params).status_code==422
    assert not lookup_network
    assert c.get('/map/parcels/options').json()['preferred_code']=='33510'
    settings(module_maps='0')
    assert c.get('/map/parcels/options').status_code==404
    settings(module_maps='1')


def test_preferred_search_adds_actual_gemarkung_codes_not_approximate_bbox(lookup_network):
    parcels.fetch({'scope':'preferred','gemarkung':'Otterbach'},cfg={})
    assert '<fes:Literal>074926*</fes:Literal>' in lookup_network[-1][1]['content'].decode()
    assert 'BBOX' not in lookup_network[-1][1]['content'].decode()
    with pytest.raises(ValueError): parcels.fetch({'scope':'evil','gemarkung':'Otterbach'})


def test_admin_vg_search_requires_rights_and_validates_official_code(lookup_network):
    assert client().get('/admin/maps/verbandsgemeinden',params={'q':'Ot'}).status_code in (401,403,303)
    admin=login('admin@example.org','admin-passwort-123')
    assert admin.get('/admin/maps/verbandsgemeinden',params={'q':'O'}).status_code==422
    d=admin.get('/admin/maps/verbandsgemeinden',params={'q':'Ot'}).json()
    assert d['items']==[{'code':'33510','name':'Otterbach-Otterberg (33510)'}]
    page=admin.get('/admin/maps')
    assert 'parcel-vg-search' in page.text
    assert parcels.validate_vg('33510')=='Otterbach-Otterberg (33510)'
    with pytest.raises(ValueError):parcels.validate_vg('https://127.0.0.1')
    assert admin.post('/admin/maps/settings',data={'csrf':csrf_of(page.text),'map_center_lat':'49.49','map_center_lon':'7.77','map_parcel_vg_code':'12345'}).status_code==303
    # The service response cannot validate a different requested code.
    from app.db import SessionLocal,get_settings
    with SessionLocal() as db: assert get_settings(db)['map_parcel_vg_code']=='33510'
