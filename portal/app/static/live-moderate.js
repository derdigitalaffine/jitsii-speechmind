/* Moderator preview follows the shared server state, including presenter changes. */
(function () {
  'use strict';
  var root = document.getElementById('live-moderation');
  if (!root || !document.getElementById('lm-chart')) return;
  var seed = document.getElementById('lm-initial');
  var message = document.getElementById('lm-connection');
  var shownQuestion = null, shownStatus = null;
  function text(id, value) {
    var element = document.getElementById(id);
    if (element.textContent !== value) element.textContent = value;
  }
  function draw(state) {
    var index = state.questions.findIndex(function (q) { return q.id === state.current; });
    index = index < 0 ? 0 : index;
    var question = state.questions[index];
    if (!question) return;
    if ((shownQuestion !== null && shownQuestion !== question.id) || (shownStatus !== null && shownStatus !== state.status)) {
      if (document.activeElement && document.activeElement.matches('input,textarea,select')) { message.textContent = 'Die aktuelle Frage wurde geändert. Beenden Sie Ihre Eingabe, um die Steuerung zu aktualisieren.'; return; }
      window.location.reload(); return;
    }
    shownQuestion = question.id;
    shownStatus = state.status;
    text('lm-title', question.title);
    text('lm-position', 'Aktuelle Frage · ' + (index + 1) + ' von ' + state.questions.length);
    var total = question.results ? question.results.total : 0;
    text('lm-count', total + (total === 1 ? ' Antwort' : ' Antworten'));
    if (window.LiveChart) window.LiveChart.render(document.getElementById('lm-chart'), question, {});
    var previous = root.querySelector('button[value="prev"]');
    var next = root.querySelector('button[value="next"]');
    if (previous) previous.disabled = index === 0;
    if (next) next.disabled = index === state.questions.length - 1;
  }
  try { draw(JSON.parse(seed.textContent)); } catch (error) { message.textContent = 'Die Vorschau wird geladen.'; }
  var busy = false;
  function refresh() {
    if (document.hidden || busy) return;
    busy = true;
    fetch('/votes/live/' + root.dataset.poll + '/state.json', {credentials:'same-origin', cache:'no-store'})
      .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
      .then(function (state) { draw(state); message.textContent = ''; })
      .catch(function () { message.textContent = 'Verbindung unterbrochen. Die Vorschau wird automatisch erneut geladen. Antworten bleiben gespeichert.'; })
      .finally(function () { busy = false; });
  }
  setInterval(refresh, 2500);
})();
