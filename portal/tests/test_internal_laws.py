import json
import secrets
import pytest
from sqlalchemy import select
from app import laws, law_catalog, law_io, circulations as cl
from app.db import LawText, LawVersion, SessionLocal, User, Circulation
from conftest import client, login, settings


@pytest.fixture
def instruction(db):
    settings(module_laws='1',laws_embed='1')
    slug='internal-'+secrets.token_hex(4)
    law=LawText(title='Vertrauliche Dienstanweisung',slug=slug,short_title='INTERNTEST',internal=True,published=True,
                doc_type='dienstanweisung',body_md='# Dienstanweisung\n\n### § 1 Geheimwort\n\nInternes Sonderverfahren.\n')
    db.add(law);db.flush();laws.store(db,law);laws.snapshot(db,law,public=True)
    attachment=law_io.add_attachment(law,'Interner Plan.pdf',b'%PDF-1.4\n%%EOF')
    db.commit()
    yield law,attachment
    db.delete(law);db.commit();laws.invalidate_refs()


def test_internal_text_is_not_public_through_any_reader(db,instruction):
    law,attachment=instruction;public=client()
    version=law.versions[0]
    for base in ['/recht','/recht-embed']:
        for suffix in ['', '.md','/paragraf-1',f'/fassung/{version.id}',f'/anlage/{attachment.id}']:
            assert public.get(base+'/'+law.slug+suffix).status_code==404
        assert law.title not in public.get(base,params={'sicht':'all','bereich':'alle'}).text
        assert law.title not in public.get(base+'/suche',params={'q':'Vertrauliche','alle':'1'}).text
        assert law.title not in public.get(base+'/suche.json',params={'q':'Vertrauliche'}).text
        assert law.title not in public.get(base+'/suche.json',params={'q':'Vertrauliche','catalog':'1','sicht':'all'}).text
    assert law.id not in {x.id for x in law_catalog.browse(db,{'sicht':'all','bereich':'alle'})['items']}
    assert 'interntest' not in laws.ref_map(db)
    assert 'sonderverfahren' not in laws._vocabulary(db)


def test_authenticated_readers_and_embed_separation(db,instruction):
    law,attachment=instruction
    from app.security import hash_password
    user=User(name='Interner Leser',email=law.slug+'@example.org',password_hash=hash_password('internal-test-123'),permissions='')
    db.add(user);db.commit()
    try:
        signed=login(user.email,'internal-test-123')
        assert signed.get('/recht/'+law.slug).status_code==200
        assert signed.get('/recht/'+law.slug+'.md').status_code==200
        assert signed.get(f'/recht/{law.slug}/anlage/{attachment.id}').status_code==200
        assert law.title in signed.get('/recht',params={'sicht':'internal','bereich':'alle'}).text
        assert law.title not in signed.get('/recht-embed',params={'sicht':'internal','bereich':'alle'}).text
        assert signed.get('/recht-embed/'+law.slug).status_code==404
    finally:db.delete(user);db.commit()


def test_internal_history_and_attachments_stay_protected_after_scope_change(db,instruction):
    law,attachment=instruction;old=law.versions[0]
    assert old.internal and attachment.internal
    law.internal=False;law.doc_type='richtlinie';law.body_md='# Öffentlich\n\n### § 1 Öffentlich\nNeue Angaben.';laws.store(db,law);db.commit()
    public=client()
    assert public.get('/recht/'+law.slug).status_code==200
    assert public.get(f'/recht/{law.slug}/fassung/{old.id}').status_code==404
    assert public.get(f'/recht/{law.slug}/anlage/{attachment.id}').status_code==404
    assert attachment.name not in public.get('/recht/'+law.slug).text


def test_internal_law_cannot_be_sent_to_guests(db,instruction):
    law,attachment=instruction
    from fastapi import HTTPException
    admin=db.scalar(select(User).where(User.is_admin.is_(True)))
    c=cl.default();c.update(title='Intern',body='Text',items=[dict(key='law',kind='law',id=law.id,title=law.title)])
    c['audience']['guests']=[dict(name='Gast',email='guest@example.org')]
    row=Circulation(owner_id=admin.id,draft_json=cl.dumps(c));db.add(row);db.flush()
    try:
        with pytest.raises(HTTPException) as err:cl.publish(db,row,admin)
        assert err.value.status_code==422
    finally:db.rollback()


def test_internal_scope_is_exported_and_preserved(db,instruction):
    law,attachment=instruction;payload=json.loads(law_io.export(db,[law]))
    assert payload['laws'][0]['internal'] is True
    assert payload['laws'][0]['versions'][0]['internal'] is True
    assert payload['laws'][0]['attachments'][0]['internal'] is True


def test_legacy_database_migration_preserves_public_laws(monkeypatch):
    import app.db as database
    from sqlalchemy import create_engine, text
    engine=create_engine('sqlite://')
    database.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(database.LawText.__table__.insert().values(title='Altbestand',slug='altbestand',internal=False,published=True))
        for table in ['law_texts','law_versions','law_attachments']:
            conn.execute(text(f'ALTER TABLE {table} DROP COLUMN internal'))
    monkeypatch.setattr(database,'engine',engine)
    database._migrate();database._migrate()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title,internal,published FROM law_texts WHERE slug='altbestand'")).one()==('Altbestand',0,1)
    engine.dispose()
