import pytest

from conftest import csrf_of, login
from test_circulations import actors


def test_active_user_without_circulation_permissions_cannot_preview(actors):
    user = actors[3]
    assert user.active and not user.permissions
    client = login(user.email, 'passwort-test-123')
    token = csrf_of(client.get('/umlaeufe').text)

    response = client.post('/umlaeufe/preview', data={'csrf': token, 'body': '**Vorschau**'})

    assert response.status_code == 403
    assert '<strong>Vorschau</strong>' not in response.text


@pytest.mark.parametrize('permission', [
    'circulations_create', 'circulations_publish', 'circulations_manage',
])
def test_each_circulation_permission_allows_preview(db, actors, permission):
    user = actors[3]
    user.permissions = permission
    db.commit()
    client = login(user.email, 'passwort-test-123')
    token = csrf_of(client.get('/umlaeufe').text)

    response = client.post('/umlaeufe/preview', data={'csrf': token, 'body': '**Vorschau**'})

    assert response.status_code == 200
    assert '<strong>Vorschau</strong>' in response.text
