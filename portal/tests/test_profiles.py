import json
from datetime import date
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, inspect, text
from app import profiles, forms, form_fields, db as database
from app.db import User, SessionLocal
from app.security import decrypt
from conftest import login, client, csrf_of


def test_allowlist_validation_and_standard_fields():
    value = profiles.clean({'given_name':'Ada', 'employee_number':'0012', 'home_country':'de', 'locale':'de-DE', 'zoneinfo':'Europe/Berlin', 'iban':'DE89 3704 0044 0532 0130 00', 'sub':'hacked', 'permissions':'admin', 'prefill_enabled':'1'})
    assert value == {'given_name':'Ada','employee_number':'0012','home_country':'DE','locale':'de-DE','zoneinfo':'Europe/Berlin','iban':'DE89370400440532013000','prefill_enabled':True}
    for raw in ({'iban':'DE89370400440532013001'}, {'birthdate':'2999-01-01'}, {'zoneinfo':'unknown'}, {'contact_email':'broken'}, {'bic':'bad'}, {'website':'javascript:alert(1)'}, {'locale':'<script>'}):
        with pytest.raises(ValueError):
            profiles.clean(raw)


def test_opt_in_field_types_and_answers_priority():
    raw = {'given_name':'Ada','birthdate':'1990-01-01','home_street':'Hauptstraße','home_house_no':'1','home_zip':'67699','home_city':'Heiligenmoschel','home_district':'Test'}
    user = SimpleNamespace(name='Ada Example',email='ada@example.org',profile_data_enc=profiles.store(raw))
    items = forms.clean_schema([{'id':'first','type':'short','profile_value':'given_name'}, {'id':'date','type':'date','profile_value':'birthdate'}, {'id':'address','type':'address','profile_value':'home_address','district':True}, {'id':'account','type':'short','profile_value':'email'}, {'id':'secret','type':'short','profile_value':'permissions'}, {'id':'bad','type':'date','profile_value':'iban'}])
    assert 'profile_value' not in items[-1] and 'profile_value' not in items[-2]
    assert form_fields.profile_values(items, {}, user) == {'account':'ada@example.org'}
    raw['prefill_enabled']='1';user.profile_data_enc=profiles.store(raw)
    got=form_fields.profile_values(items, {'first':'','date':'2000-01-01'}, user)
    assert got['first']=='' and got['date']=='2000-01-01'
    assert got['address']=={'street':'Hauptstraße','house_no':'1','zip':'67699','city':'Heiligenmoschel','district':'Test'}
    assert form_fields.profile_values(items,{},None)=={}
    items[2]['mode']='zip_city';items[2]['district']=False
    address=form_fields.profile_values(items,{},user)['address']
    assert address['street']==address['house_no']==address['district']==''


def test_own_profile_encrypted_export_clear_and_error_preservation():
    c=login('admin@example.org','admin-passwort-123');token=csrf_of(c.get('/profile').text)
    with SessionLocal() as db:
        u=db.get(User,1);old=u.profile_data_enc;name=u.name;email=u.email;perms=u.permissions
    try:
        response=c.post('/profile/details',data={'csrf':token,'given_name':'Ada','employee_number':'0012','prefill_enabled':'1','user_id':'999','permissions':'all','sub':'spoof'})
        assert response.status_code==303
        with SessionLocal() as db:
            u=db.get(User,1)
            assert 'Ada' not in u.profile_data_enc and json.loads(decrypt(u.profile_data_enc))['given_name']=='Ada'
            assert (u.name,u.email,u.permissions)==(name,email,perms)
        exported=c.get('/profile/details/export')
        assert exported.json()=={'given_name':'Ada','employee_number':'0012','prefill_enabled':True}
        assert exported.headers['cache-control']=='no-store'
        assert client().get('/profile/details/export').status_code in (303,401,403)
        page=c.get('/profile');assert 'value="0012"' in page.text
        failed=c.post('/profile/details',data={'csrf':token,'given_name':'Retained','iban':'invalid'})
        assert failed.status_code==422 and 'value="Retained"' in failed.text
        assert c.get('/profile/details/export').json()['given_name']=='Ada'
        assert c.post('/profile/details/clear',data={'csrf':'invalid'}).status_code==400
        assert c.post('/profile/details/clear',data={'csrf':token}).status_code==303
        assert c.get('/profile/details/export').json()=={}
    finally:
        with SessionLocal() as db:
            db.get(User,1).profile_data_enc=old;db.commit()


def test_profile_column_migrates_legacy_users_idempotently(monkeypatch):
    engine=create_engine('sqlite:///:memory:')
    database.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(User.__table__.insert().values(email='legacy@example.org',name='Legacy',password_hash='hash'))
        conn.execute(text('ALTER TABLE users DROP COLUMN profile_data_enc'))
    monkeypatch.setattr(database,'engine',engine)
    database._migrate();database._migrate()
    assert 'profile_data_enc' in {c['name'] for c in inspect(engine).get_columns('users')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT name, profile_data_enc FROM users')).one()==('Legacy',None)
