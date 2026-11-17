// Quick read-back of every field tagged by scan-form.js: {id: value}. File fields show the attached file name.
(() => {
  const out = {};
  document.querySelectorAll('[data-ja]').forEach(el => {
    const id = el.getAttribute('data-ja');
    if (el.type === 'file') out[id] = el.files[0] ? el.files[0].name : '(no file)';
    else if (el.type === 'radio' || el.type === 'checkbox') out[id] = el.checked;
    else if (el.tagName === 'SELECT') out[id] = el.selectedIndex > 0 ? el.options[el.selectedIndex].text.trim() : '';
    else out[id] = el.value;
  });
  return out;
})()
