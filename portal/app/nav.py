"""Hauptmenü im angemeldeten Portal: Einträge, Gruppen und persönliche Anpassung (Favoriten, ausgeblendete Gruppen).

Sechs Aufgabenbereiche mit Kontextnavigation und persönlichen Favoriten.
Expansion und ausgeblendete Bereiche werden im Benutzerkonto gespeichert.
"""

import json
from dataclasses import dataclass
from typing import Callable

GROUPS = {
    "work": "Mein Arbeitsplatz",
    "service": "Formulare & Vorgänge",
    "schedule": "Termine & Räume",
    "comm": "Kommunikation",
    "know": "Wissen & Dokumente",
    "admin": "Administration",
}
MAX_FAVORITES = 12


@dataclass
class Ctx:
    user: object
    path: str
    modules: set
    shared: set
    task_badge: int
    dms_nav: bool
    res_nav: bool
    krank_nav: dict

    def can(self, perm: str) -> bool:
        return self.user.can(perm)

    @property
    def admin(self) -> bool:
        return bool(self.user.is_admin)


@dataclass
class Item:
    id: str
    group: str
    url: str
    icon: str
    label: str
    show: Callable[[Ctx], bool]
    active: Callable[[str], bool]
    badge: Callable[[Ctx], tuple[int, str]] | None = None


def _pre(*prefixes: str) -> Callable[[str], bool]:
    return lambda p: any(p == x or p.startswith(x.rstrip("/") + "/") for x in prefixes)


def _is(*paths: str) -> Callable[[str], bool]:
    return lambda p: p in paths


def _forms_active(p: str) -> bool:
    return p == "/forms" or (p.startswith("/forms/") and not p.startswith(("/forms/inbox", "/forms/blocks"))
                             and "/applications" not in p)


def _apps(c: Ctx) -> bool:
    return "applications" in c.modules and "forms" in c.modules


def _tasks_badge(c: Ctx) -> tuple[int, str]:
    return c.task_badge, (f"{c.task_badge} offene Aufgaben" if c.task_badge else "")


def _absence_badge(c: Ctx) -> tuple[int, str]:
    from sqlalchemy import func, select
    from .db import Absence, SessionLocal
    with SessionLocal() as db:
        n = db.scalar(select(func.count(Absence.id)).where(Absence.substitute_id == c.user.id, Absence.status == "pending")) or 0
    return n, (f"{n} Bitte(n) um Vertretung" if n else "")


def _krank_badge(c: Ctx) -> tuple[int, str]:
    n = c.krank_nav.get("badge", 0)
    return n, (f"{n} neue Meldungen bzw. offene eAU-Abrufe" if n else "")


