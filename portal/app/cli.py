"""Notfall-Werkzeug auf der Kommandozeile, z. B. wenn niemand mehr als Admin anmelden kann.

  docker compose exec portal python -m app.cli users
  docker compose exec portal python -m app.cli set-password admin@example.org
  docker compose exec portal python -m app.cli make-admin kollege@example.org
  docker compose exec portal python -m app.cli reset-2fa admin@example.org
"""

import getpass
import sys

from sqlalchemy import select

from .db import SessionLocal, User, init_db
from .security import hash_password


def main(argv: list[str]) -> int:
    init_db()
    cmd = argv[0] if argv else ""
    with SessionLocal() as db:
        if cmd == "users":
            for u in db.scalars(select(User).order_by(User.email)):
                print(f"{u.email:40} {'Admin' if u.is_admin else 'Benutzer':9} "
                      f"{'aktiv' if u.active else 'gesperrt':9} {'2FA' if u.totp_enabled or u.mfa_email else ''}")
            return 0
        if cmd in ("set-password", "make-admin", "reset-2fa") and len(argv) == 2:
            user = db.scalar(select(User).where(User.email == argv[1].strip().lower()))
            if user is None:
                print(f"Kein Konto mit der Adresse {argv[1]} gefunden. Vorhandene: python -m app.cli users")
                return 1
            if cmd == "reset-2fa":
                from . import twofa
                twofa.reset(user)
                db.commit()
                print(f"Zwei-Faktor-Anmeldung für {user.email} zurückgesetzt.")
                return 0
            if cmd == "make-admin":
                user.is_admin, user.active = True, True
                db.commit()
                print(f"{user.email} ist jetzt aktiver Admin.")
                return 0
            password = getpass.getpass("Neues Passwort (mindestens 10 Zeichen): ")
            if len(password) < 10 or password != getpass.getpass("Wiederholen: "):
                print("Abgebrochen: zu kurz oder Eingaben verschieden.")
                return 1
            user.password_hash = hash_password(password)
            user.password_set, user.active, user.must_change_password = True, True, False
            user.token_hash = user.token_expires_at = None
            db.commit()
            print(f"Passwort für {user.email} gesetzt.")
            return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
