import argparse
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import peerharbor


class InstallerTests(unittest.TestCase):
    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return peerharbor.main(list(args))

    def test_endpoint_normalization(self):
        self.assertEqual(peerharbor.endpoint('vpn.example.com'), 'vpn.example.com:51820')
        self.assertEqual(peerharbor.endpoint('192.0.2.1:443'), '192.0.2.1:443')
        self.assertEqual(peerharbor.endpoint('[2001:db8::1]'), '[2001:db8::1]:51820')

    def test_endpoint_rejects_config_and_shell_injection(self):
        for value in ['vpn.example.com\nPostUp=evil', '$(id)', 'host;id', '-option', 'host:0', 'host:65536', 'https://host', '[not-ipv6]', 'host:５３']:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                peerharbor.endpoint(value)

    def test_plan_and_doctor_never_execute_commands(self):
        with patch('peerharbor.subprocess.run') as run:
            self.assertEqual(self.run_main('plan', 'vpn', '--endpoint', 'vpn.example.com', '--json'), 0)
            self.assertEqual(self.run_main('plan', 'desktop', '--json'), 0)
            self.run_main('doctor', 'desktop', '--json')
            run.assert_not_called()

    def test_peer_name_cannot_be_an_option(self):
        for value in ['--help', '-h', 'phone\nPostUp=evil']:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                peerharbor.peer_name(value)

    def test_missing_endpoint_cannot_install(self):
        with patch('peerharbor.subprocess.run') as run:
            self.assertEqual(self.run_main('install', 'vpn'), 2)
            run.assert_not_called()

    def test_failed_preflight_cannot_install(self):
        with patch('peerharbor.doctor', return_value={'ready': False, 'checks': []}), patch('peerharbor.subprocess.run') as run:
            self.assertEqual(self.run_main('install', 'desktop'), 1)
            run.assert_not_called()

    def test_existing_config_requires_explicit_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'wg0.conf'
            config.touch()
            with patch('peerharbor.VPN_STATE', (config,)), patch('peerharbor.doctor', return_value={'ready': True}), patch('peerharbor.subprocess.run') as run:
                self.assertEqual(self.run_main('install', 'vpn', '--endpoint', 'vpn.example.com'), 1)
                run.assert_not_called()
                self.assertEqual(self.run_main('install', 'vpn', '--endpoint', 'vpn.example.com', '--reuse-existing'), 0)
                self.assertEqual(run.call_count, 1)

    def test_unreadable_config_is_not_treated_as_fresh_host(self):
        with patch('peerharbor.Path.stat', side_effect=PermissionError):
            self.assertTrue(peerharbor.existing_vpn_config())

    def test_failure_stops_later_install_steps(self):
        with patch('peerharbor.doctor', return_value={'ready': True}), patch('peerharbor.subprocess.run', side_effect=subprocess.CalledProcessError(100, ['apt-get', 'update'])) as run:
            self.assertEqual(self.run_main('install', 'desktop'), 1)
            self.assertEqual(run.call_count, 1)

    def test_desktop_plan_keeps_user_venv_and_check_only(self):
        args = argparse.Namespace(component='desktop')
        with patch('peerharbor.os.geteuid', return_value=1000):
            commands = peerharbor.plan(args)['commands']
        self.assertTrue(all(command[0] == 'sudo' for command in commands[:2]))
        self.assertTrue(all(command[0] != 'sudo' for command in commands[2:]))
        self.assertEqual(commands[-1][-1], '--check')

    def test_paths_with_spaces_remain_single_arguments(self):
        with patch('peerharbor.ROOT', Path('/tmp/a project')):
            commands = peerharbor.plan(argparse.Namespace(component='desktop'))['commands']
        self.assertEqual(commands[2][-1], '/tmp/a project/remotedesktop/.venv')

    def test_wayland_and_root_desktop_fail_preflight(self):
        with patch.dict('peerharbor.os.environ', {'DISPLAY': ':0', 'XDG_SESSION_TYPE': 'wayland'}), patch('peerharbor.os.geteuid', return_value=0):
            checks = {c['name']: c['ok'] for c in peerharbor.doctor('desktop')['checks']}
        self.assertFalse(checks['xorg_display'])
        self.assertFalse(checks['desktop_user'])


if __name__ == '__main__':
    unittest.main()
