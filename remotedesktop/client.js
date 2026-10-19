import RFB from './vendor/package/lib/rfb.js';

const ui = Object.fromEntries(['login-panel', 'login-form', 'username', 'password', 'login', 'connect', 'disconnect', 'logout', 'status', 'screen', 'screen-shell', 'backend', 'description', 'view-only', 'fullscreen', 'exit-fullscreen'].map(id => [id, document.getElementById(id)]));
let authenticated = false;
let active = null;
let busy = false;
let connectionState = 'disconnected';
let authRevision = 0;
let backend = null;

function status(message) { ui.status.textContent = message; }
function connectedStatus() {
  const name = backend === 'fixture' ? '模拟桌面' : '真实桌面';
  status(ui['view-only'].checked ? `已连接${name}（仅查看）。` : `已连接${name}。点击画面后可操作。`);
}
function describeBackend(value) {
  backend = value;
  const fixture = value === 'fixture';
  ui.backend.textContent = fixture ? '模拟桌面 · 功能测试' : '当前 Xorg 桌面';
  ui.description.textContent = fixture
    ? '当前画面为合成测试数据，不是本机桌面。'
    : '共享当前已登录的桌面。键盘和鼠标操作会作用于这台电脑。';
}
function controls() {
  ui['login-panel'].hidden = authenticated;
  ui.login.disabled = busy;
  ui.connect.disabled = !authenticated || busy || connectionState !== 'disconnected';
  ui.disconnect.disabled = !active;
  ui.logout.disabled = !authenticated || busy;
  ui.fullscreen.disabled = connectionState !== 'connected';
}
function clearScreen() {
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  ui['screen-shell'].hidden = true;
  ui.screen.replaceChildren();
}
function disconnect(message = '连接已断开，可以重新连接。') {
  const previous = active;
  active = null;
  connectionState = 'disconnected';
  if (previous) previous.disconnect();
  clearScreen();
  status(message);
  controls();
}
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
  if (!response.ok) {
    const messages = {401: '登录已过期或账号、口令不正确。', 409: '已有一个控制连接，请先断开该连接。', 429: '登录尝试过于频繁，请稍后再试。', 503: '桌面暂不可用，请检查服务终端。'};
    const error = new Error(messages[response.status] || `请求失败（${response.status}）。`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
async function connect() {
  if (!authenticated || busy || active) return;
  busy = true;
  controls();
  try {
    const info = await api('/status');
    describeBackend(info.backend);
    if (info.display_error) throw new Error(info.display_error);
    if (info.active) throw new Error('已有一个控制连接，或上次连接仍在关闭，请稍后重试。');
    clearScreen();
    connectionState = 'connecting';
    status('正在连接桌面…');
    const endpoint = new URL('/ws', location.href);
    endpoint.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const rfb = new RFB(ui.screen, endpoint.href, { shared: true });
    active = rfb;
    rfb.qualityLevel = 6;
    rfb.compressionLevel = 6;
    rfb.resizeSession = false;
    rfb.scaleViewport = true;
    rfb.clipViewport = false;
    // x11vnc composites the remote cursor into desktop pixels. Do not draw a
    // separate browser cursor, including noVNC's invisible-cursor fallback.
    rfb.showDotCursor = false;
    rfb.viewOnly = ui['view-only'].checked;
    rfb.focusOnClick = true;
    rfb.addEventListener('connect', () => {
      if (active !== rfb) return;
      connectionState = 'connected';
      ui['screen-shell'].hidden = false;
      connectedStatus();
      controls();
    });
    rfb.addEventListener('disconnect', event => {
      if (active !== rfb) return;
      disconnect(event.detail.clean
        ? '连接已结束。会话可能已过期或桌面发生变化，请重新连接。'
        : '桌面连接中断。请检查服务终端后重试；画面已清除。');
      void refreshAuth(true);
    });
    rfb.addEventListener('securityfailure', () => {
      if (active === rfb) disconnect('桌面连接被拒绝，请检查服务终端。');
    });
  } catch (error) {
    if (error.status === 401) authenticated = false;
    disconnect(error.message);
  } finally {
    busy = false;
    controls();
  }
}
async function refreshAuth(preserveStatus = false) {
  const revision = authRevision;
  try {
    const info = await api('/status');
    if (revision !== authRevision) return;
    authenticated = true;
    describeBackend(info.backend);
    if (!active && !preserveStatus) status(info.display_error || '已登录，点击“连接桌面”开始。');
  } catch (error) {
    if (revision !== authRevision) return;
    if (error.status === 401) {
      authenticated = false;
      disconnect('请输入账号和启动终端中的访问口令。');
    } else if (!preserveStatus) {
      status('无法访问服务，请确认启动终端仍在运行。');
    }
  }
  controls();
}
ui['login-form'].addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  authRevision += 1;
  controls();
  status('正在登录…');
  try {
    await api('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: ui.username.value, password: ui.password.value }) });
    authenticated = true;
    ui.password.value = '';
    await refreshAuth();
  } catch (error) {
    authenticated = false;
    clearScreen();
    status(error.message);
  } finally {
    busy = false;
    controls();
  }
});
ui.connect.addEventListener('click', () => void connect());
ui.disconnect.addEventListener('click', () => disconnect());
ui['view-only'].addEventListener('change', () => {
  if (active) active.viewOnly = ui['view-only'].checked;
  if (connectionState === 'connected') connectedStatus();
});
ui.fullscreen.addEventListener('click', async () => {
  try { await ui['screen-shell'].requestFullscreen(); }
  catch { status('浏览器未允许全屏，可以继续在当前窗口操作。'); }
});
ui['exit-fullscreen'].addEventListener('click', async () => {
  try { await document.exitFullscreen(); }
  catch { status('请按 Esc 退出全屏。'); }
});
ui.logout.addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  authRevision += 1;
  disconnect('正在退出…');
  try {
    await api('/logout', { method: 'POST' });
    authenticated = false;
    status('已退出，桌面画面已清除。');
  } catch (error) {
    status('暂时无法确认退出。' + error.message);
  } finally {
    busy = false;
    controls();
  }
});
window.addEventListener('pagehide', () => disconnect());
void refreshAuth();
