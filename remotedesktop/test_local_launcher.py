import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_launcher as launcher


class LauncherTests(unittest.TestCase):
    def test_rejects_other_users_inactive_sessions_and_wayland(self):
        for user, active, kind in [('99999','yes','x11'), (str(os.getuid()),'no','x11'),
                                   (str(os.getuid()),'yes','wayland')]:
            with self.subTest(user=user, active=active, kind=kind):
                data = f'User={user}\nActive={active}\nType={kind}\nLeader=123'
                with patch.object(launcher, 'command', return_value=data):
                    with self.assertRaises(ValueError): launcher.session_identity('2')

    def test_wayland_environment_rejected_before_display_access(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE':'wayland'}):
            with self.assertRaisesRegex(ValueError, 'Wayland'):
                launcher.desktop_configuration()

    def test_current_process_start_identity_is_stable(self):
        first = launcher.process_start(os.getpid())
        self.assertTrue(first.isdigit())
        self.assertEqual(first, launcher.process_start(os.getpid()))


class SessionWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_switch_invalidates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory)/'display.json'
            manifest.write_text('{}')
            expected = ('2', {'Leader':'123'}, '456', '789')
            with patch.object(launcher, 'session_identity', return_value={'Leader':'124'}):
                await asyncio.wait_for(launcher.watch_desktop(manifest, expected), 3)
            self.assertFalse(manifest.exists())

    async def test_xorg_restart_invalidates_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory)/'display.json'
            manifest.write_text('{}')
            expected = ('2', {'Leader':'123'}, '456', '789')
            with patch.object(launcher, 'session_identity', return_value={'Leader':'123'}), \
                 patch.object(launcher, 'process_start', return_value='790'):
                await asyncio.wait_for(launcher.watch_desktop(manifest, expected), 3)
            self.assertFalse(manifest.exists())
