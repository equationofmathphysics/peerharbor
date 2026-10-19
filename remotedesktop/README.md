# RemoteDesktop

English | [中文](README.zh-CN.md) · [Repository](../README.md)

A browser console for the current user's already logged-in Xorg desktop.
Python/aiohttp authenticates the browser and bridges noVNC to a private x11vnc
socket. Use it locally or through an SSH tunnel on a LAN/WireGuard network.

## Requirements

- Linux with an active Xorg session and systemd-logind; validated on Ubuntu 24.04.
- Python 3.12 or a compatible version, `x11vnc`, and `xdpyinfo` (`x11-utils`).
- The current desktop user's `DISPLAY` and `XAUTHORITY` environment variables.
- A modern browser. Node.js is needed only to rebuild the frontend.

## Install and start

Run as the desktop user from a terminal in the graphical session:

```bash
sudo apt install -y python3-venv x11vnc x11-utils
cd /path/to/longtail/remotedesktop
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start.sh
```

The startup terminal prints the URL, username (`demo`), and a newly generated
access password. Open `http://127.0.0.1:8765/`. The password is not stored;
restarting generates a new one. Login sessions last one hour. Ctrl+C stops the
service and invalidates its in-memory sessions.

If a virtualenv cannot be created, install your distribution's `python3-venv`
package. Avoid installing these dependencies into the system Python globally.

```bash
./start.sh --check             # Validate this desktop without opening a port
./start.sh --backend fixture   # Synthetic demo; not the physical desktop
./start.sh --port 8766         # Alternative localhost port
```

Click **连接桌面** to connect. **断开** disconnects; **仅查看** disables input in
this browser; **全屏** opens fullscreen with an **退出全屏** button. Click inside
the desktop image before typing. One control connection is allowed at a time.

The pointer is composited into the desktop framebuffer by x11vnc. The browser
hides its own pointer only inside the remote canvas, so the remote pointer scales
with the desktop image. Pointer updates share the screen stream's network delay.

## Connect from another computer

An SSH server and access to the desktop host are prerequisites. On the client:

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host
```

Use the host's LAN or WireGuard address. Keep the tunnel running and browse to
`http://127.0.0.1:8765/` on the client. SSH uses your existing OS account; the web
login uses the random password printed by RemoteDesktop.

The forwarded local port must match the gateway port because Host and Origin
are checked exactly. For port 8766, change the startup port and both tunnel
ports together. Use `127.0.0.1`, not the hostname `localhost`, in the URL.

The gateway binds only to loopback; no public VNC listener is created. Do not
expose this HTTP endpoint directly to the network. PeerHarbor membership does not
replace SSH authentication or the desktop gateway password.

## Session behavior and scope

The launcher verifies the active logind session, its owner, the Xorg process,
and the private Xauthority file. When the session changes or stops being active,
the manifest is invalidated and old connections are closed. Start the service
again from the desired graphical session.

This shares an existing user session. Wayland, the boot/login greeter, PAM web
login, automatic boot services, public HTTPS/WSS deployment, clipboard, file
transfer, and remotely changing resolution are outside the current scope.
A forced gateway/Xorg crash cannot guarantee held-key cleanup; normal disconnect
and transport-loss paths release tracked input.

## Development and tests

```bash
.venv/bin/python -m unittest -v test_gateway test_local_launcher
npm ci
npm run build
npm run check
```

The 27 automated tests cover protocol negotiation, authentication, origins,
single-controller behavior, input cleanup, session expiry, process reaping,
and desktop identity changes. They do not operate your physical desktop.

The included `frontend.js` is built from `client.js` and the bundled noVNC 1.6.0
source. The build disables one incompatible CommonJS top-level-await H.264
feature probe; x11vnc's other compression formats remain available. Unsupported
clipboard, extended-input, power-control and separate-cursor capabilities are
removed during negotiation instead of weakening protocol validation.

`manual_input_target.py` is an optional Tk target for an explicitly selected,
separate virtual X11 display. It rejects the current `DISPLAY` and does not
start a display server by itself.

Local runtime state and test output go into ignored `runtime/` and `artifacts/`
directories. Virtualenvs, downloaded system packages, credentials, and machine
inspection reports are not distributed in this repository.

## License

Project-authored code is released under the [MIT License](LICENSE). Bundled noVNC and its
components retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
