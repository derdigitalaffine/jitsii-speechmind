"""Gesetzliche Feiertage je Bundesland (berechnet, inkl. Ostern) und eigene Tage (z. B. Kerwe) – für Wochenend-
und Feiertagspreise der Ressourcenbuchung."""

from datetime import date, timedelta
from functools import lru_cache

STATES = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg", "HB": "Bremen", "HH": "Hamburg",
    "HE": "Hessen", "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz", "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt", "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}


def easter(year: int) -> date:
    """Ostersonntag (gregorianisch, Gauß/Meeus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _buss_und_bettag(year: int) -> date:
    d = date(year, 11, 23)
    while d.weekday() != 2:   # Mittwoch vor dem 23. November
        d -= timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def legal(year: int, state: str = "RP") -> dict[date, str]:
    e = easter(year)
    days = {
        date(year, 1, 1): "Neujahr", e - timedelta(days=2): "Karfreitag", e + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit", e + timedelta(days=39): "Christi Himmelfahrt",
        e + timedelta(days=50): "Pfingstmontag", date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 12, 25): "1. Weihnachtsfeiertag", date(year, 12, 26): "2. Weihnachtsfeiertag",
    }
    if state in ("BW", "BY", "ST"):
        days[date(year, 1, 6)] = "Heilige Drei Könige"
    if state in ("BE", "MV"):
        days[date(year, 3, 8)] = "Internationaler Frauentag"
    if state in ("BB",):
        days[e] = "Ostersonntag"
        days[e + timedelta(days=49)] = "Pfingstsonntag"
    if state in ("BW", "BY", "HE", "NW", "RP", "SL"):
        days[e + timedelta(days=60)] = "Fronleichnam"
    if state in ("SL", "BY"):
        days[date(year, 8, 15)] = "Mariä Himmelfahrt"
    if state == "TH":
        days[date(year, 9, 20)] = "Weltkindertag"
    if state in ("BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"):
        days[date(year, 10, 31)] = "Reformationstag"
    if state in ("BW", "BY", "NW", "RP", "SL"):
        days[date(year, 11, 1)] = "Allerheiligen"
    if state == "SN":
        days[_buss_und_bettag(year)] = "Buß- und Bettag"
    return dict(sorted(days.items()))


def special_days(db, year: int) -> dict[date, str]:
    """Gesetzliche Feiertage des eingestellten Bundeslands plus eigene Tage."""
    from sqlalchemy import extract, select

    from .db import CustomHoliday, get_settings
    state = get_settings(db).get("holiday_state", "RP")
    out = dict(legal(year, state if state in STATES else "RP"))
    for h in db.scalars(select(CustomHoliday).where(extract("year", CustomHoliday.day) == year)):
        out[h.day] = h.name
    return out


def is_special(day: date, specials: dict[date, str]) -> bool:
    """Wochenende (Sa/So) oder Feiertag."""
    return day.weekday() >= 5 or day in specials
