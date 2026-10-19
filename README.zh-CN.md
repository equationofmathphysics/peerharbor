# PeerHarbor — WireGuard 组网与 Ubuntu 远程桌面

[English](README.md) | 中文

**把设备连起来，在浏览器里打开远端正在使用的 Ubuntu 桌面。**

PeerHarbor 包含一个**自托管 WireGuard VPN 网页管理后台**和一个独立的 **Ubuntu/Linux Xorg 浏览器远程桌面工具**。扫码添加组网设备、管理节点和可信端口，再通过 SSH 隧道与浏览器操作远端电脑上已经打开的桌面。

[快速部署与 AI 安装](#快速部署与-ai-安装) · [启动远程桌面](#启动-remotedesktop) · [与 Tailscale、NoMachine、RDP 的关系](#与-tailscalenomachinerdp-的关系)

![PeerHarbor WireGuard 管理界面：VPN 设备、节点操作与可信端口](longtail/docs/longtail-dashboard.png)

*图为更名前 Longtail 版本的 WireGuard 管理后台。实际管理地址和端口以安装输出为准。*

## 能用它做什么

- **让 AI 准备部署：**以 JSON 读取环境检查和安装计划，再通过统一入口执行安装。
- **在网页里管理私有网络：**添加设备、扫描 WireGuard 二维码、下载配置、暂停或恢复节点、管理后台访问权限。
- **连接自己的电脑：**使用标准 WireGuard 客户端和自己管理的服务器入口，为 SSH、RDP 等服务配置可信端口。
- **共享屏幕上正在使用的桌面：**通过 noVNC 与 x11vnc 查看、控制当前 Ubuntu Xorg 会话，支持仅查看和全屏。
- **按需组合：**只用组网后台、在现有局域网内单独使用 RemoteDesktop，或通过 WireGuard 地址建立 SSH 隧道访问桌面。

适合家庭实验室、个人工作站或少量 Linux 设备：自己管理网络，并远程操作已有的图形桌面。

## 快速部署与 AI 安装

在已有 Python 3.10+ 和 Git 的 Ubuntu/Debian 主机上：

```bash
git clone https://github.com/equationofmathphysics/peerharbor.git
cd peerharbor
```

**VPN 服务器：**将示例地址换成自己可达的服务器地址。

```bash
python3 peerharbor.py doctor vpn
python3 peerharbor.py plan vpn --endpoint vpn.example.com:51820
python3 peerharbor.py install vpn --endpoint vpn.example.com:51820 --peer phone
```

**Ubuntu 桌面：**在活动的 Xorg 图形会话中，以当前桌面用户运行。

```bash
python3 peerharbor.py doctor desktop
python3 peerharbor.py install desktop
./remotedesktop/start.sh
```

安装器通过 sudo 安装系统软件包，可能需要输入已有的 sudo 密码。桌面安装创建用户虚拟环境并验证会话，随后由 `start.sh` 启动共享；VPN 安装会配置 WireGuard 并启动服务。已有 VPN 安装需要先查看计划，再使用 `--reuse-existing`：已有密钥会复用，托管环境配置会更新。

**给 AI 的入口：**`doctor` 和 `plan` 支持 `--json`，不会修改系统。完整输入、退出码、验证和连接交接说明见 [AI 安装指南](docs/AI_INSTALL.md) 与 [llms.txt](llms.txt)。

```text
请在我的服务器上安装 PeerHarbor 的 VPN 管理工具，入口是 <服务器地址>:51820。
阅读 docs/AI_INSTALL.md，运行 doctor 和 plan 的 JSON 模式，然后安装并验证。
给我管理地址和连接步骤；密钥、客户端配置与二维码保留在本机。
```

## 两个工具，一条远程访问流程

| 工具 | 用途 | 文档 |
| --- | --- | --- |
| [PeerHarbor 组网管理](longtail/) | 在网页后台管理 WireGuard 网络、节点和可信端口 | [中文](longtail/README.zh-CN.md) · [English](longtail/README.md) |
| [PeerHarbor RemoteDesktop](remotedesktop/) | 在浏览器中查看和操作当前已登录的 Xorg 桌面 | [中文](remotedesktop/README.zh-CN.md) · [English](remotedesktop/README.md) |

```text
访问端电脑 ── WireGuard 网络（已有局域网时可省略）── Ubuntu 主机
访问端浏览器 ── 本地 SSH 隧道 ── RemoteDesktop 网关 ── 已有 Xorg 桌面
```

两者独立运行，各自处理认证与 Web 服务。RemoteDesktop 只监听本机，从其他电脑访问时需要 SSH 隧道；加入 VPN 并不代替 SSH 登录和桌面网关认证。

## 与 Tailscale、NoMachine、RDP 的关系

如果你在寻找 Tailscale 替代方案、NoMachine 替代方案、Ubuntu 远程桌面或 RDP 内网访问工具，可以按实际需求判断：

| 你的需求 | PeerHarbor 提供什么 | 当前边界 |
| --- | --- | --- |
| 自托管组网，替代自己的 Tailscale 使用流程 | 自己部署 WireGuard 服务器，在网页里管理标准 WireGuard 节点。 | 使用自己的 WireGuard 配置，不实现 Tailscale 控制平面、客户端注册或自动 Mesh/中继系统；需要可达的服务器入口。 |
| 考虑 NoMachine，希望访问已有的 Ubuntu 桌面 | 通过 SSH 隧道，在浏览器里用 noVNC/x11vnc 操作当前 Xorg 会话。 | 不实现 NoMachine/NX 协议，不承诺性能或功能对等。 |
| 通过私有网络连接已有的 RDP 服务 | 使用 WireGuard 网络承载连接，配置所需可信端口。 | RDP 客户端和服务端需要另行准备；自带浏览器桌面使用 VNC/RFB，不是 RDP。 |
| 在浏览器中共享 Linux 桌面 | 使用随附的 RemoteDesktop，已在 Ubuntu 24.04 Xorg 环境验证。 | 需要已经登录且活动的图形会话；当前不支持 Wayland 和开机登录界面。 |

RemoteDesktop 同时只允许一个控制连接，当前不包含剪贴板、文件传输、远程修改分辨率、无人值守开机登录和直接公网 HTTPS/WSS 部署。完整条件见 [环境要求与功能范围](remotedesktop/README.zh-CN.md#环境要求)。

## 为什么做 PeerHarbor

这是一个为自用搭建的局域网管理与远程桌面项目。起因很简单：我希望避开 NoMachine 付费方案带来的成本，同时觉得 Tailscale 在自己的使用场景下不够顺手，所以做了一套可以自己部署、自己管理的工具。现在将它公开，方便有相似需求的人使用和改进。

## 安装 PeerHarbor

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/equationofmathphysics/peerharbor.git /opt/longtail
cd /opt/longtail/longtail
sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN:51820 phone
```

安装器会配置 WireGuard 并管理 `longtail-web` 服务。服务器部署前请阅读 [PeerHarbor 文档](longtail/README.zh-CN.md)。

## 启动 RemoteDesktop

在 Ubuntu 已登录的 Xorg 图形桌面中，以当前桌面用户执行：

```bash
sudo apt install -y python3-venv x11vnc x11-utils
cd /path/to/longtail/remotedesktop
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start.sh
```

打开 `http://127.0.0.1:8765/`。账号为 `demo`，每次启动的随机访问口令显示在终端。前端已经构建，正常运行不需要 Node.js。

从局域网或 WireGuard 网络中的另一台电脑访问：

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host
```

将用户名和地址换成被控电脑的实际值。保持隧道运行，在访问端浏览器打开 `http://127.0.0.1:8765/`。完整说明见 [RemoteDesktop 文档](remotedesktop/README.zh-CN.md)。

## 已安装 Longtail / PeerHarbor 的升级

PeerHarbor 原名 Longtail。为兼容现有安装，`longtail/` 目录、`longtail-web` 服务，以及 `/etc/longtail`、`/var/lib/longtail` 数据路径保留原名。

原应用从仓库根目录移到了 `longtail/` 子目录。`/etc/longtail`、`/etc/wireguard` 和 `/var/lib/longtail` 的数据位置不变。旧安装在拉取后，需要更新虚拟环境和 systemd 服务路径：

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

上述命令假设仓库位于 `/opt/longtail`。若安装在其他目录，请先调整服务文件中的 `WorkingDirectory` 和 `ExecStart`。不要移动或覆盖已有的 WireGuard 配置与密钥。

## 许可证

本项目自有代码使用 [MIT 许可证](LICENSE)。第三方组件保留各自许可证，详见 [RemoteDesktop 第三方声明](remotedesktop/THIRD_PARTY_NOTICES.md)。
