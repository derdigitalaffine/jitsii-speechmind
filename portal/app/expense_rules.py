"""Versioned, time-valid reimbursement profiles shared by form and request fields."""
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from .db import ExpenseRuleSet, SessionLocal, utcnow
from .form_fields import number
from .routing import CATEGORIES

SOURCE='https://www.lff.rlp.de/fachliche-themen/reisemanagement/reisekosten'
LABELS={
 'private_car':'Privat-Pkw ohne triftigen Grund (€/km)', 'private_car_reason':'Privat-Pkw mit triftigem Grund (€/km)',
 'recognized_car':'Anerkannter Privat-Pkw (€/km)', 'company_car':'Dienstfahrzeug (€/km)',
 'motorcycle':'Motorrad ohne triftigen Grund (€/km)', 'motorcycle_reason':'Motorrad mit triftigem Grund (€/km)',
 'bicycle':'Fahrrad (€/km)', 'walk':'Zu Fuß (€/km)', 'public_transport':'ÖPNV (€/km)',
 'recognized_limit':'Anerkannter Privat-Pkw: Grenze Jahreskilometer (0 = keine Staffel)', 'recognized_after':'Anerkannter Privat-Pkw: Satz oberhalb der Grenze (€/km)',
 'day8':'Tagegeld bei mehr als 8 Stunden (€)', 'day14':'Tagegeld ab 14 Stunden (€)', 'day24':'Tagegeld voller Kalendertag (€)',
 'local_day':'Tagegeld am Dienstort (€)', 'training_factor':'Faktor Ausbildungsreise',
 'breakfast_fraction':'Frühstück: Anteil des zustehenden Tagegelds', 'lunch_fraction':'Mittagessen: Anteil', 'dinner_fraction':'Abendessen: Anteil',
 'breakfast_min':'Sachbezugswert Frühstück (€)', 'lunch_min':'Sachbezugswert Mittagessen (€)', 'dinner_min':'Sachbezugswert Abendessen (€)',
 'overnight':'Übernachtungspauschale ohne Nachweis (€)'}
# Proposal only, never silently active. HR must review applicability and less common cases.
PROPOSAL={'private_car':'0.18','private_car_reason':'0.28','recognized_car':'0.38','company_car':'0',
 'motorcycle':'0.10','motorcycle_reason':'0.15','bicycle':'0.05','walk':'0','public_transport':'0',
 'recognized_limit':'10000','recognized_after':'0.28',
 'day8':'8','day14':'14','day24':'24','local_day':'2.05','training_factor':'0.70',
 'breakfast_fraction':'0.20','lunch_fraction':'0.40','dinner_fraction':'0.40',
 'breakfast_min':'2.37','lunch_min':'4.57','dinner_min':'4.57','overnight':'0'}


def money(value):return Decimal(value).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
def text_money(value):return f'{money(value):.2f}'


def validate(raw):
    rates={}
    for key in LABELS:
        n=number(raw.get(key))
        upper=Decimal(1) if key.endswith('_fraction') or key=='training_factor' else Decimal(100000000) if key=='recognized_limit' else Decimal(10000)
        if n is None or not 0<=n<=upper:raise ValueError(f'Bitte einen gültigen Satz für „{LABELS[key]}“ angeben.')
        rates[key]=str(n)
    return rates


def save(db,raw,actor):
    try:start=date.fromisoformat(str(raw.get('valid_from') or ''));end=date.fromisoformat(str(raw.get('valid_until') or ''))
    except ValueError:raise ValueError('Gültigkeitszeitraum angeben.') from None
    if end<start:raise ValueError('Ungültiger Gültigkeitszeitraum.')
    if raw.get('reviewed')!='1':raise ValueError('Sätze und Anwendbarkeit ausdrücklich prüfen und bestätigen.')
    profile=str(raw.get('profile') or 'rlp').strip()[:40]
    if not profile.replace('_','').isalnum():raise ValueError('Ungültiger Profilname.')
    overlap=db.scalar(select(ExpenseRuleSet).where(ExpenseRuleSet.profile==profile,ExpenseRuleSet.valid_from<=end,ExpenseRuleSet.valid_until>=start))
    if overlap and (raw.get('supersede')!='1' or not str(raw.get('change_reason') or '').strip()):raise ValueError('Gültigkeit überschneidet eine bestehende Fassung. Ersetzung ausdrücklich bestätigen und begründen.')
    name=str(raw.get('name') or 'Reisekostensätze').strip()[:200]
    row=ExpenseRuleSet(profile=profile,name=name,valid_from=start,valid_until=end,rates_json=json.dumps(validate(raw)),source=(str(raw.get('source') or SOURCE)+'; Änderungsgrund: '+str(raw.get('change_reason') or 'Erstfassung'))[:1000],reviewed_by=actor.id)
    db.add(row);db.flush();return row


