"""Real component rendering, semantic contrast and list integration."""
import re
from pathlib import Path
from jinja2 import Environment
from app.db import SessionLocal, Resource, User
from app import resources as rs
from conftest import login, settings

ROOT=Path(__file__).resolve().parents[1]/'app'

def macros():
    env=Environment(autoescape=True)
    env.filters.update(local=str,filesize=str)
    return env.from_string((ROOT/'templates/_macros.html').read_text()).module

def luminance(hexcolor):
    rgb=[int(hexcolor[i:i+2],16)/255 for i in (1,3,5)]
    c=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(a*b for a,b in zip(c,(.2126,.7152,.0722)))

def test_semantic_status_contrast_light_and_dark():
    css=(ROOT/'static/design-system.css').read_text()
    for block in re.findall(r'\{([^}]*--ds-neutral-bg:[^}]*)\}',css):
        colors=dict(re.findall(r'--ds-([a-z]+-(?:bg|fg)):(#[0-9a-f]{6})',block))
        assert len(colors)==10
        for tone in ('neutral','info','success','warning','error'):
            a,b=sorted((luminance(colors[tone+'-bg']),luminance(colors[tone+'-fg'])))
            assert (b+.05)/(a+.05)>=4.5,tone

def test_actual_components_escape_labels_and_keep_native_controls():
    m=macros()
    assert '&lt;script&gt;' in str(m.status_chip('<script>','error'))
    assert 'ds-status-neutral' in str(m.status_chip('X','invalid'))
    assert '<details' in str(m.action_menu(caller=lambda:'<a href="/x">Ansehen</a>'))
    assert '<summary' in str(m.filter_bar(caller=lambda:'Suche'))
    assert '<dt>Name</dt><dd>Anna</dd>' in str(m.detail_meta([('Name','Anna')]))
    assert 'aria-hidden="true"' in str(m.status_chip('Offen','warning'))
    header=str(m.page_header('Dokumente','', '/new','Neu'))
    assert 'ds-primary' in header and header.count('btn-primary')==1

def test_resources_search_both_views_and_preserve_query():
    settings(module_resources='1')
    with SessionLocal() as db:
        for name,location in [('DS Treffer Alpha','Otterberg'),('DS Fremd Beta','Otterbach')]:
            r=Resource(name=name,slug=rs.unique_slug(db,name),location=location,category='DS',owner_id=1,public=False)
            db.add(r)
        db.commit()
    c=login('admin@example.org','admin-passwort-123')
    for view in ('karten','tabelle'):
        page=c.get('/resources',params={'q':'Otterberg','ansicht':view})
        assert page.status_code==200
        assert 'DS Treffer Alpha' in page.text and 'DS Fremd Beta' not in page.text
        assert 'q=Otterberg' in page.text
        if view=='tabelle':
            assert 'ds-mobile-table' in page.text
            for label in ('Ressource','Art','Status','Anfragen','Nächste Buchung','Aktionen'):
                assert f'data-label="{label}"' in page.text
    empty=c.get('/resources?q=NoMatchingResourceEver')
    assert empty.status_code==200 and 'Suche zurücksetzen' in empty.text

def test_resources_search_cannot_reveal_unshared_objects(monkeypatch):
    # Route receives its real ACL-filtered set before applying the new search.
    from app import routes_resources
    settings(module_resources='1')
    with SessionLocal() as db:
        user=User(email='ds-limited@example.org',name='DS Nutzer',password_hash='unused',permissions='resources')
        db.add(user);db.flush()
        visible=Resource(name='DS PublicOwned',slug=rs.unique_slug(db,'DS PublicOwned'),owner_id=user.id,public=False)
        hidden=Resource(name='DS PrivateSecret',slug=rs.unique_slug(db,'DS PrivateSecret'),owner_id=1,public=False)
        db.add_all([visible,hidden]);db.commit();uid=user.id
    original=routes_resources.rs.visible
    def restricted(db,admin):
        return original(db,db.get(User,uid))
    monkeypatch.setattr(routes_resources.rs,'visible',restricted)
    c=login('admin@example.org','admin-passwort-123')
    for view in ('karten','tabelle'):
        page=c.get('/resources',params={'q':'PrivateSecret','ansicht':view})
        assert page.status_code==200 and 'DS PrivateSecret' not in page.text
        assert '0 Ressourcen' in page.text

def test_reference_has_all_states_and_actual_macros():
    html=(ROOT.parents[1]/'docs/design-system-reference.html').read_text()
    for item in ('data-bs-theme="light"','data-bs-theme="dark"','ds-empty','role="status"','role="alert"','disabled','ds-mobile-table','<dialog'):
        assert item in html


def test_resource_header_preserves_outer_actions_through_nested_macro():
    from jinja2 import FileSystemLoader
    env=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=True)
    env.filters.update(local=str,filesize=str)
    class Person:
        def can(self,permission):return True
    template=env.from_string("""{% import '_res_macros.html' as rm with context %}{% call rm.head('home', [], 'Ressourcen') %}<button data-qr-url="/r">QR-Code</button><a href="/resources/new">Neue Ressource</a><a href="/resources/caretakers/new">Hausmeister:in anlegen</a>{% endcall %}""")
    html=template.render(user=Person())
    assert 'data-qr-url="/r"' in html
    assert '<a href="/resources/new">Neue Ressource</a>' in html
    assert 'Hausmeister:in anlegen' in html
    assert html.count('ds-page-header')==1
