"""Reproducible tests. These exercise synthetic RFB, NOT a real Linux desktop."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import tempfile
import time
import unittest

from aiohttp import ClientSession, CookieJar, WSServerHandshakeError, WSMsgType, web
from PIL import Image
from gateway import Gateway, InputTracker, ProtocolError, ROOT

ART = ROOT/'artifacts'
ART.mkdir(exist_ok=True)


class TrackerTests(unittest.TestCase):
    def tracker(self):
        t=InputTracker()
        for x in b'RFB 003.008\n\x01\x01':
            t.feed(bytes([x]))
        self.assertTrue(t.ready)
        return t

    def test_fragmented_handshake_and_remote_input_release(self):
        t=self.tracker()
        for k in (0xffe1, 0xffe3, 0xffe9, 0xffeb):
            msg=struct.pack('!BBHI',4,1,0,k)
            for x in msg: t.feed(bytes([x]))
        t.feed(struct.pack('!BBHH',5,1,90,110))
        out=t.releases()
        self.assertEqual(len(out),5)
        self.assertEqual(out[-1],struct.pack('!BBHH',5,0,90,110))
        self.assertEqual(t.releases(),[])

    def test_extended_keys_are_released_in_same_format(self):
        t=self.tracker(); m=struct.pack('!BBHII',255,0,1,0xffe3,29)
        t.feed(m); self.assertEqual(t.releases(),[struct.pack('!BBHII',255,0,0,0xffe3,29)])

    def test_clipboard_resize_and_unknown_messages_fail_closed(self):
        for typ in [6,251,7,249]:
            with self.subTest(typ=typ), self.assertRaises(ProtocolError): self.tracker().feed(bytes([typ]))

    def test_handshake_and_buffer_limits_fail_closed(self):
        with self.assertRaises(ProtocolError): InputTracker().feed(b'RFB 003.003\n')
        with self.assertRaises(ProtocolError): self.tracker().feed(b'\x02\x00\xff\xff')
        with self.assertRaises(ProtocolError): InputTracker().feed(b'x'*1_048_577)


    def test_fragmented_novnc_encoding_negotiation_suppresses_unsupported_extensions(self):
        # Actual noVNC extensions that made x11vnc trigger ClientCutText and
        # caused an immediate browser disconnect before this fix.
        encodings = [1, 7, 16, 0, -223, -1063131698, -316, -309, -258,
                     -239, -240, -232, 0x574d5664]
        message = struct.pack('!BBH', 2, 0, len(encodings)) + b''.join(
            struct.pack('!i', e) for e in encodings)
        tracker = self.tracker()
        output = []
        for value in message:
            output.extend(tracker.feed(bytes([value])))
        kept = [1, 7, 16, 0, -223, -258]
        self.assertEqual(output, [struct.pack('!BBH', 2, 0, len(kept)) + b''.join(
            struct.pack('!i', e) for e in kept)])
        with self.assertRaises(ProtocolError): tracker.feed(b'\x06')

    def test_encoding_filter_preserves_following_input_and_empty_negotiation(self):
        tracker = self.tracker()
        key = struct.pack('!BBHI', 4, 1, 0, 0xffe3)
        message = struct.pack('!BBHi', 2, 0, 1, -1063131698)
        self.assertEqual(tracker.feed(message + key), [b'\x02\x00\x00\x00', key])
        self.assertEqual(tracker.releases(), [struct.pack('!BBHI', 4, 0, 0, 0xffe3)])


class Rfb:
    def __init__(self,ws): self.ws=ws; self.buf=bytearray()
    async def read(self,n):
        while len(self.buf)<n:
            m=await asyncio.wait_for(self.ws.receive(),5)
            if m.type != WSMsgType.BINARY: raise EOFError(f'RFB ended: {m.type}')
            self.buf.extend(m.data)
        out=bytes(self.buf[:n]); del self.buf[:n]; return out
    async def initialize(self):
        assert await self.read(12)==b'RFB 003.008\n'
        await self.ws.send_bytes(b'RFB 003.008\n')
        assert await self.read(2)==b'\x01\x01'
        await self.ws.send_bytes(b'\x01')
        assert await self.read(4)==b'\0'*4
        await self.ws.send_bytes(b'\x01')
        header=await self.read(24)
        self.width,self.height=struct.unpack('!HH',header[:4])
        self.name=(await self.read(struct.unpack('!I',header[20:24])[0])).decode()
        await self.ws.send_bytes(struct.pack('!BBHi',2,0,1,0))
        return self
    async def frame(self,save=None):
        await self.ws.send_bytes(struct.pack('!BBHHHH',3,0,0,0,self.width,self.height))
        header=await self.read(4)
        assert header[0]==0
        count=struct.unpack('!H',header[2:])[0]
        pixels=0
        for _ in range(count):
            rect=await self.read(12)
            x,y,w,h,enc=struct.unpack('!HHHHi',rect)
            assert enc==0
            data=await self.read(w*h*4); pixels+=len(data)
            if save: Image.frombytes('RGB',(w,h),data,'raw','BGRX').save(save)
        return pixels
    async def key(self,k,down): await self.ws.send_bytes(struct.pack('!BBHI',4,int(down),0,k))
    async def pointer(self,mask,x=120,y=180): await self.ws.send_bytes(struct.pack('!BBHH',5,mask,x,y))


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT/'runtime').mkdir(mode=0o700, exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runtime')
        self.dir=Path(self.temp.name); self.manifest=self.dir/'display.json'; self.state=self.dir/'state.json'
        self.write_manifest()
        self.g=Gateway(port=0,password=secrets.token_urlsafe(24),manifest=self.manifest,
                       fixture_state=self.state,handshake_timeout=.4,heartbeat=1)
        # Use a random temporary password known only to this test process.
        self.password=secrets.token_urlsafe(24)
        import hashlib
        self.g.password_hash=hashlib.pbkdf2_hmac('sha256',self.password.encode(),self.g.salt,120000)
        self.runner=web.AppRunner(self.g.app,access_log=None); await self.runner.setup()
        self.site=web.TCPSite(self.runner,'127.0.0.1',0); await self.site.start()
        port=self.site._server.sockets[0].getsockname()[1]
        self.g.host=f'127.0.0.1:{port}'; self.g.origin=f'http://{self.g.host}'; self.url=self.g.origin
        self.client=ClientSession(cookie_jar=CookieJar(unsafe=True))
        self.clients=[self.client]
        self.websockets=[]

    def write_manifest(self,generation='g1',kind='synthetic'):
        tmp=self.manifest.with_suffix('.new'); tmp.write_text(json.dumps({'type':kind,'display':':91','generation':generation}))
        tmp.chmod(0o600); tmp.replace(self.manifest)

    async def login(self,client=None):
        c=client or self.client
        async with c.post(self.url+'/login',headers={'Origin':self.url},json={'username':'demo','password':self.password}) as r:
            self.assertEqual(r.status,200,await r.text())
            cookie=r.cookies['console_session']; self.assertTrue(cookie['httponly']); self.assertEqual(cookie['samesite'],'Strict')
            return cookie.value

    async def connect(self,client=None):
        ws=await (client or self.client).ws_connect(self.url+'/ws',headers={'Origin':self.url})
        self.websockets.append(ws)
        return await Rfb(ws).initialize()

    async def idle(self):
        for _ in range(100):
            if self.g.active is None: return
            await asyncio.sleep(.03)
        self.fail('controller slot was not released')

    async def state_until(self,predicate):
        for _ in range(100):
            try:
                d=json.loads(self.state.read_text())
                if predicate(d): return d
            except (OSError,json.JSONDecodeError): pass
            await asyncio.sleep(.02)
        self.fail('fixture state did not reach expected result')

    async def asyncTearDown(self):
        for ws in self.websockets: await ws.close()
        for c in self.clients: await c.close()
        await self.runner.cleanup()
        self.temp.cleanup()

    async def test_auth_origin_host_gates_no_backend(self):
        async with self.client.get(self.url+'/status') as r: self.assertEqual(r.status,401)
        for hdr,status in [({'Origin':self.url},401),({'Origin':'http://evil.example'},403),({},403),({'Origin':self.url,'Host':'evil.example'},403)]:
            with self.assertRaises(WSServerHandshakeError) as exc:
                await self.client.ws_connect(self.url+'/ws',headers=hdr)
            self.assertEqual(exc.exception.status,status)
        async with self.client.post(self.url+'/login',json={'username':'demo','password':self.password}) as r: self.assertEqual(r.status,403)
        async with self.client.post(self.url+'/login',headers={'Origin':self.url},json={'username':'demo','password':'wrong'}) as r: self.assertEqual(r.status,401)
        self.assertEqual(self.g.stats['spawned'],0)
        await self.login()
        for hdr in ({'Origin':'null'},{'Origin':'http://evil.example'},{'Origin':self.url,'Host':'evil.example'}):
            with self.assertRaises(WSServerHandshakeError) as exc:
                await self.client.ws_connect(self.url+'/ws',headers=hdr)
            self.assertEqual(exc.exception.status,403)
        self.assertEqual(self.g.stats['spawned'],0)

    async def test_synthetic_pixels_keyboard_pointer_and_reconnect(self):
        await self.login(); r=await self.connect()
        self.assertIn('synthetic',r.name.lower())
        pixels=await r.frame(ART/'synthetic-protocol-frame.png')
        self.assertEqual(pixels,800*500*4)
        for ch in 'Hello': await r.key(ord(ch),True); await r.key(ord(ch),False)
        await r.pointer(1); await r.pointer(0)
        state=await self.state_until(lambda d:d['typed_text']=='Hello' and d['click_count']==1)
        self.assertEqual(state['pointer_x'],120); self.assertEqual(state['pointer_y'],180)
        await r.ws.close(); await self.idle()
        r2=await self.connect(); self.assertEqual((r2.width,r2.height),(800,500))
        await r2.ws.close(); await self.idle()
        self.assertEqual(self.g.stats['child_reaped'],2)
        (ART/'synthetic-transport.json').write_text(json.dumps({'kind':'synthetic RFB protocol only; not bandwidth or desktop acceptance','width':800,'height':500,'raw_frame_payload_bytes':pixels,'typed_text':state['typed_text'],'click_count':state['click_count']},indent=2))

    async def test_single_controller_and_simultaneous_upgrade(self):
        await self.login()
        other=ClientSession(cookie_jar=CookieJar(unsafe=True)); self.clients.append(other); await self.login(other)
        async def attempt(c):
            try:return await c.ws_connect(self.url+'/ws',headers={'Origin':self.url})
            except WSServerHandshakeError as e:return e.status
        a,b=await asyncio.gather(attempt(self.client),attempt(other))
        outcomes=[a,b]; self.assertEqual(sum(x==409 for x in outcomes),1)
        live=next(x for x in outcomes if x!=409)
        await Rfb(live).initialize(); self.assertEqual(self.g.stats['spawned'],1)
        await live.close(); await self.idle()

    async def test_novnc_negotiation_keeps_stream_and_input_working(self):
        await self.login(); r = await self.connect()
        encodings = [0, -1063131698, -316, -309, -239, -240, -232, 0x574d5664]
        await r.ws.send_bytes(struct.pack('!BBH', 2, 0, len(encodings)) + b''.join(
            struct.pack('!i', e) for e in encodings))
        self.assertEqual(await r.frame(), 800 * 500 * 4)
        await r.key(ord('A'), True); await r.key(ord('A'), False)
        state = await self.state_until(lambda d: d['typed_text'] == 'A')
        self.assertEqual(state['requested_encodings'], [0])
        self.assertIsNotNone(self.g.active)

    async def test_status_reports_backend_and_unavailable_display(self):
        await self.login()
        async with self.client.get(self.url+'/status') as r:
            data = await r.json()
            self.assertEqual(data['backend'], 'fixture')
            self.assertIsNone(data['display_error'])
        self.manifest.unlink()
        async with self.client.get(self.url+'/status') as r:
            self.assertTrue((await r.json())['display_error'])

    async def test_disconnect_releases_only_tracked_keys_and_mouse(self):
        await self.login(); r=await self.connect()
        keys=[0xffe1,0xffe3,0xffe9,0xffeb]
        for k in keys: await r.key(k,True)
        await r.pointer(1)
        await self.state_until(lambda d:len(d['held_keys'])==4 and d['button_mask']==1)
        await r.ws.close(); await self.idle()
        state=json.loads(self.state.read_text())
        self.assertEqual(state['held_keys'],[]); self.assertEqual(state['button_mask'],0)
        self.assertEqual(self.g.stats['releases_sent'],5)

    async def test_abrupt_transport_eof_releases_input(self):
        await self.login(); r=await self.connect(); await r.key(0xffe3,True); await r.pointer(1)
        await self.state_until(lambda d:d['held_keys'] and d['button_mask']==1)
        # Test deliberately drops the TCP connection without a websocket close frame.
        r.ws._response.connection.transport.abort()
        await self.idle()
        state=json.loads(self.state.read_text())
        self.assertEqual(state['held_keys'],[]); self.assertEqual(state['button_mask'],0)

    async def test_manifest_rotation_closes_old_generation_before_reconnect(self):
        await self.login(); r=await self.connect(); await r.key(0xffe3,True)
        await self.state_until(lambda d:d['held_keys'])
        self.write_manifest('g2'); await self.idle()
        old=json.loads(self.state.read_text()); self.assertEqual(old['generation'],'g1'); self.assertEqual(old['held_keys'],[])
        r2=await self.connect(); self.assertIn('g2',r2.name)
        await r2.ws.close(); await self.idle()

    async def test_wayland_missing_manifest_bad_permissions_fail_closed(self):
        await self.login()
        for mode in ('wayland','missing','permissions','symlink'):
            self.write_manifest(kind='wayland' if mode=='wayland' else 'synthetic')
            if mode=='missing':self.manifest.unlink()
            if mode=='permissions':self.manifest.chmod(0o644)
            if mode=='symlink':
                target=self.manifest.with_suffix('.target'); self.manifest.rename(target); self.manifest.symlink_to(target)
            with self.assertRaises(WSServerHandshakeError) as exc:
                await self.client.ws_connect(self.url+'/ws',headers={'Origin':self.url})
            self.assertEqual(exc.exception.status,503)
        self.assertEqual(self.g.stats['spawned'],0)

    async def test_expiry_revokes_active_stream(self):
        sid=await self.login(); r=await self.connect()
        self.g.sessions[sid]=time.monotonic()+.1
        await self.idle()
        async with self.client.get(self.url+'/status') as response:self.assertEqual(response.status,401)
        self.assertEqual(self.g.stats['child_reaped'],1)

    async def test_logout_revokes_active_stream(self):
        await self.login(); r=await self.connect()
        async with self.client.post(self.url+'/logout',headers={'Origin':self.url}) as response:self.assertEqual(response.status,200)
        await self.idle(); self.assertEqual(self.g.stats['child_reaped'],1)
        async with self.client.get(self.url+'/status') as response:self.assertEqual(response.status,401)

    async def test_stalled_handshake_expires_and_reaps(self):
        await self.login(); ws=await self.client.ws_connect(self.url+'/ws',headers={'Origin':self.url})
        await self.idle(); self.assertEqual(self.g.stats['child_reaped'],1)
        await ws.close()

    async def test_child_failure_releases_slot(self):
        await self.login(); r=await self.connect(); self.g.active['proc'].kill(); await self.idle()
        self.assertEqual(self.g.stats['child_reaped'],1)
        # This proves reaping only. A killed real X backend cannot promise key cleanup.

    async def test_invalid_rfb_message_closes_and_releases_input(self):
        await self.login(); r=await self.connect(); await r.key(0xffe3,True)
        await self.state_until(lambda d:d['held_keys'])
        await r.ws.send_bytes(b'\x06'); await self.idle()
        self.assertEqual(json.loads(self.state.read_text())['held_keys'],[])

    async def test_gateway_shutdown_reaps_child(self):
        await self.login(); r=await self.connect(); await r.pointer(1)
        await self.state_until(lambda d:d['button_mask']==1)
        await self.runner.cleanup(); await self.idle()
        self.assertEqual(self.g.stats['child_reaped'],1)
        self.assertEqual(json.loads(self.state.read_text())['button_mask'],0)

    async def test_login_rate_limit_and_cookie_rotation(self):
        old=await self.login(); new=await self.login(); self.assertNotEqual(old,new); self.assertNotIn(old,self.g.sessions)
        for _ in range(6):
            async with self.client.post(self.url+'/login',headers={'Origin':self.url},json={'username':'demo','password':'bad'}) as r:self.assertEqual(r.status,401)
        async with self.client.post(self.url+'/login',headers={'Origin':self.url},json={'username':'demo','password':'bad'}) as r:self.assertEqual(r.status,429)


if __name__=='__main__':unittest.main(verbosity=2)
