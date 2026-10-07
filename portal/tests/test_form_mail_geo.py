import asyncio
import base64
import csv
import io
import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import select
from pypdf import PdfReader

from app import applications as apps, forms as fm, form_mail, notify, workflow
from app.db import ApplicationRequest, Form, FormMailDownload, FormResponse, Notification, User, utcnow
from app.security import decrypt, hash_password
from conftest import client, login, settings


@pytest.fixture
def case(db):
    settings(module_forms="1", module_applications="1", smtp_host="smtp.example.org", mail_from="portal@example.org")
    admin = db.scalar(select(User).where(User.email == "admin@example.org"))
    schema = fm.clean_schema([{"id": "name", "type": "short", "title": "Name"},
                              {"id": "geo", "type": "geo", "title": "Ort", "geometries": ["point", "line", "polygon"], "max_features": 10},
                              {"id": "upload", "type": "file", "title": "Unterlagen"}])
    form = Form(owner_id=admin.id, title="Antrag mit Umlauten: Straße", kind="application", notify_csv=True,
                notify_json=True, notify_files=True, confirm_csv=True, confirm_json=True, confirm_files=True,
                confirm_mail=True, pdf_uploads=False, schema_json=json.dumps(schema))
    db.add(form); db.flush()
    value = {"features": [{"type": "point", "lat": 49.48, "lon": 7.79, "acc": 5, "src": "gps"},
                           {"type": "line", "coordinates": [[7.7, 49.4], [7.8, 49.5]], "length": 123}],
             "position": {"lat": 49.5, "lon": 7.8, "acc": 10}}
    resp = FormResponse(form_id=form.id, name="Erika", email="erika@example.org", ref_no=f"TEST-{form.id}",
                        status="received", answers_json=json.dumps({"name": "Alt", "geo": value,
                        "upload": [{"file": "one.txt", "name": "Unterlagen.txt", "type": "text/plain"}]}))
    db.add(resp); db.flush(); db.refresh(form)
    target = fm.files_dir(form.id, resp.id); target.mkdir(parents=True, exist_ok=True); (target / "one.txt").write_text("Original")
    db.commit()
    yield form, resp
    db.rollback()
    settings(smtp_host="", mail_from="")


def test_application_intake_formats_and_no_status_attachments(db, case):
    form, resp = case
    assert apps.notify_staff(db, form, resp, "app_new")
    apps.notify_applicant(db, form, resp, "app_received")
    apps.notify_staff(db, form, resp, "app_assigned")
    db.flush()
    mails = db.scalars(select(Notification).where(Notification.body.contains(resp.ref_no))).all()
    intake = next(m for m in mails if m.kind == "app_new")
    atts = json.loads(intake.attachments_json)
    assert {a['mime'] for a in atts} == {'text/csv', 'application/json', 'application/pdf', 'text/plain'}
    assert next(m for m in mails if m.kind == 'app_assigned').attachments_json is None
    assert json.loads(next(m for m in mails if m.kind == 'app_received').attachments_json)


def test_export_name_geo_and_current_request(db, case):
    form, resp = case
    req = ApplicationRequest(response_id=resp.id, title="Nachreichung", state="answered", answered_at=utcnow(),
                             schema_json=json.dumps([{"id": "extra", "type": "short", "title": "Zusatz"}]),
                             reopen_json='["name"]', answers_json='{"name": "Neu", "extra": "Ergänzung"}')
    db.add(req); db.flush(); db.refresh(resp)
    rows = list(csv.DictReader(io.StringIO(fm.to_csv(form, [resp]).lstrip('\ufeff')), delimiter=';'))
    assert rows[0]['Formularname'] == form.title
    assert rows[0]['Ort – Breitengrad'] == '49.48'
    assert rows[0]['Ort – Standort Breitengrad'] == '49.5'
    assert len(json.loads(rows[0]['Ort – GeoJSON'])['features']) == 3
    assert rows[0]['Name'] == 'Neu' and rows[0]['Nachreichung: Zusatz'] == 'Ergänzung'
    data = json.loads(fm.to_json(form, [resp]))
    assert data['formular']['titel'] == data['antworten'][0]['formularname'] == form.title
    assert data['antworten'][0]['werte']['Ort']['objekte'][0]['geometrie']['coordinates'] == [7.79, 49.48]
    assert data['antworten'][0]['werte']['Ort']['standort']['acc'] == 10
    text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(form_mail.response_pdf(form, resp))).pages)
    assert 'Neu' in text and 'Nachgereichte Angaben' in text


