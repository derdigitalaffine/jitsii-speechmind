// Hauptmenü: Scrollposition über Seitenwechsel halten, Gruppen ein-/ausklappen (gemerkt), Menüsuche (Taste / bzw.
// Strg+K), Pfeiltasten, schmale Leiste nur mit Symbolen. Die Zustände liegen in Cookies, damit der Server das Menü
// gleich richtig ausgibt (kein Flackern beim Laden).
(function () {
  'use strict';
  var nav = document.getElementById('app-nav');
  if (!nav) return;
  var scroller = document.getElementById('nav-scroll');
  var aside = document.querySelector('.app-aside');
  var main = document.getElementById('inhalt');
  var search = document.getElementById('nav-search');
  var empty = document.querySelector('.app-nav-empty');
  var YEAR = 365 * 86400;

  function setCookie(name, value) {
    document.cookie = name + '=' + encodeURIComponent(value) + '; Max-Age=' + YEAR + '; Path=/; SameSite=Lax' +
      (location.protocol === 'https:' ? '; Secure' : '');
  }
  function store(key, value) { try { sessionStorage.setItem(key, value); } catch (e) { /* privat: egal */ } }

  // --- Scrollposition: beim Verlassen merken, aktiven Eintrag sichtbar halten -------------------------------
  function remember() { if (scroller) store('jsm-nav-scroll', String(scroller.scrollTop)); }
  window.addEventListener('pagehide', remember);
  nav.addEventListener('click', function (e) { if (e.target.closest('a')) remember(); });
  var active = nav.querySelector('.nav-link.active');
  if (active && scroller) {
    var a = active.getBoundingClientRect(), s = scroller.getBoundingClientRect();
    if (a.top < s.top + 8 || a.bottom > s.bottom - 8) active.scrollIntoView({ block: 'center' });
  }

  // --- Gruppen -------------------------------------------------------------------------------------------
  function closedGroups() {
    return Array.prototype.filter.call(nav.querySelectorAll('.nav-group'), function (g) {
      return !g.classList.contains('is-open') && !g.classList.contains('has-active');
    }).map(function (g) { return g.dataset.group; });
  }
  nav.querySelectorAll('.nav-group-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var g = btn.closest('.nav-group'), open = !g.classList.contains('is-open');
      g.classList.toggle('is-open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      setCookie('jsm_nav_closed', closedGroups().join(','));
    });
  });

  // --- Schmale Leiste ----------------------------------------------------------------------------------
  var railBtn = document.getElementById('nav-rail');
  function applyRail(on) {
    if (aside) aside.classList.toggle('is-rail', on);
    if (main) main.classList.toggle('is-rail', on);
    nav.querySelectorAll('.nav-link').forEach(function (l) { if (on) l.setAttribute('title', l.dataset.label || ''); else l.removeAttribute('title'); });
    if (railBtn) {
      railBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      railBtn.title = on ? 'Menü ausklappen' : 'Menü einklappen';
      railBtn.setAttribute('aria-label', on ? 'Menü ausklappen' : 'Menü auf Symbole verkleinern');
      railBtn.querySelector('i').className = 'fa-solid ' + (on ? 'fa-angles-right' : 'fa-angles-left');
    }
  }
  if (railBtn) {
    applyRail(aside && aside.classList.contains('is-rail'));
    railBtn.addEventListener('click', function () {
      var on = !(aside && aside.classList.contains('is-rail'));
      applyRail(on);
      setCookie('jsm_nav_rail', on ? '1' : '0');
      window.dispatchEvent(new Event('resize'));   // Karten, Kalender und Tabellen passen ihre Breite an
    });
  }

  // --- Suche -------------------------------------------------------------------------------------------
  function norm(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ß/g, 'ss'); }
  function filter() {
    var q = norm(search.value.trim()), any = false;
    nav.classList.toggle('is-searching', !!q);
    nav.querySelectorAll(':scope > .nav-item, .nav-group').forEach(function (node) {
      if (node.classList.contains('nav-group')) {
        var groupHit = q && norm(node.querySelector('.nav-group-toggle').textContent).indexOf(q) >= 0, shown = 0;
        node.querySelectorAll('.nav-item').forEach(function (it) {
          var ok = !q || groupHit || norm(it.textContent).indexOf(q) >= 0;
          it.hidden = !ok; if (ok) shown++;
        });
        node.hidden = q && !shown;
        if (shown && q) any = true;
      } else {
        var ok = !q || norm(node.textContent).indexOf(q) >= 0;
        node.hidden = !ok; if (ok && q) any = true;
      }
    });
    if (empty) empty.hidden = !q || any;
  }
  function visibleLinks() {
    return Array.prototype.filter.call(nav.querySelectorAll('.nav-link'), function (l) { return l.offsetParent !== null; });
  }
  if (search) {
    search.addEventListener('input', filter);
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { var first = visibleLinks()[0]; if (first) { e.preventDefault(); first.click(); } }
      else if (e.key === 'ArrowDown') { var l = visibleLinks()[0]; if (l) { e.preventDefault(); l.focus(); } }
      else if (e.key === 'Escape') { search.value = ''; filter(); search.blur(); }
    });
  }
  document.addEventListener('keydown', function (e) {
    var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    if (!search) return;
    if ((e.key === '/' && !typing) || (e.key.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey))) {
      e.preventDefault();
      if (window.matchMedia('(max-width: 991.98px)').matches && window.bootstrap) {
        bootstrap.Offcanvas.getOrCreateInstance(document.getElementById('sidebar')).show();
      }
      if (aside && aside.classList.contains('is-rail')) applyRail(false);
      search.focus(); search.select();
    }
  });

  // --- Pfeiltasten im Menü ----------------------------------------------------------------------------
  nav.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
    var items = Array.prototype.filter.call(nav.querySelectorAll('.nav-link, .nav-group-toggle'), function (l) { return l.offsetParent !== null; });
    var i = items.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    var next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : i + (e.key === 'ArrowDown' ? 1 : -1);
    if (next < 0 && search) { search.focus(); return; }
    if (items[next]) items[next].focus();
  });
})();
