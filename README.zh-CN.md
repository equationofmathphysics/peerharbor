# Longtail

[English](README.md) | 中文

这是一个为自用搭建的局域网管理与远程桌面项目。起因很简单：我希望避开 NoMachine 付费方案带来的成本，同时觉得 Tailscale 在自己的使用场景下不够顺手，所以做了一套可以自己部署、自己管理的替代工具。现在将它公开，方便有相似需求的人使用和改进。

仓库包含两个工具，分别负责私有网络管理和桌面远程操作：

| 目录 | 用途 | 文档 |
| --- | --- | --- |
| [`longtail/`](longtail/) | 原有的 WireGuard 局域网与设备管理后台 | [中文](longtail/README.zh-CN.md) · [English](longtail/README.md) |
| [`remotedesktop/`](remotedesktop/) | 在浏览器中查看和操作当前已登录的 Xorg 桌面 | [中文](remotedesktop/README.zh-CN.md) · [English](remotedesktop/README.md) |

Longtail 负责组网，RemoteDesktop 负责桌面共享。两者独立运行，暂不共享登录或 Web 服务。RemoteDesktop 当前只监听本机，通过 SSH 隧道访问；隧道可使用局域网地址或 WireGuard 地址。

## 目录结构

```text
longtail/
├── longtail/       # 原 WireGuard 管理后台
├── remotedesktop/  # 新 Xorg 远程桌面工具
├── README.md
└── LICENSE
```

## 安装 Longtail

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/equationofmathphysics/longtail.git /opt/longtail
cd /opt/longtail/longtail
sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN:51820 phone
```

安装器会配置 WireGuard 并管理 `longtail-web` 服务。服务器部署前请阅读 [Longtail 文档](longtail/README.zh-CN.md)。

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

## 已安装 Longtail 的升级

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

本项目自有代码沿用仓库现有的 [WH Covenant Public License](LICENSE)。第三方组件保留各自许可证，详见 [RemoteDesktop 第三方声明](remotedesktop/THIRD_PARTY_NOTICES.md)。
