"""Abstimmungen und Wahlen (Teil des Moduls „Umfragen & Abstimmungen“).

Fragearten: eine Antwort, mehrere Antworten, Rangfolge (Borda-Punkte) und Punkte verteilen – jeweils mit
optionaler Enthaltung. Geheimhaltung je Abstimmung:
  offen  – Stimmzettel mit Namen (für die Auswertung sichtbar),
  geheim – das Wählerverzeichnis zeigt, wer abgestimmt hat, die Stimmzettel sind davon getrennt gespeichert,
  anonym – weder Namen noch Beteiligung einzelner Personen werden angezeigt.
Stimmzettel haben eine zufällige ID und keinen Zeitstempel; im Wählerverzeichnis steht nur der Tag.
Zugang: persönliche Einladung (Mail), öffentlicher Link mit E-Mail-Bestätigung (der persönliche Link aus der
Mail ist die Bestätigung) und Zugangscodes zum Ausdrucken. Beim Beenden wird das Ergebnis mit SHA-256 über alle
Stimmzettel eingefroren.
"""

import hashlib
import io
import json
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from . import csvsafe, links, mailtpl, notify
from .db import Group, User, Vote, VoteBallot, VoteQuestion, VoteVoter, get_settings, to_local, utcnow
from .planning import EMAIL_RE
from .security import new_link_token

KINDS = {"single": ("Eine Antwort", "fa-circle-dot"), "multi": ("Mehrere Antworten", "fa-square-check"),
         "rank": ("Rangfolge", "fa-arrow-down-1-9"), "points": ("Punkte verteilen", "fa-coins")}
SECRECY = {"secret": ("Geheim", "Wer abgestimmt hat, ist sichtbar – wie, nicht. Stimmzettel und Wählerverzeichnis "
                                "sind getrennt gespeichert."),
           "open": ("Offen", "Namen und Stimmen sind in der Auswertung sichtbar (z. B. Gremienbeschluss)."),
           "anonymous": ("Anonym", "Weder Namen noch die Beteiligung einzelner Personen werden angezeigt.")}
ACCESS = {"invite": ("Persönliche Einladung", "Wahlberechtigte bekommen einen persönlichen Link per Mail."),
          "public": ("Öffentlicher Link mit E-Mail-Bestätigung", "Jede:r kann sich mit E-Mail-Adresse melden; abgestimmt "
                     "wird über den Link aus der Bestätigungsmail – eine Stimme je Adresse."),
          "codes": ("Zugangscodes zum Ausdrucken", "Einmal-Codes für Präsenz oder Briefversand, mit QR-Code.")}
RESULTS = {"after_end": ("Nach dem Ende", "verhindert Beeinflussung"),
           "after_vote": ("Nach der eigenen Stimme", "wer abgestimmt hat, sieht den Zwischenstand"),
           "live": ("Sofort (live)", "alle mit Zugang sehen den Zwischenstand"),
           "owner": ("Nur für die Veranstaltung", "Ergebnis bleibt intern")}
STATUSES = {"draft": ("Entwurf", "secondary"), "open": ("läuft", "primary"), "closed": ("beendet", "success")}
ABSTAIN = "abstain"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # ohne 0/O, 1/I
MAX_QUESTIONS, MAX_OPTIONS, MAX_CODES = 50, 100, 2000
OPTION_ID = re.compile(r"^[a-z0-9]{1,12}$")


# --- Aufbau ----------------------------------------------------------------------------------

