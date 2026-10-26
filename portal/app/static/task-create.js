/* Feedback stays beside the native file picker; the server validates the same limits. */
(() => {
  const picker = document.getElementById('task-initial-files');
  const feedback = document.getElementById('task-file-feedback');
  const list = document.getElementById('task-file-list');
  if (!picker || !feedback || !list) return;
  picker.addEventListener('change', () => {
    const files = Array.from(picker.files || []);
    const total = files.reduce((sum, file) => sum + file.size, 0);
    let error = '';
    if (files.length > 10) error = 'Bitte höchstens 10 Dateien auswählen.';
    else if (files.some(file => file.size > 20 * 1024 * 1024)) error = 'Eine Datei ist größer als 20 MB. Bitte die Auswahl anpassen.';
    else if (total > 100 * 1024 * 1024) error = 'Die Dateien sind zusammen größer als 100 MB. Bitte die Auswahl anpassen.';
    picker.setCustomValidity(error);
    picker.setAttribute('aria-invalid', error ? 'true' : 'false');
    feedback.textContent = error || (files.length ? `${files.length} ${files.length === 1 ? 'Datei ausgewählt' : 'Dateien ausgewählt'}.` : '');
    feedback.classList.toggle('text-danger', Boolean(error));
    list.replaceChildren();
    for (const file of files) {
      const item = document.createElement('li');
      item.textContent = file.name;
      list.appendChild(item);
    }
  });
})();
