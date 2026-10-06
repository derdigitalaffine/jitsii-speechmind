"""Live-Umfragen (Teil des Moduls „Umfragen & Abstimmungen“).

Teilnehmende scannen den QR-Code und antworten sofort – ohne Einladungslink, ohne Anmeldung, ohne Namen. Jedes
Gerät bekommt eine zufällige Kennung (Cookie); gespeichert wird nur deren Hash. Je Gerät und Frage gibt es eine
Antwort, die sich bis zum Sperren der Frage ändern lässt. Ablauf je Umfrage wählbar:
  * moderiert – alle sehen die Frage, die die Moderation gerade zeigt (Präsentationsmodus, Pfeiltasten),
  * frei – alle Fragen auf einmal, in eigenem Tempo.
Ergebnisse für Teilnehmende je Frage: sofort, erst nach Freigabe oder nie.
"""

import hashlib
import json
import secrets
import statistics

from sqlalchemy import select

from .db import LiveAnswer, LivePoll, LiveQuestion

# Art → (Bezeichnung, Symbol, mögliche Darstellungen)
KINDS = {
    "single": ("Auswahl (eine Antwort)", "fa-circle-dot", ("bar", "column", "pie", "donut")),
    "multi": ("Auswahl (mehrere Antworten)", "fa-square-check", ("bar", "column", "pie", "donut")),
    "yesno": ("Ja / Nein", "fa-thumbs-up", ("pie", "donut", "bar", "column")),
    "scale": ("Skala (z. B. 1–5)", "fa-sliders", ("column", "bar", "number")),
    "stars": ("Sterne (1–5)", "fa-star", ("number", "column", "bar")),
    "slider": ("Schieberegler (Zahl)", "fa-ruler-horizontal", ("number", "column")),
}
CHARTS = {"bar": "Balken liegend", "column": "Säulen", "pie": "Torte", "donut": "Ring", "number": "Kennzahlen",
          "cloud": "Wortwolke", "table": "Tabelle"}
SHOW_RESULTS = {"immediate": "sofort nach der Antwort", "release": "erst nach Freigabe", "never": "nie (nur Beamer)"}
PACING = {"moderated": ("Moderiert", "Alle sehen die Frage, die Sie gerade zeigen – Frage für Frage."),
          "free": ("Frei", "Alle Fragen auf einmal, jede:r im eigenen Tempo.")}
STATUSES = {"draft": ("Vorbereitung", "secondary"), "open": ("läuft", "primary"), "closed": ("beendet", "success")}
DEVICE_COOKIE = "jsm_live"
MAX_QUESTIONS = 50
MAX_OPTIONS = 20


def opts(q: LiveQuestion) -> list[dict]:
    if q.kind == "yesno":
        return [{"id": "y", "label": "Ja"}, {"id": "n", "label": "Nein"}]
    try:
        data = json.loads(q.options_json or "[]")
    except ValueError:
        return []
    return [o for o in data if isinstance(o, dict) and o.get("id") and o.get("label")]


