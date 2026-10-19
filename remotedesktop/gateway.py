#!/usr/bin/env python3
"""Authenticated loopback console for the current Xorg desktop or a test fixture.

Use an SSH tunnel for remote access. This is not a system login/PAM service.
"""
import argparse
import asyncio
import collections
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import shutil
import stat
import struct
import sys
import time

from aiohttp import web, WSMsgType

ROOT = Path(__file__).resolve().parent


class ProtocolError(ValueError):
    pass


class InputTracker:
    """Bounded RFB 3.8/None client parser; forwards complete allowed messages.

    Only the no-password child stream uses None; the HTTP gateway authenticates
    before creating it. Clipboard and resize are deliberately not implemented.
    """
    # Advertising ExtendedClipboard makes noVNC respond with ClientCutText even
    # without a clipboard UI. Negotiate only extensions this gateway accepts.
    # Also suppress extended mouse buttons and server power control (XVP).
    # Cursor shapes/positions are painted by x11vnc into the framebuffer, not
    # separately rendered by the browser (RichCursor, XCursor, PointerPos,
    # VMwareCursor). This keeps cursor and desktop scaling identical.
    BLOCKED_ENCODINGS = frozenset({-1063131698, -316, -309,
                                  -239, -240, -232, 0x574d5664})

    def __init__(self):
        self.buffer = bytearray()
        self.phase = 0
        self.keys = {}
        self.pointer = (0, 0)
        self.buttons = 0
        self.message_types = set()

    @property
    def ready(self):
        return self.phase == 3

    def feed(self, data):
        self.buffer.extend(data)
        if len(self.buffer) > 1_048_576:
            raise ProtocolError('client buffer limit')
        messages = []
        while self.buffer:
            if self.phase < 3:
                n = 12 if self.phase == 0 else 1
                if len(self.buffer) < n:
                    break
                msg = bytes(self.buffer[:n])
                del self.buffer[:n]
                if self.phase == 0 and msg != b'RFB 003.008\n':
                    raise ProtocolError('RFB 3.8 required')
                if self.phase == 1 and msg != b'\x01':
                    raise ProtocolError('unexpected backend security selection')
                if self.phase == 2 and msg not in (b'\x00', b'\x01'):
                    raise ProtocolError('invalid ClientInit')
                self.phase += 1
                messages.append(msg)
                continue
            t = self.buffer[0]
            sizes = {0: 20, 3: 10, 4: 8, 5: 6, 150: 10, 255: 12}
            if t == 2:
                if len(self.buffer) < 4:
                    break
                n = 4 + 4 * struct.unpack('!H', self.buffer[2:4])[0]
                if n > 4096:
                    raise ProtocolError('too many encodings')
            elif t == 248:
                if len(self.buffer) < 9:
                    break
                n = 9 + self.buffer[8]
                if n > 73:
                    raise ProtocolError('fence payload too large')
            elif t in sizes:
                n = sizes[t]
            else:
                raise ProtocolError(f'unsupported client message {t}')
            if len(self.buffer) < n:
                break
            msg = bytes(self.buffer[:n])
            del self.buffer[:n]
            if t == 2:
                encodings = [e[0] for e in struct.iter_unpack('!i', msg[4:])
                             if e[0] not in self.BLOCKED_ENCODINGS]
                msg = struct.pack('!BBH', 2, 0, len(encodings)) + b''.join(
                    struct.pack('!i', encoding) for encoding in encodings)
            elif t == 4:
                key = ('std', struct.unpack('!I', msg[4:8])[0])
                if msg[1]:
                    self.keys[key] = b'\x04\x00\x00\x00' + msg[4:8]
                else:
                    self.keys.pop(key, None)
            elif t == 255:
                if msg[1] != 0:
                    raise ProtocolError('unsupported extended input')
                key = ('ext', msg[4:12])
                if struct.unpack('!H', msg[2:4])[0]:
                    self.keys[key] = msg[:2] + b'\x00\x00' + msg[4:]
                else:
                    self.keys.pop(key, None)
            elif t == 5:
                if msg[1] & 128:
                    raise ProtocolError('extended mouse buttons not supported')
                self.buttons = msg[1]
                self.pointer = struct.unpack('!HH', msg[2:6])
            self.message_types.add(t)
            messages.append(msg)
        return messages

    def releases(self):
        out = list(self.keys.values())
        if self.buttons:
            out.append(struct.pack('!BBHH', 5, 0, *self.pointer))
        self.keys.clear()
        self.buttons = 0
        return out


