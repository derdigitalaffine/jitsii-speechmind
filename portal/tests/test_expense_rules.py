import json
from decimal import Decimal
import pytest
from starlette.datastructures import FormData
from app import expense_rules as er, travel_template as tt, forms, workflow
from app.db import ExpenseRuleSet, SessionLocal, User, FormResponse, ApplicationRequest
from conftest import login, csrf_of


@pytest.fixture
def rate():
    with SessionLocal() as db:
        admin=db.query(User).filter_by(is_admin=True).first()
        values=er.PROPOSAL|{'profile':'test_expense','name':'Testfassung','valid_from':'2026-01-01','valid_until':'2026-12-31','reviewed':'1'}
        row=er.save(db,values,admin);db.commit();rid=row.id
    yield rid
    with SessionLocal() as db:
        db.delete(db.get(ExpenseRuleSet,rid));db.commit()


def item():return er.clean({'period_source':'period','route_source':'route','costs_source':'costs','days_source':'days','advance_source':'advance','reason_source':'grounds','special_source':'special','year_km_source':'year','profile':'test_expense'})
def base():return {'period':{'start':'2026-10-07T08:00','end':'2026-10-07T17:00'},'route':{'legs':[{'meters':10000,'quote':{'category':'private_car'}}]},'advance':'2'}


def test_thresholds_meals_and_version_snapshot(rate):
    result=er.calculate(item(),base()|{'days':[{'date':'2026-10-07','breakfast':True}]})
    assert result['day_total']=='5.63'  # max(20% of €8, €2.37) deducted
    assert result['mileage_total']=='1.80' and result['total']=='5.43'
    assert result['rule_snapshots'][0]['id']==rate
    assert result['rule_snapshots'][0]['rates']['breakfast_min']=='2.37'
    for hours,expected in [(8,'0.00'),(14,'14.00'),(24,'24.00')]:
        answers=base();answers['period']={'start':'2026-10-07T00:00','end':'2026-10-08T00:00' if hours==24 else f'2026-10-07T{hours:02d}:00'}
        assert er.calculate(item(),answers)['day_total']==expected


def test_vehicle_categories_staffel_and_payout_not_required(rate):
    a=base();a['route']['legs'][0]['quote']['category']='company_car'
    assert er.calculate(item(),a)['mileage_total']=='0.00'
    a['route']['legs'][0]['quote']['category']='recognized_car';a['year']='9995'
    assert er.calculate(item(),a)['mileage_total']=='3.30'  # 5 km .38 + 5 km .28
    a.pop('year')
    with pytest.raises(ValueError,match='Jahreskilometer'):er.calculate(item(),a)
    a=base()|{'grounds':['Dienstliches Gepäck']}
    assert er.calculate(item(),a)['mileage_total']=='2.80'


def test_costs_advance_and_missing_receipt(rate):
    cost={'date':'2026-10-07','kind':'Ticket','amount':'40','third_party':'10','receipt':True}
    result=er.calculate(item(),base()|{'costs':[cost]})
    assert result['cost_total']=='30.00' and result['total']=='37.80'
    with pytest.raises(ValueError,match='fehlenden Beleg'):er.calculate(item(),base()|{'costs':[cost|{'receipt':False}]})
    with pytest.raises(ValueError):er.calculate(item(),base()|{'costs':[cost|{'third_party':'41'}]})
    with pytest.raises(ValueError,match='eindeutig'):er.calculate(item(),base()|{'days':[{'date':'2026-10-07'},{'date':'2026-10-07'}]})


def test_hotel_meal_deduction_and_private_time(rate):
    cost={'date':'2026-10-07','kind':'Hotel','amount':'100','receipt':True,'breakfast':True}
    result=er.calculate(item(),base()|{'costs':[cost],'days':[{'date':'2026-10-07','private_hours':'1'}]})
    assert result['cost_total']=='95.20' and result['day_total']=='0.00'
    with pytest.raises(ValueError,match='doppelt'):er.calculate(item(),base()|{'costs':[cost],'days':[{'date':'2026-10-07','nights':'1'}]})


def test_unreviewed_overlapping_and_missing_rates(rate):
    with SessionLocal() as db:
        admin=db.query(User).filter_by(is_admin=True).first()
        values=er.PROPOSAL|{'profile':'test_expense','valid_from':'2026-01-01','valid_until':'2026-12-31','reviewed':'1'}
        with pytest.raises(ValueError,match='überschneidet'):er.save(db,values,admin)
        with pytest.raises(ValueError,match='ausdrücklich'):er.save(db,values|{'reviewed':''},admin)
    with pytest.raises(ValueError,match='fehlt'):er.calculate(item()|{'profile':'unknown'},base())