def options(q: VoteQuestion) -> list[dict]:
    try:
        data = json.loads(q.options_json or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def editor_data(vote: Vote | None) -> list[dict]:
    if vote is None:
        return []
    return [{"id": q.id, "title": q.title, "description": q.description, "kind": q.kind, "options": options(q),
             "min": q.min_choices, "max": q.max_choices, "points": q.points_total, "abstain": q.abstain}
            for q in vote.questions]


def _int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def set_questions(db, vote: Vote, raw) -> str:
    """Fragen aus dem Editor übernehmen. Gibt eine Fehlermeldung oder "" zurück."""
    if not isinstance(raw, list) or not raw:
        return "Bitte mindestens eine Frage anlegen."
    clean = []
    for i, item in enumerate(raw[:MAX_QUESTIONS]):
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title", "")).split())[:500]
        kind = item.get("kind") if item.get("kind") in KINDS else "single"
        opts, seen = [], set()
        for o in (item.get("options") or [])[:MAX_OPTIONS]:
            if not isinstance(o, dict):
                continue
            label = " ".join(str(o.get("label", "")).split())[:300]
            if not label:
                continue
            oid = str(o.get("id", ""))
            if not OPTION_ID.match(oid) or oid in seen or oid == ABSTAIN:
                oid = secrets.token_hex(3)
            seen.add(oid)
            opts.append({"id": oid, "label": label, "info": str(o.get("info", "")).strip()[:1000]})
        if not title:
            return f"Frage {i + 1} braucht einen Text."
        if len(opts) < 2:
            return f"„{title[:60]}“ braucht mindestens zwei Antwortmöglichkeiten."
        n = len(opts)
        mx = _int(item.get("max"), 1, n, 1 if kind == "single" else n)
        mn = _int(item.get("min"), 0, mx, 1 if kind != "multi" else 0)
        clean.append({"id": item.get("id"), "title": title, "description": str(item.get("description", "")).strip()[:3000],
                      "kind": kind, "options": opts, "min": 1 if kind == "single" else mn, "max": 1 if kind == "single" else mx,
                      "points": _int(item.get("points"), 1, 1000, 10), "abstain": bool(item.get("abstain", True))})
    if vote.status != "draft" and db.query(VoteBallot).filter(VoteBallot.vote_id == vote.id).first():
        return "Es wurde schon abgestimmt – die Fragen lassen sich nicht mehr ändern."
    existing = {q.id: q for q in vote.questions}
    keep = []
    for pos, c in enumerate(clean):
        q = existing.pop(c["id"], None) if isinstance(c["id"], int) else None
        if q is None:
            q = VoteQuestion(title=c["title"])
            vote.questions.append(q)
        q.position, q.title, q.description, q.kind = pos, c["title"], c["description"], c["kind"]
        q.options_json = json.dumps(c["options"], ensure_ascii=False)
        q.min_choices, q.max_choices, q.points_total, q.abstain = c["min"], c["max"], c["points"], c["abstain"]
        keep.append(q)
    for q in existing.values():
        vote.questions.remove(q)
    return ""


def access_modes(vote: Vote) -> set[str]:
    return {a for a in (vote.access or "").split(",") if a in ACCESS}


def is_open(vote: Vote) -> bool:
    return not vote.archived_at and vote.status == "open" and (vote.ends_at is None or vote.ends_at > utcnow())


def public_link(vote: Vote) -> str:
    return f"{links.base('polls')}/v/{vote.public_token}"


def personal_link(voter: VoteVoter) -> str:
    return f"{links.base('polls')}/v/p/{voter.token}"


# --- Stimmzettel lesen und zählen -------------------------------------------------------------

def read_ballot(vote: Vote, data) -> tuple[dict, list[str]]:
    """Antworten aus dem Formular prüfen. Gibt (Antworten, Fehler je Frage) zurück."""
    answers, errors = {}, []
    for q in vote.questions:
        opts = [o["id"] for o in options(q)]
        key = f"q{q.id}"
        label = q.title[:80]
        if q.abstain and data.get(f"{key}_abstain") == "1":
            answers[str(q.id)] = ABSTAIN
            continue
        if q.kind == "single":
            v = str(data.get(key, ""))
            if v == ABSTAIN and q.abstain:
                answers[str(q.id)] = ABSTAIN
            elif v in opts:
                answers[str(q.id)] = [v]
            else:
                errors.append(f"„{label}“: Bitte eine Antwort wählen{' oder sich enthalten' if q.abstain else ''}.")
        elif q.kind == "multi":
            chosen = [v for v in data.getlist(key) if v in opts]
            chosen = list(dict.fromkeys(chosen))
            if len(chosen) < max(1, q.min_choices) or len(chosen) > q.max_choices:
                errors.append(f"„{label}“: Bitte {_range_text(max(1, q.min_choices), q.max_choices)} wählen.")
            else:
                answers[str(q.id)] = chosen
        elif q.kind == "rank":
            ranks = {}
            for oid in opts:
                raw = str(data.get(f"{key}_{oid}", "")).strip()
                if raw:
                    if not raw.isdigit() or not 1 <= int(raw) <= len(opts):
                        errors.append(f"„{label}“: ungültiger Platz.")
                        break
                    ranks[oid] = int(raw)
            else:
                order = [oid for oid, _ in sorted(ranks.items(), key=lambda x: x[1])]
                places = sorted(ranks.values())
                limit = q.max_choices or len(opts)
                if places != list(range(1, len(places) + 1)):
                    errors.append(f"„{label}“: Jeder Platz darf nur einmal vergeben werden (1, 2, 3 …).")
                elif not order or len(order) < max(1, q.min_choices) or len(order) > limit:
                    errors.append(f"„{label}“: Bitte {_range_text(max(1, q.min_choices), limit)} in eine Reihenfolge bringen.")
                else:
                    answers[str(q.id)] = order
        else:   # points
            pts, total = {}, 0
            for oid in opts:
                raw = str(data.get(f"{key}_{oid}", "")).strip() or "0"
                if not raw.isdigit():
                    errors.append(f"„{label}“: Punkte nur als ganze Zahlen.")
                    break
                if int(raw):
                    pts[oid] = int(raw)
                    total += int(raw)
            else:
                if total == 0:
                    errors.append(f"„{label}“: Bitte Punkte verteilen{' oder sich enthalten' if q.abstain else ''}.")
                elif total > q.points_total:
                    errors.append(f"„{label}“: höchstens {q.points_total} Punkte (vergeben: {total}).")
                else:
                    answers[str(q.id)] = pts
    return answers, errors


def _range_text(lo: int, hi: int) -> str:
    if lo == hi:
        return f"genau {lo} Antwort{'en' if lo != 1 else ''}"
    return f"{lo} bis {hi} Antworten"


def display(q: VoteQuestion, value) -> str:
    """Antwort eines Stimmzettels lesbar (für offene Abstimmungen und den Export)."""
    labels = {o["id"]: o["label"] for o in options(q)}
    if value is None:
        return ""
    if value == ABSTAIN:
        return "Enthaltung"
    if q.kind == "points":
        return ", ".join(f"{labels.get(k, k)}: {p}" for k, p in value.items())
    if q.kind == "rank":
        return " > ".join(labels.get(k, k) for k in value)
    return ", ".join(labels.get(k, k) for k in value)


def ballots(db, vote: Vote) -> list[VoteBallot]:
    return db.scalars(select(VoteBallot).where(VoteBallot.vote_id == vote.id).order_by(VoteBallot.id)).all()


def tally(db, vote: Vote) -> list[dict]:
    """Ergebnis je Frage. Einfach/Mehrfach: Stimmen; Rangfolge: Borda-Punkte (Platz 1 = n Punkte …); Punkte: Summe."""
    rows = [json.loads(b.answers_json or "{}") for b in ballots(db, vote)]
    out = []
    for q in vote.questions:
        opts = options(q)
        n = len(opts)
        res = {o["id"]: {"id": o["id"], "label": o["label"], "info": o.get("info", ""), "value": 0, "firsts": 0,
                         "ranked": 0, "rank_sum": 0} for o in opts}
        abstain = valid = 0
        for a in rows:
            v = a.get(str(q.id))
            if v is None:
                continue
            if v == ABSTAIN:
                abstain += 1
                continue
            valid += 1
            if q.kind in ("single", "multi"):
                for oid in v:
                    if oid in res:
                        res[oid]["value"] += 1
            elif q.kind == "rank":
                for pos, oid in enumerate(v):
                    if oid in res:
                        res[oid]["value"] += n - pos
                        res[oid]["ranked"] += 1
                        res[oid]["rank_sum"] += pos + 1
                        res[oid]["firsts"] += pos == 0
            else:
                for oid, p in v.items():
                    if oid in res:
                        res[oid]["value"] += int(p)
        items = list(res.values())
        total_value = sum(i["value"] for i in items) or 1
        for i in items:
            base = valid if q.kind in ("single", "multi") else total_value
            i["percent"] = round(100 * i["value"] / base, 1) if base else 0.0
            i["avg_rank"] = round(i["rank_sum"] / i["ranked"], 2) if i["ranked"] else None
        ordered = sorted(items, key=lambda i: (-i["value"], i["label"].lower()))
        top = ordered[0]["value"] if ordered else 0
        winners = [i["id"] for i in ordered if i["value"] == top and top > 0]
        out.append({"id": q.id, "title": q.title, "kind": q.kind, "ballots": valid + abstain, "valid": valid,
                    "abstain": abstain, "items": ordered, "winners": winners, "unit": UNITS[q.kind],
                    "chart": {"labels": [i["label"] for i in ordered], "values": [i["value"] for i in ordered],
                              "label": UNITS[q.kind][1]}})
    return out


UNITS = {"single": ("Stimme", "Stimmen"), "multi": ("Stimme", "Stimmen"), "rank": ("Punkt", "Borda-Punkte"),
         "points": ("Punkt", "Punkte")}


def turnout(vote: Vote, ballot_count: int) -> dict:
    eligible = [v for v in vote.voters if v.confirmed]
    voted = sum(1 for v in eligible if v.voted)
    return {"eligible": len(eligible), "voted": voted, "ballots": ballot_count,
            "percent": round(100 * voted / len(eligible), 1) if eligible else None,
            "pending": sum(1 for v in vote.voters if not v.confirmed)}


def results_visible_to_voter(vote: Vote, voter: VoteVoter | None) -> bool:
    if vote.results == "live":
        return vote.status != "draft"
    if vote.results == "after_vote":
        return vote.status == "closed" or bool(voter and voter.voted)
    if vote.results == "after_end":
        return vote.status == "closed"
    return False


# --- Abstimmen -------------------------------------------------------------------------------

def existing_ballot(db, vote: Vote, voter: VoteVoter) -> VoteBallot | None:
    if vote.secrecy != "open":
        return None
    return db.scalar(select(VoteBallot).where(VoteBallot.vote_id == vote.id, VoteBallot.voter_id == voter.id))


def cast(db, vote: Vote, voter: VoteVoter, answers: dict) -> str:
    """Stimme abgeben. Gibt die Quittung zurück (bei offener Abstimmung mit Ändern: dieselbe)."""
    ballot = existing_ballot(db, vote, voter) if vote.allow_change else None
    if ballot is None:
        ballot = VoteBallot(id=secrets.token_hex(16), vote_id=vote.id, receipt=_code(10),
                            voter_id=voter.id if vote.secrecy == "open" else None)
        db.add(ballot)
    ballot.answers_json = json.dumps(answers, ensure_ascii=False, sort_keys=True)
    voter.voted = True
    voter.voted_on = to_local(utcnow()).date()
    return ballot.receipt


def can_vote(vote: Vote, voter: VoteVoter) -> bool:
    if not is_open(vote) or not voter.confirmed:
        return False
    return not voter.voted or (vote.allow_change and vote.secrecy == "open")


# --- Wählerverzeichnis ------------------------------------------------------------------------

def _code(n: int = 8) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(n))


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def _mail(db, vote: Vote, voter: VoteVoter, key: str, actor: User | None = None) -> bool:
    if not voter.email:
        return False
    cfg = get_settings(db)
    values = {"name": voter.name or voter.email, "titel": vote.title, "beschreibung": vote.description,
              "link": personal_link(voter), "absender": actor.name if actor else "",
              "frist": ("Abstimmen bis " + to_local(vote.ends_at).strftime("%d.%m.%Y, %H:%M Uhr") + ".") if vote.ends_at else "",
              "geheim": SECRECY[vote.secrecy][0] + ": " + SECRECY[vote.secrecy][1]}
    subject, body = mailtpl.render(db, key, values, cfg)
    return notify.enqueue(db, voter.email, subject, body, key, cfg, reply_to=actor.email if actor else None)


