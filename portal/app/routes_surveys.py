"""Unified navigation and creation; existing engines retain their protected endpoints."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from . import poll_lifecycle, surveys
from .db import User
from .main import app, current_user, enabled_modules, get_db, render


def _modules():
    modules = enabled_modules()
    if 'polls' not in modules:
        raise HTTPException(404, 'Umfragen sind auf diesem Server nicht eingeschaltet.')
    return modules


@app.get('/umfragen')
def survey_list(request: Request, q: str = '', kind: str = '', state: str = 'active', scope: str = 'all',
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    modules = _modules()
    q = q.strip()[:200]
    kind = kind if kind in surveys.KINDS else ''
    state = state if state in ('active', 'archive', 'trash') else 'active'
    scope = scope if scope in ('own', 'shared', 'all', 'portal') else 'all'
    if scope == 'portal' and not user.is_admin:
        scope = 'all'
    rows = surveys.collect(db, user, modules, state=state, scope=scope, admin_all=scope == 'portal') if state != 'trash' else []
    totals = {key: sum(row['kind'] == key for row in rows) for key in surveys.KINDS}
    rows = [row for row in rows if (not kind or row['kind'] == kind)
            and (not q or q.casefold() in (row['title'] + ' ' + row['description'] + ' ' + row['owner']).casefold())]
    trash = []
    if state == 'trash':
        if 'polls' in modules:
            for item in poll_lifecycle.trash_items(db, ['poll', 'vote', 'live_poll'], user):
                item_kind = {'poll': 'poll', 'vote': 'vote', 'live_poll': 'live'}[item.kind]
                if (not kind or kind == item_kind) and (not q or q.casefold() in item.label.casefold()) and scope != 'shared' and (scope == 'portal' or poll_lifecycle.trash_owner(item) == user.id):
                    trash.append(dict(title=item.label, kind=item_kind, expires=item.expires_at,
                                      restore=f'/umfragen/papierkorb/{item.id}/restore'))
    return render(request, 'surveys.html', user, rows=rows, trash=trash, kinds=surveys.KINDS,
                  create_kinds=surveys.available(user, modules), q=q, kind=kind, state=state, scope=scope, totals=totals,
                  survey_url=lambda **overrides: surveys.url(**{'q': q, 'kind': kind, 'state': state, 'scope': scope, **overrides}))


@app.get('/umfragen/neu')
def survey_new(request: Request, user: User = Depends(current_user)):
    choices = surveys.available(user, _modules())
    if not choices:
        raise HTTPException(403, 'Zum Anlegen einer Umfrage fehlt die Berechtigung.')
    return render(request, 'survey_new.html', user, kinds=surveys.KINDS, choices=choices)
