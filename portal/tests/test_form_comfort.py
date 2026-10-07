import json
from types import SimpleNamespace
from app import forms, form_fields
from app.db import Form, SessionLocal
from conftest import client, login


def test_profile_defaults_do_not_override_answers_or_anonymous_values():
    items=forms.clean_schema([{'id':'name','type':'short','profile_value':'name'},{'id':'mail','type':'long','profile_value':'email'},{'id':'secret','type':'short','profile_value':'password'}])
    user=SimpleNamespace(name='Ada',email='ada@example.org')
    assert 'profile_value' not in items[2]
    assert form_fields.profile_values(items,{},user)=={'name':'Ada','mail':'ada@example.org'}
    assert form_fields.profile_values(items,{'name':''},user)['name']==''
    assert form_fields.profile_values(items,{},None)=={}


def test_profile_defaults_in_signed_in_form_only():
    with SessionLocal() as db:
        f=Form(title='Profilvorbelegung',owner_id=1,public_token='comfort-profile',schema_json=json.dumps(forms.clean_schema([{'id':'mail','type':'short','subtype':'email','profile_value':'email'}])))
        db.add(f);db.commit()
    assert 'value="admin@example.org"' not in client().get('/f/comfort-profile').text
    assert 'value="admin@example.org"' in login('admin@example.org','admin-passwort-123').get('/f/comfort-profile').text