def invite(db, vote: Vote, actor: User, user_ids: list[int], group_ids: list[int], emails: list[str]) -> tuple[int, int]:
    existing = {v.email for v in vote.voters if v.email}
    targets: list[tuple[str, str, int | None]] = []
    if user_ids:
        targets += [(u.email, u.name, u.id) for u in db.scalars(select(User).where(User.id.in_(user_ids), User.active.is_(True)))]
    for g in db.scalars(select(Group).where(Group.id.in_(group_ids))) if group_ids else []:
        targets += [(u.email, u.name, u.id) for u in g.members if u.active]
    for email in emails:
        u = db.scalar(select(User).where(User.email == email))
        targets.append((email, u.name if u else "", u.id if u else None))
    added = skipped = 0
    for email, name, uid in targets:
        if email in existing:
            skipped += 1
            continue
        existing.add(email)
        voter = VoteVoter(source="invite", email=email, name=name or email.split("@")[0], user_id=uid,
                          token=new_link_token(), confirmed=True)
        vote.voters.append(voter)
        db.flush()
        if vote.status == "open" and _mail(db, vote, voter, "vote_invite", actor):
            voter.invited_at = utcnow()
        added += 1
    return added, skipped


def send_pending_invites(db, vote: Vote, actor: User) -> int:
    """Beim Start: alle noch nicht angeschriebenen Eingeladenen benachrichtigen."""
    n = 0
    for voter in vote.voters:
        if voter.source == "invite" and voter.invited_at is None and _mail(db, vote, voter, "vote_invite", actor):
            voter.invited_at = utcnow()
            n += 1
    return n


