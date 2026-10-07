(() => {
  document.querySelector('#kind')?.addEventListener('change', event => {
    const mode = document.querySelector('#mode');
    if (mode) mode.value = event.target.value === 'circulation' ? 'ack' : 'info';
  });
  const textarea = document.querySelector('#body');
  document.querySelectorAll('[data-md]').forEach(button => button.addEventListener('click', () => {
    if (!textarea) return;
    const start = textarea.selectionStart, end = textarea.selectionEnd, mark = button.dataset.md;
    const selected = textarea.value.slice(start, end);
    textarea.setRangeText(mark + selected + (mark === '**' ? mark : ''), start, end, 'select');
    textarea.focus();
  }));
  const preview = document.querySelector('#cl-preview');
  document.querySelector('#cl-preview-button')?.addEventListener('click', async () => {
    preview.hidden = false; preview.textContent = 'Vorschau wird geladen …';
    try {
      const data = new FormData(); data.set('body', textarea.value);
      data.set('csrf', document.querySelector('meta[name="csrf"]').content);
      const response = await fetch('/umlaeufe/preview', {method:'POST', body:data});
      if (!response.ok) throw new Error();
      preview.innerHTML = await response.text(); // Server Markdown parser disables raw HTML and unsafe schemes.
    } catch (_) { preview.textContent = 'Vorschau konnte nicht geladen werden. Bitte erneut versuchen.'; }
  });
  document.querySelectorAll('.cl-object-select').forEach(select => {
    if (window.TomSelect && !select.tomselect) new TomSelect(select, {plugins:['remove_button'], maxOptions:100, placeholder:'Suchen und auswählen …'});
  });
})();