class Gateway:
    def __init__(self, *, port, password, manifest, backend='fixture', ttl=600,
                 handshake_timeout=8, heartbeat=10, fixture_state=None):
        (ROOT/'runtime').mkdir(mode=0o700, exist_ok=True)
        self.host = f'127.0.0.1:{port}'
        self.origin = f'http://{self.host}'
        self.manifest = Path(manifest)
        self.backend = backend
        self.fixture_state = Path(fixture_state or ROOT/'runtime/fixture-state.json')
        self.salt = secrets.token_bytes(16)
        self.password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), self.salt, 120000)
        self.ttl = ttl
        self.handshake_timeout = handshake_timeout
        self.heartbeat = heartbeat
        self.sessions = {}
        self.attempts = collections.deque()
        self.active = None
        self.stats = {'spawned': 0, 'closed': 0, 'bytes_to_client': 0,
                      'bytes_to_backend': 0, 'releases_sent': 0, 'child_reaped': 0}
        self.app = web.Application(middlewares=[self.guard], client_max_size=4096)
        self.app.add_routes([
            web.get('/', self.index), web.get('/frontend.js', self.javascript),
            web.post('/login', self.login), web.post('/logout', self.logout),
            web.get('/status', self.status), web.get('/ws', self.websocket),
        ])
        self.app.on_shutdown.append(self.shutdown)

    @web.middleware
    async def guard(self, request, handler):
        if request.host != self.host:
            raise web.HTTPForbidden(text='Invalid Host')
        if request.method == 'POST' or request.path == '/ws':
            if request.headers.get('Origin') != self.origin:
                raise web.HTTPForbidden(text='Invalid Origin')
        response = await handler(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            f"connect-src 'self' ws://{self.host}; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    def session(self, request):
        sid = request.cookies.get('console_session', '')
        expiry = self.sessions.get(sid, 0)
        if expiry <= time.monotonic():
            self.sessions.pop(sid, None)
            raise web.HTTPUnauthorized(text='Authentication required')
        return sid

    async def index(self, request):
        return web.FileResponse(ROOT/'index.html')

    async def javascript(self, request):
        return web.FileResponse(ROOT/'frontend.js')

    async def login(self, request):
        now = time.monotonic()
        while self.attempts and self.attempts[0] < now - 60:
            self.attempts.popleft()
        if len(self.attempts) >= 8:
            raise web.HTTPTooManyRequests(text='Try again later')
        self.attempts.append(now)
        try:
            body = await request.json()
            name, password = body['username'], body['password']
            if not isinstance(name, str) or not isinstance(password, str) or len(password) > 256:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text='Invalid login request')
        candidate = await asyncio.to_thread(hashlib.pbkdf2_hmac, 'sha256', password.encode(), self.salt, 120000)
        if not hmac.compare_digest(candidate, self.password_hash) or name != 'demo':
            raise web.HTTPUnauthorized(text='Invalid credentials')
        # Rotate this browser's previous session; invalidate any associated stream.
        old = request.cookies.get('console_session')
        self.sessions.pop(old, None)
        if self.active and self.active['sid'] == old and self.active.get('ws'):
            await self.active['ws'].close(code=1008, message=b'Session rotated')
        sid = secrets.token_urlsafe(32)
        # Bound memory even if the test password is deliberately shared.
        self.sessions = {k: v for k, v in self.sessions.items() if v > now}
        if len(self.sessions) >= 16:
            raise web.HTTPServiceUnavailable(text='Session capacity reached')
        self.sessions[sid] = time.monotonic() + self.ttl
        response = web.json_response({'ok': True, 'mode': 'TEST ONLY'})
        response.set_cookie('console_session', sid, httponly=True, samesite='Strict',
                            secure=False, path='/', max_age=int(self.ttl))
        return response

    async def logout(self, request):
        sid = request.cookies.get('console_session', '')
        self.sessions.pop(sid, None)
        if self.active and self.active['sid'] == sid and self.active.get('ws'):
            await self.active['ws'].close(code=1008, message=b'Logged out')
        response = web.json_response({'ok': True})
        response.del_cookie('console_session', path='/')
        return response

    async def status(self, request):
        self.session(request)
        try:
            self.selection()
            display_error = None
        except (OSError, ValueError, KeyError):
            display_error = '桌面会话不可用，请在已登录的 Xorg 桌面中重新启动服务。'
        return web.json_response({'test_only': True, 'backend': self.backend,
                                  'display_error': display_error,
                                  'active': self.active is not None, **self.stats})

    @staticmethod
    def private_file(path):
        p = Path(path)
        s = p.lstat()
        if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise ValueError('expected a private regular file owned by gateway uid')
        return s

    def selection(self):
        self.private_file(self.manifest)
        data = json.loads(self.manifest.read_text())
        if data.get('type') == 'wayland':
            raise ValueError('Wayland is unsupported; physical Xorg required')
        expected = 'synthetic' if self.backend == 'fixture' else 'x11'
        if data.get('type') != expected or not re.fullmatch(r':[0-9]{1,4}', data.get('display', '')):
            raise ValueError('unsupported display identity')
        if not isinstance(data.get('generation'), str) or not data['generation']:
            raise ValueError('missing generation')
        if self.backend == 'x11vnc':
            auth = Path(data['auth'])
            # This gateway only reads its owner's X authority. A production
            # privileged seat broker needs its own separately reviewed boundary.
            s = self.private_file(auth)
            data['auth_identity'] = [s.st_dev, s.st_ino, s.st_mtime_ns]
        return data

    async def spawn(self, selection):
        parent, child = socket.socketpair()
        parent.setblocking(False)
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(ROOT/'runtime'),
               'LD_LIBRARY_PATH': str(ROOT/'vendor/root/usr/lib/x86_64-linux-gnu')}
        if self.backend == 'fixture':
            argv = [sys.executable, str(ROOT/'fixture.py'), '--state', str(self.fixture_state),
                    '--generation', selection['generation']]
        else:
            executable = shutil.which('x11vnc') or str(ROOT/'vendor/root/usr/bin/x11vnc')
            argv = [executable, '-norc', '-inetd', '-nopw',
                    '-display', selection['display'], '-auth', selection['auth'],
                    '-safer', '-nocmds', '-noxdamage', '-nosel', '-noprimary',
                    '-nosetprimary', '-noclipboard', '-nosetclipboard',
                    '-nocursorshape', '-nocursorpos', '-q']
        log = open(ROOT/'runtime/backend.log', 'ab', buffering=0)
        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=child,
                        stdout=asyncio.subprocess.DEVNULL, stderr=log, env=env)
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
            log.close()
        self.stats['spawned'] += 1
        return parent, proc

    async def websocket(self, request):
        sid = self.session(request)
        if self.active is not None:
            raise web.HTTPConflict(text='One remote controller is already active')
        try:
            selection = self.selection()
        except (OSError, ValueError, KeyError):
            raise web.HTTPServiceUnavailable(text='No supported authorized display')
        # No await between check and reservation: atomic in this event loop.
        active = {'sid': sid, 'ws': None, 'proc': None}
        self.active = active
        ws = web.WebSocketResponse(heartbeat=self.heartbeat, timeout=.5, max_msg_size=1_048_576,
                                   compress=False)
        tracker = InputTracker()
        sock = proc = None
        tasks = []
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        try:
            await ws.prepare(request)
            active['ws'] = ws
            sock, proc = await self.spawn(selection)
            active['proc'] = proc

            async def backend_to_client():
                while True:
                    data = await loop.sock_recv(sock, 65536)
                    if not data:
                        break
                    self.stats['bytes_to_client'] += len(data)
                    await ws.send_bytes(data)

            async def client_to_backend():
                async for msg in ws:
                    if msg.type != WSMsgType.BINARY:
                        if msg.type == WSMsgType.TEXT:
                            raise ProtocolError('binary RFB only')
                        break
                    for data in tracker.feed(msg.data):
                        await loop.sock_sendall(sock, data)
                        self.stats['bytes_to_backend'] += len(data)

            async def lifecycle():
                while True:
                    await asyncio.sleep(.1)
                    if self.sessions.get(sid, 0) <= time.monotonic():
                        break
                    try:
                        if self.selection() != selection:
                            break
                    except (OSError, ValueError, KeyError):
                        break
                    if not tracker.ready and time.monotonic() - started > self.handshake_timeout:
                        break
                await ws.close(code=1008, message=b'Session/display expired or changed')

            tasks = [asyncio.create_task(x()) for x in (backend_to_client, client_to_backend, lifecycle)]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                with contextlib.suppress(asyncio.CancelledError):
                    error = task.exception()
                    if error:
                        detail = f': {error}' if isinstance(error, ProtocolError) else ''
                        print(f'bridge stopped: {type(error).__name__}{detail}', file=sys.stderr)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Release only tracked remote input, not global physical keyboard state.
            if sock and proc and proc.returncode is None:
                releases = tracker.releases()
                for data in releases:
                    try:
                        await asyncio.wait_for(loop.sock_sendall(sock, data), .25)
                        self.stats['releases_sent'] += 1
                    except (OSError, asyncio.TimeoutError):
                        break
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_WR)
                # EOF allows an ordinary exit after queued releases are processed.
                try:
                    await asyncio.wait_for(proc.wait(), 1)
                except asyncio.TimeoutError:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), 1)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
            if sock:
                sock.close()
            if proc:
                await proc.wait()
                self.stats['child_reaped'] += 1
            await ws.close()
            self.stats['closed'] += 1
            if self.active is active:
                self.active = None
        return ws

    async def shutdown(self, app):
        if self.active and self.active.get('ws'):
            await self.active['ws'].close(code=1001, message=b'Gateway shutdown')
        # aiohttp runner waits for handler cleanup/reap before shutdown completes.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-mode', action='store_true', required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--backend', choices=['fixture', 'x11vnc'], default='fixture')
    parser.add_argument('--manifest', default=str(ROOT/'runtime/display.json'))
    args = parser.parse_args()
    password = os.environ.pop('POC_TEST_PASSWORD', '')
    if len(password) < 16:
        parser.error('set a temporary POC_TEST_PASSWORD of at least 16 characters')
    if not (1024 <= args.port <= 65535):
        parser.error('use an unprivileged loopback port')
    g = Gateway(port=args.port, password=password, manifest=args.manifest, backend=args.backend)
    print('TEST ONLY: loopback HTTP, synthetic auth; never expose this service.', flush=True)
    web.run_app(g.app, host='127.0.0.1', port=args.port, access_log=None)


if __name__ == '__main__':
    main()
