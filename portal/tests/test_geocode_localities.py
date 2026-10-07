"""Regression: Ortsgemeinden must not become their Verbandsgemeinde."""
import pytest
from app import geocode

@pytest.mark.parametrize('locality', ['Heiligenmoschel', 'Höringen', 'Schneckenhausen'])
def test_locality_survives_administrative_municipality(locality):
    result = geocode._address({'address': {'village': locality, 'municipality': 'Otterbach-Otterberg', 'postcode': '67699'}})
    assert result['city'] == locality
    assert result['district'] == ''
    assert result['municipality'] == 'Otterbach-Otterberg'


def test_city_and_real_suburb_stay_separate():
    result = geocode._address({'address': {'city': 'Kaiserslautern', 'suburb': 'Erfenbach', 'municipality': 'Kaiserslautern'}})
    assert result['city'] == 'Kaiserslautern'
    assert result['district'] == 'Erfenbach'


def test_hamlet_is_not_overwritten_by_administrative_municipality():
    result = geocode._address({'address': {'hamlet': 'Testweiler', 'municipality': 'Verbandsgemeinde'}})
    assert result['city'] == 'Testweiler'


def test_shared_postcode_provides_distinct_localities(monkeypatch):
    monkeypatch.setattr(geocode, 'config', lambda: {'countries': 'de'})
    monkeypatch.setattr(geocode, '_fetch', lambda *a: [
        {'address': {'village': name, 'municipality': 'Otterbach-Otterberg', 'postcode': '67699'}}
        for name in ['Heiligenmoschel', 'Höringen', 'Heiligenmoschel']])
    assert [(v['city'], v['district']) for v in geocode.postcode('67699')] == [('Heiligenmoschel', ''), ('Höringen', '')]
