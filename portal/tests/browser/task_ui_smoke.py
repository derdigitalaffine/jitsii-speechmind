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
OUTPUT=Path('browser-artifacts')
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
    expect(page).not_to_have_url(re.compile('/login'))
    page.goto(BASE+'/tasks?view=list')
    expect(page.get_by_role('heading',name='Meine Aufgaben',exact=True)).to_be_visible()
    expect(page.locator('#capture-text')).to_be_visible()
    assert page.locator('.task-page .btn-primary:visible').count()==1
    no_horizontal_scroll(page)
    capture(page,'tasks-desktop')

    page.get_by_role('link',name='Mit Formular anlegen',exact=True).click()
    title='Aufgabe aus dem Formular'
    expect(page.locator('#task-title')).to_be_focused()
    page.keyboard.type(title)
    page.keyboard.press('Tab')
    expect(page.locator('#task-person')).to_be_focused()
    page.locator('#task-description').fill('Beschreibung und Unterlagen vor dem ersten Speichern prüfen.')
    page.locator('#task-date').fill((datetime.now(ZoneInfo('Europe/Berlin')).date()+timedelta(days=3)).isoformat())
    page.locator('#task-checklist').fill('Unterlagen sammeln\nZahlen prüfen')
    page.locator('#task-initial-files').set_input_files([
        {'name':'Unterlagen.txt','mimeType':'text/plain','buffer':b'Unterlagen fuer den Browser-Test'},
        {'name':'Notizen.txt','mimeType':'text/plain','buffer':b'Notizen'}])
    expect(page.locator('#task-file-feedback')).to_contain_text('2 Dateien ausgewählt')
    capture(page,'task-form-desktop')
    page.set_viewport_size({'width':390,'height':844})
    no_horizontal_scroll(page)
    capture(page,'task-form-mobile-light')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_attribute('data-bs-theme','dark')
    capture(page,'task-form-mobile-dark')
    page.emulate_media(color_scheme='light')
    page.get_by_role('button',name='Aufgabe anlegen',exact=True).click()
    expect(page).to_have_url(re.compile(r'/tasks\?view=list$'))
    expect(page.locator('.alert').filter(has_text=title)).to_be_visible()
    no_horizontal_scroll(page)
    page.get_by_role('link',name=title,exact=True).click()
    task_id=re.search(r'/aufgaben/(\d+)',page.url).group(1)
    expect(page.get_by_text('Unterlagen sammeln',exact=True)).to_be_visible()
    expect(page.get_by_text('Zahlen prüfen',exact=True)).to_be_visible()
    expect(page.get_by_role('link',name='Notizen.txt',exact=True)).to_be_visible()
    with page.expect_download() as downloaded:
        page.get_by_role('link',name='Unterlagen.txt',exact=True).click()
    assert Path(downloaded.value.path()).read_bytes()==b'Unterlagen fuer den Browser-Test'
    capture(page,'task-detail-mobile')

    page.set_viewport_size({'width':1440,'height':1000})
    page.goto(BASE+'/tasks?view=board')
    select=page.locator('#board-status-'+task_id)
    select.select_option('in_progress')
    select.focus()
    page.keyboard.press('Tab')
    page.keyboard.press('Enter')
    expect(page.locator('[data-task-column="in_progress"]').get_by_role('link',name=title,exact=True)).to_be_visible()
    capture(page,'task-board-desktop')
    page.set_viewport_size({'width':390,'height':844})
    no_horizontal_scroll(page)
    capture(page,'task-board-mobile')
    page.goto(BASE+'/tasks?view=calendar&period=week')
    expect(page.get_by_role('group',name='Kalenderdarstellung',exact=True)).to_be_visible()
    no_horizontal_scroll(page)
    capture(page,'task-calendar-mobile')

    page.goto(BASE+'/tasks?view=list')
    page.locator('#capture-text').fill('Schnell erfasst bis morgen')
    page.locator('#capture-text').press('Enter')
    expect(page.get_by_role('heading',name='Kurz prüfen, dann loslegen',exact=True)).to_be_visible()
    assert page.locator('.task-page .btn-primary:visible').count()==1
    page.get_by_role('button',name='Aufgabe anlegen',exact=True).click()
    expect(page).to_have_url(re.compile(r'/tasks\?view=list$'))
    expect(page.get_by_role('link',name='Schnell erfasst',exact=True)).to_be_visible()
    assert not errors, '\n'.join(errors)


with tempfile.TemporaryDirectory(prefix='takt-browser-') as root:
    env={**os.environ,'DATA_DIR':root+'/data','RECORDINGS_DIR':root+'/recordings','CADDY_CONF_DIR':root+'/caddy',
         'PORTAL_ROOMS_FILE':root+'/rooms.json','PORTAL_CHAT_DIR':root+'/chat'}
    with (OUTPUT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','task_ui_app:app','--app-dir','tests/browser',
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
print('Browser task flows passed: form, files, checklist, quick capture, keyboard, themes and mobile layouts.')
