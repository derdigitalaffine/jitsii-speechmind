"""An editable ready-made template using the general forms and process engine."""
import json
from . import forms, workflow
from .db import Form, Process

REASONS=['Ziel mit öffentlichen Verkehrsmitteln nicht oder schwer erreichbar','Erhebliche Zeitersparnis für dringende Dienstgeschäfte','Umfangreiches oder schweres dienstliches Gepäck','Fahrgemeinschaft spart Kosten','Öffentliche Verkehrsmittel aus persönlichen Gründen unzumutbar','Sonstiger zwingender Grund']
SPECIAL=['Auslandsreise','Privater Reiseanteil','Reise abgebrochen','Reise ausgefallen / Stornokosten','Längerfristiger Aufenthalt']


def question(qid,kind,title,**extra):return {'id':qid,'type':kind,'title':title,**extra}
def selection(qid,title,options,**extra):return question(qid,'checkbox',title,options=[{'label':x} for x in options],**extra)
def col(key,label,kind='text',**extra):return {'id':key,'label':label,'type':kind,**extra}


def application_items():
    return forms.clean_schema([
      question('intro','text','Dienstreise beantragen',description='Die Reise wird grundsätzlich ab Dienststätte geplant. Abweichende Start-/Zielpunkte begründen. Jede Person stellt einen eigenen Antrag und rechnet ihre eigenen Kosten ab.'),
      question('employee','short','Name',required=True),question('mail','short','Dienstliche E-Mail-Adresse',subtype='email',required=True),
      question('personnel','short','Personalnummer'),question('department','short','Dienststelle / Organisationseinheit',required=True),
      question('office','short','Reguläre Dienststätte',required=True),question('purpose','long','Anlass und Dienstgeschäft',required=True),
      question('area','radio','Reisegebiet',required=True,options=[{'label':x} for x in ['Innerhalb des Landkreises','Außerhalb des Landkreises','Ausland']]),
      question('planned','period','Geplanter Reisezeitraum',required=True),question('business','period','Geplanter Zeitraum des Dienstgeschäfts',required=True,within_source='planned'),
      question('planned_route','route','Geplante Fahrtstrecken',required=True),selection('grounds','Gründe für private Fahrzeugnutzung',REASONS),
      question('other_ground','long','Sonstigen zwingenden Grund erläutern',show_if={'rules':[{'q':'grounds','op':'contains','value':'Sonstiger zwingender Grund'}]},required_if={'rules':[{'q':'grounds','op':'contains','value':'Sonstiger zwingender Grund'}]}),
      question('recognition','short','Anerkennung des Privat-Pkw (Datum / Aktenzeichen)',description='Bei anerkanntem Privat-Pkw ausfüllen. Die Anerkennung betrifft Ihr Privatfahrzeug, kein Fahrzeug des Arbeitgebers.'),
      question('companions','table','Mitreisende / Fahrgemeinschaft',columns=[col('name','Name',required=True),col('role','Rolle (Fahrer / Mitfahrer)'),col('case','Eigener Antrag / Aktenzeichen')]),
      question('deviation','long','Abweichender Start / Ziel, Streckenwahl oder Reisebesonderheiten begründen'),
      question('estimate','short','Voraussichtliche Gesamtkosten (€)',subtype='number',min=0),
      question('truth','declaration','Angaben bestätigen',required=True,statement='Ich bestätige ausdrücklich, dass meine Angaben richtig und vollständig sind. Ich beantrage die Genehmigung der Dienstreise und der angegebenen Verkehrsmittel.')])


