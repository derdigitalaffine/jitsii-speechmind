"""Isolated browser-test server. No worker, mail delivery or real user data."""
import os
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select

os.environ.update(PORTAL_BASE_URL='http://127.0.0.1:8765', MEET_BASE_URL='http://127.0.0.1:8080',
                  PORTAL_SECRET_KEY='browser-tests-only-secret-with-at-least-32-characters',
                  JWT_APP_SECRET='browser-tests-only-jwt-key-with-at-least-32-characters', TZ='Europe/Berlin')
from app import main, tasks
from app.db import SessionLocal, User, init_db, set_setting, to_local, utcnow
from app.security import hash_password

init_db()
with SessionLocal() as db:
    for key in main.MODULES:
        set_setting(db, main.MODULES[key][1], '1' if key=='tasks' else '0')
    user=db.scalar(select(User).where(User.email=='browser@example.org'))
    if not user:
        user=User(name='Mara Schneider',email='browser@example.org',password_hash=hash_password('browser-test-password'),
                  permissions='tasks,tasks_manage')
        db.add(user);db.flush()
        for title,offset in [('Präsentation vorbereiten',-1),('Teilnehmerliste prüfen',2)]:
            tasks.create(db,user,{'title':title,'assignee_id':user.id,
                                 'due_date':to_local(utcnow()+timedelta(days=offset)).date().isoformat()})
    db.commit()
app=main.app
