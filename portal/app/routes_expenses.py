from fastapi import Depends, Request
from sqlalchemy import select
from . import expense_rules, travel_template
from .db import ExpenseRuleSet
from .main import app, admin_user, get_db, check_csrf, flash, render, redirect

@app.get('/settings/expense-rules')
def rules_page(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    return render(request,'expense_rules.html',user,rules=list(db.scalars(select(ExpenseRuleSet).order_by(ExpenseRuleSet.valid_from.desc()))),labels=expense_rules.LABELS,proposal=expense_rules.PROPOSAL,source=expense_rules.SOURCE)

@app.post('/settings/expense-rules',dependencies=[Depends(check_csrf)])
async def rules_save(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    try:
        expense_rules.save(db,await request.form(),user);db.commit();flash(request,'Geprüfte Satzfassung gespeichert. Bestehende Abrechnungen behalten ihre Fassung.')
    except ValueError as exc:
        db.rollback();flash(request,str(exc),'error')
    return redirect('/settings/expense-rules')

@app.post('/forms/templates/travel',dependencies=[Depends(check_csrf)])
def install_travel(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    form,process=travel_template.install(db,user);db.commit()
    flash(request,'Dienstreisevorlage als inaktiver Entwurf angelegt. Satzfassungen und Zuständigkeiten prüfen, Prozess veröffentlichen, Formular aktivieren.')
    return redirect(f'/forms/{form.id}')