def accounting_items():
    daily=[col('date','Datum','date',required=True),col('breakfast','Frühstück unentgeltlich / gestellt','checkbox'),col('lunch','Mittagessen unentgeltlich / gestellt','checkbox'),col('dinner','Abendessen unentgeltlich / gestellt','checkbox'),col('free_lodging','Unterkunft kostenlos gestellt','checkbox'),col('nights','Übernachtung ohne Nachweis (0 oder 1)','number',min='0',max='1'),col('training','Ausbildungsreise (70 %)','checkbox'),col('private','Privater Tag ohne Anspruch','checkbox'),col('private_hours','Private Stunden / Stunden am Wohnort','number',min='0',max='24'),col('local','Aufenthalt am Dienstort','checkbox'),col('home','Aufenthalt am Wohnort','checkbox')]
    costs=[col('date','Kosten-/Übernachtungsdatum','date',required=True),col('kind','Kostenart','select',required=True,options=['Ticket','Hotel','Parken','Maut','Taxi','Kursgebühr','Sonstige','Geprüfter Auslands-/Sonderbetrag']),col('description','Beschreibung / Belegnummer',required=True),col('amount','Gesamtbetrag (€)','amount',required=True,min='0'),col('third_party','Bereits durch Arbeitgeber / Dritte bezahlt (€)','amount',min='0'),col('receipt','Beleg vorhanden','checkbox'),col('missing','Fehlenden Beleg begründen'),col('breakfast','Hotel: Frühstück enthalten, nicht einzeln ausgewiesen','checkbox'),col('lunch','Hotel: Mittagessen enthalten','checkbox'),col('dinner','Hotel: Abendessen enthalten','checkbox'),col('employer_meals','Mahlzeiten vom Arbeitgeber veranlasst (am Verpflegungstag erfassen)','checkbox'),col('shared','Gemeinsamer Beleg / Antrag anderer Person')]
    return forms.clean_schema([
      question('actual','period','Tatsächlicher Reisezeitraum',required=True,prefill_from='planned'),
      question('actual_business','period','Tatsächliches Dienstgeschäft',required=True,prefill_from='business',within_source='actual'),
      question('pause','short','Mittagspause (Minuten, optional)',subtype='number',min=0,description='Keine automatische Kürzung von Reisezeit oder Tagegeld.'),
      question('actual_route','route','Tatsächliche Fahrtstrecken',prefill_from='planned_route'),
      selection('actual_grounds','Gründe private Fahrzeugnutzung (genehmigter Stand)',REASONS,prefill_from='grounds'),
      question('actual_recognition','short','Anerkennung Privat-Pkw',prefill_from='recognition'),
      selection('special','Besonderheiten der Abrechnung',SPECIAL),question('special_note','long','Reiseabweichungen, private Anteile, Abbruch oder Stornierung erläutern'),
      question('days','table','Verpflegung und Übernachtung je Tag',columns=daily,max_rows=100,period_source='actual',description='Tage aus dem tatsächlichen Zeitraum ergänzen. Gestellte Mahlzeiten werden nur einmal erfasst. Bei Hotel mit Arbeitgeberveranlassung hier die Mahlzeiten angeben. Pauschale Übernachtung nur ohne bereits abgerechnete Hotelkosten.'),
      question('costs','table','Kostenpositionen',columns=costs,max_rows=100,description='Nur den eigenen Kostenanteil angeben. Gemeinsame Belege einem Antrag zuordnen. Sonstige fremdfinanzierte Anteile werden abgezogen.'),
      question('receipts','file','Belege hochladen',max_files=10,description='PDF oder Originaldateien; Belegnummer den Kostenpositionen zuordnen.'),
      question('advance','short','Erhaltener Vorschuss (€)',subtype='number',min=0),
      question('year_km','short','Bisherige dienstliche Jahreskilometer des anerkannten Privat-Pkw',subtype='number',min=0,description='Für eine gegebenenfalls konfigurierte Staffel. Personalabteilung prüft den Jahresstand.'),
      question('accounting','expense_accounting','Berechnung für die Personalabteilung',period_source='actual',route_source='actual_route',costs_source='costs',days_source='days',advance_source='advance',reason_source='actual_grounds',special_source='special',year_km_source='year_km',profile='rlp'),
      question('accounting_truth','declaration','Abrechnung ausdrücklich bestätigen',required=True,statement='Ich bestätige ausdrücklich die Richtigkeit und Vollständigkeit meiner Abrechnung. Ich habe nur meine eigenen erstattungsfähigen Kosten geltend gemacht und Vorschüsse, gestellte Mahlzeiten und bereits bezahlte Anteile vollständig angegeben.')])


