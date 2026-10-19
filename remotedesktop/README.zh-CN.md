# RemoteDesktop

[English](README.md) | 中文 · [仓库首页](../README.zh-CN.md)

在浏览器中共享当前用户已登录的 Xorg 桌面。Python/aiohttp 网关负责认证，noVNC 通过网关连接 x11vnc 的私有 socket。支持本机访问，也可以通过局域网或 WireGuard 网络中的 SSH 隧道使用。

## 环境要求

- Linux、活动的 Xorg 桌面和 systemd-logind；已在 Ubuntu 24.04 验证。
- Python 3.12 或兼容版本、`x11vnc`、`xdpyinfo`（来自 `x11-utils`）。
- 当前桌面用户的 `DISPLAY` 和 `XAUTHORITY` 环境变量。
- 现代浏览器。正常运行不需要 Node.js；修改前端后才需要重新构建。

## 安装与启动

在图形桌面的终端中，以当前桌面用户运行：

```bash
sudo apt install -y python3-venv x11vnc x11-utils
cd /path/to/longtail/remotedesktop
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./start.sh
```

终端会显示地址、账号 `demo` 和本次随机生成的访问口令。打开 `http://127.0.0.1:8765/`。口令不会保存，重启服务会重新生成；登录有效期为一小时。Ctrl+C 停止服务并使内存中的会话失效。

如果创建虚拟环境失败，请安装发行版的 `python3-venv` 包。不要把项目依赖直接装进系统 Python。

```bash
./start.sh --check             # 只检查桌面条件，不启动监听
./start.sh --backend fixture   # 合成测试画面，不是真实桌面
./start.sh --port 8766         # 使用其他本机端口
```

点击“连接桌面”开始操作。“断开”关闭连接；“仅查看”关闭当前浏览器的键鼠输入；“全屏”后可点击“退出全屏”返回。先点击画面再输入，同时只允许一个控制连接。

鼠标光标由 x11vnc 在远端合成到桌面帧中。浏览器仅在远程画布内隐藏本地指针，远端光标随整张桌面一起缩放，更新速度受到画面传输延迟影响。

## 从其他电脑访问

被控电脑需要已有 SSH 服务，并允许使用你的系统账号登录。在访问端运行：

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 desktop-user@desktop-host
```

把用户名和主机地址换成实际值，地址可以是局域网 IP 或 WireGuard IP。保持隧道运行，在访问端浏览器打开 `http://127.0.0.1:8765/`。

SSH 使用已有系统账号；网页使用 RemoteDesktop 启动终端里的随机口令。网关严格检查 Host 和 Origin，隧道本地端口必须与网关端口相同。若使用 8766，请把启动端口及隧道两端端口一起修改。浏览器地址使用 `127.0.0.1`，不要替换成 `localhost`。

网关只监听 loopback，x11vnc 不开放额外的 VNC TCP 端口。不要将 HTTP 网关直接公开到网络。Longtail 组网并不代替 SSH 和桌面网关认证。

## 会话与功能范围

启动器会检查活动 logind 会话、用户、Xorg 进程和私有 Xauthority 文件。会话退出、切换、失去活动状态或 Xorg 进程变化时，旧显示清单失效并关闭旧连接；请在目标图形桌面重新启动。

当前支持已有用户会话，不包含 Wayland、开机登录界面、PAM 网页认证、自动开机服务、公网 HTTPS/WSS、剪贴板、文件传输和远程修改分辨率。

正常断开和连接丢失会释放已跟踪的按键；网关或 Xorg 被强杀时无法保证清理。

## 开发与验证

```bash
.venv/bin/python -m unittest -v test_gateway test_local_launcher
npm ci
npm run build
npm run check
```

27 项自动化测试覆盖协议协商、认证、Host/Origin、单连接、按键释放、会话过期、子进程回收及桌面身份变化，不操作物理桌面。

`frontend.js` 已构建并随源码提供，源代码为 `client.js` 和随附的 noVNC 1.6.0。构建脚本关闭 npm CommonJS 产物中不兼容的顶层 await H.264 探测，其他压缩编码仍可使用。网关在协商阶段过滤不支持的剪贴板、扩展输入、电源控制和独立光标能力，实际不允许的消息仍会被拒绝。

`manual_input_target.py` 是可选的 Tk 测试窗口，只能指定独立的虚拟 X11 显示，拒绝当前 `DISPLAY`；它不负责创建显示服务器。

运行状态和测试产物保存在被 Git 忽略的 `runtime/` 与 `artifacts/`。虚拟环境、系统软件包、口令和本机检查报告不随仓库分发。

## 许可证

自有代码使用 [LICENSE](LICENSE)。noVNC 等第三方组件保留原许可证，见 [第三方声明](THIRD_PARTY_NOTICES.md)。
