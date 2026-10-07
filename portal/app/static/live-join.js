// Live-Umfrage, Teilnahme am Handy: aktuelle Frage(n) laden (alle paar Sekunden), antworten, eigene Antwort ändern,
// Ergebnis anzeigen, sobald die Moderation es freigibt. Ohne Anmeldung – die Gerätekennung steckt im Cookie und
// geht zusätzlich als Kopf mit (Schutz vor fremden Seiten).
(function () {
  'use strict';
  var root = document.getElementById('live-join');
  if (!root || !window.fetch) return;
  var box = document.getElementById('live-questions');
  var token = root.dataset.token, device = root.dataset.device;
  var esc = window.LiveChart ? LiveChart.esc : function (s) { return String(s); };
  var last = '', drafts = {}, busy = false;

  function load() {
    if (busy) return;
    var ae = document.activeElement;
    if (ae && ae.classList && (ae.classList.contains('js-word') || ae.classList.contains('js-entry'))) return;   // nicht beim Tippen neu zeichnen
    fetch('/l/' + token + '/state.json', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); }).then(render).catch(function () { /* nächster Versuch */ });
  }

  function choiceButtons(q) {
    var mine = q.mine || {}, multi = q.kind === 'multi';
    var chosen = multi ? (drafts[q.id] || mine.o || []) : null;
    if (q.kind === 'yesno') {
      return '<div class="live-yesno">' + q.options.map(function (o) {
        var on = mine.o === o.id;
        return '<button type="button" class="btn ' + (on ? 'btn-primary' : 'btn-outline-primary') + ' js-pick" data-q="' + q.id + '" data-o="' + esc(o.id) + '" aria-pressed="' + on + '">' + esc(o.label) + '</button>';
      }).join('') + '</div>';
    }
    return q.options.map(function (o) {
      var on = multi ? chosen.indexOf(o.id) >= 0 : mine.o === o.id;
      return '<button type="button" class="btn live-choice ' + (on ? 'btn-primary is-mine' : 'btn-outline-primary') + ' ' + (multi ? 'js-toggle' : 'js-pick') + '" data-q="' + q.id + '" data-o="' + esc(o.id) + '" aria-pressed="' + on + '">' +
        (multi ? '<i class="fa-' + (on ? 'solid fa-square-check' : 'regular fa-square') + ' me-2"></i>' : '') + esc(o.label) + '</button>';
    }).join('') + (multi ? '<div class="d-flex align-items-center gap-2"><button type="button" class="btn btn-primary js-send-multi" data-q="' + q.id + '">Absenden</button><span class="small text-secondary">höchstens ' + q.settings.max_choices + '</span></div>' : '');
  }
  function scaleButtons(q) {
    var s = q.settings, mine = (q.mine || {}).n, out = '';
    if (q.kind === 'stars') {
      out = '<div class="live-stars-input text-center" role="group" aria-label="Sterne">';
      for (var i = 1; i <= 5; i++) out += '<button type="button" class="btn js-num" data-q="' + q.id + '" data-n="' + i + '" aria-label="' + i + ' Sterne"><i class="fa-' + (mine >= i ? 'solid' : 'regular') + ' fa-star"></i></button>';
      return out + '</div>';
    }
    if (q.kind === 'slider') {
      var v = mine != null ? mine : Math.round((s.min + s.max) / 2);
      return '<input type="range" class="form-range js-range" id="r-' + q.id + '" data-q="' + q.id + '" min="' + s.min + '" max="' + s.max + '" step="' + s.step + '" value="' + v + '" aria-label="Wert">' +
        '<div class="d-flex justify-content-between small text-secondary"><span>' + s.min + '</span><output class="fw-semibold fs-5 text-body" for="r-' + q.id + '">' + v + (s.unit ? ' ' + esc(s.unit) : '') + '</output><span>' + s.max + '</span></div>' +
        '<button type="button" class="btn btn-primary mt-2 js-send-range" data-q="' + q.id + '">Absenden</button>';
    }
    out = '<div class="live-scale" role="group">';
    for (var n = s.min; n <= s.max; n++) out += '<button type="button" class="btn ' + (mine === n ? 'btn-primary' : 'btn-outline-primary') + ' js-num" data-q="' + q.id + '" data-n="' + n + '" aria-pressed="' + (mine === n) + '">' + n + '</button>';
    return out + '</div>' + ((s.low || s.high) ? '<div class="d-flex justify-content-between small text-secondary mt-1"><span>' + esc(s.low) + '</span><span>' + esc(s.high) + '</span></div>' : '');
  }

  function wordInputs(q) {
    var s = q.settings, mine = (q.mine || {}).w || [], out = '<div class="live-words">';
    for (var i = 0; i < s.max_words; i++) {
      out += '<input class="form-control mb-2 js-word" data-q="' + q.id + '" maxlength="' + s.max_len + '" value="' + esc(drafts[q.id] ? drafts[q.id][i] || '' : (mine[i] || '')) +
        '" placeholder="' + (i === 0 ? 'Ihr Begriff' : 'weiterer Begriff (optional)') + '" aria-label="Begriff ' + (i + 1) + '" autocomplete="off">';
    }
    return out + '<button type="button" class="btn btn-primary js-send-words" data-q="' + q.id + '">' + (mine.length ? 'Begriffe ändern' : 'Absenden') + '</button></div>';
  }

  function entryBox(q) {
    var s = q.settings, list = q.entries || [], qa = q.kind === 'qa';
    var mineCount = list.filter(function (e) { return e.mine; }).length;
    var form = q.locked ? '<p class="text-secondary"><i class="fa-solid fa-lock me-1"></i>Keine neuen Beiträge mehr möglich.</p>'
      : (mineCount >= s.max_entries ? '<p class="small text-secondary">Sie haben ' + mineCount + ' Beiträge geschickt – mehr geht hier nicht.</p>' :
      '<textarea class="form-control mb-2 js-entry" data-q="' + q.id + '" rows="2" maxlength="' + s.max_len + '" placeholder="' + (qa ? 'Ihre Frage …' : 'Ihre Antwort …') + '" aria-label="' + (qa ? 'Ihre Frage' : 'Ihre Antwort') + '">' + esc(drafts[q.id] || '') + '</textarea>' +
      '<button type="button" class="btn btn-primary js-send-entry" data-q="' + q.id + '">' + (qa ? 'Frage stellen' : 'Absenden') + '</button>' +
      (s.approve ? '<span class="small text-secondary ms-2">wird nach Freigabe angezeigt</span>' : ''));
    var items = list.map(function (e) {
      var badge = !e.approved ? '<span class="badge text-bg-warning ms-1">wartet auf Freigabe</span>' : (e.answered ? '<span class="badge text-bg-success ms-1">beantwortet</span>' : '');
      var vote = qa && e.approved ? (e.mine ? '<span class="small text-secondary text-nowrap"><i class="fa-solid fa-thumbs-up"></i> ' + e.upvotes + '</span>'
        : '<button type="button" class="btn btn-sm ' + (e.voted ? 'btn-primary' : 'btn-outline-primary') + ' js-upvote text-nowrap" data-q="' + q.id + '" data-a="' + e.id + '" aria-pressed="' + e.voted + '" aria-label="Frage unterstützen (' + e.upvotes + ')"><i class="fa-solid fa-thumbs-up"></i> ' + e.upvotes + '</button>') : '';
      return '<div class="live-entry"><span class="live-entry-text">' + (e.mine ? '<i class="fa-regular fa-user me-1 text-secondary" title="Ihr Beitrag"></i>' : '') + esc(e.text) + badge + '</span>' + vote + '</div>';
    }).join('');
    return form + (items ? '<hr><div class="small text-secondary mb-1">' + (qa ? 'Fragen – die meistunterstützten zuerst' : 'Beiträge') + '</div>' + items : '');
  }

  function render(state) {
    var key = JSON.stringify(state) + JSON.stringify(drafts);
    if (key === last) return;
    last = key;
    if (state.status !== 'open') {
      box.innerHTML = '<div class="card live-q"><div class="card-body text-center py-5"><i class="fa-regular fa-hourglass-half fa-2x text-secondary mb-3"></i><p class="mb-0">' +
        (state.status === 'closed' ? 'Die Umfrage ist beendet. Vielen Dank fürs Mitmachen!' : 'Gleich geht es los – diese Seite aktualisiert sich von selbst.') + '</p></div></div>';
      return;
    }
    if (!state.questions.length) {
      box.innerHTML = '<div class="card live-q"><div class="card-body text-center py-5 text-secondary">Bitte warten Sie auf die nächste Frage …</div></div>';
      return;
    }
    var focus = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-q]');
    var focusKey = focus ? focus.dataset.q + '|' + (focus.dataset.o || focus.dataset.n || '') : '';
    box.innerHTML = state.questions.map(function (q) {
      var entry = q.kind === 'open' || q.kind === 'qa';
      var inner = entry ? entryBox(q) : (q.locked ? '<p class="text-secondary mb-0"><i class="fa-solid fa-lock me-1"></i>Für diese Frage sind keine Antworten mehr möglich.</p>'
        : (['single', 'multi', 'yesno'].indexOf(q.kind) >= 0 ? choiceButtons(q) : (q.kind === 'words' ? wordInputs(q) : scaleButtons(q))));
      return '<section class="card live-q mb-3" aria-labelledby="lq-' + q.id + '"><div class="card-body">' +
        '<h2 class="h5 mb-3" id="lq-' + q.id + '">' + esc(q.title) + '</h2>' + inner +
        (q.answered && !entry ? '<p class="live-done mt-3 mb-0"><i class="fa-solid fa-circle-check me-1"></i>Antwort gespeichert – ändern ist möglich.</p>' : '') +
        '<div class="small text-danger mt-2 js-err" data-q="' + q.id + '"></div>' +
        (q.results && !entry ? '<hr><div class="small text-secondary mb-2">Ergebnis (' + q.results.total + ' Antworten)</div><div class="js-chart" data-q="' + q.id + '"></div>' : '') +
        '</div></section>';
    }).join('');
    state.questions.forEach(function (q) {
      var el = box.querySelector('.js-chart[data-q="' + q.id + '"]');
      if (el && window.LiveChart) LiveChart.render(el, q);
    });
    if (focusKey) {
      var parts = focusKey.split('|');
      var again = box.querySelector('[data-q="' + parts[0] + '"][data-o="' + parts[1] + '"], [data-q="' + parts[0] + '"][data-n="' + parts[1] + '"]');
      if (again) again.focus();
    }
  }

  function send(qid, value) {
    busy = true;
    fetch('/l/' + token + '/answer', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Live-Device': device },
      body: JSON.stringify({ question: qid, value: value }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        busy = false;
        if (!d.ok) { var e = box.querySelector('.js-err[data-q="' + qid + '"]'); if (e) e.textContent = d.error || 'Das hat nicht geklappt.'; return; }
        delete drafts[qid];
        last = '';
        if (document.activeElement) document.activeElement.blur();
        render(d);
      })
      .catch(function () { busy = false; var e = box.querySelector('.js-err[data-q="' + qid + '"]'); if (e) e.textContent = 'Keine Verbindung – bitte erneut versuchen.'; });
  }

  box.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    var qid = +b.dataset.q;
    if (b.classList.contains('js-pick')) send(qid, { o: b.dataset.o });
    else if (b.classList.contains('js-num')) send(qid, { n: +b.dataset.n });
    else if (b.classList.contains('js-toggle')) {
      var list = (drafts[qid] || []).slice();
      if (!drafts[qid]) {
        box.querySelectorAll('.js-toggle[data-q="' + qid + '"][aria-pressed="true"]').forEach(function (x) { list.push(x.dataset.o); });
      }
      var i = list.indexOf(b.dataset.o);
      if (i >= 0) list.splice(i, 1); else list.push(b.dataset.o);
      drafts[qid] = list;
      last = '';
      load();
    } else if (b.classList.contains('js-send-multi')) send(qid, { o: drafts[qid] || [] });
    else if (b.classList.contains('js-send-entry')) {
      var ta = box.querySelector('.js-entry[data-q="' + qid + '"]');
      send(qid, { t: ta ? ta.value : '' });
    } else if (b.classList.contains('js-upvote')) {
      busy = true;
      fetch('/l/' + token + '/upvote', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Live-Device': device },
        body: JSON.stringify({ question: qid, answer: +b.dataset.a }) })
        .then(function (r) { return r.json(); }).then(function (d) { busy = false; if (d.ok) { last = ''; render(d); } })
        .catch(function () { busy = false; });
    } else if (b.classList.contains('js-send-words')) {
      var words = Array.prototype.map.call(box.querySelectorAll('.js-word[data-q="' + qid + '"]'), function (x) { return x.value; })
        .filter(function (w) { return w.trim(); });
      send(qid, { w: words });
    } else if (b.classList.contains('js-send-range')) send(qid, { n: +box.querySelector('.js-range[data-q="' + qid + '"]').value });
  });
  box.addEventListener('input', function (e) {
    if (e.target.classList.contains('js-entry')) { drafts[e.target.dataset.q] = e.target.value; return; }
    if (e.target.classList.contains('js-word')) {
      var q = e.target.dataset.q;
      drafts[q] = Array.prototype.map.call(box.querySelectorAll('.js-word[data-q="' + q + '"]'), function (x) { return x.value; });
      return;
    }
    if (!e.target.classList.contains('js-range')) return;
    busy = true;   // während des Schiebens nicht neu zeichnen
    var out = e.target.parentNode.querySelector('output');
    if (out) out.textContent = e.target.value + (out.textContent.replace(/^[-\d.,]+/, ''));
    clearTimeout(e.target._t);
    e.target._t = setTimeout(function () { busy = false; }, 4000);
  });

  load();
  setInterval(load, 2500);
})();