ITEMS: list[Item] = [
    # Mein Arbeitsplatz
    Item("tasks", "work", "/tasks", "fa-list-check", "Meine Aufgaben",
         lambda c: _apps(c) or c.res_nav or "circulations" in c.modules, _pre("/tasks"), _tasks_badge),
    Item("inbox", "work", "/forms/inbox", "fa-inbox", "Zum Ausfüllen", lambda c: "forms" in c.modules, _pre("/forms/inbox")),
    Item("absences", "work", "/abwesenheiten", "fa-umbrella-beach", "Abwesenheiten", lambda c: True,
         _pre("/abwesenheiten"), lambda c: _absence_badge(c)),
    Item("krank_me", "work", "/krank", "fa-notes-medical", "Krank melden", lambda c: bool(c.krank_nav),
         lambda p: p == "/krank" or (p.startswith("/krank/") and not p.startswith("/krank/meine"))),
    Item("krank_mine", "work", "/krank/meine", "fa-folder-open", "Meine Krankmeldungen", lambda c: bool(c.krank_nav),
         _pre("/krank/meine")),
    # Bürgerservice
    Item("app_inbox", "service", "/forms/applications", "fa-file-signature", "Antragseingang", _apps,
         lambda p: "/applications" in p),
    Item("processes", "service", "/processes", "fa-diagram-project", "Prozesse",
         lambda c: _apps(c) and c.can("processes"), _pre("/processes")),
    Item("forms", "service", "/forms", "fa-clipboard-list", "Formulare", lambda c: "forms" in c.modules, _forms_active),
    Item("blocks", "service", "/forms/blocks", "fa-cubes", "Datenblöcke",
         lambda c: "forms" in c.modules and c.can("formblocks"), _pre("/forms/blocks")),
    Item("resources", "schedule", "/resources", "fa-building", "Ressourcen & Belegung", lambda c: c.res_nav,
         lambda p: p == "/resources" or (p.startswith("/resources/") and not p.startswith(("/resources/bookings", "/resources/planner")))),
    Item("res_planner", "schedule", "/resources/planner", "fa-table-cells", "Belegungsplaner", lambda c: c.res_nav,
         _pre("/resources/planner")),
    Item("res_bookings", "schedule", "/resources/bookings", "fa-calendar-check", "Raumbuchungen", lambda c: c.res_nav,
         _pre("/resources/bookings")),
    Item("bookings", "schedule", "/bookings", "fa-calendar-plus", "Terminbuchung",
         lambda c: "bookings" in c.modules and (c.can("bookings") or "bookings" in c.shared), _pre("/bookings")),
    Item("krank_staff", "service", "/krankmelder", "fa-user-nurse", "Krankmeldungen",
         lambda c: bool(c.krank_nav.get("staff")), _pre("/krankmelder"), _krank_badge),
    # Kommunikation
    Item("circulations", "comm", "/umlaeufe", "fa-bullhorn", "Umläufe & Aushänge",
         lambda c: "circulations" in c.modules, lambda p: p.startswith(("/umlaeufe", "/sammelmappen"))),
    Item("meetings", "comm", "/meetings", "fa-video", "Meetings", lambda c: c.can("video"),
         lambda p: (p == "/meetings" or p.startswith("/meetings/")) and p != "/meetings/plan"),
    Item("meeting_plan", "comm", "/meetings/plan", "fa-calendar-plus", "Besprechung planen", lambda c: c.can("video"),
         _is("/meetings/plan")),
    Item("polls", "comm", "/polls", "fa-calendar-check", "Terminumfragen",
         lambda c: "polls" in c.modules and (c.can("polls") or "polls" in c.shared), _pre("/polls")),
    Item("votes", "comm", "/votes", "fa-check-to-slot", "Abstimmungen",
         lambda c: "polls" in c.modules and (c.can("votes") or "votes" in c.shared), _pre("/votes")),
    Item("shortlinks", "comm", "/shortlinks", "fa-link", "Kurzlinks & QR-Codes",
         lambda c: "shortlinks" in c.modules and c.can("shortlinks"), _pre("/shortlinks")),
    # Wissen & Ablage
    Item("dms", "know", "/dms", "fa-box-archive", "Ablage: Recherche",
         lambda c: "dms" in c.modules and (c.admin or c.can("dms_admin") or c.dms_nav),
         lambda p: p == "/dms" or p.startswith(("/dms/r/", "/dms/new"))),
    Item("dms_persons", "know", "/dms/persons", "fa-address-book", "Ablage: Personen",
         lambda c: "dms" in c.modules and (c.admin or c.can("dms_admin") or c.dms_nav), _pre("/dms/persons")),
    Item("dms_areas", "know", "/dms/areas", "fa-sitemap", "Aktenplan",
         lambda c: "dms" in c.modules and (c.admin or c.can("dms_admin")), _pre("/dms/areas", "/dms/retention")),
    Item("recht", "know", "/recht", "fa-scale-balanced", "Ortsrecht", lambda c: "laws" in c.modules, _pre("/recht")),
    Item("laws", "know", "/laws", "fa-pen-to-square", "Rechtstexte pflegen",
         lambda c: "laws" in c.modules and c.can("laws"), _pre("/laws")),
    Item("map", "know", "/karte", "fa-map-location-dot", "Kartenbrowser", lambda c: "maps" in c.modules, _pre("/karte")),
    Item("maps", "know", "/maps", "fa-folder-open", "Meine Karten", lambda c: "maps" in c.modules,
         _pre("/maps")),
    # Verwaltung
    Item("users", "admin", "/admin/users", "fa-users", "Benutzer & Gruppen", lambda c: c.can("users"), _is("/admin/users")),
    Item("orgs", "admin", "/admin/orgs", "fa-landmark-flag", "Körperschaften", lambda c: c.can("orgs"), _pre("/admin/orgs")),
    Item("payments", "admin", "/payments", "fa-euro-sign", "Zahlungen", lambda c: c.can("payments"), _pre("/payments")),
    Item("expense_rules", "admin", "/settings/expense-rules", "fa-calculator", "Reisekostensätze", lambda c: c.admin, _pre("/settings/expense-rules")),
    Item("locations", "know", "/settings/locations", "fa-location-dot", "Orte und Fahrtstrecken", lambda c: "forms" in c.modules, _pre("/settings/locations")),
    Item("map_layers", "admin", "/admin/maps", "fa-layer-group", "Kartenlayer", lambda c: c.can("maps_admin"),
         _pre("/admin/maps")),
    Item("recordings", "admin", "/admin/recordings", "fa-file-audio", "Aufnahmen", lambda c: c.admin,
         lambda p: p == "/admin/recordings" or p.startswith("/recordings")),
    Item("modules", "admin", "/admin/modules", "fa-puzzle-piece", "Module", lambda c: c.admin, _is("/admin/modules")),
    Item("design", "admin", "/admin/design", "fa-palette", "Design & Branding", lambda c: c.admin, _is("/admin/design")),
    Item("public_nav", "admin", "/admin/oeffentlich", "fa-signs-post", "Öffentliches Menü", lambda c: c.admin,
         _is("/admin/oeffentlich")),
    Item("notifications", "admin", "/admin/notifications", "fa-envelope", "Benachrichtigungen", lambda c: c.admin,
         _pre("/admin/notifications")),
    Item("mail_templates", "admin", "/admin/templates", "fa-envelope-open-text", "E-Mail-Vorlagen", lambda c: c.admin,
         _is("/admin/templates")),
    Item("pay_settings", "admin", "/admin/payments", "fa-credit-card", "PayPal & Bankverbindung", lambda c: c.admin,
         _is("/admin/payments")),
    Item("sessions", "admin", "/admin/sessions", "fa-user-clock", "Sitzungen & Cookies", lambda c: c.admin,
         _is("/admin/sessions")),
    Item("https", "admin", "/admin/https", "fa-shield-halved", "HTTPS & Zertifikat", lambda c: c.admin, _pre("/admin/https")),
    Item("domains", "admin", "/admin/domains", "fa-globe", "Domains", lambda c: c.admin, _pre("/admin/domains")),
    Item("speechmind", "admin", "/admin/speechmind", "fa-wand-magic-sparkles", "SpeechMind", lambda c: c.admin,
         _is("/admin/speechmind")),
    Item("trash", "admin", "/admin/loeschen", "fa-trash-can", "Löschen & Papierkorb", lambda c: c.admin,
         _pre("/admin/loeschen")),
]
ITEMS.append(Item("oidc", "admin", "/admin/oidc", "fa-key", "Nextcloud / OIDC-Anmeldung", lambda c: c.admin, _pre("/admin/oidc")))
ITEMS.append(Item("seminars", "schedule", "/seminare", "fa-chalkboard-user", "Seminare & Lehrgänge", lambda c: "seminars" in c.modules, _pre("/seminare")))
ITEMS.append(Item("circulation_reports", "work", "/umlaeufe/auswertung", "fa-chart-column", "Meine Umläufe & Rückmeldungen", lambda c: "circulations" in c.modules, _pre("/umlaeufe/auswertung")))
BY_ID = {it.id: it for it in ITEMS}
CONTEXTS = [("resources", "res_planner", "res_bookings"), ("meetings", "meeting_plan"), ("dms", "dms_persons", "dms_areas"), ("recht", "laws"), ("map", "maps"), ("krank_me", "krank_mine")]
CONTEXT_ONLY = {i for group in CONTEXTS for i in group[1:]}
ADMIN_SECTIONS = {
    "Menschen & Organisation": ["users", "orgs", "recordings"],
    "Finanzen": ["payments", "expense_rules", "pay_settings"],
    "Integrationen & Versand": ["oidc", "map_layers", "notifications", "mail_templates", "speechmind"],
    "Portal & System": ["modules", "design", "public_nav", "sessions", "https", "domains", "trash"],
}