def remind(db, vote: Vote, actor: User) -> int:
    n = 0
    for voter in vote.voters:
        if voter.source != "code" and voter.confirmed and not voter.voted and _mail(db, vote, voter, "vote_reminder", actor):
            voter.reminded_at = utcnow()
            n += 1
    return n


def signup(db, vote: Vote, name: str, email: str) -> VoteVoter | None:
    """Öffentliche Anmeldung: Bestätigungsmail mit persönlichem Link (eine Stimme je Adresse)."""
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        return None
    voter = db.scalar(select(VoteVoter).where(VoteVoter.vote_id == vote.id, VoteVoter.email == email))
    if voter is None:
        voter = VoteVoter(source="public", email=email, name=" ".join(name.split())[:255], token=new_link_token(),
                          confirmed=False)
        vote.voters.append(voter)
        db.flush()
    if not voter.voted:
        _mail(db, vote, voter, "vote_confirm")
    return voter


def make_codes(db, vote: Vote, count: int, label: str = "") -> int:
    count = max(1, min(count, MAX_CODES - sum(1 for v in vote.voters if v.source == "code")))
    used = set(db.scalars(select(VoteVoter.code).where(VoteVoter.vote_id == vote.id)))
    made = 0
    while made < count:
        code = _code(8)
        if code in used:
            continue
        used.add(code)
        vote.voters.append(VoteVoter(source="code", code=code, token=new_link_token(), confirmed=True,
                                     name=label[:255]))
        made += 1
    return made


