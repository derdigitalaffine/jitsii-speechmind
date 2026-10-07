from app import geocode
from app.db import set_setting
from conftest import client, login, csrf_of


def test_public_live_never_queries_upstream(monkeypatch):
    monkeypatch.setattr(geocode, 'config', lambda: {'url': geocode.DEFAULT_URL, 'countries': 'de', 'contact': '', 'search_mode': 'live', 'delay_ms': '250'})
    monkeypatch.setattr(geocode.httpx, 'get', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Public autocomplete request')))
    response = client().get('/geo/search', params={'q': 'Never cached public search', 'live': '1'})
    assert response.status_code == 200 and response.json()['results'] == []
    info = client().get('/geo/info').json()
    assert info['delay_ms'] == 1000 and not info['live_upstream']
    assert client().get('/geo/search?q=public').status_code == 400


def test_custom_live_and_manual_are_enforced(monkeypatch):
    cfg = {'url': 'https://own.example.invalid', 'countries': 'de', 'contact': '', 'search_mode': 'auto', 'delay_ms': '250'}
    monkeypatch.setattr(geocode, 'config', lambda: cfg)
    calls = []
    monkeypatch.setattr(geocode, 'search', lambda q, limit, cache_only: calls.append(cache_only) or [])
    assert client().get('/geo/search?q=custom&live=1').status_code == 200
    assert calls == [False]
    assert client().get('/geo/info').json()['delay_ms'] == 250
    cfg['search_mode'] = 'manual'
    client().get('/geo/search?q=custom&live=1')
    assert calls == [False, True]
    client().get('/geo/search?q=custom')
    assert calls == [False, True, False]


def test_settings_validate_and_persist(db):
    browser = login('admin@example.org', 'admin-passwort-123')
    page = browser.get('/admin/maps')
    assert 'Adresssuche beim Tippen' in page.text
    data = {'csrf': csrf_of(page.text), 'map_center_lat': '49', 'map_center_lon': '7', 'geocoder_search_mode': 'live', 'geocoder_delay_ms': '450'}
    response = browser.post('/admin/maps/settings', data=data)
    assert response.status_code == 303
    assert browser.get('/geo/info').json()['search_mode'] == 'live'
    data['geocoder_delay_ms'] = '5'
    browser.post('/admin/maps/settings', data=data)
    assert browser.get('/geo/info').json()['search_mode'] == 'live'
    set_setting(db, 'geocoder_search_mode', 'auto')
    set_setting(db, 'geocoder_delay_ms', '300')
    db.commit()


def test_public_cached_search_and_provider_isolation(monkeypatch):
    cfg = {'url': geocode.DEFAULT_URL, 'countries': 'de', 'contact': '', 'search_mode': 'auto', 'delay_ms': '300'}
    monkeypatch.setattr(geocode, 'config', lambda: cfg)
    class Response:
        status_code = 200
        def json(self):
            return [{'lat': '49', 'lon': '7', 'address': {'village': 'Heiligenmoschel', 'postcode': '67699'}, 'display_name': 'Cache test town'}]
    calls = []
    monkeypatch.setattr(geocode.httpx, 'get', lambda *a, **kw: calls.append(a) or Response())
    query = 'Unique complete public cache test'
    original = geocode.search(query)
    assert original[0]['city'] == 'Heiligenmoschel'
    assert geocode.search(query, cache_only=True) == original
    assert len(calls) == 1
    cfg['url'] = 'https://other.example.invalid'
    assert geocode.search(query, cache_only=True) == []
    assert len(calls) == 1
