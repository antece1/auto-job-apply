// Fills text, textarea and select fields tagged by scan-form.js.
// Replace the {} at the very end with a map like {"0": "Jane Doe", "3": "jane@example.com", "8": "Yes"}.
// Works with React-style inputs (uses the native value setter, then fires input/change).
// Returns what each field holds afterwards, or NOT FOUND / NO MATCHING OPTION.
((VALUES) => {
  const norm = s => String(s).replace(/\s+/g, ' ').trim().toLowerCase();
  const res = {};
  for (const [id, v] of Object.entries(VALUES)) {
    const el = document.querySelector('[data-ja="' + id + '"]');
    if (!el) { res[id] = 'NOT FOUND'; continue; }
    if (el.tagName === 'SELECT') {
      const opts = [...el.options];
      const want = norm(v);
      const opt = opts.find(o => norm(o.text) === want)
        || opts.find(o => norm(o.text).startsWith(want))
        || opts.find(o => norm(o.text).includes(want));
      if (!opt) { res[id] = 'NO MATCHING OPTION'; continue; }
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(el, opt.value);
    } else {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(v));
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    res[id] = el.tagName === 'SELECT' ? el.options[el.selectedIndex].text.trim() : el.value;
  }
  return res;
})({})
