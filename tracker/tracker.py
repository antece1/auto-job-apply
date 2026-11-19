#!/usr/bin/env python3
"""Job Tracker: a small local web server and a row editor, both run from this file (Python 3, standard library only).

The page is tracker.html next to this file. The rows are in tracker-data.json next to this file (created empty on
first run), with a daily copy in backups/. To keep the data somewhere else, set the TRACKER_DATA environment variable
or pass --data-file PATH before the command.

Start the server (it keeps running in the background, with no window):
    python tracker.py start                 add --open to open the page as well
Then open http://localhost:8787 in a browser on this computer. Stop it with:  python tracker.py stop
    python tracker.py status                is it running, and at which address(es)
    python tracker.py serve                 run in this window instead (Ctrl+C stops it)
By default the server answers only to this computer (127.0.0.1). To use the page from a phone or another computer on
the same network, start it with --lan. Anyone on that network can then read and change your tracker.

Read and change rows. This works whether or not the server is running, and an open page shows the change within a
few seconds. Rows are in the "jobs" collection; add -c interviews for the interview cards.
    python tracker.py find Acme "Test Technician"
    python tracker.py list --status todo
    python tracker.py get log-acme-robotics-test-technician
    python tracker.py update log-acme-robotics-test-technician --set response=interview --set responseOn=2026-01-15
    python tracker.py update ID --stdin < fields.json        fields as one JSON object
    python tracker.py add --set company="Acme Robotics" --set role="Test Technician"   id = log-<company>-<role>
    python tracker.py add --file row.json
    python tracker.py add -c interviews ID --set company=Acme --set status=action
    python tracker.py delete ID
--set values are text. For numbers, quotes or $ signs, pass a JSON object with --data, --file or --stdin.
--unset KEY removes a field. Add --if-version N to a write to refuse it if the row changed since you read it.

Job row fields: company, role, url, location, pay, status (todo | applied | error | skipped), appliedOn (YYYY-MM-DD),
resume, notes, issue, source (log | manual), priority (1 = top), track (role family: engineering, software, test,
manufacturing, research, operations, customer, other; the list is TRACKS in tracker.html), lane (fresh | standard),
response (none | received | review | screen | interview | offer | rejected), responseOn, responseNote.
"""

import argparse
import contextlib
import copy
import datetime as _dt
import glob
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_FILE = os.path.join(HERE, 'tracker.html')
SHIM_FILE = os.path.join(HERE, 'tracker-local-db.js')
DEFAULT_DATA = os.path.join(HERE, 'tracker-data.json')
DEFAULT_PORT = 8787
KEEP_BACKUPS = 30
MAX_BODY = 2_000_000
ID_RE = re.compile(r'^[A-Za-z0-9_\-.~:@+]{1,200}$')
COLL_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# Set by configure(): the data file and the files kept beside it.
DATA_FILE = DEFAULT_DATA
LOCK_FILE = LOG_FILE = None
STORE = None


# ---------------------------------------------------------------- helpers

def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def out(*parts):
    if sys.stdout is not None:
        try:
            print(*parts, flush=True)
        except (OSError, ValueError):
            pass


def eprint(*parts):
    if sys.stderr is not None:
        try:
            print(*parts, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass


def log(msg):
    if not LOG_FILE:
        return
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + '.1')
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{_dt.datetime.now().isoformat(timespec="seconds")} {msg}\n')
    except OSError:
        pass


def _retry(fn, tries=40, delay=0.05):
    """A cloud-sync client or a virus scanner can hold a file open for a moment; try again briefly."""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


class TrackerError(Exception):
    status = 400
    code = 'invalid_argument'


class NotFound(TrackerError):
    status = 404
    code = 'not_found'


class Exists(TrackerError):
    status = 409
    code = 'already_exists'


class Conflict(TrackerError):
    status = 409
    code = 'version_conflict'

    def __init__(self, msg, current=None):
        super().__init__(msg)
        self.current = current


@contextlib.contextmanager
def data_lock(timeout=20.0):
    """Cross-process lock, so the server and command-line writes never overlap."""
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TrackerError('The tracker data is busy (another program holds the lock). Try again.')
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                if os.name == 'nt':
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


# ---------------------------------------------------------------- data store

