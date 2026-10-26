"""Real-browser task flows and responsive/theme screenshots, run by the browser CI job."""
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from playwright.sync_api import expect, sync_playwright

BASE='http://127.0.0.1:8765'
OUTPUT=Path('survey-browser-artifacts')
OUTPUT.mkdir(exist_ok=True)


def no_horizontal_scroll(page):
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Page overflows horizontally'


def capture(page,name):
    page.screenshot(path=str(OUTPUT/(name+'.png')),full_page=True,animations='disabled')


def exercise(page):
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE+'/login')
    page.get_by_label('E-Mail',exact=True).fill('browser@example.org')
    page.get_by_label('Passwort',exact=True).fill('browser-test-password')
    page.get_by_role('button',name='Anmelden',exact=True).click()
    page.goto(BASE+'/umfragen')
    expect(page.get_by_role('heading',name='Umfragen & Abstimmungen',exact=True)).to_be_visible()
    expect(page.locator('main')).not_to_contain_text('Eigenständiges Formular')
    assert page.locator('main .btn-primary:visible').count()==1
    capture(page,'surveys-desktop')
    page.get_by_role('link',name='Neu erstellen',exact=True).click()
    expect(page.locator('main input[name="title"]')).to_have_count(0)
    capture(page,'survey-create-desktop')
    page.get_by_role('button',name='Live-Umfrage vorbereiten',exact=True).click()
    expect(page.locator('#qnew-single-t')).to_be_visible()
    base=re.search(r'/votes/live/\d+',page.url)[0]
    page.locator('#qnew-single-t').fill('Pizza oder Pasta?')
    page.locator('#qnew-single-o').fill('Pizza')
    page.get_by_role('button',name='Frage hinzufügen',exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('mindestens zwei')
    expect(page.locator('#qnew-single-t')).to_have_value('Pizza oder Pasta?')
    expect(page.locator('#qnew-single-o')).to_have_value('Pizza')
    page.locator('#qnew-single-o').fill('Pizza\nPasta')
    page.get_by_role('button',name='Frage hinzufügen',exact=True).click()
    expect(page.get_by_role('heading',name='Pizza oder Pasta?',exact=True)).to_be_visible()
    page.get_by_role('link',name='Einstellungen',exact=True).click()
    page.get_by_label('Titel',exact=True).fill('Unser Teamabend')
    page.get_by_role('button',name='Einstellungen speichern',exact=True).click()
    page.get_by_role('link',name='Fragen',exact=True).click()
    page.get_by_role('link',name='Wortwolke (Begriffe sammeln)',exact=True).click()
    page.locator('#qnew-words-t').fill('Was wünschen Sie sich?')
    page.get_by_role('button',name='Frage hinzufügen',exact=True).click()
    capture(page,'live-questions-desktop')
    page.get_by_role('link',name='Teilnahme',exact=True).click()
    join=page.locator('#live-share-link').input_value()
    capture(page,'live-share-desktop')
    page.get_by_role('link',name='Durchführung',exact=True).click()
    page.get_by_role('button',name='Teilnahme starten',exact=True).click()
    expect(page.locator('#lm-title')).to_have_text('Pizza oder Pasta?')
    expect(page.get_by_role('button',name='Vorige Frage',exact=True)).to_be_disabled()
    guest_context=page.context.browser.new_context(viewport={'width':390,'height':844})
    guest=guest_context.new_page()
    guest.goto(join)
    guest.get_by_role('button',name='Pizza',exact=True).click()
    expect(guest.get_by_text('Antwort gespeichert.',exact=True)).to_be_visible()
    expect(page.locator('#lm-count')).to_have_text('1 Antworten',timeout=10000)
    capture(page,'live-moderation-desktop')
    page.get_by_role('button',name='Nächste Frage',exact=True).focus()
    page.keyboard.press('Enter')
    expect(page.locator('#lm-title')).to_have_text('Was wünschen Sie sich?')
    expect(page.get_by_role('button',name='Nächste Frage',exact=True)).to_be_disabled()
    guest.get_by_label('Begriff 1',exact=True).fill('Zusammenhalt')
    guest.get_by_role('button',name='Absenden',exact=True).click()
    expect(guest.get_by_text('Antwort gespeichert.',exact=True)).to_be_visible()
    capture(guest,'live-participation-mobile')
    page.get_by_role('link',name='Beiträge aktualisieren',exact=True).click()
    expect(page.locator('main')).to_contain_text('Zusammenhalt')
    page.set_viewport_size({'width':390,'height':844})
    no_horizontal_scroll(page)
    capture(page,'live-moderation-mobile')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_attribute('data-bs-theme','dark')
    capture(page,'live-moderation-mobile-dark')
    page.get_by_role('link',name='Ergebnisse',exact=True).click()
    expect(page.locator('main')).to_contain_text('Zusammenhalt')
    with page.expect_download() as download:
        page.get_by_role('link',name='CSV herunterladen',exact=True).last.click()
    assert 'Zusammenhalt' in Path(download.value.path()).read_text(encoding='utf-8-sig')
    no_horizontal_scroll(page)
    capture(page,'live-results-mobile-dark')
    page.emulate_media(color_scheme='light')
    page.set_viewport_size({'width':1440,'height':1000})
    with page.expect_popup() as popup:
        page.get_by_role('link',name=re.compile('Präsentieren')).click()
    presenter=popup.value
    expect(presenter.locator('#lp-title')).to_have_text('Was wünschen Sie sich?')
    presenter.locator('#lp-prev').click()
    expect(presenter.locator('#lp-title')).to_have_text('Pizza oder Pasta?')
    capture(presenter,'live-presentation-desktop')
    presenter.close()
    page.goto(BASE+base+'?tab=build')
    page.set_viewport_size({'width':390,'height':844})
    for kind in ('scale','slider','quiz','rank','qa','open','multi','stars','yesno'):
        page.goto(BASE+base+'?tab=build&kind='+kind+'#neu')
        no_horizontal_scroll(page)
        expect(page.locator('#qnew-'+kind+'-t')).to_be_visible()
    capture(page,'live-question-editor-mobile')
    page.goto(BASE+'/votes/new?simple=1')
    no_horizontal_scroll(page)
    expect(page.locator('#sec-anonymous')).to_be_checked()
    expect(page.locator('#acc-public')).to_be_checked()
    page.locator('#v-title').fill('Entscheidung zum Ausflug')
    page.get_by_label('Frage',exact=True).fill('Wohin fahren wir?')
    page.get_by_role('button',name='Abstimmung anlegen',exact=True).click()
    expect(page.get_by_role('heading',name='Entscheidung zum Ausflug',exact=True)).to_be_visible()
    for label in ('Teilnahme','Durchführung','Ergebnisse','Einstellungen'):
        page.get_by_role('link',name=label,exact=True).click()
        no_horizontal_scroll(page)
    capture(page,'vote-settings-mobile')
    page.goto(BASE+'/umfragen')
    no_horizontal_scroll(page)
    capture(page,'surveys-mobile')
    page.goto(BASE+'/forms')
    expect(page.locator('main')).to_contain_text('Eigenständiges Formular')
    assert not errors, '\n'.join(errors)
    guest_context.close()


with tempfile.TemporaryDirectory(prefix='takt-browser-') as root:
    env={**os.environ,'DATA_DIR':root+'/data','RECORDINGS_DIR':root+'/recordings','CADDY_CONF_DIR':root+'/caddy',
         'PORTAL_ROOMS_FILE':root+'/rooms.json','PORTAL_CHAT_DIR':root+'/chat'}
    with (OUTPUT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','survey_ui_app:app','--app-dir','tests/browser',
                                 '--host','127.0.0.1','--port','8765','--lifespan','off'],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            for attempt in range(60):
                try:
                    if httpx.get(BASE+'/login',timeout=1).status_code==200:break
                except httpx.HTTPError:pass
                if server.poll() is not None:raise RuntimeError('Test server failed to start; see server.log')
                time.sleep(.25)
            else:raise RuntimeError('Test server did not become ready')
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                try:
                    page=browser.new_page(viewport={'width':1440,'height':1000},color_scheme='light',reduced_motion='reduce',accept_downloads=True)
                    try:exercise(page)
                    except Exception:
                        capture(page,'failure')
                        raise
                finally:browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
print('Browser survey flows passed: direct entry, errors, moderator, guest answers, presentation, exports, vote, themes and mobile layouts.')