def prefs(user) -> dict:
    """Persönliche Einstellungen: {"fav": [Eintrag, …], "hidden": [Gruppe, …]}."""
    try:
        data = json.loads(getattr(user, "nav_json", "") or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ('fav','hidden','closed'):
        if key in data and not isinstance(data[key],list): data.pop(key)
        elif key in data: data[key]=[v for v in data[key] if isinstance(v,str)]
    fav = [i for i in data.get("fav", []) if i in BY_ID][:MAX_FAVORITES]
    hidden = [g for g in data.get("hidden", []) if g in GROUPS]
    return {"fav": list(dict.fromkeys(fav)), "hidden": hidden, "closed": [g for g in data.get("closed", [g for g in GROUPS if g != "work"]) if g in GROUPS]}


def dump(fav: list[str], hidden: list[str], closed=None) -> str:
    fav = list(dict.fromkeys(i for i in fav if i in BY_ID))[:MAX_FAVORITES]
    data = {"fav": fav, "hidden": [g for g in dict.fromkeys(hidden) if g in GROUPS]}
    if closed is not None: data["closed"] = list(dict.fromkeys(g for g in closed if g in GROUPS))
    return json.dumps(data)


def _entry(it: Item, c: Ctx, fav: set) -> dict:
    badge, title = it.badge(c) if it.badge else (0, "")
    label = "Geteilte Formulare" if it.id == "forms" and not c.can("forms") else it.label
    return {"id": it.id, "url": it.url, "icon": it.icon, "label": label, "active": it.active(c.path),
            "context_only": it.id in CONTEXT_ONLY, "badge": badge, "badge_title": title, "fav": it.id in fav}


def visible(c: Ctx) -> list[Item]:
    return [it for it in ITEMS if it.show(c)]


def build(c: Ctx) -> dict:
    """Menü für die Vorlage: Favoriten, sichtbare Gruppen (nur mit Einträgen), Zahl ausgeblendeter Gruppen."""
    p = prefs(c.user)
    fav = set(p["fav"])
    items = visible(c)
    entries = {it.id: _entry(it, c, fav) for it in items}
    # Bei mehreren passenden Einträgen nur den genauesten markieren (z. B. /forms/inbox nicht auch /forms)
    hits = [e for e in entries.values() if e["active"]]
    if len(hits) > 1:
        best = max(hits, key=lambda e: len(e["url"]))
        for e in hits:
            e["active"] = e is best
    groups, hidden = [], 0
    for key, label in GROUPS.items():
        rows = [entries[it.id] for it in items if it.group == key]
        if not rows:
            continue
        if key in p["hidden"] and not any(r["active"] for r in rows):
            hidden += 1
            continue
        groups.append({"key": key, "label": label, "items": rows, "sections": [{"label": title, "items": [r for r in rows if r["id"] in ids]} for title, ids in ADMIN_SECTIONS.items()] if key == "admin" else []})
    favorites = [entries[i] for i in p["fav"] if i in entries]
    context = []
    for family in CONTEXTS:
        if any(entries[i]["active"] for i in family if i in entries):
            context = [entries[i] for i in family if i in entries]
            break
    return {"groups": groups, "favorites": favorites, "hidden": hidden, "closed": p["closed"], "context": context}


def options(c: Ctx) -> list[dict]:
    """Für „Menü anpassen“: alle Gruppen mit ihren für die Person sichtbaren Einträgen."""
    p = prefs(c.user)
    items = visible(c)
    out = []
    for key, label in GROUPS.items():
        rows = [{"id": it.id, "label": it.label, "icon": it.icon, "fav": it.id in p["fav"]} for it in items if it.group == key]
        if rows:
            out.append({"key": key, "label": label, "hidden": key in p["hidden"], "items": rows})
    return out
