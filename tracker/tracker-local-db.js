/* Data layer for tracker.html: connects the page to the server in tracker.py (its /api).
   It offers a small document-database interface (collections of rows with live updates):
     window.TrackerServer.db.collection('jobs').onSnapshot(cb)   -> cb({ docs: [{ id, version, data() }] })
     window.TrackerServer.db.collection('jobs').doc(id).get() / set(data) / update(patch) / delete()
     window.TrackerServer.info()                                 -> the server's addresses
   Changes made elsewhere (another browser, or tracker.py on the command line) show up within a few seconds. */
(function () {
  'use strict';
  if (window.TrackerServer) return;

  const listeners = new Map(); // collection -> Set of { cb, err }
  let rev = null, timer = null, inflight = null, offlineEl = null;

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ cache: 'no-store', credentials: 'same-origin' }, opts || {}));
    let body = {};
    try { body = await r.json(); } catch (e) { body = {}; }
    if (!r.ok) {
      const err = new Error((body && body.error) || 'HTTP ' + r.status);
      err.code = (body && body.code) || 'http_' + r.status; err.status = r.status; err.current = body && body.current;
      throw err;
    }
    return body;
  }

  function setOnline(ok) {
    if (ok) { if (offlineEl) offlineEl.hidden = true; return; }
    if (!offlineEl) {
      offlineEl = document.createElement('div');
      offlineEl.setAttribute('role', 'status');
      offlineEl.textContent = 'Can’t reach the tracker server. Retrying…';
      offlineEl.style.cssText = 'position:fixed;z-index:10;left:max(16px,env(safe-area-inset-left,0px));bottom:calc(16px + env(safe-area-inset-bottom,0px));'
        + 'background:var(--err-bg,#FBE7E5);color:var(--err,#B3261E);border:1px solid var(--err,#B3261E);border-radius:4px;padding:8px 12px;font-size:13px;';
      document.body.appendChild(offlineEl);
    }
    offlineEl.hidden = false;
  }

  async function pull(coll) {
    const res = await api('/api/c/' + encodeURIComponent(coll));
    if (rev === null) rev = res.rev;
    const snap = { docs: (res.docs || []).map((d) => ({ id: d.id, version: d.version, data: () => d.data })), metadata: { fromCache: false } };
    (listeners.get(coll) || new Set()).forEach((l) => { try { l.cb(snap); } catch (e) { console.error(e); } });
  }

  function refresh() {
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const r = await api('/api/rev');
        if (r.rev !== rev) { await Promise.all([...listeners.keys()].map(pull)); rev = r.rev; }
        setOnline(true);
      } catch (e) { setOnline(false); }
      finally { inflight = null; }
    })();
    return inflight;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { refresh().then(schedule); }, document.hidden ? 15000 : 2500);
  }
  const now = () => { refresh().then(schedule); };
  document.addEventListener('visibilitychange', () => { if (!document.hidden) now(); });
  window.addEventListener('focus', now);

  const db = {
    collection(coll) {
      const base = '/api/c/' + encodeURIComponent(coll);
      return {
        onSnapshot(cb, err) {
          const l = { cb, err };
          if (!listeners.has(coll)) listeners.set(coll, new Set());
          listeners.get(coll).add(l);
          pull(coll).then(() => setOnline(true), () => setOnline(false));
          if (!timer) schedule();
          return () => { const s = listeners.get(coll); if (s) s.delete(l); };
        },
        doc(id) {
          const url = base + '/' + encodeURIComponent(id);
          const send = (method, data) => api(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data }) })
            .then((r) => { now(); return r; });
          return {
            get: () => api(url).then((d) => ({ id: d.id, exists: true, data: () => d.data }),
              (e) => { if (e.status === 404) return { id, exists: false, data: () => undefined }; throw e; }),
            set: (data) => send('PUT', data),
            update: (patch) => send('PATCH', patch),
            delete: () => api(url, { method: 'DELETE' }).then((r) => { now(); return r; }),
          };
        },
      };
    },
  };

  window.TrackerServer = { info: () => api('/api/info'), db };
})();
