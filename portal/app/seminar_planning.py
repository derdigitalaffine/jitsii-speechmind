"""Calendar planning in local time; preview and save use the same validation."""
import calendar
import json
from datetime import date, datetime, timedelta
from fastapi import HTTPException
from . import seminars as sm


def day(value):
    try:return date.fromisoformat(str(value))
    except (TypeError, ValueError):raise HTTPException(422, 'Bitte ein gültiges Datum auswählen.')


def easter(year):
    a=year%19;b=year//100;c=year%100;d=b//4;e=b%4;f=(b+8)//25;g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30;i=c//4;k=c%4;l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
    return date(year,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)


def holiday(d):
    fixed={(1,1):'Neujahr',(5,1):'Tag der Arbeit',(10,3):'Tag der Deutschen Einheit',(11,1):'Allerheiligen',(12,25):'1. Weihnachtstag',(12,26):'2. Weihnachtstag'}
    return fixed.get((d.month,d.day)) or {easter(d.year)+timedelta(days=n):name for n,name in [(-2,'Karfreitag'),(1,'Ostermontag'),(39,'Christi Himmelfahrt'),(50,'Pfingstmontag'),(60,'Fronleichnam')]}.get(d,'')


def preview(data):
    s=data.get('schedule') or {};kind=s.get('kind','once')
    if kind not in {'once','weekly','fortnightly','monthly','monthly_weekday','dates'}:raise HTTPException(422,'Unbekannte Wiederholung.')
    first=day(s.get('first'));duration=sm.integer(s.get('duration',60),1,10080)
    try:clock=datetime.strptime(str(s.get('time','09:00')),'%H:%M').time()
    except ValueError:raise HTTPException(422,'Bitte eine gültige Uhrzeit eingeben.')
    count=sm.integer(s.get('count',6),1,100);until=day(s.get('until')) if s.get('end_mode')=='until' else None
    if until and (until<first or until>first+timedelta(days=366*5)):raise HTTPException(422,'Enddatum muss innerhalb von fünf Jahren ab Beginn liegen.')
    nth=sm.integer(s.get('nth',1),-1,5);weekday=sm.integer(s.get('weekday',0),0,6)
    if kind=='monthly_weekday' and nth==0:raise HTTPException(422,'Bitte erste bis fünfte oder letzte Woche auswählen.')
    dates=[];skipped=[]
    if kind=='dates':
        raw=s.get('dates',[])
        if not isinstance(raw,list) or len(raw)>100:raise HTTPException(422,'Maximal 100 einzelne Termine auswählen.')
        candidates=sorted({day(v) for v in raw})
    elif kind=='once':candidates=[first]
    else:
        candidates=[]
        for n in range(520):
            if kind in {'weekly','fortnightly'}:d=first+timedelta(days=n*(14 if kind=='fortnightly' else 7))
            else:
                y=first.year+(first.month-1+n)//12;m=(first.month-1+n)%12+1
                if y>first.year+5:break
                if kind=='monthly':d=date(y,m,min(first.day,calendar.monthrange(y,m)[1]))
                else:
                    days=[v for v in range(1,calendar.monthrange(y,m)[1]+1) if date(y,m,v).weekday()==weekday]
                    if nth>len(days):continue
                    d=date(y,m,days[nth-1] if nth>0 else days[-1])
                if d<first:continue
            if until and d>until:break
            candidates.append(d)
            # Count means scheduled occurrences; holidays may reduce the preview.
            if not until and len(candidates)>=count:break
    for d in candidates:
        if s.get('skip_holidays') and holiday(d):skipped.append(d.isoformat());continue
        dates.append(d)
    if len(dates)>100:raise HTTPException(422,'Die Auswahl enthält mehr als 100 Termine. Bitte Zeitraum verkürzen.')
    locations=data.get('locations') or ['']
    if not isinstance(locations,list) or len(locations)>20:raise HTTPException(422,'Maximal 20 wechselnde Orte.')
    locations=[str(v).strip()[:500] for v in locations] or ['']
    terms=[]
    for i,d in enumerate(dates):
        start=datetime.combine(d,clock);end=start+timedelta(minutes=duration)
        # Validate nonexistent local times using the common portal converter.
        sm.parse_time(start.isoformat(timespec='minutes'));sm.parse_time(end.isoformat(timespec='minutes'))
        terms.append(dict(starts_at=start.isoformat(timespec='minutes'),ends_at=end.isoformat(timespec='minutes'),title='',location=locations[i%len(locations)],holiday=holiday(d),include=True))
    warnings=['Schulferien sind nicht automatisch hinterlegt. Bitte Ferien und örtliche Schließtage bei Bedarf prüfen.']
    if skipped:warnings.append(f'{len(skipped)} Feiertagstermine ausgelassen: '+', '.join(skipped))
    return {'terms':terms,'warnings':warnings}


def guests(raw):
    if not isinstance(raw,list) or len(raw)>30:raise HTTPException(422,'Maximal 30 externe Dozenten.')
    result=[]
    for g in raw:
        if not isinstance(g,dict):raise HTTPException(422,'Ungültiger externer Dozent.')
        name=str(g.get('name','')).strip()[:255];email=str(g.get('email','')).strip().lower()[:255]
        if not name:continue
        if email and not sm.re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email):raise HTTPException(422,'E-Mail-Adresse eines externen Dozenten ist ungültig.')
        result.append(dict(name=name,email=email,organization=str(g.get('organization','')).strip()[:255],lead=bool(g.get('lead')),save=bool(g.get('save'))))
    return result


def json_object(raw):
    try:value=json.loads(raw or '{}')
    except (ValueError,TypeError):return {}
    return value if isinstance(value,dict) else {}
