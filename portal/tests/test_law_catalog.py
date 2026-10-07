import json
from urllib.parse import parse_qs, urlsplit
import pytest
from sqlalchemy import select
from app import law_catalog as cat, laws, law_io
from app.db import LawLevel, LawText, SessionLocal
from conftest import client, csrf_of, login, settings


@pytest.fixture
def catalogue():
    settings(module_laws='1', laws_embed='1')
    with SessionLocal() as db:
        root = LawLevel(name='Katalog-VG', kind='vg')
        town = LawLevel(name='Katalog-Ortsgemeinde', kind='og', parent=root)
        state = LawLevel(name='Katalog-Landesrecht', kind='land')
        db.add_all([root,town,state]); db.flush()
        examples = [
            ('cat-main','Hauptsatzung der Katalog-Gemeinde',town,True,'','', ['Verwaltung & Gremien']),
            ('cat-fees','Gebührensatzung für den Friedhof',town,True,'','', ['Friedhof & Bestattung','Gebühren & Steuern']),
            ('cat-state','Katalog-Landesgesetz',state,True,'','', ['Friedhof & Bestattung']),
            ('cat-expired','Alte Katalog-Satzung',town,True,'2000-01-01','', ['Friedhof & Bestattung']),
            ('cat-future','Neue Katalog-Satzung',town,True,'','2099-01-01', ['Friedhof & Bestattung']),
            ('cat-draft','Unveröffentlichter Katalog-Entwurf',town,False,'','', ['Vertrauliches Thema']),
        ]
        for slug,title,level,published,until,since,topics in examples:
            law=LawText(slug=slug,title=title,level=level,published=published,body_md=f'# {title}\n\n### § 5 Erlaubnis\n\nEin Antrag für Gartenarbeiten muss eingereicht werden.\n',valid_until=until,valid_from=since,topics_json=json.dumps(topics))
            db.add(law);db.flush();laws.store(db,law)
        db.commit(); ids={'root':root.id,'town':town.id,'state':state.id}
    yield ids
    with SessionLocal() as db:
        for row in db.scalars(select(LawText).where(LawText.slug.like('cat-%'))): db.delete(row)
        db.flush()
        for key in ['town','root','state']: db.delete(db.get(LawLevel,ids[key]))
        db.commit()


def slugs(result):
    return {law.slug for law in result['items']}


def test_catalogue_scope_combined_filters_and_search(catalogue):
    with SessionLocal() as db:
        local = cat.browse(db, {'ebene':str(catalogue['root'])})
        assert slugs(local)=={'cat-main','cat-fees','cat-future'}
        assert 'Vertrauliches Thema' not in dict(local['topics'])
        filtered=cat.browse(db,{'ebene':str(catalogue['town']),'thema':'Friedhof & Bestattung','q':'Gartenarbeiten'})
        assert slugs(filtered)=={'cat-fees','cat-future'}
        assert 'cat-state' in slugs(cat.browse(db,{'bereich':'weitere','q':'Katalog-Landesgesetz'}))
        assert slugs(cat.browse(db,{'ebene':str(catalogue['town']),'geltung':'archiv'}))=={'cat-expired'}
        assert slugs(cat.browse(db,{'ebene':str(catalogue['town']),'q':'FRIEDHOFS GEBÜHREN'}))=={'cat-fees'}
        assert slugs(cat.browse(db,{'ebene':str(catalogue['town']),'q':'Friedhofsgebühren'}))=={'cat-fees'}
        assert slugs(cat.browse(db,{'ebene':str(catalogue['town']),'q':'GEBÜHRENSATZUNG'}))=={'cat-fees'}
        assert slugs(cat.browse(db,{'ebene':str(catalogue['town']),'q':'§ 5 Hauptsatzung'}))=={'cat-main'}


