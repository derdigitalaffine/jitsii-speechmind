from datetime import date
from fastapi import Depends, Request, HTTPException
from sqlalchemy import select
from . import expense_rules, expense_editor, travel_template
from .db import ExpenseRuleSet, User
from .main import app, admin_user, get_db, check_csrf, flash, render, redirect


def _base(db, value):
    if not value:
        return None
    try:
        row = db.get(ExpenseRuleSet, int(value))
    except (ValueError, TypeError):
        row = None
    if row is None:
        raise HTTPException(404, 'Satzfassung nicht gefunden.')
    return row


def _page(request, user, db, values=None, error='', base=None):
    rows = list(db.scalars(select(ExpenseRuleSet).order_by(ExpenseRuleSet.id.desc())))
    active_ids, active_profiles = set(), set()
    for row in rows:
        if row.valid_from <= date.today() <= row.valid_until and row.profile not in active_profiles:
            active_ids.add(row.id)
            active_profiles.add(row.profile)
    editing = values is not None or request.query_params.get('new') == '1' or base is not None or not rows
    response = render(request,'expense_rules.html',user,
                      rules=[expense_editor.overview(row,active_ids) for row in rows],
                      groups=expense_editor.GROUPS, labels={k:expense_editor.label(k) for k in expense_rules.LABELS},
                      units={k:expense_editor.unit(k) for k in expense_rules.LABELS}, percent=expense_editor.PERCENT,
                      profiles=sorted({r.profile for r in rows}), reviewers={u.id:u.name for u in db.scalars(select(User))},
                      editing=editing, values=values if values is not None else expense_editor.initial(base),
                      original=expense_editor.initial(base) if base else {}, base=base, error=error, source=expense_rules.SOURCE)
    if error:
        response.status_code = 422
    return response


@app.get('/settings/expense-rules')
def rules_page(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    return _page(request,user,db,base=_base(db,request.query_params.get('edit')))


@app.post('/settings/expense-rules',dependencies=[Depends(check_csrf)])
async def rules_save(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    raw = dict(await request.form())
    base = _base(db,raw.get('base_id'))
    try:
        expense_rules.save(db,expense_editor.posted(raw),user)
        db.commit()
        flash(request,'Geprüfte Satzfassung gespeichert. Bestehende Abrechnungen behalten ihre Fassung.')
    except ValueError as exc:
        db.rollback()
        if raw.get('editor_format') != 'percent':
            for key in expense_editor.PERCENT:
                raw[key] = expense_editor.display(key, raw.get(key))
        return _page(request,user,db,values=raw,error=str(exc),base=base)
    return redirect('/settings/expense-rules')

@app.post('/forms/templates/travel',dependencies=[Depends(check_csrf)])
def install_travel(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    form,process=travel_template.install(db,user);db.commit()
    flash(request,'Dienstreisevorlage als inaktiver Entwurf angelegt. Satzfassungen und Zuständigkeiten prüfen, Prozess veröffentlichen, Formular aktivieren.')
    return redirect(f'/forms/{form.id}')
