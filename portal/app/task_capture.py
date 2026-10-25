"""Small German parser: proposals only, never writes or guesses ambiguous people."""
import re
from datetime import datetime, timedelta
from .db import to_local, utcnow

WEEKDAYS = ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag']
PRIORITY = {'dringend': 'urgent', 'hoch': 'high', 'mittel': 'normal', 'normal': 'normal', 'niedrig': 'low'}


def parse(text, people, user_id, *, now=None):
    original = text.strip()
    rest = original
    today = to_local(now or utcnow()).date()
    result = dict(title=original, assignee_id=str(user_id), priority='normal', tags='', due_date='', due_time='')
    notices, candidates = [], []
    tag_names = re.findall(r'(?<!\S)#([\w-]{1,40})(?=\s|$)', rest)
    if tag_names:
        result['tags'] = ','.join(dict.fromkeys(tag_names))
        rest = re.sub(r'(?<!\S)#[\w-]{1,40}(?=\s|$)', '', rest)
    priority = re.search(r'(?<!\S)!(' + '|'.join(PRIORITY) + r')(?=\s|$)', rest, re.I)
    if priority:
        result['priority'] = PRIORITY[priority[1].lower()]
        rest = rest[:priority.start()] + rest[priority.end():]
    # Full names can be quoted. Unquoted @Anna matches both first and complete names.
    mention = re.search(r'(?<!\S)@(?:"([^"]+)"|([\w.\-]+))', rest)
    if mention:
        name = (mention[1] or mention[2]).casefold()
        candidates = [u for u in people if u.name.casefold() == name or u.name.casefold().split()[0] == name or u.email.casefold() == name]
        if len(candidates) == 1:
            result['assignee_id'] = str(candidates[0].id)
            rest = rest[:mention.start()] + rest[mention.end():]
        else:
            result['assignee_id'] = ''
            notices.append('Der Name ist mehrdeutig. Bitte die verantwortliche Person auswählen.' if candidates else 'Zum Namen gibt es keinen aktiven Treffer. Bitte eine Person auswählen; der Name bleibt im Text erhalten.')
    date_pattern = r'(?<!\w)(?:bis\s+)?(übermorgen|morgen|heute|(?:nächsten?\s+)?(?:' + '|'.join(WEEKDAYS) + r')|\d{1,2}\.\d{1,2}\.(?:\d{4})?)(?!\w)'
    date_match = re.search(date_pattern, rest, re.I)
    if date_match:
        token = date_match[1].lower()
        try:
            if token in {'heute', 'morgen', 'übermorgen'}:
                day = today + timedelta(days={'heute': 0, 'morgen': 1, 'übermorgen': 2}[token])
            elif token.split()[-1] in WEEKDAYS:
                delta = (WEEKDAYS.index(token.split()[-1]) - today.weekday()) % 7
                # "nächsten" means the next occurrence, including next week on the same weekday.
                day = today + timedelta(days=delta or 7)
            else:
                pieces = token.rstrip('.').split('.')
                explicit = len(pieces) == 3
                day = datetime(int(pieces[2]) if explicit else today.year, int(pieces[1]), int(pieces[0])).date()
                if not explicit and day < today:
                    day = day.replace(year=day.year + 1)
            result['due_date'] = day.isoformat()
            rest = rest[:date_match.start()] + rest[date_match.end():]
        except ValueError:
            notices.append('Das Datum ist ungültig. Bitte die Fälligkeit korrigieren; der ursprüngliche Text bleibt erhalten.')
    clock = re.search(r'(?<![\w:])(?:um\s+)?(\d{1,2})(?:(?::(\d{2}))(?:\s*Uhr)?|\s*Uhr)(?!\w)', rest, re.I)
    if clock:
        hour, minute = int(clock[1]), int(clock[2] or 0)
        if hour < 24 and minute < 60 and result['due_date']:
            result['due_time'] = f'{hour:02d}:{minute:02d}'
            rest = rest[:clock.start()] + rest[clock.end():]
        else:
            notices.append('Zur Uhrzeit fehlt ein gültiges Datum oder die Uhrzeit ist ungültig. Bitte unten korrigieren.')
    result['title'] = re.sub(r'\s+', ' ', rest).strip() or original
    return result, notices, candidates
