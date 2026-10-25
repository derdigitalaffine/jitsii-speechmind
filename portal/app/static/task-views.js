/* Dragging is a convenience; every action also has a keyboard-accessible form. */
(() => {
  const select = document.querySelector('[data-mention-select]');
  document.querySelector('[data-mention-insert]')?.addEventListener('click', () => {
    const input = document.getElementById('new-comment');
    if (!input || !select) return;
    input.setRangeText(`@"${select.value.replaceAll('"', '')}" `, input.selectionStart, input.selectionEnd, 'end');
    input.focus();
  });
  let drag = null;
  document.querySelectorAll('[draggable][data-task-id]').forEach(card => {
    card.addEventListener('dragstart', event => {
      drag = {id: card.dataset.taskId, version: card.dataset.taskVersion};
      event.dataTransfer.setData('text/plain', card.dataset.taskId);
      event.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => { drag = null; });
  });
  document.querySelectorAll('[data-task-column],[data-task-date]').forEach(zone => {
    zone.addEventListener('dragover', event => { if (drag) event.preventDefault(); });
    zone.addEventListener('drop', event => {
      if (!drag) return;
      event.preventDefault();
      const form = document.getElementById('task-drag-form');
      if (!form) return;
      form.elements.task_id.value = drag.id;
      form.elements.version.value = drag.version;
      form.elements.status.value = zone.dataset.taskColumn || '';
      form.elements.due_date.value = zone.dataset.taskDate || '';
      form.requestSubmit();
    });
  });
})();