def test_applicant_never_gets_other_answers(db, case):
    form, resp = case
    other = FormResponse(form_id=form.id, email='other@example.org', answers_json='{"name":"Geheim"}')
    db.add(other); db.flush(); db.refresh(form)
    form.notify_scope = 'all'
    internal = form_mail.attachments(form, resp)
    external = form_mail.attachments(form, resp, applicant=True)
    assert 'Geheim' in next(a['content'] for a in internal if a['mime'] == 'application/json')
    assert 'Geheim' not in next(a['content'] for a in external if a['mime'] == 'application/json')


def test_encoded_mail_limit_and_expiring_snapshot(db, case, monkeypatch):
    form, resp = case
    form.app_pdf = False; form.confirm_pdf = False
    big = form_mail.binary('groß.txt', b'x' * (8 * 1024 * 1024), 'text/plain')
    monkeypatch.setattr(form_mail, 'attachments', lambda *a, **k: [big])
    assert form_mail.enqueue(db, form, resp, 'erika@example.org', 'Groß', 'Dateien', 'form_confirmation', applicant=True)
    db.flush()
    bundle = db.scalar(select(FormMailDownload).where(FormMailDownload.response_id == resp.id))
    mail = db.scalars(select(Notification).where(Notification.subject == 'Groß')).all()[-1]
    assert mail.attachments_json is None
    assert '10 MB' in mail.body and bundle.expires_at > utcnow() + timedelta(days=6)
    assert 'xxxxxxxx' not in bundle.payload_enc and bundle.token_hash not in mail.body
    link = re.search(r'https://portal.example.org/form-mail/[^\s]+', mail.body).group()
    db.commit()
    c = client()
    r = c.get(link)
    assert r.status_code == 200 and len(r.content) == 8 * 1024 * 1024
    assert r.headers['cache-control'] == 'no-store'
    assert c.get(link[:-1] + '99').status_code == 404
    assert c.get(link.replace('/form-mail/', '/form-mail/x')).status_code == 404
    bundle.expires_at = utcnow() - timedelta(seconds=1); db.commit()
    assert c.get(link).status_code == 404


def test_staff_download_requires_access(db, case, monkeypatch):
    form, resp = case
    monkeypatch.setattr(form_mail, 'MAX_MAIL_BYTES', 4096)
    monkeypatch.setattr(form_mail, 'attachments', lambda *a, **k: [form_mail.binary('large.txt', b'x'*4096, 'text/plain')])
    assert form_mail.enqueue(db, form, resp, 'admin@example.org', 'Intern', 'Dateien', 'app_new')
    db.flush(); bundle = db.scalar(select(FormMailDownload).where(FormMailDownload.response_id == resp.id)); db.commit()
    url = f'/forms/{form.id}/responses/{resp.id}/mail-downloads/{bundle.id}/0'
    assert client().get(url).status_code == 303
    c = login('admin@example.org', 'admin-passwort-123')
    assert c.get(url).status_code == 200
    assert c.get(url.replace(f'/responses/{resp.id}/', '/responses/999999/')).status_code == 404
    outsider = User(name='Unbefugt', email=f'outside-{form.id}@example.org', password_hash=hash_password('test-passwort-123'), permissions='forms')
    db.add(outsider); db.commit()
    assert login(outsider.email, 'test-passwort-123').get(url).status_code == 404


def test_independent_options_and_survey_pdf(db, case):
    form, resp = case
    form.notify_csv = form.notify_json = form.notify_files = form.app_pdf = False
    assert form_mail.attachments(form, resp) == []
    form.kind = 'survey'; form.notify_pdf = True
    assert form_mail.attachments(form, resp)[0]['mime'] == 'application/pdf'
    form.confirm_pdf = False; form.confirm_csv = form.confirm_json = form.confirm_files = False
    assert form_mail.attachments(form, resp, applicant=True) == []


def test_originals_only_from_current_request(db, case):
    form, resp = case
    req = ApplicationRequest(response_id=resp.id, title='Dateien', state='answered', answered_at=utcnow(),
                             schema_json='[]', answers_json='{"upload": [{"file":"two.txt", "name":"Neu.txt"}]}')
    db.add(req); db.flush()
    target = fm.files_dir(form.id, resp.id) / f'req{req.id}'; target.mkdir(); (target/'two.txt').write_text('Nachgereicht')
    atts = form_mail.attachments(form, resp, request=req)
    originals = [a for a in atts if a['mime'] == 'text/plain']
    assert len(originals) == 1 and originals[0]['filename'] == 'Neu.txt'
    assert base64.b64decode(originals[0]['content_b64']) == b'Nachgereicht'


@pytest.mark.parametrize('value', [{'lat':49.4,'lon':7.7}, '49.4, 7.7',
    {'type':'Point','coordinates':[7.7,49.4]},
    {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[7.7,49.4]}}]}])
def test_legacy_coordinates(value):
    assert fm.geo_csv(value)[:2] == [49.4, 7.7]
    assert fm.geo_features(value)[0]['geometry']['coordinates'] == [7.7, 49.4]


