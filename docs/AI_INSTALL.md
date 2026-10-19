# PeerHarbor installation for AI agents

PeerHarbor provides a self-hosted WireGuard VPN manager and an independent Ubuntu
Xorg browser desktop. The standard-library entry point is `peerharbor.py` at the
repository root. Run commands on the intended host, from a persistent checkout.

## Required inputs

Choose `vpn` or `desktop`. These components can run on different computers.

- **VPN:** Ubuntu/Debian with systemd, Python 3.10+, root or sudo access, a reachable
  public server IP/DNS name and UDP port (default 51820). Ask for the actual server
  endpoint when missing. The initial administrator peer name defaults to `phone`.
- **Desktop:** Ubuntu/Linux with an active, already logged-in Xorg session,
  systemd, Python 3.10+, apt and sudo. Use a checkout owned by the desktop user and
  run from that user's graphical terminal with its `DISPLAY` and `XAUTHORITY`.
  A headless SSH session alone is insufficient. Do not invent these values or
  switch another user's desktop session. Wayland is not supported.

Git and Python must already be available. The installer uses existing sudo
access and may prompt for a password. It does not configure passwordless sudo,
provision a cloud server, open cloud firewall rules or provide remote SSH access.

## Inspect, plan, install

After cloning `https://github.com/equationofmathphysics/peerharbor.git` and entering
the checkout, select the component and inspect the target:

```bash
python3 peerharbor.py doctor vpn --json
python3 peerharbor.py plan vpn --endpoint vpn.example.com:51820 --peer phone --json
python3 peerharbor.py install vpn --endpoint vpn.example.com:51820 --peer phone
```

Substitute the real endpoint. For a desktop:

```bash
python3 peerharbor.py doctor desktop --json
python3 peerharbor.py plan desktop --json
python3 peerharbor.py install desktop
./remotedesktop/start.sh
```

`doctor` and `plan` do not install packages, modify configuration, start services
or invoke installation commands. `doctor` checks prerequisites, while `plan`
describes commands, effects and next steps even on a host not ready to install.
JSON objects include `schema_version: 1`; a successful plan is not proof that
installation can succeed. `install` repeats preflight checks before execution.

Proceed with installation when the user requested it on this host. Use the plan
to explain changes when needed. A request only to inspect or generate commands
does not request installation. The install command streams native output rather
than JSON, stops at the first failed command, and does not roll back completed
steps. Read failure output before retrying.

If `/etc/longtail/longtail.env` or `/etc/wireguard/wg0.conf` exists, VPN installation
stops before making changes unless `--reuse-existing` is supplied. Inspect the
existing setup first: this option reuses the WireGuard key but reruns bootstrap,
updates managed environment settings and may change the initial peer's admin
access. It is not a general configuration migration tool.

Exit codes: `0` means the requested check/plan/steps succeeded; `1` means failed
preflight, an existing-config guard or an installation failure; `2` means invalid
arguments. Network reachability, sudo authorization, package availability and
end-to-end connectivity must still be verified. Desktop installation additionally
runs the existing launcher's `--check`, which validates the actual Xorg session.

## Verify and hand over

For VPN, check `systemctl is-active wg-quick@wg0 longtail-web`, allow the selected
UDP port at the server/cloud firewall, connect a standard WireGuard client and
open the admin URL printed by bootstrap. A service reporting active does not
prove a client can reach it. Report separately which checks were completed.

For desktop, installation validates the session without starting sharing. Run
`./remotedesktop/start.sh` in the desktop terminal when sharing is requested.
Keep that process running; Ctrl+C stops it. The browser username is `demo` and
the random access password appears in that terminal. For another computer:

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host
```

Use the real host's LAN/WireGuard address and open `http://127.0.0.1:8765/` on the
client. Report the URL, tunnel command, service status and any remaining check.
Keep generated client configs, private keys, QR codes and access passwords local;
do not put them into commits, issues or public logs. Desktop access remains
loopback-only, with SSH and web authentication required independently of VPN.

## 中文速查

先确定部署对象是 VPN 服务器还是已有 Xorg 桌面，并取得真实的服务器入口。
在目标主机运行 `doctor --json` 检查环境、`plan --json` 查看计划；用户已要求
安装时，再执行 `install`。这些选项的完整顺序见上面的命令。

VPN 安装需要 sudo/root，会安装依赖、更新托管配置、启用 IPv4 转发和启动服务。
桌面安装以当前桌面用户运行，只对系统软件包使用 sudo；检查通过后用 `start.sh`
启动共享。当前不支持无人值守登录、Wayland 或通过 SSH 猜测图形会话身份。
已有 VPN 配置必须先检查，再决定是否用 `--reuse-existing` 重新执行引导流程。

完成后交付实际管理地址、连接方法和验证结果。安装步骤成功不等于网络已连通；
没有完成的端到端检查要明确说明。密钥、二维码和口令不要写入公开内容。