def empty_data():
    return {'format': 1, 'rev': 0, 'collections': {'jobs': {}, 'interviews': {}}}


class Store:
    """tracker-data.json: {"format": 1, "rev": N, "collections": {name: {id: {"version": V, "data": {...}}}}}"""

    def __init__(self, path):
        self.path = path
        folder = os.path.dirname(path)
        self.tmp = os.path.join(folder, '~$' + os.path.basename(path) + '.tmp')
        self.backup_dir = os.path.join(folder, 'backups')
        self.mu = threading.RLock()
        self._data = None
        self._sig = None

    def _stat(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self, force=False):
        sig = self._stat()
        if not force and self._data is not None and sig == self._sig:
            return self._data
        if sig is None:
            data = empty_data()
        else:
            def read():
                with open(self.path, 'r', encoding='utf-8-sig') as f:
                    return f.read()
            text = _retry(read)
            try:
                data = json.loads(text)
            except ValueError as e:
                raise TrackerError(f'{self.path} is not valid JSON ({e}). Restore it from the backups folder.')
            if not isinstance(data, dict) or not isinstance(data.get('collections'), dict):
                raise TrackerError(f'{self.path} does not look like tracker data.')
        self._data, self._sig = data, sig
        return data

    def ensure(self):
        """Create an empty data file if there is none yet."""
        with self.mu, data_lock():
            if self._stat() is None:
                self._save(empty_data())
                self._data, self._sig = None, None

    def snapshot(self):
        with self.mu:
            return self._load()

    def rev(self):
        return int(self.snapshot().get('rev', 0))

    def mutate(self, fn):
        """Apply fn to a fresh copy of the data and save it. Nothing is saved if fn raises."""
        with self.mu, data_lock():
            current = self._load(force=True)
            existed = self._sig is not None
            work = copy.deepcopy(current)
            work.setdefault('collections', {})
            result = fn(work)
            work['format'] = 1
            work['rev'] = int(current.get('rev', 0)) + 1
            work['updatedAt'] = now_iso()
            if existed:
                self._backup()
            self._save(work)
            self._data, self._sig = work, self._stat()
            return result

    def _save(self, data):
        text = json.dumps(data, ensure_ascii=False, indent=1)

        def write():
            with open(self.tmp, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        _retry(write)
        _retry(lambda: os.replace(self.tmp, self.path))

    def _backup(self):
        """Once a day, before the first change, keep a copy of the data (the last 30 days)."""
        try:
            os.makedirs(self.backup_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(self.path))[0]
            target = os.path.join(self.backup_dir, f'{stem}-{_dt.date.today().isoformat()}.json')
            if not os.path.exists(target):
                _retry(lambda: shutil.copyfile(self.path, target))
                for old in sorted(glob.glob(os.path.join(self.backup_dir, f'{stem}-*.json')))[:-KEEP_BACKUPS]:
                    os.remove(old)
        except OSError as e:
            log(f'backup failed: {e}')


def configure(data_file=None):
    """Point the tracker at a data file: --data-file, else $TRACKER_DATA, else tracker-data.json next to this file.
    The lock and the server log sit beside it."""
    global DATA_FILE, LOCK_FILE, LOG_FILE, STORE
    path = data_file or os.environ.get('TRACKER_DATA') or DEFAULT_DATA
    DATA_FILE = os.path.abspath(os.path.expanduser(path))
    folder = os.path.dirname(DATA_FILE)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(DATA_FILE))[0]
    LOCK_FILE = os.path.join(folder, stem + '.lock')
    LOG_FILE = os.path.join(folder, 'tracker-server.log')
    STORE = Store(DATA_FILE)


def check_names(coll, doc_id=None):
    if not COLL_RE.match(coll or ''):
        raise TrackerError(f'Bad collection name: {coll!r}')
    if doc_id is not None and not ID_RE.match(doc_id or ''):
        raise TrackerError(f'Bad row id: {doc_id!r} (letters, digits and - _ . ~ : @ + only, at most 200).')


def _check_data(data):
    if not isinstance(data, dict):
        raise TrackerError('Row data must be a JSON object of fields.')
    if len(json.dumps(data)) > 500_000:
        raise TrackerError('That row is too large.')