def voter_by_code(db, vote: Vote, raw: str) -> VoteVoter | None:
    code = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if len(code) != 8:
        return None
    return db.scalar(select(VoteVoter).where(VoteVoter.vote_id == vote.id, VoteVoter.code == code))


# --- Abschluss, Export, Protokoll -------------------------------------------------------------

def close(db, vote: Vote) -> None:
    vote.status = "closed"
    vote.closed_at = utcnow()
    result = tally(db, vote)
    digest = hashlib.sha256()
    for b in sorted(ballots(db, vote), key=lambda b: b.id):
        digest.update(b.id.encode() + b"|" + (b.answers_json or "").encode() + b"\n")
    vote.result_json = json.dumps(result, ensure_ascii=False)
    digest.update(vote.result_json.encode())
    vote.result_hash = digest.hexdigest()


def frozen(vote: Vote) -> list[dict] | None:
    try:
        return json.loads(vote.result_json) if vote.result_json else None
    except ValueError:
        return None


def to_csv(db, vote: Vote) -> str:
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    qs = vote.questions
    head = ["Stimmzettel"] + (["Name", "E-Mail"] if vote.secrecy == "open" else []) + [q.title for q in qs]
    w.writerow(head)
    voters = {v.id: v for v in vote.voters}
    for b in ballots(db, vote):
        a = json.loads(b.answers_json or "{}")
        row = [b.id[:8]]
        if vote.secrecy == "open":
            v = voters.get(b.voter_id)
            row += [v.name if v else "", v.email if v else ""]
        for q in qs:
            row.append(display(q, a.get(str(q.id))))
        w.writerow(row)
    return "\ufeff" + buf.getvalue()


