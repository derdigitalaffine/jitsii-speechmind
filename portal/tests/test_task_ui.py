"""Action hierarchy and navigation use the same components as the rest of TAKT."""
from datetime import datetime
from html.parser import HTMLParser
from app.main import templates
from test_native_tasks import task_people, client_for, make  # noqa: F401


class Actions(HTMLParser):
    def __init__(self,html):
        super().__init__();self.primary=[];self.groups=[]
        if '<main' in html:html=html.split('<main',1)[1].split('</main>',1)[0]
        self.feed(html)
    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        if tag in {'a','button'} and 'btn-primary' in attrs.get('class','').split():self.primary.append(attrs)
        if attrs.get('role')=='group':self.groups.append(attrs.get('aria-label'))


def test_workplace_keeps_a_single_primary_action_and_quick_capture(db,task_people):
    make(db,task_people)
    c,token=client_for(task_people[1])
    html=c.get('/tasks?view=list').text
    actions=Actions(html)
    assert len(actions.primary)==1 and actions.primary[0]['href'].startswith('/aufgaben/neu?')
    assert 'id="capture-text"' in html and 'Aufgabe erfassen' in html
    assert 'nav nav-tabs task-perspectives' in html
    assert 'Ansicht' in actions.groups and 'btn-group btn-group-sm task-view-switch' in html
    preview=c.post('/aufgaben/vorschau',data={'csrf':token,'capture':'Ein neuer Schritt morgen'})
    assert preview.status_code==200 and 'Kurz prüfen, dann loslegen' in preview.text
    assert len(Actions(preview.text).primary)==1
    assert 'href' not in Actions(preview.text).primary[0]


def test_calendar_controls_expose_grouped_navigation_and_active_period(db,task_people):
    c,_=client_for(task_people[0])
    html=c.get('/tasks?view=calendar&period=week&date=2026-12-01').text
    assert {'Ansicht','Zeitraum wechseln','Kalenderdarstellung'}<=set(Actions(html).groups)
    assert 'aria-label="Vorheriger Zeitraum"' in html and 'aria-label="Nächster Zeitraum"' in html
    assert len(Actions(html).primary)==1


def test_quieter_task_rows_do_not_restyle_existing_dashboard_actions():
    macro=templates.env.get_template('_work_list.html').module.work_list
    item=dict(source_label='Aufgaben',scope='personal',icon='fa-list-check',title='Test',href='/aufgaben/1',
              detail='Offen',due=None,late=False,action='Öffnen')
    assert len(Actions(str(macro([item],datetime(2026,1,1),'csrf'))).primary)==1
    quiet=str(macro([item],datetime(2026,1,1),'csrf',quiet=True))
    assert not Actions(quiet).primary and 'btn-outline-secondary' in quiet