def _is_delete(v):
    return isinstance(v, dict) and v.get('__delete__') is True and len(v) == 1


def _strip_deletes(obj):
    if isinstance(obj, dict):
        return {k: _strip_deletes(v) for k, v in obj.items() if not _is_delete(v)}
    if isinstance(obj, list):
        return [_strip_deletes(v) for v in obj]
    return obj


def deep_merge(base, patch):
    merged = dict(base)
    for k, v in patch.items():
        if _is_delete(v):
            merged.pop(k, None)
        elif isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = deep_merge(merged[k], v)
        else:
            merged[k] = _strip_deletes(copy.deepcopy(v))
    return merged


def _pin(cur, doc_id, if_version):
    if if_version is not None and cur['version'] != int(if_version):
        raise Conflict(f'{doc_id} changed since you read it: it is at version {cur["version"]}, not {if_version}. '
                       'Read it again and redo the change.', cur['version'])


def _row(doc_id, entry):
    return {'id': doc_id, 'version': entry['version'], 'data': entry['data']}


def list_docs(store, coll):
    check_names(coll)
    snap = store.snapshot()
    docs = snap['collections'].get(coll, {})
    return {'rev': int(snap.get('rev', 0)), 'docs': [_row(k, v) for k, v in docs.items()]}


def get_doc(store, coll, doc_id):
    check_names(coll, doc_id)
    entry = store.snapshot()['collections'].get(coll, {}).get(doc_id)
    if entry is None:
        raise NotFound(f'No row {doc_id!r} in {coll}.')
    return _row(doc_id, entry)


def set_doc(store, coll, doc_id, data, if_version=None, create_only=False):
    check_names(coll, doc_id)
    _check_data(data)

    def fn(work):
        rows = work['collections'].setdefault(coll, {})
        cur = rows.get(doc_id)
        if cur is not None:
            if create_only:
                raise Exists(f'Row {doc_id!r} already exists in {coll}. Use update to change it.')
            _pin(cur, doc_id, if_version)
        elif if_version is not None:
            raise NotFound(f'No row {doc_id!r} in {coll}.')
        rows[doc_id] = {'version': cur['version'] + 1 if cur else 1, 'data': _strip_deletes(copy.deepcopy(data))}
        return _row(doc_id, rows[doc_id])
    return store.mutate(fn)


def update_doc(store, coll, doc_id, patch, if_version=None):
    check_names(coll, doc_id)
    _check_data(patch)

    def fn(work):
        rows = work['collections'].setdefault(coll, {})
        cur = rows.get(doc_id)
        if cur is None:
            raise NotFound(f'No row {doc_id!r} in {coll}. Use add to create it.')
        _pin(cur, doc_id, if_version)
        rows[doc_id] = {'version': cur['version'] + 1, 'data': deep_merge(cur['data'], patch)}
        return _row(doc_id, rows[doc_id])
    return store.mutate(fn)


def delete_doc(store, coll, doc_id, if_version=None):
    check_names(coll, doc_id)

    def fn(work):
        rows = work['collections'].setdefault(coll, {})
        cur = rows.get(doc_id)
        if cur is None:
            raise NotFound(f'No row {doc_id!r} in {coll}.')
        _pin(cur, doc_id, if_version)
        del rows[doc_id]
        return {'id': doc_id, 'deleted': True}
    return store.mutate(fn)


# ---------------------------------------------------------------- web server

LOOPBACK = ('127.0.0.1', '::1', 'localhost')


def local_ipv4s():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        # Picks the address of the interface that would route outward. UDP connect sends nothing.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    ips = [ip for ip in ips if not ip.startswith(('127.', '169.254.', '0.'))]
    return sorted(ips, key=lambda ip: (not ip.startswith('192.'), ip))


_hosts = {'at': 0.0, 'names': set()}


def allowed_hosts(refresh=False):
    if refresh or not _hosts['names'] or time.monotonic() - _hosts['at'] > 300:
        hn = socket.gethostname().lower()
        names = {'localhost', '127.0.0.1', '::1', hn, hn + '.local', hn + '.lan', hn + '.home', hn + '.localdomain'}
        names.update(local_ipv4s())
        _hosts['names'], _hosts['at'] = names, time.monotonic()
    return _hosts['names']