def test_single_response_and_large_map_show_geometry(db, case):
    form, resp = case; db.commit()
    c = login('admin@example.org', 'admin-passwort-123')
    url = f'/forms/{form.id}/responses/{resp.id}'
    r = c.get(url)
    assert r.status_code == 200 and 'js-geo-view' in r.text and '7.79' in r.text
    r = c.get(url + '/map/geo')
    assert r.status_code == 200 and 'LineString' in r.text and 'map-response' in r.text
    assert c.get(url + '/map/name').status_code == 404


def test_request_received_mail_contains_current_data_and_new_originals(db, case):
    form, resp = case
    req = workflow.create_request(db, resp, 'Korrektur', 'Bitte ergänzen.',
                                  [{"id": "note", "type": "short", "title": "Ergänzung"}], ['name'], None, 'Sachbearbeitung')
    db.flush()
    class Data(dict):
        def getlist(self, key):
            v = self.get(key)
            return [] if v is None else (v if isinstance(v, list) else [v])
    qid = req.items[0]['id']
    assert asyncio.run(workflow.answer_request(db, resp, req, Data({'q_name':'Aktuell', 'q_'+qid:'Zusatz'}), {})) == {}
    db.flush()
    mails = db.scalars(select(Notification).where(Notification.kind == 'app_request_answered')).all()
    atts = json.loads(mails[-1].attachments_json)
    payload = next(a['content'] for a in atts if a['mime'] == 'application/json')
    assert 'Aktuell' in payload and 'Zusatz' in payload
    assert not any(a['mime'] == 'text/plain' for a in atts)


def test_final_size_rechecked_for_forwarded_mail(db, case, monkeypatch):
    form, resp = case
    monkeypatch.setattr(form_mail, 'MAX_MAIL_BYTES', 8000)
    monkeypatch.setattr(form_mail, 'attachments', lambda *a, **k: [form_mail.binary('original.txt', b'x'*4000, 'text/plain')])
    assert form_mail.enqueue(db, form, resp, 'admin@example.org', 'Vertretung Größe', 'Original', 'form_response')
    db.flush()
    mail = db.scalars(select(Notification).where(Notification.subject == 'Vertretung Größe')).all()[-1]
    assert mail.attachments_json is not None
    # A forwarding note or updated frame makes a previously small message exceed the limit.
    mail.body += 'Vertretung\n' * 100
    db.commit()
    sent = []
    def deliver(cfg, to, subject, body, attachments=None, reply_to=None):
        if subject == 'Vertretung Größe':
            sent.append(notify._build(cfg, to, subject, body, attachments, reply_to))
    monkeypatch.setattr(notify, 'deliver', deliver)
    notify.process_queue()
    assert sent and not list(sent[0].iter_attachments())
    from email.policy import SMTP
    assert len(sent[0].as_bytes(policy=SMTP)) <= 8000


def test_setting_save_independent_pdf_options(db, case):
    form, resp = case; db.commit()
    c = login('admin@example.org', 'admin-passwort-123')
    page = c.get(f'/forms/{form.id}/settings')
    from conftest import csrf_of
    assert page.status_code == 200
    r = c.post(f'/forms/{form.id}/settings', data={'csrf':csrf_of(page.text), 'notify':'1',
        'notify_csv':'1','notify_json':'1','notify_files':'1','confirm_pdf':'1','notify_scope':'all'})
    assert r.status_code == 303
    db.refresh(form)
    assert not form.app_pdf and form.confirm_pdf
    assert form_mail.attachments(form, resp, applicant=True)[0]['mime'] == 'application/pdf'
    assert not any(a['mime'] == 'application/pdf' for a in form_mail.attachments(form, resp))


def test_migration_preserves_previous_confirmation_defaults(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app import db as model
    engine = create_engine('sqlite:///' + str(tmp_path/'old.db'))
    model.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Form(title='Umfrage', kind='survey'),
                    Form(title='Antrag ohne PDF', kind='application', app_pdf=False),
                    Form(title='Antrag mit PDF', kind='application', app_pdf=True)])
        db.commit()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE forms DROP COLUMN confirm_pdf'))
    monkeypatch.setattr(model, 'engine', engine)
    model._migrate()
    with engine.begin() as conn:
        assert [r[0] for r in conn.execute(text('SELECT confirm_pdf FROM forms ORDER BY id'))] == [0, 0, 1]
        conn.execute(text('UPDATE forms SET confirm_pdf = 1 WHERE id = 1'))
    model._migrate()
    with engine.connect() as conn:
        assert conn.execute(text('SELECT confirm_pdf FROM forms WHERE id = 1')).scalar() == 1
    engine.dispose()
