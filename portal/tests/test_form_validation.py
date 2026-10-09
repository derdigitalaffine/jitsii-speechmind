from datetime import date, datetime
from types import SimpleNamespace
from starlette.datastructures import FormData
from app import forms, form_validation as rules


def field(kind='date', **kwargs):
    return forms.clean_schema([dict(id='a', type=kind, title='Angabe', **kwargs)])[0]


def check(item, value, base=None, extra=None):
    return forms.validate([item], FormData({'q_a': value, **(extra or {})}), {}, base_answers=base)


def test_date_rules_fixed_relative_today_and_timezone(monkeypatch):
    import app.db as db
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(db, 'LOCAL_TZ', ZoneInfo('Europe/Berlin'))
    monkeypatch.setattr(rules, 'utcnow', lambda: datetime(2026, 10, 8, 22, 30))
    item = field(date_rule='past', include_today=False, relative_min=-2)
    assert rules.constraints(item) == {'today': '2026-10-09', 'min': '2026-10-07', 'max': '2026-10-08'}
    assert check(item, '2026-10-08')[1] == {}
    assert check(item, '2026-10-09')[1]['a']
    assert check(item, '2026-10-06')[1]['a']
    assert check(field(min='2024-02-29'), '2024-02-28')[1]['a']
    assert check(field(), '2023-02-29')[1]['a']
    assert check(field(), '20260510')[1]['a']


def test_date_relationship_uses_base_answers_and_gap_limits():
    item = field(date_reference='start', date_gap_min=2, date_gap_max=5)
    # Full-schema cleaning permits eligible references; normalizer drops dangling ones.
    item['date_reference'] = 'start'
    base={'start':'2026-05-10'}
    assert not check(item,'2026-05-12',base)[1]
    assert check(item,'2026-05-11',base)[1]['a']
    assert check(item,'2026-05-16',base)[1]['a']
    assert check(item,'2026-05-11',{'start':'2026-05-10','a':'2026-05-11'})[1] == {}
    assert check(item,'2026-05-12',{'start':'2026-05-10','a':'2026-05-11'})[0]['a'] == '2026-05-12'


def test_age_boundaries_and_leap_conversion():
    item=field(min_age=18,max_age=65)
    bounds=rules.constraints(item,date(2026,10,9))
    assert bounds['max'] == '2008-10-09'
    assert bounds['min'] == '1960-10-10'
    assert rules.age_date(date(2024,2,29),1) == date(2023,2,28)


def test_cleaning_removes_invalid_and_cyclic_references():
    items=forms.clean_schema([dict(id='a',type='date',date_reference='b'),dict(id='b',type='date',date_reference='a'),dict(id='c',type='date',date_reference='missing',min='nonsense',min_age=-1)])
    assert 'date_reference' not in items[0]
    assert 'date_reference' not in items[2]
    assert items[2]['min'] == ''
    assert 'min_age' not in items[2]


def test_text_number_step_url_and_custom_message():
    assert check(field('short',min_length=3), 'ab')[1]['a']
    assert check(field('short',max_length=3), 'abcd')[1]['a']
    item=field('short',subtype='number',min=1,step=.5)
    assert not check(item,'1.5')[1]
    assert check(item,'1.2')[1]['a']
    for bad in ('NaN','Infinity','-Infinity'):
        assert check(item,bad)[1]['a']
    assert not check(field('short',subtype='url'),'https://portal.bachberg.de/path')[1]
    assert check(field('short',subtype='url'),'javascript:alert(1)')[1]['a']
    assert check(field('long',min_length=4,validation_message='Mehr Text bitte'), 'ab')[1]['a'] == 'Mehr Text bitte'
    assert check(field('short',max_length=1),'previous',{'a':'previous'})[1] == {}


def test_upload_limits_and_existing_attachments():
    item=field('file',required=True,file_types=['pdf'],max_size_mb=1,max_files=1)
    assert item['file_types'] == ['pdf']
    uploads={'q_a':[SimpleNamespace(filename='bad.exe',size=1)]}
    assert forms.validate([item],FormData(),uploads)[1]['a']
    uploads={'q_a':[SimpleNamespace(filename='a.pdf',size=2*1024*1024)]}
    assert forms.validate([item],FormData(),uploads)[1]['a']
    old=[{'filename':'old.pdf','size':100}]
    assert forms.validate([item],FormData(),{},base_answers={'a':old})[0]['a'] == old


def test_changed_reference_revalidates_unchanged_dependent_date():
    items = forms.clean_schema([
        dict(id='start', type='date'),
        dict(id='end', type='date', date_reference='start', date_gap_min=2, date_gap_max=5),
    ])
    base = {'start': '2026-05-10', 'end': '2026-05-12'}
    def submit(start, end):
        return forms.validate(items, FormData({'q_start': start, 'q_end': end}), {}, base_answers=base)
    assert not submit('2026-05-10', '2026-05-12')[1]
    assert submit('2026-05-11', '2026-05-12')[1]['end']
    assert not submit('2026-05-09', '2026-05-12')[1]
    assert submit('2026-05-06', '2026-05-12')[1]['end']
    # A new unrelated fixed bound should not invalidate an unchanged historical
    # answer just because the start date was adjusted within the allowed gap.
    items[1]['max'] = '2026-05-11'
    assert not submit('2026-05-09', '2026-05-12')[1]


