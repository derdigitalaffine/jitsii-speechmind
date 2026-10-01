/* Terminbuchung: Zeitbereiche im Wochenkalender (FullCalendar) aufziehen und entfernen; Dialoge zu Buchungen. */
(function () {
  'use strict';
  var el = document.getElementById('bk-calendar');
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';

  /* --- Dialoge Verschieben / Absagen -------------------------------------- */
  function openModal(id, btn, attr) {
    var modal = document.getElementById(id);
    var form = modal.querySelector('form');
    form.action = form.dataset.actionBase + btn.getAttribute(attr);
    modal.querySelectorAll('.js-bk-name').forEach(function (x) { x.textContent = btn.dataset.bkName; });
    modal.querySelectorAll('.js-bk-when').forEach(function (x) { x.textContent = btn.dataset.bkWhen; });
    bootstrap.Modal.getOrCreateInstance(modal).show();
  }
  document.addEventListener('click', function (ev) {
    var mv = ev.target.closest('[data-bk-move]');
    if (mv) { openModal('move-modal', mv, 'data-bk-move'); return; }
    var cn = ev.target.closest('[data-bk-cancel]');
    if (cn) { openModal('cancel-modal', cn, 'data-bk-cancel'); }
  });

  if (!el || !window.FullCalendar) { return; }
  var pageId = el.dataset.page;
  var events = JSON.parse(document.getElementById('bk-events').textContent || '[]');

  function post(url, fields) {
    var body = new FormData();
    body.append('csrf', csrf);
    Object.keys(fields || {}).forEach(function (k) { body.append(k, fields[k]); });
    return fetch(url, { method: 'POST', body: body, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (d) { d.status = r.status; return d; }); });
  }
  function toast(text, error) {
    if (window.Swal) {
      Swal.fire({ toast: true, position: 'top-end', timer: error ? 6000 : 2500, showConfirmButton: false,
        icon: error ? 'error' : 'success', title: text });
    }
  }
  function reload(list) {
    calendar.removeAllEvents();
    list.forEach(function (e) { calendar.addEvent(e); });
  }
  function windowAt(date) {
    var t = date.getTime();
    return calendar.getEvents().find(function (e) {
      return e.extendedProps.kind === 'window' && e.start.getTime() <= t && t < e.end.getTime();
    });
  }

  var calendar = new FullCalendar.Calendar(el, {
    locale: 'de',
    initialView: window.innerWidth < 768 ? 'timeGridDay' : 'timeGridWeek',
    initialDate: el.dataset.initial || undefined,
    firstDay: 1,
    allDaySlot: false,
    slotMinTime: '07:00:00',
    slotMaxTime: '20:00:00',
    slotDuration: '00:15:00',
    slotLabelInterval: '01:00',
    snapDuration: '00:15:00',
    nowIndicator: true,
    selectable: true,
    selectMirror: true,
    selectMinDistance: 5,
    height: 'auto',
    expandRows: true,
    weekNumbers: true,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay,dayGridMonth' },
    businessHours: { daysOfWeek: [1, 2, 3, 4, 5], startTime: '08:00', endTime: '17:00' },
    events: events,
    selectAllow: function (info) {
      return info.start.toDateString() === new Date(info.end.getTime() - 1).toDateString() && info.start > new Date(Date.now() - 864e5);
    },
    select: function (info) {
      calendar.unselect();
      if (info.view.type === 'dayGridMonth') { calendar.changeView('timeGridDay', info.start); return; }
      post('/bookings/' + pageId + '/windows', { start: info.startStr, end: info.endStr }).then(function (d) {
        if (d.ok) { reload(d.events); toast('Zeitbereich freigegeben'); } else { toast(d.error || 'Nicht gespeichert', true); }
      }).catch(function () { toast('Verbindung fehlgeschlagen', true); });
    },
    dateClick: function (info) {
      var w = windowAt(info.date);
      if (!w) { return; }
      var fmt = function (d) { return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }); };
      Swal.fire({
        title: 'Zeitbereich entfernen?', icon: 'question',
        text: w.start.toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit' }) + ', ' + fmt(w.start) + '–' + fmt(w.end) + ' Uhr. Buchungen darin bleiben bestehen.',
        showCancelButton: true, confirmButtonText: 'Entfernen', cancelButtonText: 'Abbrechen', reverseButtons: true,
        buttonsStyling: false, customClass: { confirmButton: 'btn btn-danger ms-2', cancelButton: 'btn btn-outline-secondary' }
      }).then(function (res) {
        if (!res.isConfirmed) { return; }
        post('/bookings/' + pageId + '/windows/' + w.extendedProps.wid + '/delete').then(function (d) {
          reload(d.events); toast(d.message || 'Entfernt');
        });
      });
    },
    eventClick: function (info) {
      if (info.event.extendedProps.kind !== 'booking') { return; }
      var row = document.querySelector('[data-bk-cancel="' + info.event.extendedProps.bid + '"]');
      if (row) { row.closest('tr').scrollIntoView({ behavior: 'smooth', block: 'center' }); row.closest('tr').classList.add('table-warning'); }
    }
  });
  calendar.render();
  window.bkCalendar = calendar;
})();
