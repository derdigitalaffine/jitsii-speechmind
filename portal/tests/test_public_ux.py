from types import SimpleNamespace as N
from app.main import templates


def status(**changes):
    context = dict(resp=N(ref_no='AZ', status='new', closed_at=None, created_at=None, track_token='token'), form=N(title='Antrag'), statuses={}, progress=[], open_payments=[], confirm_task=None, open_requests=[], documents=[], events=[], questions=[], current={}, corrections={}, applicant='', money=lambda n:str(n))
    context.update(changes)
    template = templates.env.from_string(templates.env.loader.get_source(templates.env, 'application_status.html')[0].replace('{% extends "base.html" %}', ''))
    return template.render(**context)


def payment(state):
    return N(status=state, token=state, amount_cents=100, purpose='Gebühr', due_at=None)


def test_pending_payment_is_not_a_new_payment_request():
    html=status(open_payments=[payment('pending')])
    assert 'Zahlung wird geprüft' in html and 'Bitte nicht erneut bezahlen' in html
    assert 'Jetzt bezahlen' not in html and 'Zahlungsstand ansehen' in html


def test_open_payment_is_single_primary_action():
    html=status(open_payments=[payment('open')])
    assert html.count('class="btn btn-primary"') == 1
    assert 'Jetzt bezahlen' in html


def test_confirmation_has_priority_over_payment():
    html=status(confirm_task=N(due_at=None),open_payments=[payment('open')])
    assert 'Bestätigungslink finden' in html and 'Jetzt bezahlen' not in html
    assert html.count('class="btn btn-primary"') == 1


def test_request_has_priority_over_payment():
    req=N(id=1,title='Ergänzen',due_at=None,message='',items=[],reopen=[])
    html=status(open_requests=[req],open_payments=[payment('open')])
    assert 'Angaben ergänzen' in html and 'Jetzt bezahlen' not in html
    assert html.count('class="btn btn-primary"') == 1


def test_closed_case_does_not_prompt_action():
    html=status(resp=N(ref_no='AZ',status='withdrawn',closed_at=True,created_at=None,track_token='token'),open_payments=[payment('open')])
    assert 'Ihr Antrag ist abgeschlossen' in html
    assert 'Jetzt bezahlen' not in html


def test_error_summary_has_original_labels_escaped_and_file_warning():
    html=templates.env.get_template('_form_error_summary.html').render(errors={'a':'Ungültig'},error_items=[dict(id='a',title='<Name>')])
    assert '&lt;Name&gt;' in html and 'href="#frage-a"' in html
    assert 'Dateien' in html and 'erneut' in html


def test_error_summary_empty_without_errors():
    assert not templates.env.get_template('_form_error_summary.html').render(errors={}).strip()


def test_terminal_status_without_timestamp_does_not_show_old_tasks():
    for terminal in ('approved', 'rejected', 'done', 'withdrawn'):
        html = status(resp=N(ref_no='AZ',status=terminal,closed_at=None,created_at=None,track_token='token'),confirm_task=N(due_at=None),open_payments=[payment('open')])
        assert 'Ihr Antrag ist abgeschlossen' in html
        assert 'Bestätigungslink finden' not in html and 'Zur Zahlung' in html
        assert 'application-message' not in html


def test_full_fill_template_keeps_values_and_links_to_original_question():
    from app import forms
    field=forms.clean_schema([dict(id='a',type='short',title='Ihr Name')])[0]
    source=templates.env.loader.get_source(templates.env,'form_fill.html')[0].replace('{% extends "base.html" %}', '')
    html=templates.env.from_string(source).render(form=N(id=1,title='Test',description='',anonymous=False,expires_at=None),pages=[dict(title='',description='',items=[field])],errors={'a':'Bitte prüfen'},values={'a':'Erhalten'},types=forms.TYPES,other='__other__',page_index=0)
    assert 'value="Erhalten"' in html
    assert 'Ihr Name: Bitte prüfen' in html
    assert 'data-server-error="error-a"' in html


def test_approved_case_with_fee_retains_payment_action_after_decision():
    html=status(resp=N(ref_no='AZ',status='approved',closed_at=True,created_at=None,track_token='token'),open_payments=[payment('open')])
    assert 'Ihr Antrag ist abgeschlossen' in html
    assert 'Die Entscheidung beendet nicht automatisch offene Gebühren' in html
    assert 'href="/pay/open"' in html and 'Zur Zahlung' in html
    assert html.count('class="btn btn-primary"') == 1
    assert 'Sie müssen derzeit nichts tun' not in html


def test_done_case_pending_payment_remains_inspectable_without_repayment():
    html=status(resp=N(ref_no='AZ',status='done',closed_at=True,created_at=None,track_token='token'),open_payments=[payment('pending')])
    assert 'Zahlung wird geprüft' in html and 'href="/pay/pending"' in html
    assert 'Zahlungsstand ansehen' in html and 'Bitte nicht erneut bezahlen' in html
    assert 'Jetzt bezahlen' not in html and 'Zur Zahlung' not in html