def test_derived_expense_field_ignores_posted_total(rate):
    schema=forms.clean_schema([{'id':'period','type':'period','required':True},{'id':'result','type':'expense_accounting',**item()}])
    answers,errors,_=forms.validate(schema,FormData({'q_period':json.dumps(base()['period']),'q_result':'99999'}),{})
    assert not errors and answers['result']['total']=='8.00'


def test_template_and_hr_document_include_request_fields():
    with SessionLocal() as db:
        admin=db.query(User).filter_by(is_admin=True).first()
        form,process=tt.install(db,admin)
        assert form.internal and not form.active and not process.current
        items=forms.schema(form)
        other=next(q for q in items if q['id']=='other_ground')
        assert other['required_if']['rules'][0]['q']=='grounds'
        definitions=workflow.definition_of(process)
        accounting=next(s for s in definitions['steps'] if s['id']=='account')['items']
        assert not any(q['type']=='signature' for q in items+accounting)
        assert next(q for q in accounting if q['id']=='accounting_truth')['required']
        assert all(f.get('required') is not True for s in definitions['steps'] for f in s.get('fields',[]) if f['key']=='payout_note')
        resp=FormResponse(form_id=form.id,name='Testperson',answers_json='{}',track_token='x'*50);db.add(resp);db.flush()
        req=ApplicationRequest(response_id=resp.id,title='Abrechnung',state='answered',schema_json=json.dumps([{'id':'actual','type':'period','title':'Tatsächlicher Reisezeitraum','with_time':True}]),answers_json=json.dumps({'actual':base()['period']}));db.add(req);db.flush();db.refresh(resp)
        assert '07.10.2026 08:00' in workflow.fill('{frage:Tatsächlicher Reisezeitraum}',resp)
        db.rollback()


def test_rules_and_template_ui():
    c=login('admin@example.org','admin-passwort-123')
    page=c.get('/settings/expense-rules');assert page.status_code==200 and 'Sachbezugswert Frühstück' in page.text
    assert 'Dienstreisevorlage' in c.get('/forms').text
    resp=c.post('/forms/templates/travel',data={'csrf':csrf_of(page.text)})
    assert resp.status_code==303


def test_correction_recomputes_with_existing_data_and_requires_declaration(rate):
    with SessionLocal() as db:
        admin=db.query(User).filter_by(is_admin=True).first()
        form,process=tt.install(db,admin)
        resp=FormResponse(form_id=form.id,user_id=admin.id,answers_json='{}');db.add(resp);db.flush()
        fields=[{'id':'period','type':'period','with_time':True},{'id':'advance','type':'short','subtype':'number'},{'id':'result','type':'expense_accounting',**item()},{'id':'check','type':'declaration','required':True,'statement':'Alles richtig'}]
        previous=ApplicationRequest(response_id=resp.id,title='Abrechnung',state='answered',schema_json=json.dumps(fields),answers_json=json.dumps(base()|{'result':er.calculate(item(),base()),'check':{'confirmed':True}}));db.add(previous);db.flush();db.refresh(resp)
        req=workflow.create_request(db,resp,'Korrektur','',[],['advance'],None,'Test')
        assert 'result' in req.reopen and 'check' in req.reopen
        context=workflow.current_answers(resp)
        answers,errors,_=forms.validate(workflow.reopen_items(resp,req),FormData({'q_advance':'5','q_check':'1'}),{},base_answers=context)
        assert not errors and answers['result']['total']=='4.80'
        db.rollback()


def test_new_rate_revision_preserves_snapshot(rate):
    before=er.calculate(item(),base())
    with SessionLocal() as db:
        admin=db.query(User).filter_by(is_admin=True).first()
        row=er.save(db,er.PROPOSAL|{'profile':'test_expense','valid_from':'2026-01-01','valid_until':'2026-12-31','reviewed':'1','supersede':'1','change_reason':'Neue geprüfte Regel','day8':'9'},admin);db.commit();rid=row.id
    try:
        after=er.calculate(item(),base())
        assert before['day_total']=='8.00' and after['day_total']=='9.00'
        assert before['rule_snapshots'][0]['id']==rate and after['rule_snapshots'][0]['id']==rid
    finally:
        with SessionLocal() as db:db.delete(db.get(ExpenseRuleSet,rid));db.commit()
