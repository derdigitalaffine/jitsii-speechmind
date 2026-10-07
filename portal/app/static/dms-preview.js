(() => {
  const panel = document.querySelector('#dms-preview');
  if (!panel) return;
  let lastTrigger;
  const frame = panel.querySelector('iframe'), image = panel.querySelector('img');
  document.querySelectorAll('[data-dms-preview]').forEach(button => button.addEventListener('click', () => {
    lastTrigger = button;
    const url = button.dataset.dmsPreview;
    const parsed = new URL(url, location.href);
    if (parsed.origin !== location.origin || !parsed.pathname.startsWith('/dms/r/')) return;
    frame.removeAttribute('src'); image.removeAttribute('src');
    const isImage = button.dataset.mime?.startsWith('image/');
    frame.hidden = !!isImage; image.hidden = !isImage;
    if (isImage) { image.src = url; image.alt = button.dataset.title || 'Dokumentvorschau'; }
    else frame.src = url + '#toolbar=1';
    panel.querySelector('h2').textContent = button.dataset.title || 'Dokumentvorschau';
    panel.querySelector('[data-preview-open]').href = url;
    panel.hidden = false; panel.scrollIntoView({behavior:'smooth',block:'start'});
    panel.querySelector('[data-preview-close]').focus({preventScroll:true});
  }));
  panel.querySelector('[data-preview-close]').addEventListener('click', () => {
    panel.hidden = true; frame.removeAttribute('src'); image.removeAttribute('src'); lastTrigger?.focus();
  });
})();