def settings(q: LiveQuestion) -> dict:
    try:
        data = json.loads(q.settings_json or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    if q.kind == "scale":
        lo = _int(data.get("min"), 0, 10, 1)
        return {**data, "min": lo, "max": _int(data.get("max"), lo + 1, 10, max(lo + 1, 5)),
                "low": str(data.get("low", ""))[:40], "high": str(data.get("high", ""))[:40]}
    if q.kind == "stars":
        return {**data, "min": 1, "max": 5}
    if q.kind == "slider":
        lo = _int(data.get("min"), -100000, 100000, 0)
        hi = _int(data.get("max"), lo + 1, 1000000, max(lo + 1, 100))
        return {**data, "min": lo, "max": hi, "step": _int(data.get("step"), 1, max(1, hi - lo), 1),
                "unit": str(data.get("unit", ""))[:12]}
    if q.kind == "multi":
        return {**data, "max_choices": _int(data.get("max_choices"), 1, MAX_OPTIONS, 3)}
    return data


def _int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def device_hash(raw: str) -> str:
    return hashlib.sha256(f"live:{raw}".encode()).hexdigest()


def new_device() -> str:
    return secrets.token_hex(16)


# --- Fragen anlegen ---------------------------------------------------------------------------------

def apply_question(q: LiveQuestion, data) -> str:
    """Formularfelder → Frage. Gibt eine Fehlermeldung oder ''."""
    title = " ".join(str(data.get("title", "")).split())[:500]
    if not title:
        return "Bitte die Frage eintragen."
    kind = data.get("kind") if data.get("kind") in KINDS else q.kind or "single"
    q.kind, q.title = kind, title
    if kind in ("single", "multi"):
        labels = [" ".join(line.split())[:200] for line in str(data.get("options", "")).splitlines() if line.strip()]
        if len(labels) < 2:
            return "Bitte mindestens zwei Antwortmöglichkeiten angeben (eine je Zeile)."
        old = {o["label"]: o["id"] for o in opts(q)} if q.options_json else {}
        out, used = [], set()
        for label in labels[:MAX_OPTIONS]:
            oid = old.get(label) or f"o{len(out) + 1}"
            while oid in used:
                oid = f"o{secrets.token_hex(2)}"
            used.add(oid)
            out.append({"id": oid, "label": label})
        q.options_json = json.dumps(out, ensure_ascii=False)
    sett = {k: str(data.get(k, "")) for k in ("min", "max", "low", "high", "step", "unit", "max_choices")}
    tmp = LiveQuestion(kind=kind, settings_json=json.dumps(sett))
    q.settings_json = json.dumps(settings(tmp), ensure_ascii=False)
    chart = data.get("chart")
    q.chart = chart if chart in KINDS[kind][2] else KINDS[kind][2][0]
    q.show_results = data.get("show_results") if data.get("show_results") in SHOW_RESULTS else "immediate"
    return ""


# --- Antworten -------------------------------------------------------------------------------------

def read_answer(q: LiveQuestion, raw) -> tuple[dict | None, str]:
    """Antwort eines Geräts prüfen. raw: dict aus JSON."""
    raw = raw if isinstance(raw, dict) else {}
    ids = {o["id"] for o in opts(q)}
    if q.kind in ("single", "yesno"):
        choice = str(raw.get("o", ""))
        return ({"o": choice}, "") if choice in ids else (None, "Bitte eine Antwort wählen.")
    if q.kind == "multi":
        chosen = [str(x) for x in (raw.get("o") or []) if str(x) in ids] if isinstance(raw.get("o"), list) else []
        chosen = list(dict.fromkeys(chosen))
        mx = settings(q)["max_choices"]
        if not chosen:
            return None, "Bitte mindestens eine Antwort wählen."
        if len(chosen) > mx:
            return None, f"Bitte höchstens {mx} Antworten wählen."
        return {"o": chosen}, ""
    if q.kind in ("scale", "stars", "slider"):
        s = settings(q)
        try:
            n = float(str(raw.get("n", "")).replace(",", "."))
        except ValueError:
            return None, "Bitte einen Wert wählen."
        if not s["min"] <= n <= s["max"]:
            return None, "Der Wert liegt außerhalb der Skala."
        return {"n": int(n) if q.kind != "slider" or n.is_integer() else round(n, 2)}, ""
    return None, "Unbekannte Frageart."


def save_answer(db, poll: LivePoll, q: LiveQuestion, device: str, value: dict) -> LiveAnswer:
    """Eine Antwort je Gerät und Frage – erneutes Antworten ändert die eigene Antwort."""
    a = db.scalar(select(LiveAnswer).where(LiveAnswer.question_id == q.id, LiveAnswer.device == device))
    if a is None:
        a = LiveAnswer(poll_id=poll.id, question_id=q.id, device=device)
        db.add(a)
    a.value_json = json.dumps(value, ensure_ascii=False)
    return a


def my_answers(db, poll: LivePoll, device: str) -> dict[int, dict]:
    out = {}
    for a in db.scalars(select(LiveAnswer).where(LiveAnswer.poll_id == poll.id, LiveAnswer.device == device)):
        try:
            out[a.question_id] = json.loads(a.value_json or "{}")
        except ValueError:
            pass
    return out


# --- Auswertung ------------------------------------------------------------------------------------

def tally(db, q: LiveQuestion) -> dict:
    """Ergebnis einer Frage: {total, rows: [{label, count, pct}], stats: {avg, median, min, max}}."""
    values = []
    for raw in db.scalars(select(LiveAnswer.value_json).where(LiveAnswer.question_id == q.id,
                                                             LiveAnswer.hidden.is_(False))):
        try:
            values.append(json.loads(raw or "{}"))
        except ValueError:
            continue
    total = len(values)
    out: dict = {"total": total, "rows": [], "stats": {}}
    if q.kind in ("single", "multi", "yesno"):
        counts = {o["id"]: 0 for o in opts(q)}
        for v in values:
            chosen = v.get("o")
            for c in (chosen if isinstance(chosen, list) else [chosen]):
                if c in counts:
                    counts[c] += 1
        out["rows"] = [{"label": o["label"], "count": counts[o["id"]],
                        "pct": round(100 * counts[o["id"]] / total) if total else 0} for o in opts(q)]
    elif q.kind in ("scale", "stars", "slider"):
        nums = [v["n"] for v in values if isinstance(v.get("n"), (int, float))]
        s = settings(q)
        if q.kind == "slider":
            span = s["max"] - s["min"]
            buckets = 10 if span >= 10 else max(1, int(span))
            width = span / buckets
            counts = [0] * buckets
            for n in nums:
                counts[min(buckets - 1, int((n - s["min"]) / width))] += 1
            out["rows"] = [{"label": f"{s['min'] + i * width:g}–{s['min'] + (i + 1) * width:g}", "count": c,
                            "pct": round(100 * c / total) if total else 0} for i, c in enumerate(counts)]
        else:
            out["rows"] = [{"label": ("★" * i) if q.kind == "stars" else str(i),
                            "count": sum(1 for n in nums if n == i),
                            "pct": round(100 * sum(1 for n in nums if n == i) / total) if total else 0}
                           for i in range(s["min"], s["max"] + 1)]
        if nums:
            out["stats"] = {"avg": round(statistics.fmean(nums), 2), "median": statistics.median(nums),
                            "min": min(nums), "max": max(nums), "unit": s.get("unit", "")}
    return out


def visible_to_participants(q: LiveQuestion) -> bool:
    return q.show_results == "immediate" or (q.show_results == "release" and q.released)


def question_payload(db, q: LiveQuestion, mine: dict | None = None, staff: bool = False) -> dict:
    """Frage für die Teilnehmer- bzw. Präsentationsansicht (JSON)."""
    data = {"id": q.id, "kind": q.kind, "title": q.title, "options": opts(q), "settings": settings(q),
            "chart": q.chart, "locked": q.locked, "answered": mine is not None, "mine": mine}
    if staff or (mine is not None and visible_to_participants(q)):
        data["results"] = tally(db, q)
    if staff:
        data["show_results"], data["released"] = q.show_results, q.released
    return data


def state(db, poll: LivePoll, device: str | None = None, staff: bool = False) -> dict:
    """Zustand für die Teilnehmerseite (Abfrage alle paar Sekunden) bzw. die Präsentation."""
    mine = my_answers(db, poll, device) if device else {}
    if poll.pacing == "moderated" and not staff:
        current = next((q for q in poll.questions if q.id == poll.current_id), None)
        shown = [current] if current else []
    else:
        shown = list(poll.questions)
    return {"status": poll.status, "pacing": poll.pacing, "title": poll.title, "current": poll.current_id,
            "questions": [question_payload(db, q, mine.get(q.id), staff) for q in shown],
            "participants": len(set(db.scalars(select(LiveAnswer.device).where(LiveAnswer.poll_id == poll.id))))}


def step(poll: LivePoll, direction: int) -> LiveQuestion | None:
    """Moderation: zur nächsten (1) bzw. vorigen (-1) Frage."""
    qs = poll.questions
    if not qs:
        return None
    idx = next((i for i, q in enumerate(qs) if q.id == poll.current_id), -1)
    idx = max(0, min(len(qs) - 1, idx + direction)) if idx >= 0 else 0
    poll.current_id = qs[idx].id
    return qs[idx]