def test_datetime_requires_canonical_local_datetime():
    for item in (field('datetime'), field('date', with_time=True)):
        assert not check(item, '2026-05-10T12:30')[1]
        for value in ('2026-05-10', '20260510T1230', '2026-05-10T12:30+02:00', '2026-02-30T12:30'):
            assert check(item, value)[1]['a']


def test_schema_rejects_contradictory_ranges():
    for item in (field(min='2026-05-20', max='2026-05-10'),
                 field(relative_min=10, relative_max=0),
                 field(min_age=50, max_age=20),
                 field('short', min_length=8, max_length=3),
                 field('short', subtype='number', min=10, max=2)):
        assert rules.schema_errors([item])['a']
    item = field(date_gap_min=5, date_gap_max=2)
    assert rules.schema_errors([item])['a']
    assert not rules.schema_errors([field('short', subtype='number', min=0, max=0)])


def test_invalid_rules_are_not_saved():
    import json
    from app.db import Form, SessionLocal
    from conftest import login, csrf_of
    with SessionLocal() as db:
        form = Form(title='Unchanged title', owner_id=1, schema_json='[]')
        db.add(form); db.commit(); form_id = form.id
    c = login('admin@example.org', 'admin-passwort-123')
    response = c.post(f'/forms/{form_id}/schema', data={
        'csrf': csrf_of(c.get(f'/forms/{form_id}').text), 'title': 'Changed title',
        'items_json': json.dumps([dict(id='a', type='date', title='Zeitraum', min='2026-05-20', max='2026-05-10')]),
    })
    assert response.status_code == 400
    assert 'Zeitraum' in response.text
    with SessionLocal() as db:
        form = db.get(Form, form_id)
        assert form.title == 'Unchanged title'
        assert form.schema_json == '[]'


def test_extreme_reference_date_and_malformed_url_do_not_bypass_rules():
    item = field(date_gap_min=2)
    item['date_reference'] = 'start'
    assert check(item, '9999-12-31', {'start': '9999-12-31'})[1]['a']
    for value in ('https://:password@example.org', 'https://example.org:99999/path', 'https://example.org/a b'):
        assert check(field('short', subtype='url'), value)[1]['a']


def test_block_rules_guard_and_references_follow_renamed_ids():
    import json
    from app.db import FormBlock, SessionLocal
    from conftest import login, csrf_of, settings
    settings(module_forms='1')
    with SessionLocal() as db:
        block = FormBlock(name='Date rules block', schema_json='[]')
        db.add(block); db.commit(); block_id = block.id
    c = login('admin@example.org', 'admin-passwort-123')
    token = csrf_of(c.get(f'/forms/blocks/{block_id}').text)
    response = c.post(f'/forms/blocks/{block_id}/schema', data={'csrf': token, 'title': 'Changed',
        'items_json': json.dumps([dict(id='a', type='date', title='Start', min='2026-05-20', max='2026-05-10')])})
    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.get(FormBlock, block_id).name == 'Date rules block'
    response = c.post(f'/forms/blocks/{block_id}/schema', data={'csrf': token, 'title': 'Date rules block',
        'items_json': json.dumps([dict(id='randomstart', type='date', title='Beginn'),
                                 dict(id='randomend', type='date', title='Ende', date_reference='randomstart')])})
    assert response.status_code == 303
    with SessionLocal() as db:
        saved = json.loads(db.get(FormBlock, block_id).schema_json)
        assert saved[0]['id'] == 'beginn'
        assert saved[1]['date_reference'] == 'beginn'


def test_requests_include_transitive_date_dependencies_without_truncating():
    import json
    from app import workflow
    from app.db import Form, FormResponse, ApplicationRequest, SessionLocal
    items = forms.clean_schema([dict(id=f'd{n}', type='date', title=f'Datum {n}',
                                    **({'date_reference': f'd{n-1}'} if n else {})) for n in range(42)])
    with SessionLocal() as db:
        form = Form(title='Date dependency request', owner_id=1, kind='application', schema_json=json.dumps(items))
        db.add(form); db.flush()
        resp = FormResponse(form_id=form.id, status='in_progress', answers_json=json.dumps({i['id']: '2026-05-10' for i in items}))
        db.add(resp); db.flush()
        req = workflow.create_request(db, resp, 'Dates', '', [], ['d0'], None, 'Test', set_query=False)
        assert len(req.reopen) == 42
        assert req.reopen[-1] == 'd41'
        assert 'Datum 41' in workflow.requested_text(resp, req)
        legacy = ApplicationRequest(schema_json='[]', reopen_json='["d0"]')
        assert len(workflow.reopen_items(resp, legacy)) == 42
        questions = workflow.reopen_items(resp, req)
        data = FormData({f'q_d{n}': '2026-05-10' for n in range(42)} | {'q_d0': '2026-05-11'})
        assert forms.validate(questions, data, {}, base_answers=workflow.current_answers(resp))[1]['d1']
        db.rollback()