def host_name(header):
    h = (header or '').strip().lower()
    if h.startswith('['):
        return h[1:h.find(']')] if ']' in h else h
    if h.count(':') == 1:
        return h.split(':', 1)[0]
    return h


def is_lan_bind(bind):
    return bind not in LOOPBACK and not str(bind).startswith('127.')


def server_info(port, bind='127.0.0.1'):
    if not is_lan_bind(bind):
        lan = []
    elif bind in ('0.0.0.0', '::', ''):
        lan = [f'http://{ip}:{port}' for ip in local_ipv4s()]
    else:
        lan = [f'http://{bind}:{port}']
    return {'port': port, 'local': f'http://localhost:{port}', 'lan': lan, 'bind': bind}


def page_html():
    with open(PAGE_FILE, 'r', encoding='utf-8-sig') as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    server_version = 'JobTracker/1.0'
    protocol_version = 'HTTP/1.1'
    timeout = 60

    def log_message(self, fmt, *args):  # no per-request log
        pass

    def log_error(self, fmt, *args):
        msg = fmt % args
        if 'Request timed out' in msg:  # an idle browser connection closing; normal
            return
        log('http: ' + msg)

    def _send(self, status, body=b'', ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        if self.command != 'HEAD' and body:
            self.wfile.write(body)

    def _host_ok(self):
        name = host_name(self.headers.get('Host'))
        if name in LOOPBACK:
            return True
        if not is_lan_bind(self.server.bind):
            return False
        if name in allowed_hosts():
            return True
        # The network address may have changed; look again, at most every few seconds.
        if time.monotonic() - _hosts['at'] > 5:
            return name in allowed_hosts(refresh=True)
        return False

    def do_GET(self):
        self._handle('GET')

    def do_HEAD(self):
        self._handle('HEAD')

    def do_PUT(self):
        self._handle('PUT')

    def do_PATCH(self):
        self._handle('PATCH')

    def do_DELETE(self):
        self._handle('DELETE')

    def do_POST(self):
        self._handle('POST')

    def do_OPTIONS(self):
        self._handle('OPTIONS')

    def _handle(self, method):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            return self._send(413, {'error': 'Request body too large or malformed.', 'code': 'invalid_argument'})
        raw = self.rfile.read(n) if n else b''
        try:
            if not self._host_ok():
                # Blocks DNS-rebinding pages from reaching the tracker under another site's name.
                return self._send(403, {'error': 'This server answers only to this computer\'s own names and addresses.',
                                        'code': 'forbidden'})
            return self._route(method, raw)
        except TrackerError as e:
            body = {'error': str(e), 'code': e.code}
            if isinstance(e, Conflict) and e.current is not None:
                body['current'] = e.current
            return self._send(e.status, body)
        except Exception as e:  # keep serving; record what happened
            log(f'error on {method} {self.path}: {e!r}')
            return self._send(500, {'error': f'Server error. Details are in {LOG_FILE}.', 'code': 'internal'})

    def _json(self, raw):
        # Requiring a JSON content type forces a CORS preflight for any cross-site write, which this server never grants.
        ctype = (self.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        if ctype != 'application/json':
            raise TrackerError('Send the body as JSON with Content-Type: application/json.')
        try:
            obj = json.loads(raw.decode('utf-8') or '{}')
        except ValueError:
            raise TrackerError('The body is not valid JSON.')
        if not isinstance(obj, dict):
            raise TrackerError('The body must be a JSON object.')
        return obj

    def _route(self, method, raw):
        parts = urlsplit(self.path)
        path = parts.path
        read = method in ('GET', 'HEAD')
        if read and path in ('/', '/index.html', '/tracker.html'):
            return self._send(200, page_html(), 'text/html; charset=utf-8')
        if read and path == '/tracker-local-db.js':
            with open(SHIM_FILE, 'r', encoding='utf-8-sig') as f:
                return self._send(200, f.read(), 'text/javascript; charset=utf-8')
        if read and path == '/favicon.ico':
            return self._send(204)
        if read and path == '/api/rev':
            return self._send(200, {'rev': STORE.rev()})
        if read and path == '/api/info':
            return self._send(200, server_info(self.server.server_address[1], self.server.bind))
        if path == '/api/admin/stop' and method == 'PUT':
            if self.client_address[0] not in ('127.0.0.1', '::1'):
                raise TrackerError('Only this computer can stop the server.')
            self._json(raw)
            self._send(200, {'stopping': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        m = re.fullmatch(r'/api/c/([^/]+)(?:/([^/]+))?', path)
        if not m:
            return self._send(404, {'error': 'Not found.', 'code': 'not_found'})
        coll = unquote(m.group(1))
        doc_id = unquote(m.group(2)) if m.group(2) is not None else None
        if doc_id is None:
            if read:
                return self._send(200, list_docs(STORE, coll))
            return self._send(405, {'error': 'Method not allowed.', 'code': 'invalid_argument'})
        if read:
            return self._send(200, get_doc(STORE, coll, doc_id))
        if method in ('PUT', 'PATCH'):
            body = self._json(raw)
            iv = body.get('if_version')
            if iv is not None and (not isinstance(iv, int) or isinstance(iv, bool)):
                raise TrackerError('if_version must be a whole number.')
            if method == 'PUT':
                return self._send(200, set_doc(STORE, coll, doc_id, body.get('data'), iv))
            return self._send(200, update_doc(STORE, coll, doc_id, body.get('data'), iv))
        if method == 'DELETE':
            iv = parse_qs(parts.query).get('if_version', [''])[0]
            if iv and not iv.isdigit():
                raise TrackerError('if_version must be a whole number.')
            return self._send(200, delete_doc(STORE, coll, doc_id, int(iv) if iv else None))
        return self._send(405, {'error': 'Method not allowed.', 'code': 'invalid_argument'})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows, address reuse would let two servers share the port

    def __init__(self, addr, handler):
        self.bind = addr[0]
        super().__init__(addr, handler)

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)  # skips HTTPServer's slow reverse-DNS lookup
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


# ---------------------------------------------------------------- command line

LAN_WARNING = ('Warning: the tracker is open to your local network. Anyone on this network who can reach this '
               'computer can read and change your tracker. Use it only on a network you trust.')


def _http(method, path, port, body=None, timeout=2.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route localhost through a proxy
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, method=method, headers=headers)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8') or '{}')


def running(port):
    try:
        return _http('GET', '/api/rev', port, timeout=1.5)
    except Exception:
        return None


def print_urls(info):
    out(f'On this computer: {info["local"]}')
    for u in info.get('lan') or []:
        out(f'On other devices on this network: {u}')
    if is_lan_bind(info.get('bind', '127.0.0.1')):
        if not info.get('lan'):
            out('No network address found; only this computer can reach the tracker for now.')
        out(LAN_WARNING)


def bind_of(args):
    return '0.0.0.0' if args.lan else args.bind


def cmd_serve(args):
    deadline = time.monotonic() + max(0, args.wait)
    while True:
        try:
            STORE.ensure()
            STORE.snapshot()  # stop now if the data file is damaged
            break
        except TrackerError as e:
            log(f'not starting: {e}')
            raise
        except OSError as e:  # right after sign-in, a synced folder may not be available yet
            if time.monotonic() >= deadline:
                msg = f'Could not read {DATA_FILE} ({e}).'
                log(msg)
                eprint(msg)
                return 1
            time.sleep(2)
    bind = bind_of(args)
    try:
        httpd = Server((bind, args.port), Handler)
    except OSError as e:
        msg = f'Could not listen on port {args.port} ({e}). Is the tracker already running? Try: python tracker.py status'
        log(msg)
        eprint(msg)
        return 1
    info = server_info(args.port, bind)
    log(f'serving {DATA_FILE} on {bind}:{args.port}')
    out('Job tracker running.')
    print_urls(info)
    out('Press Ctrl+C to stop.')
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log('server stopped')
    return 0


def cmd_start(args):
    if running(args.port) is not None:
        out('The job tracker is already running.')
    else:
        STORE.ensure()
        exe = sys.executable
        if os.name == 'nt':
            pyw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
            if os.path.exists(pyw):
                exe = pyw  # no console window
        cmd = [exe, os.path.abspath(__file__), '--data-file', DATA_FILE, 'serve', '--port', str(args.port), '--bind', bind_of(args)]
        kw = dict(cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == 'nt':
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            try:
                subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)  # also leave the caller's job object
            except OSError:
                subprocess.Popen(cmd, creationflags=flags, **kw)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kw)
        for _ in range(60):
            time.sleep(0.25)
            if running(args.port) is not None:
                break
        else:
            eprint(f'The server did not start. Details: {LOG_FILE}')
            return 1
        out('Started the job tracker.')
    try:
        info = _http('GET', '/api/info', args.port)
    except Exception:
        info = server_info(args.port)
    print_urls(info)
    if args.lan and not is_lan_bind(info.get('bind', '127.0.0.1')):
        out('It is running for this computer only. To open it to the network: python tracker.py stop, then start --lan.')
    if args.open:
        import webbrowser
        webbrowser.open(f'http://localhost:{args.port}/')
    return 0


def cmd_stop(args):
    if running(args.port) is None:
        out('The job tracker is not running.')
        return 0
    try:
        _http('PUT', '/api/admin/stop', args.port, body={}, timeout=3)
    except Exception as e:
        eprint(f'Could not stop it: {e}')
        return 1
    for _ in range(20):
        time.sleep(0.25)
        if running(args.port) is None:
            out('Stopped the job tracker.')
            return 0
    eprint('It is still running.')
    return 1


def cmd_status(args):
    r = running(args.port)
    if r is None:
        out('The job tracker is not running. Start it with: python tracker.py start')
        return 1
    out(f'The job tracker is running (data revision {r.get("rev")}).')
    try:
        print_urls(_http('GET', '/api/info', args.port))
    except Exception:
        print_urls(server_info(args.port))
    return 0


def collect_fields(args):
    data = {}
    src = None
    if getattr(args, 'stdin', False):
        src = sys.stdin.buffer.read().decode('utf-8-sig')
    elif getattr(args, 'file', None):
        with open(args.file, 'r', encoding='utf-8-sig') as f:
            src = f.read()
    elif getattr(args, 'data', None):
        src = args.data
    if src is not None and src.strip():
        try:
            obj = json.loads(src)
        except ValueError as e:
            raise TrackerError(f'Not valid JSON: {e}')
        if not isinstance(obj, dict):
            raise TrackerError('The JSON must be one object of fields, like {"status": "applied"}.')
        data.update(obj)
    for pair in getattr(args, 'set', None) or []:
        key, sep, value = pair.partition('=')
        key = key.strip()
        if not sep or not key:
            raise TrackerError(f'--set needs key=value, got {pair!r}.')
        data[key] = value
    for key in getattr(args, 'unset', None) or []:
        data[key.strip()] = {'__delete__': True}
    return data


def norm_text(s):
    s = str(s or '').lower().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]', '', s)


def norm_url(u):
    u = str(u or '').strip().lower()
    u = re.sub(r'[?#].*$', '', u)
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = u.replace('%2c', ',').replace('/en-us/', '/')
    u = re.sub(r'(job-boards|boards)\.greenhouse\.io', 'greenhouse.io', u)
    u = re.sub(r'/apply(/.*)?$', '', u)
    u = re.sub(r'/(application|apps/new)$', '', u)
    return re.sub(r'[^a-z0-9]', '', u.rstrip('/'))


def row_matches(d, terms):
    hay = norm_text(' '.join(str(d.get(k, '')) for k in ('company', 'role', 'location')))
    du = norm_url(d.get('url', ''))
    for t in terms:
        if re.match(r'^(https?://|www\.)', t.strip().lower()):
            tu = norm_url(t)
            if not (tu and du and (tu in du or du in tu)):
                return False
        else:
            nt = norm_text(t)
            if nt and nt not in hay and nt not in du:
                return False
    return True


def show(r):
    d = r['data']
    return f"{r['id']}  v{r['version']}  {d.get('status', '-')}  {d.get('company', '')} | {d.get('role', '')} | {d.get('url', '')}"


def _print_rows(rows, as_json):
    rows = sorted(rows, key=lambda r: (str(r['data'].get('company', '')).lower(), str(r['data'].get('role', '')).lower(), r['id']))
    if as_json:
        out(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    for r in rows:
        out(show(r))
    out(f'{len(rows)} row' + ('' if len(rows) == 1 else 's'))


def cmd_list(args):
    rows = list_docs(STORE, args.collection)['docs']
    if args.status:
        rows = [r for r in rows if str(r['data'].get('status', '')) == args.status]
    for cond in args.where or []:
        k, _, v = cond.partition('=')
        rows = [r for r in rows if str(r['data'].get(k.strip(), '')) == v]
    _print_rows(rows, args.json)
    return 0


def cmd_find(args):
    rows = [r for r in list_docs(STORE, args.collection)['docs'] if row_matches(r['data'], args.terms)]
    _print_rows(rows, args.json)
    return 0


def cmd_get(args):
    out(json.dumps(get_doc(STORE, args.collection, args.id), ensure_ascii=False, indent=1))
    return 0


def cmd_update(args):
    data = collect_fields(args)
    if not data:
        raise TrackerError('Nothing to change. Give --set key=value, --unset key, --data, --file or --stdin.')
    data.setdefault('updatedAt', now_iso())
    r = update_doc(STORE, args.collection, args.id, data, args.if_version)
    out(f'Updated {r["id"]} (now version {r["version"]}).')
    return 0


def cmd_set(args):
    data = collect_fields(args)
    if not data:
        raise TrackerError("Give the row's fields with --set, --data, --file or --stdin.")
    data.setdefault('updatedAt', now_iso())
    r = set_doc(STORE, args.collection, args.id, data, args.if_version)
    out(f'Saved {r["id"]} (version {r["version"]}).')
    return 0


def slugify(*parts):
    s = '-'.join(str(p or '') for p in parts).lower().replace('&', ' and ')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:76].strip('-')


def cmd_add(args):
    data = collect_fields(args)
    if args.collection == 'jobs':
        if not str(data.get('company', '')).strip() or not str(data.get('role', '')).strip():
            raise TrackerError('A new job row needs at least company and role.')
        data.setdefault('source', 'log')
        data.setdefault('priority', 2)
    elif not args.id:
        raise TrackerError('Give an id for a new row outside the jobs collection.')
    data.setdefault('createdAt', now_iso())
    data.setdefault('updatedAt', data['createdAt'])
    doc_id = args.id or ('log-' + slugify(data.get('company'), data.get('role')))
    r = set_doc(STORE, args.collection, doc_id, data, create_only=True)
    out(f'Added {r["id"]} (version {r["version"]}).')
    return 0


def cmd_delete(args):
    delete_doc(STORE, args.collection, args.id, args.if_version)
    out(f'Deleted {args.id}.')
    return 0


def cmd_import_dir(args):
    files = sorted(glob.glob(os.path.join(args.dir, '*.json')))
    if not files:
        raise TrackerError(f'No .json files in {args.dir}')
    incoming = {}
    for p in files:
        doc_id = os.path.splitext(os.path.basename(p))[0]
        check_names(args.collection, doc_id)
        with open(p, 'r', encoding='utf-8-sig') as f:
            obj = json.load(f)
        if isinstance(obj, dict) and isinstance(obj.get('data'), dict) and set(obj) <= {'id', 'version', 'data'}:
            obj = obj['data']
        _check_data(obj)
        incoming[doc_id] = obj

    def fn(work):
        rows = work['collections'].setdefault(args.collection, {})
        if args.replace:
            rows.clear()
        new = 0
        for doc_id, data in incoming.items():
            cur = rows.get(doc_id)
            new += cur is None
            rows[doc_id] = {'version': cur['version'] + 1 if cur else 1, 'data': data}
        return new
    new = STORE.mutate(fn)
    out(f'Imported {len(incoming)} rows into {args.collection}: {new} new, {len(incoming) - new} replaced.')
    return 0


def cmd_export(args):
    snap = STORE.snapshot()
    payload = {'rev': snap.get('rev', 0), 'exportedAt': now_iso(),
               'collections': {name: [_row(k, v) for k, v in rows.items()] for name, rows in snap['collections'].items()}}
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text)
        out(f'Saved {args.out}')
    else:
        out(text)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='tracker.py', description='Job Tracker: local web server and row editor.',
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument('--data-file', metavar='PATH',
                   help='the data file to use (default: $TRACKER_DATA, else tracker-data.json next to this script)')
    sub = p.add_subparsers(dest='cmd', required=True)

    def coll(sp):
        sp.add_argument('-c', '--collection', default='jobs', help='jobs (default) or interviews')

    def fields(sp):
        sp.add_argument('--set', action='append', metavar='KEY=VALUE', help='set a text field (repeat for more)')
        sp.add_argument('--unset', action='append', metavar='KEY', help='remove a field (repeat for more)')
        g = sp.add_mutually_exclusive_group()
        g.add_argument('--data', metavar='JSON', help='fields as one JSON object')
        g.add_argument('--file', metavar='PATH', help='fields from a JSON file')
        g.add_argument('--stdin', action='store_true', help='fields as one JSON object on standard input')

    def port(sp):
        sp.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'default {DEFAULT_PORT}')

    def network(sp):
        sp.add_argument('--lan', action='store_true',
                        help='also answer other devices on this network (anyone on it can then edit the tracker)')
        sp.add_argument('--bind', default='127.0.0.1', help='address to listen on (default 127.0.0.1: this computer only)')

    sp = sub.add_parser('serve', help='run the server in this window')
    port(sp)
    network(sp)
    sp.add_argument('--wait', type=int, default=0, metavar='SECONDS',
                    help='keep trying this long if the data file cannot be read yet (useful when started at sign-in)')
    sp.set_defaults(func=cmd_serve)
    sp = sub.add_parser('start', help='start the server in the background')
    port(sp)
    network(sp)
    sp.add_argument('--open', action='store_true', help='open the page in the browser')
    sp.set_defaults(func=cmd_start)
    sp = sub.add_parser('stop', help='stop the background server')
    port(sp)
    sp.set_defaults(func=cmd_stop)
    sp = sub.add_parser('status', help='say whether the server is running and where')
    port(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser('list', help='list rows')
    coll(sp)
    sp.add_argument('--status', help='only rows with this status')
    sp.add_argument('--where', action='append', metavar='KEY=VALUE', help='only rows whose field equals this text')
    sp.add_argument('--json', action='store_true', help='print full rows as JSON')
    sp.set_defaults(func=cmd_list)
    sp = sub.add_parser('find', help='rows whose company, role, location or link contain every term')
    coll(sp)
    sp.add_argument('terms', nargs='+')
    sp.add_argument('--json', action='store_true', help='print full rows as JSON')
    sp.set_defaults(func=cmd_find)
    sp = sub.add_parser('get', help='print one row as JSON')
    coll(sp)
    sp.add_argument('id')
    sp.set_defaults(func=cmd_get)
    for name, func, hlp in (('update', cmd_update, 'merge fields into a row'), ('set', cmd_set, 'replace a row, or create it')):
        sp = sub.add_parser(name, help=hlp)
        coll(sp)
        sp.add_argument('id')
        fields(sp)
        sp.add_argument('--if-version', type=int, metavar='N', help='refuse the write if the row is no longer at version N')
        sp.set_defaults(func=func)
    sp = sub.add_parser('add', help='create a row (fails if the id exists); id defaults to log-<company>-<role>')
    coll(sp)
    sp.add_argument('id', nargs='?')
    fields(sp)
    sp.set_defaults(func=cmd_add)
    sp = sub.add_parser('delete', help='remove a row')
    coll(sp)
    sp.add_argument('id')
    sp.add_argument('--if-version', type=int, metavar='N', help='refuse the delete if the row is no longer at version N')
    sp.set_defaults(func=cmd_delete)
    sp = sub.add_parser('import-dir', help='load <id>.json files, one per row')
    coll(sp)
    sp.add_argument('dir')
    sp.add_argument('--replace', action='store_true', help='remove the collection\'s other rows first')
    sp.set_defaults(func=cmd_import_dir)
    sp = sub.add_parser('export', help='print or save every row as JSON')
    sp.add_argument('--out', metavar='PATH')
    sp.set_defaults(func=cmd_export)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (AttributeError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    try:
        configure(args.data_file)
        return args.func(args) or 0
    except TrackerError as e:
        eprint(f'Error: {e}')
        return 1
    except OSError as e:
        eprint(f'Error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
