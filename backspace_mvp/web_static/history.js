/* Development history is local, independent of jobs, data and model APIs. */
(() => {
  const panel = document.getElementById('history-window');
  const toggle = document.getElementById('history-toggle');
  const handle = document.getElementById('history-handle');
  const content = document.getElementById('history-content');
  const close = document.getElementById('history-close');
  let loaded = false, loading = false, drag = null, position = null;
  try { position = JSON.parse(localStorage.getItem('backspace-history-position')); } catch (_) {}
  if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) position = null;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const timestamp = date => new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(new Date(date));
  function place(x, y, persist = false) {
    const viewport = window.visualViewport;
    const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
    const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
    const rect = panel.getBoundingClientRect();
    position = {x: Math.max(left + 8, Math.min(x, left + width - rect.width - 8)),
                y: Math.max(top + 8, Math.min(y, top + height - rect.height - 8))};
    panel.style.left = position.x + 'px'; panel.style.top = position.y + 'px';
    if (persist) try { localStorage.setItem('backspace-history-position', JSON.stringify(position)); } catch (_) {}
  }
  async function load() {
    if (loaded || loading) return;
    loading = true;
    content.replaceChildren(element('p', 'history-empty', '변경 이력을 불러오고 있어요.'));
    try {
      const response = await fetch('/change-history.json', {cache: 'no-store'});
      if (!response.ok) throw new Error('history unavailable');
      const data = await response.json();
      if (!Array.isArray(data.entries)) throw new Error('invalid history');
      const entries = data.entries.filter(e => typeof e.title === 'string' &&
        typeof e.summary === 'string' && Number.isFinite(Date.parse(e.at)))
        .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      const fragment = document.createDocumentFragment();
      let day = '';
      for (const entry of entries) {
        const formatted = timestamp(entry.at), nextDay = formatted.slice(0, 10);
        if (nextDay !== day) {
          day = nextDay; fragment.append(element('h3', 'history-day', day.replaceAll('-', '.')));
        }
        const card = element('article', 'history-entry');
        const meta = element('div', 'history-meta');
        const time = element('time', '', formatted.slice(11)); time.dateTime = entry.at;
        meta.append(time, element('span', 'history-kind', entry.category || '업데이트'));
        card.append(meta, element('h4', '', entry.title), element('p', '', entry.summary));
        if (entry.time_basis) card.append(element('small', 'history-basis', entry.time_basis));
        if (Array.isArray(entry.files) && entry.files.length) {
          const details = element('details', 'history-files');
          details.append(element('summary', '', `변경 파일 ${entry.files.length}개`));
          const list = element('ul');
          for (const file of entry.files) {
            const row = element('li', '', typeof file === 'string' ? file : file.path);
            if (typeof file !== 'string' && file.modified_at) {
              row.append(element('small', '', `수정 시각 ${timestamp(file.modified_at)}`));
            }
            list.append(row);
          }
          details.append(list); card.append(details);
        }
        fragment.append(card);
      }
      content.replaceChildren(fragment);
      if (!entries.length) content.append(element('p', 'history-empty', '아직 기록된 변경 이력이 없습니다.'));
      document.getElementById('history-count').textContent = `${entries.length}개 기록 · 처음 → 최신`;
      loaded = true;
    } catch (_) {
      const message = element('p', 'history-empty', '변경 이력을 불러오지 못했어요.');
      const retry = element('button', 'button small', '다시 불러오기');
      retry.addEventListener('click', load);
      content.replaceChildren(message, retry);
      document.getElementById('history-count').textContent = '불러오기 실패';
    } finally { loading = false; }
  }
  function hide() {
    if (drag && handle.hasPointerCapture(drag.id)) handle.releasePointerCapture(drag.id);
    drag = null; panel.classList.remove('is-dragging');
    panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); toggle.focus();
  }
  toggle.addEventListener('click', () => {
    if (!panel.hidden) { hide(); return; }
    panel.hidden = false; toggle.setAttribute('aria-expanded', 'true');
    const rect = panel.getBoundingClientRect();
    place(position?.x ?? innerWidth - rect.width - 24, position?.y ?? 82);
    close.focus(); load();
  });
  close.addEventListener('click', hide);
  document.getElementById('history-first').addEventListener('click', () => {content.scrollTop = 0;});
  document.getElementById('history-latest').addEventListener('click', () => {content.scrollTop = content.scrollHeight;});
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button')) return;
    const rect = panel.getBoundingClientRect();
    drag = {id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top};
    handle.setPointerCapture(event.pointerId); handle.focus();
    panel.classList.add('is-dragging'); event.preventDefault();
  });
  handle.addEventListener('pointermove', event => {
    if (drag?.id === event.pointerId) place(drag.left + event.clientX - drag.x, drag.top + event.clientY - drag.y);
  });
  const endDrag = event => {
    if (drag?.id !== event.pointerId) return;
    drag = null; panel.classList.remove('is-dragging');
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    place(position.x, position.y, true);
  };
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('lostpointercapture', endDrag);
  handle.addEventListener('keydown', event => {
    const delta = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
    if (!delta || event.target !== handle) return;
    event.preventDefault(); const step = event.shiftKey ? 40 : 12;
    place(position.x + step * delta[0], position.y + step * delta[1], true);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden && !document.querySelector('dialog[open]')) {
      event.preventDefault(); event.stopImmediatePropagation(); hide();
    }
  }, true);
  const resized = () => {if (!panel.hidden && position) place(position.x, position.y);};
  window.addEventListener('resize', resized);
  window.visualViewport?.addEventListener('resize', resized);
})();