def definition():
    return workflow.clean_definition({'end_status':'done','end_message':'Ihre Reisekostenabrechnung wurde abgeschlossen. Das Dokument steht für die Personalabteilung bereit. Die Auszahlung wird außerhalb des Portals bearbeitet.', 'steps':[
      {'id':'review_plan','type':'task','name':'Reiseplanung prüfen','assign':{'mode':'case'},'checklist':['Dienstlicher Anlass und Zeitraum plausibel','Start ab Dienststätte oder begründete Abweichung geprüft','Privat-Pkw-Gründe, Anerkennung und voraussichtliche Kosten geprüft'],'fields':[{'key':'query_plan','label':'Planungsangaben nachfordern?','type':'yesno'}]},
      {'id':'query_plan','type':'request','name':'Planung ergänzen','condition':{'source':'f','key':'query_plan','op':'eq','value':'Ja'},'message':'Bitte ergänzen oder korrigieren Sie die Reiseplanung.','reopen':['Anlass und Dienstgeschäft','Geplanter Reisezeitraum','Geplante Fahrtstrecken','Gründe für private Fahrzeugnutzung','Anerkennung des Privat-Pkw (Datum / Aktenzeichen)'],'due_days':14},
      {'id':'approve','type':'approval','name':'Dienstreise und Verkehrsmittel genehmigen','assign':{'mode':'case'},'on_reject':'end','four_eyes':False},
      {'id':'approval_document','type':'auto','name':'Genehmigung dokumentieren','actions':[{'type':'pdf','title':'Dienstreisegenehmigung','public':True,'send':True,'body':'Die beantragte Dienstreise wurde genehmigt.\n\nAnlass: {frage:Anlass und Dienstgeschäft}\nReisezeitraum: {frage:Geplanter Reisezeitraum}\nDienstgeschäft: {frage:Geplanter Zeitraum des Dienstgeschäfts}\nStrecke und Verkehrsmittel: {frage:Geplante Fahrtstrecken}\nGründe: {frage:Gründe für private Fahrzeugnutzung}\nAnerkennung: {frage:Anerkennung des Privat-Pkw (Datum / Aktenzeichen)}\nAbweichungen: {frage:Abweichender Start / Ziel, Streckenwahl oder Reisebesonderheiten begründen}'}]},
      {'id':'account','type':'request','name':'Reise durchführen und abrechnen','public_name':'Reisekostenabrechnung','message':'Nach der Reise erfassen Sie bitte den tatsächlichen Verlauf und Ihre Kosten. Die genehmigte Planung bleibt separat erhalten.','items':accounting_items(),'due_days':180},
      {'id':'review_account','type':'task','name':'Sachlich und rechnerisch prüfen','assign':{'mode':'case'},'checklist':['Tatsächliche Zeit und Kilometerabweichungen geprüft und genehmigt','Triftige Gründe, Anerkennung und Jahreskilometerstaffel bestätigt','Belege, gemeinsame Kostenanteile und fehlende Belege geprüft','Gestellte Mahlzeiten, Unterkunft, Vorschüsse und Drittzahlungen geprüft','Sonderfälle, Auslandsreise, private Anteile und steuerliche Bewertung geprüft'],'fields':[{'key':'query_account','label':'Abrechnung korrigieren lassen?','type':'yesno'},{'key':'decision','label':'Entscheidungs-/Abweichungsvermerk','type':'textarea'},{'key':'approved_total','label':'Festgestellter Erstattungsbetrag (€)','type':'money','required':True},{'key':'payout_note','label':'Auszahlungshinweis (freiwillig)','type':'text'}]},
      {'id':'query_account','type':'request','compose':'clerk','name':'Abrechnung ergänzen / korrigieren','assign':{'mode':'previous'},'condition':{'source':'f','key':'query_account','op':'eq','value':'Ja'},'message':'Bitte die angeforderten Abrechnungsangaben ergänzen.','due_days':14},
      {'id':'final_check','type':'approval','name':'Abrechnung feststellen','assign':{'mode':'case'},'on_reject':'review_account','four_eyes':False},
      {'id':'hr_document','type':'auto','name':'Dokument für Personalabteilung erzeugen','actions':[{'type':'pdf','title':'Reisekostenabrechnung – Personalabteilung','public':True,'send':True,'body':'Name: {name}\nPersonalnummer: {frage:Personalnummer}\nDienststelle: {frage:Dienststelle / Organisationseinheit}\nDienststätte: {frage:Reguläre Dienststätte}\nAnlass: {frage:Anlass und Dienstgeschäft}\n\nGeplanter Zeitraum: {frage:Geplanter Reisezeitraum}\nTatsächlicher Zeitraum: {frage:Tatsächlicher Reisezeitraum}\nTatsächliches Dienstgeschäft: {frage:Tatsächliches Dienstgeschäft}\nMittagspause (freiwillig, Minuten): {frage:Mittagspause (Minuten, optional)}\n\nStrecken: {frage:Tatsächliche Fahrtstrecken}\nGründe: {frage:Gründe private Fahrzeugnutzung (genehmigter Stand)}\nAnerkennung: {frage:Anerkennung Privat-Pkw}\nBesonderheiten: {frage:Besonderheiten der Abrechnung}\nErläuterung: {frage:Reiseabweichungen, private Anteile, Abbruch oder Stornierung erläutern}\n\n{frage:Berechnung für die Personalabteilung}\n\nAusdrückliche Bestätigung: {frage:Abrechnung ausdrücklich bestätigen}\n\nEntscheidungsvermerk: {feld:decision}\nFestgestellter Erstattungsbetrag: {feld:approved_total} EUR\nOptionaler Auszahlungshinweis: {feld:payout_note}\n\nDokument zur Erfassung in der Lohn-/Gehaltssoftware. Ein fehlender Auszahlungshinweis verhindert den Abschluss nicht.'}]}]})


def install(db,user):
    process=Process(name='Dienstreise beantragen und abrechnen',description='Vorlage: Zuständigkeiten prüfen, Satzfassungen konfigurieren, danach Prozess veröffentlichen und Formular aktivieren.',owner_id=user.id,draft_json=json.dumps(definition(),ensure_ascii=False))
    db.add(process);db.flush()
    form=Form(owner_id=user.id,title='Dienstreise beantragen und abrechnen',description='Interner Dienstreiseantrag mit anschließender Reisekostenabrechnung.',internal=True,kind='application',active=False,anonymous=False,process_id=process.id,app_prefix='DR',app_category='Interne Prozesse',app_catalog=False,schema_json=json.dumps(application_items(),ensure_ascii=False),confirm_mail=True,app_pdf=True,notify_pdf=True)
    db.add(form);db.flush();return form,process
