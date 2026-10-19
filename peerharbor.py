#!/usr/bin/env python3
"""Inspect, plan and install PeerHarbor using only the Python standard library."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
VPN_STATE = (Path('/etc/longtail/longtail.env'), Path('/etc/wireguard/wg0.conf'))


def existing_vpn_config():
    for path in VPN_STATE:
        try:
            path.stat()
            return True
        except FileNotFoundError:
            continue
        except OSError:
            # An unreadable configuration directory is not proof of a fresh host.
            return True
    return False


def endpoint(value):
    """Accept only a host/IP and optional port, never config or shell syntax."""
    if value.startswith('['):
        # Scope IDs accepted by ipaddress can contain arbitrary text. A public
        # server endpoint must be a literal address, never an interface scope.
        match = re.fullmatch(r'\[([0-9A-Fa-f:.]+)\](?::([0-9]+))?', value)
        if not match:
            raise argparse.ArgumentTypeError('Use [IPv6]:port for an IPv6 endpoint.')
        host, port = match.group(1), match.group(2) or '51820'
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise argparse.ArgumentTypeError('Invalid IPv6 endpoint.') from exc
        host = f'[{host}]'
    else:
        parts = value.split(':')
        if len(parts) > 2:
            raise argparse.ArgumentTypeError('Use host:port or [IPv6]:port.')
        host, port = parts[0], parts[1] if len(parts) == 2 else '51820'
        labels = host.rstrip('.').split('.')
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels):
            raise argparse.ArgumentTypeError('Use an IP address or DNS name without a URL scheme.')
        if re.fullmatch(r'[0-9.]+', host):
            try:
                ipaddress.IPv4Address(host)
            except ValueError as exc:
                raise argparse.ArgumentTypeError('Invalid IPv4 endpoint.') from exc
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError('Endpoint port must be between 1 and 65535.')
    return f'{host}:{int(port)}'


def peer_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_.][A-Za-z0-9_.-]{0,31}', value):
        raise argparse.ArgumentTypeError('Peer name must be 1–32 letters, numbers, dots, underscores or hyphens and cannot start with a hyphen.')
    return value


def doctor(component):
    checks = []

    def check(name, ok, remedy):
        checks.append({'name': name, 'ok': bool(ok), 'remedy': '' if ok else remedy})

    check('linux', sys.platform.startswith('linux'), 'Run on Ubuntu or Debian Linux.')
    check('apt', shutil.which('apt-get'), 'Use an Ubuntu/Debian host with apt-get.')
    check('system_python', Path('/usr/bin/python3').is_file(), 'Install the system python3 package.')
    check('bash', shutil.which('bash'), 'Install bash.')
    check('sudo', os.geteuid() == 0 or shutil.which('sudo'), 'Install sudo or run the VPN installer as root.')
    check('systemd', Path('/run/systemd/system').is_dir() and shutil.which('systemctl'), 'Use a host running systemd.')
    if component == 'desktop':
        check('desktop_user', os.geteuid() != 0, 'Run as the logged-in desktop user, without sudo.')
        check('checkout_writable', os.access(ROOT / 'remotedesktop', os.W_OK), 'Use a checkout owned by the desktop user.')
        check('xorg_display', re.fullmatch(r':[0-9]{1,4}', os.environ.get('DISPLAY', '')) and os.environ.get('XDG_SESSION_TYPE') != 'wayland', 'Run from a terminal in an active Ubuntu on Xorg session.')
        check('xauthority', os.environ.get('XAUTHORITY') and Path(os.environ['XAUTHORITY']).is_file(), 'Run from the desktop terminal with its existing XAUTHORITY environment.')
    return {'schema_version': 1, 'component': component, 'ready': all(c['ok'] for c in checks), 'checks': checks}


def plan(args):
    privilege = [] if os.geteuid() == 0 else ['sudo']
    if args.component == 'vpn':
        if not args.endpoint:
            raise ValueError('--endpoint is required for a VPN plan or installation.')
        commands = [privilege + ['bash', str(ROOT / 'longtail/deploy/bootstrap.sh'), args.endpoint, args.peer]]
        effects = [
            'Install apt and Python dependencies and create the VPN virtualenv.',
            'Write /etc/longtail/longtail.env; create or reuse /etc/wireguard/wg0.conf.',
            'Enable IPv4 forwarding; start WireGuard and the longtail-web service.',
            'Create or reuse the initial administrator peer and print its private configuration QR code.',
            'Keep legacy longtail service and data paths for existing installations.',
        ]
        next_steps = [
            f'Allow UDP/{args.endpoint.rsplit(":", 1)[1]} in the server/cloud firewall.',
            'Import the printed configuration using a standard WireGuard client.',
            'Open the admin URL printed by bootstrap after connecting to the VPN.',
            'Verify: systemctl is-active wg-quick@wg0 longtail-web',
        ]
    else:
        python = str(ROOT / 'remotedesktop/.venv/bin/python')
        commands = [
            privilege + ['apt-get', 'update'],
            privilege + ['apt-get', 'install', '-y', 'python3-venv', 'x11vnc', 'x11-utils'],
            ['/usr/bin/python3', '-m', 'venv', str(ROOT / 'remotedesktop/.venv')],
            [python, '-m', 'pip', 'install', '-r', str(ROOT / 'remotedesktop/requirements.txt')],
            ['bash', str(ROOT / 'remotedesktop/start.sh'), '--check'],
        ]
        effects = [
            'Install apt dependencies and create a desktop-user Python virtualenv.',
            'Validate the active Xorg session using the existing desktop launcher.',
            'Do not start desktop sharing, open a public port or create a boot service.',
        ]
        next_steps = [
            f'Run: bash {shlex.quote(str(ROOT / "remotedesktop/start.sh"))}',
            'Open http://127.0.0.1:8765/ and use the password printed by the launcher.',
            'From another computer: ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host',
        ]
    return {'schema_version': 1, 'project': 'PeerHarbor', 'component': args.component,
            'commands': commands, 'effects': effects, 'next_steps': next_steps,
            'existing_vpn_config': args.component == 'vpn' and existing_vpn_config()}


def emit(value, as_json):
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if 'error' in value:
        print(f'Error: {value["error"]}')
    if 'checks' in value:
        for check in value['checks']:
            print(f'{"OK" if check["ok"] else "FAIL"} {check["name"]}' + (f': {check["remedy"]}' if check['remedy'] else ''))
    for effect in value.get('effects', []):
        print(f'- {effect}')
    for command in value.get('commands', []):
        print('$ ' + shlex.join(command))
    if value.get('existing_vpn_config'):
        print('Existing VPN configuration detected. Install requires --reuse-existing; the managed environment will be updated.')
    for step in value.get('next_steps', []):
        print(step)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['doctor', 'plan', 'install'])
    parser.add_argument('component', choices=['vpn', 'desktop'])
    parser.add_argument('--endpoint', type=endpoint, help='Public VPN host[:port], default port 51820')
    parser.add_argument('--peer', type=peer_name, default='phone', help='Initial administrator peer name')
    parser.add_argument('--reuse-existing', action='store_true', help='Allow bootstrap to update an existing VPN installation')
    parser.add_argument('--json', action='store_true', help='Machine-readable doctor/plan output; install streams native logs')
    args = parser.parse_args(argv)
    if args.json and args.action == 'install':
        parser.error('--json is available for doctor and plan; installation streams native logs.')
    if args.component == 'desktop' and (args.endpoint or args.reuse_existing or args.peer != 'phone'):
        parser.error('--endpoint, --peer and --reuse-existing apply only to VPN.')
    if args.action == 'doctor':
        result = doctor(args.component)
        emit(result, args.json)
        return 0 if result['ready'] else 1
    try:
        result = plan(args)
    except ValueError as exc:
        emit({'error': str(exc)}, args.json)
        return 2
    emit(result, args.json)
    if args.action == 'plan':
        return 0
    readiness = doctor(args.component)
    if not readiness['ready']:
        emit(readiness, False)
        return 1
    if result['existing_vpn_config'] and not args.reuse_existing:
        print('No changes made. Review the existing setup before using --reuse-existing.', file=sys.stderr)
        return 1
    try:
        for command in result['commands']:
            subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        print(f'Installation stopped (exit {exc.returncode}). Earlier steps may have completed; inspect the output before retrying.', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'Cannot execute installation command: {exc}', file=sys.stderr)
        return 1
    print('Installation steps completed. Follow the next steps above to connect.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
