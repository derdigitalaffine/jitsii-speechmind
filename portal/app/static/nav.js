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
        var head = node.querySelector('.nav-group-toggle, .nav-group-title');
        var groupHit = q && head && norm(head.textContent).indexOf(q) >= 0, shown = 0;
        node.querySelectorAll('.nav-item').forEach(function (it) {
          var ok = !q || groupHit || norm(it.textContent).indexOf(q) >= 0;
          it.hidden = !ok; if (ok) shown++;
        });
        node.hidden = (q && !shown) || (node.classList.contains('nav-favs') && !node.querySelector('.nav-item'));
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

  // --- Favoriten: Stern anheften/lösen, ohne die Seite neu zu laden ------------------------------------
  var favGroup = nav.querySelector('.nav-favs'), favList = document.getElementById('nav-favs');
  function renderFavs(ids) {
    nav.querySelectorAll('.nav-pin').forEach(function (b) {
      var on = ids.indexOf(b.dataset.pin) >= 0, label = b.closest('.nav-item').querySelector('.nav-label').textContent;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = on ? 'Aus Favoriten entfernen' : 'Als Favorit anheften';
      b.setAttribute('aria-label', label + ': ' + (on ? 'aus Favoriten entfernen' : 'als Favorit anheften'));
      b.querySelector('i').className = (on ? 'fa-solid' : 'fa-regular') + ' fa-star';
    });
    if (!favList) return;
    favList.innerHTML = '';
    ids.forEach(function (id) {
      var src = nav.querySelector('.nav-group:not(.nav-favs) [data-nav-id="' + id + '"]');
      if (!src) return;
      var copy = src.cloneNode(true), link = copy.querySelector('.nav-link');
      link.classList.remove('active'); link.removeAttribute('aria-current');
      favList.appendChild(copy);
    });
    favGroup.hidden = !favList.children.length;
  }
  nav.addEventListener('click', function (e) {
    var btn = e.target.closest('.nav-pin');
    if (!btn) return;
    e.preventDefault();
    var body = new FormData();
    body.append('csrf', nav.dataset.csrf);
    body.append('id', btn.dataset.pin);
    body.append('on', btn.classList.contains('is-on') ? '0' : '1');
    fetch('/nav/pin', { method: 'POST', body: body, credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        renderFavs(d.fav || []);
        var again = nav.querySelector('.nav-group:not(.nav-favs) .nav-pin[data-pin="' + btn.dataset.pin + '"]');
        if (again && document.activeElement !== again && btn.isConnected) btn.focus(); else if (again) again.focus();
      })
      .catch(function () { btn.classList.add('text-danger'); });
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
