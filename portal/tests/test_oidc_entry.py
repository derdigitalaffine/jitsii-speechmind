import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi.testclient import TestClient

from app import main, oidc
from app.db import set_setting
from app.security import encrypt
from conftest import client


def ready_oidc(db):
    cfg = {
        **oidc.DEFAULT,
        'base_url': 'https://cloud.example.org',
        'issuer': 'https://cloud.example.org/index.php/apps/oidc',
        'client_id': 'portal-client',
        'client_secret_enc': encrypt('test-client-secret'),
        'enabled': True,
    }
    cfg['tested_hash'] = oidc.fingerprint(cfg)
    set_setting(db, 'oidc_config', json.dumps(cfg))
    db.commit()
    return cfg


def test_login_uses_navigation_link_for_oidc(db):
    ready_oidc(db)
    page = client().get('/login?next=/seminare')

    assert page.status_code == 200
    match = re.search(r'href="/auth/oidc/start\?next=([^"]*)"', page.text)
    assert match and unquote(match.group(1)) == '/seminare'
    assert 'action="/auth/oidc/start"' not in page.text


def test_oidc_login_can_start_with_get(db, monkeypatch):
    cfg = ready_oidc(db)
    monkeypatch.setattr(oidc, 'discovery', lambda _cfg: {
        'authorization_endpoint': cfg['issuer'] + '/authorize',
    })

    response = client().get('/auth/oidc/start?next=/seminare')

    assert response.status_code == 303
    location = urlsplit(response.headers['location'])
    assert location.scheme == 'https' and location.netloc == 'cloud.example.org'
    params = parse_qs(location.query)
    assert params['client_id'] == ['portal-client']
    assert params['redirect_uri'] == [oidc.callback_url()]
    assert params['code_challenge_method'] == ['S256']
    assert params['scope'] == ['openid profile email groups']
    assert 'state' in params and 'nonce' in params


def test_module_domain_oidc_navigation_redirects_to_configured_portal(db):
    set_setting(db, 'domain_krank', 'krank.example.org')
    db.commit()
    main._host_cache['at'] = 0.0
    try:
        c = TestClient(main.app, base_url='https://krank.example.org', follow_redirects=False)
        response = c.get('/auth/oidc/start?next=/seminare')
        assert response.status_code == 302
        assert response.headers['location'] == (
            main.settings.portal_base_url + '/auth/oidc/start?next=/seminare'
        )
    finally:
        set_setting(db, 'domain_krank', '')
        db.commit()
        main._host_cache['at'] = 0.0
