import json
from datetime import date
from decimal import Decimal
import pytest
from app import expense_rules as er, expense_editor as editor
from app.db import ExpenseRuleSet, SessionLocal, User
from conftest import login, csrf_of, client


@pytest.fixture
def version():
    with SessionLocal() as db:
        row=er.save(db,er.PROPOSAL|{'profile':'editor_test','name':'Gespeicherte Fassung','valid_from':'2026-01-01','valid_until':'2026-12-31','reviewed':'1'},db.get(User,1))
        db.commit();rid=row.id
    yield rid
    with SessionLocal() as db:
        for row in db.query(ExpenseRuleSet).filter_by(profile='editor_test').all():
            db.delete(row)
        db.commit()


def test_overview_and_prepopulated_editor(version):
    c=login('admin@example.org','admin-passwort-123')
    page=c.get('/settings/expense-rules')
    assert page.status_code==200 and 'Gespeicherte Fassung' in page.text
    assert '<pre>' not in page.text and 'Sachbezugswert Frühstück' in page.text
    assert f'?edit={version}' in page.text and '0,38' in page.text
    editing=c.get(f'/settings/expense-rules?edit={version}')
    assert editing.status_code==200
    assert 'name="breakfast_fraction"' in editing.text and 'value="20"' in editing.text
    assert 'value="0.38"' in editing.text and 'value="2026-01-01"' in editing.text
    assert c.get('/settings/expense-rules?edit=999999').status_code==404
    assert client().get('/settings/expense-rules').status_code in (303,401,403)


def test_edit_preserves_old_version_and_errors_keep_input(version):
    c=login('admin@example.org','admin-passwort-123')
    page=c.get(f'/settings/expense-rules?edit={version}');token=csrf_of(page.text)
    with SessionLocal() as db:
        old=db.get(ExpenseRuleSet,version);before=old.rates_json;data=editor.initial(old)
    data.update(csrf=token, editor_format='percent', reviewed='1', private_car='0.25', breakfast_fraction='25', name='Neue geprüfte Fassung')
    failed=c.post('/settings/expense-rules',data=data)
    assert failed.status_code==422 and 'überschneidet' in failed.text
    assert 'value="0.25"' in failed.text and 'value="25"' in failed.text and 'Neue geprüfte Fassung' in failed.text
    data.update(supersede='1',change_reason='Fachliche Anpassung')
    response=c.post('/settings/expense-rules',data=data)
    assert response.status_code==303
    with SessionLocal() as db:
        old=db.get(ExpenseRuleSet,version)
        new=er.for_date(db,'editor_test',date(2026,10,7))
        assert old.rates_json==before and new.id!=version
        values=json.loads(new.rates_json)
        assert Decimal(values['private_car'])==Decimal('.25') and Decimal(values['breakfast_fraction'])==Decimal('.25')
        assert new.source.count('Änderungsgrund:')==1
        assert editor.source_parts(new)[1]=='Fachliche Anpassung'


def test_percentage_and_whole_kilometer_validation():
    assert editor.posted({'editor_format':'percent','training_factor':'70'})['training_factor']=='0.7'
    assert editor.display('breakfast_fraction','0.20')=='20'
    for values in ({'recognized_limit':'1.5'},{'breakfast_fraction':'1.01'},{'private_car':'NaN'}):
        with pytest.raises(ValueError):
            er.validate(er.PROPOSAL|values)
