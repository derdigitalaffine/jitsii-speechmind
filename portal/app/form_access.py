"""Common access checks for internal forms and applicant-facing case links."""
from fastapi import HTTPException
from . import applications as apps
from .main import session_user


def submitting_user(request, db, form):
    user = session_user(request, db)
    if form.internal and (user is None or not user.can('internal_forms')):
        raise HTTPException(403, 'Dieses interne Formular erfordert eine Anmeldung und die Berechtigung für interne Formulare.')
    return user


def response_access(request, db, resp):
    if not resp.form.internal:
        return
    user = session_user(request, db)
    if user is None or (user.id != resp.user_id and not apps.access(db, user, resp)):
        raise HTTPException(403, 'Dieser interne Vorgang ist nur für die antragstellende Person und berechtigte Bearbeitende zugänglich.')