def protocol_pdf(db, vote: Vote) -> bytes:
    """Ergebnisprotokoll als PDF (A4): Einstellungen, Zeitraum, Beteiligung, Ergebnis je Frage, Prüfsumme."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from xml.sax.saxutils import escape

    from . import branding
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=f"Ergebnisprotokoll {vote.title}")
    res = frozen(vote) or tally(db, vote)
    t = turnout(vote, len(ballots(db, vote)))
    fmt = lambda d: to_local(d).strftime("%d.%m.%Y, %H:%M Uhr") if d else "–"  # noqa: E731
    story = [Paragraph(escape(branding.load()["name"]), styles["Normal"]),
             Paragraph("Ergebnisprotokoll", styles["Title"]), Paragraph(escape(vote.title), styles["Heading2"])]
    if vote.description:
        story.append(Paragraph(escape(vote.description).replace("\n", "<br/>"), styles["Normal"]))
    meta = [["Art der Abstimmung", SECRECY[vote.secrecy][0]],
            ["Zugang", ", ".join(ACCESS[a][0] for a in sorted(access_modes(vote)))],
            ["Zeitraum", f"{fmt(vote.opened_at)} bis {fmt(vote.closed_at or vote.ends_at)}"],
            ["Stimmzettel", str(t["ballots"])]]
    if vote.secrecy != "anonymous" and t["eligible"]:
        meta.append(["Beteiligung", f"{t['voted']} von {t['eligible']} Wahlberechtigten ({t['percent']} %)"])
    story += [Spacer(1, 4 * mm), _table(meta, [50 * mm, 120 * mm], TableStyle, colors), Spacer(1, 6 * mm)]
    for i, q in enumerate(res, 1):
        story.append(Paragraph(f"{i}. {escape(q['title'])}", styles["Heading3"]))
        story.append(Paragraph(f"{KINDS[q['kind']][0]} · gültig {q['valid']} · Enthaltungen {q['abstain']}", styles["Normal"]))
        rows = [["Antwort", q["unit"][1], "Anteil"]]
        for it in q["items"]:
            mark = " ✓" if it["id"] in q["winners"] else ""
            rows.append([Paragraph(escape(it["label"]) + mark, styles["Normal"]), str(it["value"]), f"{it['percent']} %"])
        story += [_table(rows, [110 * mm, 30 * mm, 30 * mm], TableStyle, colors, head=True), Spacer(1, 5 * mm)]
    story += [Spacer(1, 6 * mm), Paragraph(f"Erstellt am {fmt(utcnow())}.", styles["Normal"])]
    if vote.result_hash:
        story.append(Paragraph(f"Prüfsumme (SHA-256 über alle Stimmzettel und das Ergebnis): <font face='Courier' size='8'>{vote.result_hash}</font>",
                               styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


def _table(rows, widths, TableStyle, colors, head: bool = False):
    from reportlab.platypus import Table
    tbl = Table(rows, colWidths=widths)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 9),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]
    if head:
        style += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]
    tbl.setStyle(TableStyle(style))
    return tbl


def finish_due() -> int:
    """Hintergrunddienst: Abstimmungen mit abgelaufener Frist beenden."""
    from .db import SessionLocal
    n = 0
    with SessionLocal() as db:
        for vote in db.scalars(select(Vote).where(Vote.status == "open", Vote.ends_at.is_not(None),
                                                  Vote.ends_at < utcnow())):
            close(db, vote)
            n += 1
        db.commit()
    return n


def parse_local(value: str) -> datetime | None:
    from .db import LOCAL_TZ
    try:
        local = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None) if local else None
