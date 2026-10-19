# Longtail

English | [中文](README.zh-CN.md)

I built this project for my own LAN management and remote desktop needs. I wanted
to avoid the cost of NoMachine's paid offerings, and Tailscale did not feel
convenient for my workflow. That led to a self-hosted alternative I could deploy
and manage myself, shared here for others with similar needs to use and improve.

The repository contains two tools for connecting and operating computers on a
private network:

| Directory | Purpose | Documentation |
| --- | --- | --- |
| [`longtail/`](longtail/) | WireGuard network and peer management through a web admin panel | [English](longtail/README.md) · [中文](longtail/README.zh-CN.md) |
| [`remotedesktop/`](remotedesktop/) | Browser-based viewing and control of an already logged-in Xorg desktop | [English](remotedesktop/README.md) · [中文](remotedesktop/README.zh-CN.md) |

Longtail establishes and manages the WireGuard network. RemoteDesktop shares the
current user's desktop. The two applications run independently; they do not
share authentication or a web process. RemoteDesktop currently listens on
localhost and is accessed through an SSH tunnel, including over a WireGuard IP.

## Repository layout

```text
longtail/
├── longtail/       # Original WireGuard administration application
├── remotedesktop/  # Xorg desktop sharing application
├── README.md
└── LICENSE
```

## Install Longtail

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/equationofmathphysics/longtail.git /opt/longtail
cd /opt/longtail/longtail
sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN:51820 phone
```

The installer manages WireGuard and the `longtail-web` service. Read the
[Longtail documentation](longtail/README.md) before deploying to a server.

## Run RemoteDesktop

Run this as the desktop user, inside an active Ubuntu Xorg graphical session:

```bash
sudo apt install -y python3-venv x11vnc x11-utils
cd /path/to/longtail/remotedesktop
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start.sh
```

Open `http://127.0.0.1:8765/`. The username is `demo`; a random access password is
printed in the terminal each time the service starts. The included frontend is
already built, so Node.js is only needed when changing frontend code.

For another computer on the LAN or WireGuard network:

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host
```

Keep the tunnel running and open `http://127.0.0.1:8765/` on that computer.
See [RemoteDesktop usage and limitations](remotedesktop/README.md).

## Existing Longtail installations

The original application moved from the repository root into `longtail/`.
Existing `/etc/longtail`, `/etc/wireguard`, and `/var/lib/longtail` data paths
have not changed. An installation using the old root-level virtualenv/service
paths needs a one-time service-path update after pulling this change:

```bash
cd /opt/longtail
sudo git pull --ff-only
cd longtail
sudo /usr/bin/python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.txt
sudo install -m 644 deploy/longtail-web.service /etc/systemd/system/longtail-web.service
sudo systemctl daemon-reload
sudo systemctl restart longtail-web
```

These paths assume the checkout is `/opt/longtail`. For a different checkout,
adjust `WorkingDirectory` and `ExecStart` in the service before installing it.
Do not move or overwrite existing WireGuard configurations or keys.

## License

Project-authored code retains the repository's existing
[WH Covenant Public License](LICENSE). Third-party components retain their own
licenses; see [RemoteDesktop third-party notices](remotedesktop/THIRD_PARTY_NOTICES.md).
