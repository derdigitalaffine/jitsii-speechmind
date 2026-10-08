import json
from urllib.parse import urlsplit,parse_qs
from sqlalchemy import select
from app import law_catalog as cat,laws as lx
from app.db import LawText,LawVersion,SessionLocal
from conftest import client,login,csrf_of
from test_law_catalog import catalogue


def test_tree_own_counts_and_descendants_switch(catalogue):
    with SessionLocal() as db:
        c=cat.browse(db,{'ebene':str(catalogue['root']),'bereich':'alle'})
        root=next(n for n in c['tree'] if n['level'].id==catalogue['root'])
        assert root['count']==0 and root['children'][0]['count']==2
        assert c['total']==2
        direct=cat.browse(db,{'ebene':str(catalogue['root']),'bereich':'alle','unter':'0'})
        assert direct['total']==0 and direct['level_counts'][catalogue['town']]==2
        assert {l.slug for l in cat.browse(db,{'ebene':str(catalogue['town']),'geltung':'zukuenftig'})['items']}=={'cat-future'}
        assert c['filters']['ansicht']=='tabelle'
        assert cat.browse(db,{'ansicht':'invalid'})['filters']['ansicht']=='tabelle'
    page=client().get('/recht',params={'ebene':catalogue['root']})
    assert page.status_code==200 and 'law-org-tree' in page.text and 'law-catalog-table' in page.text
    assert 'data-view="tabelle"' in page.text and 'data-law-view="bloecke"' in page.text
    embed=client().get('/recht-embed',params={'ebene':catalogue['town'],'q':'Gartenarbeiten'})
    assert embed.status_code==200 and '/recht-embed/cat-main' in embed.text


def edit_data(page,**extra):
    return {'csrf':csrf_of(page.text),'title':'Hauptsatzung der Katalog-Gemeinde','slug':'cat-main','published':'1','doc_type':'satzung','body_md':'# Hauptsatzung\n\n### § 5 Test\n\nText neu.','topics_present':'1',**extra}


def test_top_bottom_save_and_close_validation_and_safe_return(catalogue):
    c=login('admin@example.org','admin-passwort-123')
    with SessionLocal() as db: lid=db.scalar(select(LawText.id).where(LawText.slug=='cat-main'))
    page=c.get(f'/laws/{lid}/edit?return_to=%2Flaws%3Flevel%3D{catalogue["town"]}')
    assert page.text.count('>Speichern und schließen</button>')==2 and 'law-topic-grid' in page.text
    r=c.post(f'/laws/{lid}/edit',data=edit_data(page,save_action='close',return_to=f'/laws?level={catalogue["town"]}'))
    assert r.status_code==303 and r.headers['location']==f'/laws?level={catalogue["town"]}'
    r=c.post(f'/laws/{lid}/edit',data=edit_data(page,save_action='stay'))
    assert r.status_code==303 and urlsplit(r.headers['location']).path==f'/laws/{lid}/edit'
    assert parse_qs(urlsplit(r.headers['location']).query)['saved']==['1']
    r=c.post(f'/laws/{lid}/edit',data=edit_data(page,save_action='close',return_to='https://evil.example.org'))
    assert r.headers['location']=='/laws'
    r=c.post(f'/laws/{lid}/edit',data=edit_data(page,save_action='close',other_topics='x'*61))
    assert r.status_code==200 and 'höchstens 60' in r.text and 'law-form' in r.text
    plan=c.get(f'/laws/{lid}/plan');assert plan.text.count('>Speichern und schließen</button>')==2
    r=c.post(f'/laws/{lid}/plan',data={'csrf':csrf_of(plan.text),'valid_from':'2099-01-01','body_md':'# Zukunft\nText','save_action':'close','return_to':'/laws'})
    assert r.status_code==303 and r.headers['location']=='/laws'


def test_only_explicit_versions_available_to_editors_and_public(catalogue):
    with SessionLocal() as db:
        law=db.scalar(select(LawText).where(LawText.slug=='cat-main'))
        old=LawVersion(law_id=law.id,body_md='# Alt\n\n### § 5 Test\n\nAlter Inhalt',public=True,valid_until='2020-01-01')
        backup=LawVersion(law_id=law.id,body_md='# Sicherung',public=False)
        db.add_all([old,backup]);db.commit();oid,bid,lid=old.id,backup.id,law.id
    editor=login('admin@example.org','admin-passwort-123')
    for c in [editor,client()]:
        page=c.get('/recht/cat-main/vergleich');assert page.status_code==200
        assert f'<option value="{oid}"' in page.text and f'<option value="{bid}"' not in page.text
        assert 'Bisheriger Stand' in page.text and 'Neuer Stand' in page.text
        assert c.get('/recht/cat-main/vergleich',params={'a':bid}).status_code==404
    assert editor.get(f'/laws/{lid}/versions/{bid}').status_code==200