def for_date(db,profile,day):
    row=db.scalar(select(ExpenseRuleSet).where(ExpenseRuleSet.profile==profile,ExpenseRuleSet.valid_from<=day,ExpenseRuleSet.valid_until>=day).order_by(ExpenseRuleSet.id.desc()))
    if not row:raise ValueError(f'Für {day:%d.%m.%Y} fehlt eine geprüfte Satzfassung ({profile}). Personalabteilung informieren.')
    return row


def clean(raw):
    from .form_fields import ID
    keys=('period_source','route_source','costs_source','days_source','advance_source','reason_source','special_source','year_km_source')
    return {key:str(raw.get(key) or '') if ID.fullmatch(str(raw.get(key) or '')) else '' for key in keys}|{'profile':str(raw.get('profile') or 'rlp')[:40]}


def calculate(item,answers):
    period=answers.get(item['period_source'])
    if not isinstance(period,dict):raise ValueError('Tatsächlichen Reisezeitraum angeben.')
    start,end=datetime.fromisoformat(period['start']),datetime.fromisoformat(period['end'])
    if end<start or (end-start).days>366:raise ValueError('Reisezeitraum muss innerhalb eines Jahres liegen.')
    daily=answers.get(item['days_source']) or []
    day_rows={}
    for row in daily:
        day=date.fromisoformat(row['date'])
        if not start.date()<=day<=end.date() or day in day_rows:raise ValueError('Tagesangaben müssen eindeutig im Reisezeitraum liegen.')
        day_rows[day]=row
    reasons=answers.get(item['reason_source']) or []
    has_reason=bool(reasons)
    special=answers.get(item['special_source']) or []
    foreign='Auslandsreise' in special
    reviews=['Berechnungsvorschlag: sachlich und rechnerisch prüfen; steuerliche Bewertung durch die Personalabteilung.']
    if start.date()!=end.date():reviews.append('Mehrtagereise: An-/Abreisetage, erforderliche Übernachtungen und gegebenenfalls Mitternachtsregel gesondert prüfen.')
    if special:reviews.append('Besonderheiten prüfen: '+', '.join(special))
    route=answers.get(item['route_source']) or {}
    if route.get('has_deviation'):reviews.append('Begründete Kilometerabweichungen ausdrücklich genehmigen.')
    year_km=number(answers.get(item['year_km_source'])) if answers.get(item['year_km_source']) not in (None,'') else None
    snapshots={};mileage=[];days=[];costs=[];km_total=Decimal(0);day_total=Decimal(0);cost_total=Decimal(0);lodging_total=Decimal(0)
    with SessionLocal() as db:
        def rates(day):
            r=for_date(db,item['profile'],day)
            snapshots[str(r.id)]={'id':r.id,'name':r.name,'profile':r.profile,'valid_from':r.valid_from.isoformat(),'valid_until':r.valid_until.isoformat(),'source':r.source,'rates':json.loads(r.rates_json),'reviewed_by':r.reviewed_by,'reviewed_at':r.created_at.isoformat()}
            return {k:Decimal(v) for k,v in snapshots[str(r.id)]['rates'].items()},r.id
        for index,leg in enumerate(route.get('legs',[]),1):
            day=date.fromisoformat(leg.get('date') or start.date().isoformat())
            if not start.date()<=day<=end.date():raise ValueError('Fahrtabschnitt liegt außerhalb der tatsächlichen Reise.')
            r,version=rates(day);category=leg['quote']['category'];key=category+'_reason' if has_reason and category in ('private_car','motorcycle') else category
            if category=='recognized_car':reviews.append('Anerkennung der dienstlichen Nutzung des Privat-Pkw und gegebenenfalls Jahreskilometerstaffel prüfen.')
            km=Decimal(leg['meters'])/1000;rate=r.get(key,Decimal(0));amount=money(km*rate)
            lower_km=Decimal(0)
            if category=='recognized_car' and r['recognized_limit']>0:
                if year_km is None or year_km<0:raise ValueError('Bitte bisherige dienstliche Jahreskilometer des anerkannten Privat-Pkw angeben.')
                high_km=min(km,max(Decimal(0),r['recognized_limit']-year_km));lower_km=km-high_km
                amount=money(high_km*rate+lower_km*r['recognized_after']);year_km+=km
            km_total+=amount
            mileage.append({'leg':index,'date':str(day),'category':category,'km':str(km),'rate':str(rate),'lower_km':str(lower_km),'lower_rate':str(r.get('recognized_after',0)),'amount':str(amount),'rule_id':version})
        cursor=start.date()
        while cursor<=end.date():
            r,version=rates(cursor);row=day_rows.get(cursor,{})
            a=max(start,datetime.combine(cursor,time.min));b=min(end,datetime.combine(cursor+timedelta(days=1),time.min));hours=Decimal(str((b-a).total_seconds()/3600))
            private_hours=number(row.get('private_hours') or 0)
            if private_hours is None or not 0<=private_hours<=hours:raise ValueError('Private Stunden müssen innerhalb der Tagesabwesenheit liegen.')
            hours-=private_hours
            base=r['day24'] if hours>=24 else r['day14'] if hours>=14 else r['day8'] if hours>8 else Decimal(0)
            if row.get('local') and hours>8:base=r['local_day']
            if row.get('home') or row.get('private') or foreign:base=Decimal(0)
            if row.get('training'):base=money(base*r['training_factor'])
            deductions=Decimal(0)
            for meal in ('breakfast','lunch','dinner'):
                if row.get(meal):deductions+=max(money(base*r[meal+'_fraction']),r[meal+'_min'])
            net=max(Decimal(0),money(base-deductions));day_total+=net
            nights=number(row.get('nights') or 0)
            if nights is None or not 0<=nights<=1:raise ValueError('Höchstens eine pauschale Übernachtung pro Tag.')
            lodging=money(nights*r['overnight']) if not row.get('free_lodging') and not row.get('private') and not foreign else Decimal(0)
            if nights and any(c.get('kind')=='Hotel' and c.get('date')==str(cursor) for c in answers.get(item['costs_source']) or []):raise ValueError('Übernachtungspauschale und Hotelkosten am gleichen Tag nicht doppelt abrechnen.')
            lodging_total+=lodging
            days.append({'date':str(cursor),'hours':str(hours.quantize(Decimal('.01'))),'base':str(base),'meal_deduction':str(min(base,deductions)),'amount':str(net),'lodging':str(lodging),'rule_id':version})
            cursor+=timedelta(days=1)
        for index,row in enumerate(answers.get(item['costs_source']) or [],1):
            raw=number(row.get('amount'));paid=number(row.get('third_party') or 0)
            if raw is None or paid is None or not 0<=paid<=raw:raise ValueError('Bereits bezahlter Kostenanteil muss zwischen 0 und dem Kostenbetrag liegen.')
            day=date.fromisoformat(row['date']);r,version=rates(day)
            kind=row.get('kind');amount=money(raw-paid);deduction=Decimal(0)
            if kind=='Parken' and not has_reason and any(l['category']=='private_car' for l in mileage):
                reviews.append('Parkgebühren ohne triftigen Grund ausgeschlossen; gemischte Verkehrsmittel prüfen.');amount=Decimal(0)
            if kind=='Hotel' and not row.get('employer_meals'):
                for meal in ('breakfast','lunch','dinner'):
                    if row.get(meal):deduction+=money(r['day24']*r[meal+'_fraction'])
                amount=max(Decimal(0),amount-deduction)
            if kind=='Hotel' and row.get('employer_meals'):reviews.append('Hotel: gestellte Mahlzeiten am jeweiligen Verpflegungstag erfassen; keine doppelte Kürzung.')
            if not row.get('receipt') and not row.get('missing'):raise ValueError(f'Kostenposition {index}: fehlenden Beleg begründen.')
            if not row.get('receipt'):reviews.append(f'Kostenposition {index}: Beleg fehlt – Ersatzbegründung prüfen.')
            if day<start.date() or day>end.date():reviews.append(f'Kostenposition {index}: Vorbereitungs-/Stornokosten außerhalb des Reisezeitraums prüfen.')
            cost_total+=amount;costs.append({'position':index,'kind':kind,'date':str(day),'description':row.get('description',''),'receipt':row.get('receipt',False),'missing':row.get('missing',''),'shared':row.get('shared',''),'gross':str(raw),'third_party':str(paid),'deduction':str(deduction),'amount':str(amount),'rule_id':version})
    if foreign:reviews.append('Auslandsreise: ausländische Tages-/Übernachtungssätze werden nicht pauschal geraten; geprüfte Beträge über Kostenpositionen und Entscheidungsvermerk erfassen.')
    if (end-start).days>=14:reviews.append('Längerfristiger Aufenthalt und steuerliche Dreimonatsfrist gesondert prüfen.')
    advance=number(answers.get(item['advance_source']) or 0)
    if advance is None or advance<0:raise ValueError('Ungültiger Vorschuss.')
    total=money(km_total+day_total+cost_total+lodging_total-advance)
    return {'profile':item['profile'],'calculated_at':utcnow().isoformat(),'rule_snapshots':list(snapshots.values()),'mileage':mileage,'days':days,'costs':costs,
            'mileage_total':text_money(km_total),'day_total':text_money(day_total),'lodging_total':text_money(lodging_total),'cost_total':text_money(cost_total),'advance':text_money(advance),'total':str(total),'review_notes':list(dict.fromkeys(reviews))}


