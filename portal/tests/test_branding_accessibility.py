"""Regression checks for the actual palette, protected save and rendered controls."""
import json
from html.parser import HTMLParser
import pytest
from app import branding, forms
from app.db import Form, FormResponse, SessionLocal, get_settings, set_setting, Setting
from conftest import client, csrf_of, login

@pytest.fixture(autouse=True)
def restore_branding():
    with SessionLocal() as db:
        old = {k:v for k,v in get_settings(db).items() if k.startswith('ui_')}
    yield
    with SessionLocal() as db:
        for row in db.query(Setting).all():
            if row.key.startswith('ui_'): db.delete(row)
        for k,v in old.items(): set_setting(db,k,v)
        db.commit()
    branding.invalidate()

@pytest.mark.parametrize('color',['#ffffff','#000000','#1f5fa8','#777777','#ffcc00','#00ff00','#ff00ff'])
def test_actual_palette_contrast_and_css(color):
    for navbar in branding.NAVBARS:
        report=branding.contrast_report(color,navbar)
        for row in report['rows']:
            assert row['ratio']==round(branding.contrast(row['fg'],row['bg']),2)
            if 'Fokus' in row['label'] or 'Button' in row['label'] or 'Markierung' in row['label']:
                assert row['ok'], row
        if report['suggestion']:
            assert not branding.contrast_report(report['suggestion'],navbar)['warnings']
        css=branding.theme_css(dict(primary=color,navbar=navbar,radius='0'))
        assert f'background-color: {color} !important' in css
        assert '--app-nav-focus:' in css and '3px solid var(--app-focus)' in css
        assert branding.on_color(color).replace('#','%23') in css
    assert branding.contrast('#000000','#ffffff')==21


def test_warning_cannot_be_bypassed_or_reused_and_preserves_fields():
    c=login('admin@example.org','admin-passwort-123')
    csrf=csrf_of(c.get('/admin/design').text)
    values=dict(csrf=csrf,ui_custom='1',ui_primary='#ffffff',ui_navbar='primary',ui_brand_name='Noch nicht gespeichert',ui_product='Probe',ui_show_name='1',ui_gallery_h='420',remove_logo='1')
    response=c.post('/admin/design',data=values)
    assert response.status_code==200 and 'Kontrastprobleme' in response.text
    assert 'value="Noch nicht gespeichert"' in response.text and 'value="420"' in response.text
    with SessionLocal() as db: assert get_settings(db).get('ui_brand_name')!='Noch nicht gespeichert'
    values.update(contrast_ack='1',contrast_key='#ffffff|dark')
    assert c.post('/admin/design',data=values).status_code==200
    values['contrast_key']='#ffffff|primary'
    assert c.post('/admin/design',data=values).status_code==303
    with SessionLocal() as db: assert get_settings(db)['ui_brand_name']=='Noch nicht gespeichert'
    assert c.get('/admin/design/contrast?primary=%3Cscript%3E').status_code==422
    assert client().get('/admin/design/contrast').status_code in (303,401,403)


def test_selected_upload_is_not_consumed_on_contrast_warning():
    c=login('admin@example.org','admin-passwort-123');csrf=csrf_of(c.get('/admin/design').text)
    r=c.post('/admin/design',data=dict(csrf=csrf,ui_custom='1',ui_primary='#ffffff'),files={'logo':('bad.png',b'not-image','image/png')})
    assert r.status_code==200 and 'Dateiauswahl nicht erhalten' in r.text

class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.items=[];self.feed(html)
    def handle_starttag(self,tag,attrs): self.items.append((tag,dict(attrs)))


def test_rendered_login_dashboard_form_and_application_focus_and_names():
    c=login('admin@example.org','admin-passwort-123')
    with SessionLocal() as db:
        f=Form(title='A11y Beispiel',owner_id=1,public_token='branding-a11y-form',schema_json=json.dumps(forms.clean_schema([dict(id='name',type='short',label='Ihr Name',required=True),dict(id='day',type='date',label='Datum')])))
        db.add(f);db.commit();fid=f.id
        f.kind='application'; answer=FormResponse(form_id=fid,ref_no='A11Y-1',status='new',user_id=1);db.add(answer);db.commit();rid=answer.id
    try:
        for path,reader in [('/login',client()),('/',c),('/f/branding-a11y-form',client()),(f'/forms/{fid}/applications/{rid}',c)]:
            r=reader.get(path); assert r.status_code==200,(path,r.status_code)
            m=Markup(r.text); ids={a.get('id') for _,a in m.items}
            assert 'inhalt' in ids
            assert '3px solid var(--app-focus)' in r.text
            assert any(t=='nav' and a.get('aria-label') for t,a in m.items) or path=='/login'
            labels={a.get('for') for t,a in m.items if t=='label'}
            for t,a in m.items:
                if t in ('input','select','textarea') and a.get('type') not in ('hidden','submit','button'):
                    assert a.get('id') in labels or a.get('aria-label') or a.get('aria-labelledby'),(path,t,a)
        loginpage=client().get('/login').text
        assert '<main id="inhalt"' in loginpage and 'class="skip-link"' in loginpage
        base=c.get('/').text
        assert 'aria-label="Menü öffnen"' in base and 'id="nav-rail"' in base
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Form,fid));db.commit()