def test_public_embed_and_suggestions_keep_filters(catalogue):
    pub=client()
    params={'ebene':str(catalogue['town']),'thema':'Friedhof & Bestattung'}
    page=pub.get('/recht',params=params)
    assert page.status_code==200 and 'lex-catalog-grid' in page.text and 'lex-branch' not in page.text
    assert 'Unveröffentlichter Katalog-Entwurf' not in page.text and 'Vertrauliches Thema' not in page.text
    assert 'Alte Katalog-Satzung' not in page.text and 'Gilt ab 01.01.2099' in page.text
    result=pub.get('/recht/suche.json',params={**params,'q':'Gartenarbeiten','catalog':'1'}).json()
    assert {urlsplit(r['url']).path for r in result}=={'/recht/cat-fees','/recht/cat-future'}
    embed=pub.get('/recht-embed',params=params)
    assert embed.status_code==200 and '/recht-embed/cat-fees' in embed.text
    focused=pub.get(f"/recht/ebene/{catalogue['state']}")
    assert focused.status_code==200 and 'Katalog-Landesgesetz' in focused.text
    assert '/recht/cat-fees' not in embed.text
    editor=login('admin@example.org','admin-passwort-123')
    assert 'Unveröffentlichter Katalog-Entwurf' in editor.get('/recht',params={'ebene':str(catalogue['town'])}).text
    assert 'Unveröffentlichter Katalog-Entwurf' not in editor.get('/recht-embed',params={'ebene':str(catalogue['town'])}).text


def test_pagination_and_link_state(catalogue):
    with SessionLocal() as db:
        for i in range(15): db.add(LawText(title=f'Extra {i:02d}',slug=f'cat-extra-{i}',level_id=catalogue['town'],published=True,topics_json='["Eigenes Thema"]'))
        db.commit()
        result=cat.browse(db,{'ebene':str(catalogue['town']),'thema':'Eigenes Thema','seite':'2'})
        assert result['total']==15 and result['page']==2 and len(result['items'])==3
        state=parse_qs(urlsplit(result['url'](seite=1)).query)
        assert state['thema']==['Eigenes Thema'] and state['ebene']==[str(catalogue['town'])]
        assert cat.browse(db,{'ebene':str(catalogue['town']),'thema':'Eigenes Thema','seite':'999'})['page']==2


def test_editor_topics_validation_and_export(catalogue):
    browser=login('admin@example.org','admin-passwort-123')
    with SessionLocal() as db: lid=db.scalar(select(LawText.id).where(LawText.slug=='cat-main'))
    page=browser.get(f'/laws/{lid}/edit')
    data={'csrf':csrf_of(page.text),'title':'Hauptsatzung der Katalog-Gemeinde','slug':'cat-main','level_id':str(catalogue['town']),'published':'1','body_md':'# Hauptsatzung\n\n### § 1 Test\n\nText.','topics_present':'1','topic_bauen':'1','other_topics':'Tourismus, Tourismus'}
    assert browser.post(f'/laws/{lid}/edit',data=data).status_code==303
    with SessionLocal() as db:
        law=db.get(LawText,lid)
        assert cat.topics(law)==['Bauen & Wohnen','Tourismus']
        exported=json.loads(law_io.export(db,[law],versions=False,attachments=False))
        assert exported['laws'][0]['topics']==cat.topics(law)
    with SessionLocal() as db:
        from app.db import User
        user=db.scalar(select(User).where(User.is_admin.is_(True)))
        exported['laws'][0]['topics']=['Familie & Betreuung','Tourismus']
        assert law_io.import_(db,json.dumps(exported).encode(),user,update_existing=True)==(0,1)
        assert cat.topics(db.get(LawText,lid))==['Familie & Betreuung','Tourismus']
        db.rollback()
    data['other_topics']='x'*61
    invalid=browser.post(f'/laws/{lid}/edit',data=data)
    assert invalid.status_code==200 and '60 Zeichen' in invalid.text
    with SessionLocal() as db: assert cat.topics(db.get(LawText,lid))==['Bauen & Wohnen','Tourismus']


def test_legacy_suggestions_and_explicit_no_topics():
    law=LawText(title='Friedhofsgebührensatzung',short_title='',topics_json='')
    assert cat.topics(law)==['Gebühren & Steuern','Friedhof & Bestattung']
    law.topics_json='[]'
    assert cat.topics(law)==[]
    assert cat.clean_topics('Tourismus; tourismus, Bauen & Wohnen')==['Tourismus','Bauen & Wohnen']
    with pytest.raises(ValueError): cat.clean_topics(['x']*13+['y'*61])


def test_existing_database_topic_column_migrates(monkeypatch):
    from sqlalchemy import create_engine, text
    from app import db as database
    engine=create_engine('sqlite:///:memory:')
    from sqlalchemy.orm import Session
    database.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(LawText(title='Bestehende Satzung',slug='migration-satzung'))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE law_texts DROP COLUMN topics_json'))
    monkeypatch.setattr(database,'engine',engine)
    database._migrate()
    with engine.connect() as conn:
        assert conn.execute(text('SELECT title,topics_json FROM law_texts')).one()==('Bestehende Satzung','')
    database._migrate()
    engine.dispose()
