"""Voluntary, self-managed profile data. Not an identity or authorization source."""
import json
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .security import encrypt, decrypt

# One allowlist drives storage, profile editing and form-builder choices.
GROUPS = [
 ('Person', [('salutation','Anrede','text',40,'honorific-prefix'),('honorific_prefix','Titel vor dem Namen','text',80,''),('given_name','Vorname','text',100,'given-name'),('middle_name','Weitere Vornamen','text',100,'additional-name'),('family_name','Nachname','text',100,'family-name'),('honorific_suffix','Titel nach dem Namen','text',80,''),('nickname','Rufname','text',100,'nickname'),('birthdate','Geburtsdatum','date',10,'bday'),('gender','Geschlecht / Selbstbezeichnung','text',80,'sex')]),
 ('Kontakt', [('work_phone','Dienstliche Telefonnummer','tel',60,'work tel'),('mobile_phone','Mobiltelefon','tel',60,'mobile tel'),('private_phone','Private Telefonnummer','tel',60,'home tel'),('contact_email','Zusätzliche Kontakt-E-Mail','email',255,'email'),('website','Website','url',500,'url')]),
 ('Privatanschrift', [('home_street','Straße','text',200,'shipping address-line1'),('home_house_no','Hausnummer','text',30,''),('home_zip','Postleitzahl','text',30,'shipping postal-code'),('home_city','Ort','text',200,'shipping address-level2'),('home_district','Ortsteil','text',200,''),('home_region','Bundesland / Region','text',100,'shipping address-level1'),('home_country','Land (zweistelliger ISO-Code, z. B. DE)','text',2,'shipping country')]),
 ('Dienstanschrift', [('work_street','Straße','text',200,'billing address-line1'),('work_house_no','Hausnummer','text',30,''),('work_zip','Postleitzahl','text',30,'billing postal-code'),('work_city','Ort','text',200,'billing address-level2'),('work_district','Ortsteil','text',200,''),('work_region','Bundesland / Region','text',100,'billing address-level1'),('work_country','Land (zweistelliger ISO-Code, z. B. DE)','text',2,'billing country'),('work_location','Dienststätte / Gebäude','text',200,''),('room','Raum','text',60,'')]),
 ('Beschäftigung', [('organization','Organisation / Arbeitgeber','text',200,'organization'),('division','Bereich','text',200,''),('department','Abteilung','text',200,''),('job_title','Funktion / Stellenbezeichnung','text',200,'organization-title'),('employee_number','Personalnummer','text',80,''),('cost_center','Kostenstelle','text',80,''),('employment_type','Beschäftigungsart','text',100,''),('manager_name','Vorgesetzte Person (Angabe ohne Rechtewirkung)','text',200,'')]),
 ('Bankverbindung', [('account_holder','Kontoinhaber:in','text',200,''),('iban','IBAN','text',34,''),('bic','BIC','text',11,''),('bank_name','Bank','text',200,'')]),
 ('Sprache und Zeitzone', [('locale','Sprachkennung, z. B. de-DE','text',35,'language'),('zoneinfo','Zeitzone, z. B. Europe/Berlin','text',100,'')]),
]
FIELDS = {f[0]: f for _, fields in GROUPS for f in fields}


def read(user):
    try:
        value = json.loads(decrypt(getattr(user, 'profile_data_enc', None)) or '{}')
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if (k in FIELDS and isinstance(v, str)) or (k == 'prefill_enabled' and isinstance(v, bool))}


def clean(raw):
    values = {'prefill_enabled': raw.get('prefill_enabled') in ('1', True)}
    for key, (_, label, kind, limit, _) in FIELDS.items():
        value = str(raw.get(key) or '').strip()
        if not value:
            continue
        if key == 'iban':
            value = value.replace(' ', '').upper()
        if len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError(f'„{label}“ ist zu lang oder enthält ungültige Zeichen.')
        if kind == 'date':
            try:
                parsed = date.fromisoformat(value)
                if parsed > date.today():
                    raise ValueError()
                value = parsed.isoformat()
            except ValueError:
                raise ValueError('Bitte ein gültiges Geburtsdatum in der Vergangenheit angeben.') from None
        if kind == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Bitte eine gültige Kontakt-E-Mail angeben.')
        if kind == 'url' and not re.fullmatch(r'https?://[^\s/]+(?:/[^\s]*)?', value):
            raise ValueError('Bitte eine Website mit https:// oder http:// angeben.')
        if key.endswith('_country'):
            value = value.upper()
            if not re.fullmatch('[A-Z]{2}', value):
                raise ValueError('Länder bitte als zweistelligen ISO-Code angeben, z. B. DE.')
        if key == 'locale' and not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', value):
            raise ValueError('Bitte eine Sprachkennung wie de-DE angeben.')
        if key == 'zoneinfo':
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError('Bitte eine bekannte Zeitzone wie Europe/Berlin angeben.') from None
        if key == 'iban':
            value = value.replace(' ', '').upper()
            if not re.fullmatch(r'[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}', value):
                raise ValueError('Bitte eine gültige IBAN angeben.')
            digits = ''.join(str(ord(c)-55) if c.isalpha() else c for c in value[4:]+value[:4])
            if int(digits) % 97 != 1:
                raise ValueError('Die Prüfziffer der IBAN stimmt nicht.')
        if key == 'bic':
            value = value.upper()
            if not re.fullmatch(r'[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?', value):
                raise ValueError('Bitte eine gültige BIC mit 8 oder 11 Zeichen angeben.')
        values[key] = value
    return values


def store(raw):
    return encrypt(json.dumps(clean(raw), ensure_ascii=False))


def options():
    text = [{'label': 'Konto', 'options': [['name','Anzeigename'], ['email','Anmelde-E-Mail']]}]
    for label, fields in GROUPS:
        text.append({'label': label, 'options': [[key, title] for key, title, *_ in fields]})
    addresses = [['home_address','Privatanschrift'], ['work_address','Dienstanschrift']]
    text.append({'label': 'Zusammengesetzte Anschriften', 'options': addresses})
    return {'short': text, 'long': text, 'date': [{'label':'Person','options':[['birthdate','Geburtsdatum']]}], 'address':[{'label':'Anschriften','options':addresses}]}


def allowed(kind, key):
    return any(key == option[0] for group in options().get(kind, []) for option in group['options'])


def defaults(items, values, user):
    result = dict(values or {})
    if user is None:
        return result
    data = read(user)
    for item in items:
        key, kind = item.get('profile_value'), item.get('type')
        if item['id'] in result or not allowed(kind, key):
            continue
        if key in ('name', 'email'):
            result[item['id']] = getattr(user, key, '') or ''
        elif data.get('prefill_enabled'):
            if key in ('home_address', 'work_address'):
                prefix = key.split('_')[0]
                parts = {p: data.get(prefix+'_'+p, '') for p in ('street','house_no','zip','city','district')}
                if not any(parts.values()):
                    continue
                if kind == 'address':
                    if item.get('mode') == 'zip_city':
                        parts['street'] = parts['house_no'] = ''
                    if not item.get('district'):
                        parts['district'] = ''
                    result[item['id']] = parts
                else:
                    result[item['id']] = ', '.join(p for p in (' '.join(filter(None,[parts['street'],parts['house_no']])), ' '.join(filter(None,[parts['zip'],parts['city']])), parts['district'], data.get(prefix+'_country','')) if p)
            elif data.get(key):
                result[item['id']] = data[key]
    return result
