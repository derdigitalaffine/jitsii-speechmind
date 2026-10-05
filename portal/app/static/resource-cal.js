// Belegungskalender (FullCalendar): <div class="js-res-cal" data-src="…json" data-view="dayGridMonth" data-nav="1">
(function () {
  'use strict';
  if (!window.FullCalendar) return;
  document.querySelectorAll('.js-res-cal').forEach(function (el) {
    var cal = new FullCalendar.Calendar(el, {
      locale: 'de', firstDay: 1, height: 'auto', initialView: el.dataset.view || 'dayGridMonth',
      headerToolbar: { left: 'prev,next today', center: 'title', right: el.dataset.views === '0' ? '' : 'dayGridMonth,timeGridWeek,listMonth' },
      buttonText: { today: 'heute', month: 'Monat', week: 'Woche', list: 'Liste' },
      nowIndicator: true, slotMinTime: '06:00:00', slotMaxTime: '24:00:00', allDayText: 'ganztags',
      events: { url: el.dataset.src, failure: function () {} },
      eventDidMount: function (info) {
        var d = info.event.extendedProps && info.event.extendedProps.description;
        if (d) info.el.title = d;
      },
      dateClick: el.dataset.pick ? function (info) {
        var input = document.querySelector(el.dataset.pick);
        if (input && !input.disabled) { input.value = info.dateStr.slice(0, 10); input.dispatchEvent(new Event('change', { bubbles: true })); input.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      } : null
    });
    cal.render();
  });
})();