def display(item,value):
    if not isinstance(value,dict):return ''
    lines=['Berechnungsvorschlag für die Personalabteilung; kein Auszahlungsnachweis.']
    for rule in value.get('rule_snapshots',[]):lines.append(f"Satzfassung #{rule['id']}: {rule['name']} ({rule['valid_from']} – {rule['valid_until']})")
    for leg in value.get('mileage',[]):lines.append(f"{leg['date']} · Abschnitt {leg['leg']} · {CATEGORIES.get(leg['category'],(leg['category'],))[0]}: {leg['km']} km × {leg['rate']} € = {leg['amount']} €"+(f"; davon {leg.get('lower_km')} km zum Staffelsatz {leg.get('lower_rate')} €" if Decimal(leg.get('lower_km','0')) else ''))
    for day in value.get('days',[]):lines.append(f"{day['date']} · {day['hours']} Stunden: Tagegeld {day['base']} €, Mahlzeitenabzug {day['meal_deduction']} €, verbleiben {day['amount']} €, Übernachtung {day['lodging']} €")
    for cost in value.get('costs',[]):lines.append(f"{cost['date']} · Position {cost['position']} ({cost['kind']}, {cost.get('description','')}): {cost['gross']} €, Drittzahlung {cost['third_party']} €, Kürzung {cost['deduction']} €, Ansatz {cost['amount']} €"+(f"; fehlender Beleg: {cost.get('missing','')}" if not cost.get('receipt') else '')+(f"; gemeinsamer Beleg: {cost['shared']}" if cost.get('shared') else ''))
    lines.extend([f"Kilometer: {value['mileage_total']} € · Tagegeld: {value['day_total']} € · Übernachtungspauschale: {value['lodging_total']} € · Belege: {value['cost_total']} €",f"Abzüglich Vorschuss: {value['advance']} €",f"Berechneter Erstattungsbetrag: {value['total']} €"])
    lines.extend(value.get('review_notes',[]));return '\n'.join(lines)
