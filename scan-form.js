// Lists every visible form field with its question text, tags each with data-ja="id"
// (radio/checkbox options get "id.k"), and returns a compact array. Run with javascript_tool.
(() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const strip = (node, dropLabelsFor) => {
    const c = node.cloneNode(true);
    if (dropLabelsFor) {
      c.querySelectorAll('label').forEach(l => {
        if (l.querySelector('input') || dropLabelsFor.has(l.htmlFor)) l.remove();
      });
    }
    c.querySelectorAll('select, option, input, textarea, button, script, style, svg').forEach(n => n.remove());
    return clean(c.textContent);
  };
  const shown = el => {
    if (el.type === 'file') return true;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const question = (el, group) => {
    if (!group) {
      if (el.labels && el.labels.length) { const t = strip(el.labels[0]); if (t) return t; }
      const al = el.getAttribute('aria-label'); if (al) return clean(al);
      const lb = el.getAttribute('aria-labelledby');
      if (lb) {
        const t = clean(lb.split(/\s+/).map(id => (document.getElementById(id) || {}).textContent || '').join(' '));
        if (t) return t;
      }
    }
    const fs = el.closest('fieldset');
    const lg = fs && fs.querySelector('legend');
    if (lg && clean(lg.textContent)) return clean(lg.textContent);
    const ids = group ? new Set(group.map(g => g.id).filter(Boolean)) : null;
    let c = el.parentElement;
    for (let i = 0; i < 8 && c && c !== document.body; i++, c = c.parentElement) {
      if (group && !group.every(g => c.contains(g))) continue;
      const t = strip(c, ids);
      if (t) return t.slice(0, 200);
    }
    return clean(el.name || el.placeholder || '');
  };
  const optText = g => clean((g.labels && g.labels[0] && g.labels[0].textContent) || g.getAttribute('aria-label') || g.value);
  const skip = ['hidden', 'submit', 'button', 'reset', 'image'];
  const els = [...document.querySelectorAll('input, select, textarea')].filter(el => !skip.includes(el.type) && shown(el));
  const out = [];
  const seen = new Set();
  let id = 0;
  for (const el of els) {
    const type = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : el.type;
    if (type === 'radio' || type === 'checkbox') {
      const key = type + ':' + (el.name || el.id || Math.random());
      if (seen.has(key)) continue;
      seen.add(key);
      const group = el.name ? els.filter(g => g.type === type && g.name === el.name) : [el];
      group.forEach((g, k) => g.setAttribute('data-ja', id + '.' + k));
      out.push({
        id, type,
        q: question(el, group.length > 1 ? group : null).slice(0, 200),
        required: group.some(g => g.required || g.getAttribute('aria-required') === 'true'),
        options: group.map(optText),
        checked: group.filter(g => g.checked).map(optText),
      });
      id++;
      continue;
    }
    el.setAttribute('data-ja', String(id));
    const q = question(el, null).slice(0, 200);
    const f = { id, type, q, required: el.required || el.getAttribute('aria-required') === 'true' || /[*✱]/.test(q) };
    if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete')) f.widget = 'combobox';
    if (type === 'select') {
      f.options = [...el.options].map(o => clean(o.text)).filter(Boolean).slice(0, 40);
      f.value = el.selectedIndex > 0 ? clean(el.options[el.selectedIndex].text) : '';
    } else if (type === 'file') {
      f.files = el.files.length;
      const box = el.closest('li, .field, .form-group, section, div');
      f.near = box ? strip(box).slice(0, 150) : '';
    } else {
      f.value = el.value;
    }
    out.push(f);
    id++;
  }
  return out;
})()
