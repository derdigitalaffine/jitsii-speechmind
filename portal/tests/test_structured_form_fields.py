import json
from decimal import Decimal
import pytest
from starlette.datastructures import FormData
from app import forms as fm
from app.db import Form, SessionLocal
from conftest import client, csrf_of


def validate(schema, values):
    return fm.validate(fm.clean_schema(schema), FormData(values), {})


def test_period_rejects_backwards_time():
    answers, errors, _ = validate([{'id':'trip','type':'period','required':True}], {'q_trip':json.dumps({'start':'2026-10-07T15:00','end':'2026-10-07T14:00'})})
    assert errors and 'trip' not in answers

@pytest.mark.parametrize('bad', ['NaN','Infinity','-Infinity','100000000000000000000'])
def test_invalid_financial_values_are_rejected(bad):
    _, errors, _ = validate([{'id':'costs','type':'table','required':True}], {'q_costs':json.dumps([{'description':'Ticket','amount':bad}])})
    assert 'costs' in errors


def test_table_limit_and_required_cells():
    schema=[{'id':'costs','type':'table','max_rows':1}]
    assert validate(schema, {'q_costs':'[{"amount":"1"}]'})[1]
    assert validate(schema, {'q_costs':'[{"description":"A","amount":"1"},{"description":"B","amount":"2"}]'})[1]


def test_calculation_uses_server_values_not_submitted_result():
    schema=[{'id':'costs','type':'table'}, {'id':'sum','type':'calculation','operation':'table_total','sources':['costs'],'column':'amount'}]
    answers, errors, _=validate(schema, {'q_costs':'[{"description":"Ticket","amount":"1,005"},{"description":"Hotel","amount":"2.00"}]','q_sum':'999999'})
    assert not errors and answers['sum']=='3.01'


def test_calculation_cycles_and_unknown_fields_rejected():
    _, errors, _ = validate([{'id':'a','type':'calculation','sources':['b']},{'id':'b','type':'calculation','sources':['a']}], {})
    assert errors
    assert validate([{'id':'a','type':'calculation','sources':['missing']}], {})[1]


def test_declaration_is_explicit_and_keeps_exact_statement():
    schema=[{'id':'truth','type':'declaration','required':True,'statement':'Ich bestätige meine Angaben.'}]
    assert validate(schema, {})[1]
    answers, errors, _=validate(schema, {'q_truth':'1'})
    assert not errors and answers['truth']['confirmed'] and answers['truth']['text']=='Ich bestätige meine Angaben.'
    assert answers['truth']['at']


def test_signature_rejects_markup_and_invalid_coordinates():
    schema=[{'id':'sig','type':'signature','required':True}]
    assert validate(schema, {'q_sig':'<svg onload="alert(1)">'})[1]
    assert validate(schema, {'q_sig':json.dumps({'name':'A','strokes':[[[0,0],[2,1]]]})})[1]
    answers, errors, _=validate(schema, {'q_sig':json.dumps({'name':'A','strokes':[[[0,0],[.5,.2]]]})})
    assert not errors and answers['sig']['name']=='A'


def test_structured_fields_render_in_public_form():
    with SessionLocal() as db:
        form=Form(owner_id=1,title='Strukturierte Angaben',public_token='structured-render-test',schema_json=json.dumps(fm.clean_schema([
            {'id':'period','type':'period'},{'id':'table','type':'table'},{'id':'signature','type':'signature'},{'id':'truth','type':'declaration'}])))
        db.add(form);db.commit()
    page=client().get('/f/structured-render-test')
    assert page.status_code==200 and 'Position hinzufügen' in page.text and 'js-declaration' in page.text
    assert '/static/form-structured.js' in page.text


def test_internal_form_requires_employee_permission_and_protects_case_links():
    from app.db import FormResponse
    from conftest import login
    with SessionLocal() as db:
        form=Form(owner_id=1,title='Interner Antrag',internal=True,kind='application',public_token='internal-form-test',schema_json='[]')
        db.add(form);db.flush()
        resp=FormResponse(form_id=form.id,user_id=1,answers_json='{}',track_token='internal-track-'+'x'*30)
        db.add(resp);db.commit()
        token=resp.track_token
    c=client()
    assert c.get('/f/internal-form-test').status_code==403
    assert c.get('/a/'+token).status_code==403
    assert c.get('/a/'+token+'/pdf').status_code==403
    admin=login('admin@example.org','admin-passwort-123')
    assert admin.get('/f/internal-form-test').status_code==200
    assert admin.get('/a/'+token).status_code==200


def test_workflow_keeps_reusable_fields():
    from app import workflow
    items=workflow.clean_request_items([{'id':'costs','type':'table'},{'id':'truth','type':'declaration','required':True}])
    assert [i['type'] for i in items]==['table','declaration']


def test_request_prefill_is_a_snapshot_not_a_correction():
    from app import workflow
    from app.db import FormResponse
    with SessionLocal() as db:
        form=Form(owner_id=1,title='Planung bleibt erhalten',kind='application',schema_json='[]')
        db.add(form);db.flush()
        resp=FormResponse(form_id=form.id,user_id=1,answers_json=json.dumps({'planned':{'start':'2026-10-07','end':'2026-10-08'}}))
        db.add(resp);db.flush()
        req=workflow.create_request(db,resp,'Abrechnung','', [{'id':'actual','type':'period','with_time':False,'prefill_from':'planned'}],[],None,'Test')
        assert json.loads(req.prefill_json)['actual']==resp.answers['planned']
        resp.answers_json='{"planned":{"start":"2026-12-01","end":"2026-12-02"}}'
        assert json.loads(req.prefill_json)['actual']['start']=='2026-10-07'
        db.rollback()
