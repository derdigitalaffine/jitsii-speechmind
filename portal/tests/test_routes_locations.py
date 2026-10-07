import json
import pytest
from app import routing, forms, locations
from app.db import PortalLocation, User
from conftest import login, csrf_of


def test_public_route_guard(monkeypatch):
    monkeypatch.setattr(routing,'config',lambda:routing.DEFAULTS)
    monkeypatch.setattr(routing.httpx,'get',lambda *a,**kw:pytest.fail('No private coordinate upstream'))
    with pytest.raises(ValueError,match='öffentliche Orte'):
        routing.quote([{'lat':49,'lon':7},{'lat':50,'lon':8}],'private_car')


def test_route_cache_proof_and_deviation(monkeypatch):
    calls=[]
    class Response:
        status_code=200
        def json(self):return {'code':'Ok','routes':[{'distance':12345,'duration':900,'geometry':{'type':'LineString','coordinates':[[7,49],[8,50]]}}]}
    monkeypatch.setattr(routing,'config',lambda:{'car':'https://self-hosted.invalid'})
    monkeypatch.setattr(routing.httpx,'get',lambda *a,**kw:calls.append(a) or Response())
    quote=routing.quote([{'lat':49,'lon':7,'label':'A'},{'lat':50,'lon':8,'label':'B'}],'recognized_car')
    assert quote['category']=='recognized_car'
    assert routing.quote(quote['points'],'recognized_car')['meters']==12345
    assert len(calls)==1
    item={'type':'route','id':'r','required':True,**routing.clean({})}
    data={'q_r':json.dumps({'legs':[{'quote':quote,'actual_km':'14','reason':'Baustelle','date':'2026-10-07'}]})}
    value,error=forms.form_fields.parse(item,data,'q_r')
    assert not error and value['meters']==14000 and value['has_deviation']
    assert 'Baustelle' in forms.display(item,value)
    data['q_r']=json.dumps({'legs':[{'quote':quote,'actual_km':'14'}]})
    assert routing.parse(item,data,'q_r')[1]
    quote['meters']=999999
    with pytest.raises(ValueError,match='geändert'):
        routing.verified_quote(quote)


def test_location_visibility_csv_atomic(db):
    admin=db.query(User).filter_by(is_admin=True).first()
    a=PortalLocation(name='Öffentliche Kita',public=True,lat=49,lon=7)
    b=PortalLocation(name='Vertraulicher Ort',public=False)
    c=PortalLocation(name='Eigener Favorit',owner_id=admin.id,public=True)
    db.add_all([a,b,c]);db.flush()
    assert a in locations.visible(db,None) and b not in locations.visible(db,None) and c not in locations.visible(db,None)
    assert b in locations.visible(db,admin) and c in locations.visible(db,admin)
    count=locations.import_rows(db,locations.export([a]).encode(),admin.id)
    assert count==1
    pending=len(db.new)
    with pytest.raises(ValueError):
        locations.import_rows(db,b'name;lat;lon\nfirst;49;7\ninvalid;200;7\n')
    assert len(db.new)==pending
    db.rollback()


def test_route_endpoint_csrf_and_settings():
    client=login('admin@example.org','admin-passwort-123')
    page=client.get('/settings/locations')
    assert page.status_code==200 and 'Zentrale Dienste' in page.text
    assert client.post('/geo/route',json={}).status_code==400
    response=client.post('/geo/route',headers={'X-CSRF-Token':csrf_of(page.text)},json={'category':'public_transport','points':[{'lat':49,'lon':7},{'lat':50,'lon':8}]})
    assert response.status_code==200 and response.json()['meters']==0
    assert 'Dienstfahrzeug' in client.get('/geo/locations').text
