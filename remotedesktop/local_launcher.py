#!/usr/bin/env python3
"""Start a console for this user's active Xorg session; never bind a public port."""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile

from aiohttp import web
from gateway import Gateway, ROOT


def command(*args, env=None):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True,
                              timeout=5, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f'无法执行 {args[0]}，请在本机已登录的桌面终端中启动。') from exc


def session_identity(session):
    output = command('loginctl', 'show-session', session, '-p', 'User', '-p', 'Active',
                     '-p', 'Type', '-p', 'Leader', '--no-pager')
    identity = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
    if identity.get('User') != str(os.getuid()) or identity.get('Active') != 'yes' or identity.get('Type') != 'x11':
        raise ValueError('当前用户没有活动的 Xorg 桌面。Wayland 或其他用户的桌面不支持。')
    if not identity.get('Leader', '').isdigit():
        raise ValueError('无法确认桌面会话身份。')
    return identity


def process_start(pid):
    # /proc stat's command field can contain spaces and parentheses.
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def desktop_configuration():
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        raise ValueError('当前为 Wayland，请登录 Ubuntu on Xorg 后再启动。')
    display = os.environ.get('DISPLAY', '')
    if not re.fullmatch(r':[0-9]{1,4}', display):
        raise ValueError('未找到本地 DISPLAY。请从本机图形桌面中的终端启动。')
    auth_value = os.environ.get('XAUTHORITY', '')
    if not auth_value:
        raise ValueError('缺少 XAUTHORITY，请在已登录的图形桌面终端启动。')
    auth = Path(auth_value).absolute()
    Gateway.private_file(auth)
    executable = shutil.which('x11vnc') or str(ROOT/'vendor/root/usr/bin/x11vnc')
    if not os.access(executable, os.X_OK):
        raise ValueError('缺少 x11vnc，请先按 README 安装依赖。')
    env = {**os.environ, 'XAUTHORITY': str(auth)}
    command('xdpyinfo', '-display', display, env=env)
    session = os.environ.get('XDG_SESSION_ID') or command('loginctl', 'show-user', str(os.getuid()), '-p', 'Display', '--value')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', session):
        raise ValueError('无法确定当前桌面的 logind 会话。')
    identity = session_identity(session)
    servers = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc/'cmdline').read_bytes().split(b'\0')
            if Path(os.fsdecode(args[0])).name != 'Xorg' or b'-auth' not in args:
                continue
            if Path(os.fsdecode(args[args.index(b'-auth') + 1])) != auth:
                continue
            servers.append((proc.name, process_start(proc.name)))
        except (OSError, IndexError, ValueError):
            continue
    if len(servers) != 1:
        raise ValueError('无法唯一确认当前 Xorg 进程，已停止启动。')
    pid, started = servers[0]
    manifest = {'type': 'x11', 'display': display, 'auth': str(auth),
                'generation': f'{session}:{pid}:{started}:{secrets.token_hex(8)}'}
    return manifest, (session, identity, pid, started)


async def watch_desktop(manifest_path, expected):
    session, identity, pid, started = expected
    while True:
        await asyncio.sleep(1)
        try:
            current = await asyncio.to_thread(session_identity, session)
            if current != identity or process_start(pid) != started:
                raise ValueError('桌面会话已变化')
        except (OSError, ValueError):
            manifest_path.unlink(missing_ok=True)
            print('桌面会话已退出、切换或失去活动状态；旧连接已停用。请在目标桌面中重新启动服务。', flush=True)
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('x11vnc', 'fixture'), default='x11vnc')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--check', action='store_true', help='仅检查运行条件，不启动监听')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须在 1024 到 65535 之间。')
    try:
        if args.backend == 'x11vnc':
            selection, expected = desktop_configuration()
        else:
            selection = {'type':'synthetic', 'display':':91', 'generation':secrets.token_hex(8)}
            expected = None
    except (OSError, ValueError) as exc:
        parser.exit(1, f'启动检查失败：{exc}\n')
    if args.check:
        print(f'检查通过：{args.backend} / {selection["display"]}')
        return
    password = os.environ.pop('POC_TEST_PASSWORD', '') or secrets.token_urlsafe(24)
    if len(password) < 16:
        parser.error('POC_TEST_PASSWORD 至少需要 16 个字符。')
    runtime = ROOT/'runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='console-', dir=runtime) as directory:
        manifest = Path(directory)/'display.json'
        manifest.write_text(json.dumps(selection))
        manifest.chmod(0o600)
        gateway = Gateway(port=args.port, password=password, manifest=manifest,
                          backend=args.backend, ttl=3600)
        if expected:
            async def session_guard(app):
                task = asyncio.create_task(watch_desktop(manifest, expected))
                yield
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            gateway.app.cleanup_ctx.append(session_guard)
        print(f'\n地址：http://127.0.0.1:{args.port}/\n账号：demo\n访问口令：{password}\n'
              f'桌面：{args.backend} / {selection["display"]}\n'
              '登录有效期：1 小时；重启后口令会重新生成。按 Ctrl+C 停止。\n'
              '其他电脑请使用 SSH 本地端口转发访问。\n', flush=True)
        try:
            web.run_app(gateway.app, host='127.0.0.1', port=args.port, access_log=None)
        except OSError as exc:
            parser.exit(1, f'启动失败：{exc}\n')


if __name__ == '__main__':
    main()
