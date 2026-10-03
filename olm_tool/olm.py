#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import os, sys, re, json, time, uuid, base64, asyncio, threading, socket
import subprocess, io, zipfile, hashlib, platform, urllib.parse
import urllib.request, urllib.error, traceback
from pathlib import Path
from typing import Optional, Any, List, Dict, Tuple, Callable
from datetime import datetime, timezone, timedelta

# ─── PATHS ───────────────────────────────────────────────────────────
def _resolve_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def _resolve_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

APP_DIR = _resolve_app_dir()
RES_DIR = _resolve_resource_dir()
DATA_DIR = Path(os.path.expanduser("~")) / ".olm_tool_pro"
BROWSERS_DIR = DATA_DIR / "browsers"
DATA_DIR.mkdir(parents=True, exist_ok=True)
BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)

import webview
from curl_cffi.requests import AsyncSession as CurlAsyncSession

try:
    from playwright.async_api import async_playwright
    HAS_PW = True
except ImportError:
    HAS_PW = False

# ═══════════════════════════════════════════════════════════════
# TYPED EXCEPTIONS
# ═══════════════════════════════════════════════════════════════
class OLMError(Exception): pass
class CloudflareBlock(OLMError): pass
class ChromiumMissing(OLMError): pass
class LicenseError(OLMError): pass
class V1Required(OLMError): pass

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ywxwjzsoynbrinasvjsk.supabase.co")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl3eHdqenNveW5icmluYXN2anNrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTA3NDc3ODMsImV4cCI6MjEwNjMyMzc4M30."
    "7omBqPWx6QceG1LnAkqnJDsze3OYWczg4iWLQjjjrwc")

OLM_BASE = "https://olm.vn"
XOR_KEY = b"1047823200"
V1_QUERY = "v=v1"
V1_SUFFIX = f"?{V1_QUERY}"

def _url_v1(path: str) -> str:
    if not path or "/chu-de/" not in path: return path
    if re.search(r"[?&]v=v1(\b|$)", path): return path
    if re.search(r"[?&]v=v2(\b|$)", path):
        return re.sub(r"([?&])v=v2(\b|$)", r"\1v=v1\2", path)
    if "?" not in path: return path + V1_SUFFIX
    return path + "&" + V1_QUERY

SESSION_F = DATA_DIR / "session.json"
LICENSE_F = DATA_DIR / "license.json"
CRASH_F = DATA_DIR / "crash.log"
Q_CACHE_F = DATA_DIR / "questions_cache.json"
DOWNLOAD_DIR = Path.home() / "Downloads"
CHROME_PROFILE = Path(os.path.expanduser("~")) / ".olm_tool_chrome_profile"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

ICON_PNG = RES_DIR / "assets" / "icon.png"
ICON_ICO = RES_DIR / "app_icon.ico"
if not ICON_ICO.exists(): ICON_ICO = APP_DIR / "app_icon.ico"
if not ICON_PNG.exists(): ICON_PNG = APP_DIR / "assets" / "icon.png"

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
IMPERSONATE = "chrome124"

QTYPE_LABEL = {
    1: "Trắc nghiệm", 2: "Điền khuyết", 3: "Điền khuyết", 5: "Sắp xếp",
    6: "Nối", 9: "Gạch chân", 10: "Nhóm", 11: "Chọn từ",
    13: "Đúng/Sai", 20: "Liệt kê", 21: "Tổng hợp", 22: "Tổng hợp",
}
EXAM_TYPE_LABEL = {1: "Video", 2: "Luyện tập", 3: "Kiểm tra", 4: "Kiểm tra PDF"}

# ═══════════════════════════════════════════════════════════════
# ANTI-DETECT JS — 11 LAYERS (port 100% userscript)
# ═══════════════════════════════════════════════════════════════
ANTI_DETECT_JS = r"""
(function() {
'use strict';
if (window.__olm_patched_v19) return;
window.__olm_patched_v19 = true;

try { Object.defineProperty(navigator, 'webdriver', { get: () => false }); } catch(e) {}

// L2: JSON.parse hook — force shuffle=false, order=[0..n]
// PORT: bổ sung 'link-list' và 'group-list' vào điều kiện
const origParse = JSON.parse;
JSON.parse = function(text, reviver) {
  let data;
  try { data = origParse.call(this, text, reviver); }
  catch(e) { return origParse.call(this, text, reviver); }
  const forceOrder = (node) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node.children) && node.children.length > 0) {
      if ('shuffle' in node) node.shuffle = false;
      if ('random' in node) node.random = false;
      if (node.order || node.type === 'olm-list'
          || node.name === 'quiz-list' || node.name === 'true-false'
          || node.name === 'link-list' || node.name === 'group-list') {
        node.order = node.children.map((_, i) => i);
      }
    }
    if (Array.isArray(node.children)) node.children.forEach(forceOrder);
    if (node && typeof node === 'object' && !Array.isArray(node)) {
      try {
        Object.values(node).forEach(v => {
          if (v && typeof v === 'object' && !Array.isArray(v)) forceOrder(v);
        });
      } catch(e) {}
    }
  };
  if (data && (data.root || Array.isArray(data) || typeof data === 'object')) forceOrder(data);
  return data;
};

// L3: Storage hook — block tracking keys
const origSet = Storage.prototype.setItem;
Storage.prototype.setItem = function(k, v) {
  if (k === 'prcc' || (typeof k === 'string'
      && (k.indexOf('tmp_count_q_categories') === 0
          || k.indexOf('olm_intro_shown') === 0))) return;
  return origSet.apply(this, arguments);
};

// L4: _shuffle = identity
try { window._shuffle = function(a) { return a; }; } catch(e) {}

// L5: detectQuestion hook — capture quiz instances + force shuffle=0
window.__OLM_CAPTURED_QUESTIONS = window.__OLM_CAPTURED_QUESTIONS || [];
let _detectQuestion = window.detectQuestion;
try {
  Object.defineProperty(window, 'detectQuestion', {
    configurable: true,
    get: () => _detectQuestion,
    set: (originalFunc) => {
      if (typeof originalFunc !== 'function') { _detectQuestion = originalFunc; return; }
      _detectQuestion = function(...args) {
        let quizInstance;
        try { quizInstance = originalFunc.apply(this, args); }
        catch(e) { throw e; }
        try {
          if (quizInstance && typeof quizInstance === 'object') {
            if (quizInstance.p) {
              if (quizInstance.p.config) quizInstance.p.config.mix = false;
              quizInstance.p.shuffle = 0;
              quizInstance.p.random = 0;
            }
            window.__OLM_CAPTURED_QUESTIONS.push(quizInstance);
            const origGetMany = quizInstance.getMany;
            if (typeof origGetMany === 'function') {
              quizInstance.getMany = function() {
                if (this.p) this.p.shuffle = 0;
                const subs = origGetMany.apply(this, arguments);
                if (Array.isArray(subs)) {
                  subs.forEach(s => {
                    if (s && s.p) s.p.shuffle = 0;
                    window.__OLM_CAPTURED_QUESTIONS.push(s);
                  });
                }
                return subs;
              };
            }
          }
        } catch(e) {}
        return quizInstance;
      };
    }
  });
} catch(e) {}

// L6: EXAM_UI patch — config.not_shuffle=1 + shuffle=0 + mix=false
let _examUI = window['EXAM_UI'];
try {
  Object.defineProperty(window, 'EXAM_UI', {
    configurable: true, enumerable: true,
    get: () => _examUI,
    set: (ui) => {
      if (ui && typeof ui.init === 'function' && !ui.__shuffleDisabled) {
        const originalInit = ui.init;
        ui.init = function(config) {
          if (config) { config.not_shuffle = 1; config.shuffle = 0; config.mix = false; }
          return originalInit.call(this, config);
        };
        ui.__shuffleDisabled = true;
      }
      _examUI = ui;
    }
  });
} catch(e) {}

// L7: CATE_UI fake VIP + auth patch (with _fakeVipApplied flag)
const FAKE_VIP = { isVip: true, vipPersonal: true, isGuest: false,
  vip_day: 99999, type_vip: 1, limit: 99999, cate_is_olm: false };
const patchCateUI = () => {
  try {
    if (typeof window['CATE_UI'] === 'undefined') return;
    const c = window['CATE_UI'];
    if (typeof c.getData !== 'function') return;
    const state = c.getData();
    if (!state || state['_fakeVipApplied']) return;
    Object.assign(state, FAKE_VIP);
    state['_fakeVipApplied'] = true;
    if (typeof c.initVipLimit === 'function') c.initVipLimit = function() {};
    if (typeof c.showFooterToolbarPractice === 'function')
      try { c.showFooterToolbarPractice(); } catch(e) {}
  } catch(e) {}
};
const patchInterval = setInterval(patchCateUI, 100);
try {
  window.addEventListener('load', () => {
    patchCateUI();
    setTimeout(() => clearInterval(patchInterval), 5000);
  });
} catch(e) {}

const patchAuth = (obj) => {
  if (!obj || typeof obj !== 'object') return;
  try {
    obj['isVip'] = true; obj['vipPersonal'] = true; obj['isGuest'] = false;
    obj['vip_day'] = 99999; obj['limit'] = 99999; obj['type_vip'] = 1;
    Object.defineProperties(obj, {
      'isVip':       { value: true,  writable: false },
      'vipPersonal': { value: true,  writable: false },
      'isGuest':     { value: false, writable: false }
    });
  } catch(e) {}
};
if (window.auth) patchAuth(window.auth);
else {
  let _auth = undefined;
  try {
    Object.defineProperty(window, 'auth', {
      configurable: true, get: () => _auth,
      set: (val) => { patchAuth(val); _auth = val; }
    });
  } catch(e) {
    const ap = setInterval(() => {
      if (window.auth) { patchAuth(window.auth); clearInterval(ap); }
    }, 100);
    setTimeout(() => clearInterval(ap), 10000);
  }
}

// L8: Block dangerous events — cả Document lẫn window
const BLOCKED = ['visibilitychange', 'blur', 'contextmenu', 'selectstart', 'copy', 'cut', 'paste'];
try {
  const oD = Document.prototype.addEventListener;
  Document.prototype.addEventListener = function(t, l, o) {
    if (BLOCKED.includes(t)) return;
    return oD.call(this, t, l, o);
  };
} catch(e) {}
try {
  const oW = window.addEventListener.bind(window);
  window.addEventListener = function(t, l, o) {
    if (BLOCKED.includes(t)) return;
    return oW(t, l, o);
  };
} catch(e) {}
try {
  const oET = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(t, l, o) {
    if (this === window && BLOCKED.includes(t)) return;
    return oET.call(this, t, l, o);
  };
} catch(e) {}
try {
  const nullFunc = () => {};
  Object.defineProperties(document, {
    'oncontextmenu': { set: nullFunc, get: () => null },
    'onselectstart': { set: nullFunc, get: () => null },
    'oncopy':        { set: nullFunc, get: () => null },
    'oncut':         { set: nullFunc, get: () => null },
    'onpaste':       { set: nullFunc, get: () => null }
  });
} catch(e) {}
try {
  Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
  Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
} catch(e) {}

// L9: Block hotkeys — F12, Ctrl+U, Ctrl+Shift+I, Ctrl+S
try {
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F12'
        || (e.ctrlKey && (e.key === 'u' || e.key === 'U'))
        || (e.ctrlKey && e.shiftKey && (e.key === 'i' || e.key === 'I'))
        || (e.ctrlKey && (e.key === 's' || e.key === 'S'))) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
  }, true);
  window.addEventListener('contextmenu', (e) => e.stopImmediatePropagation(), true);
} catch(e) {}

// L10: Block fullscreen (all vendors)
const blockFS = () => Promise.reject('FS');
try {
  ['requestFullscreen', 'webkitRequestFullscreen', 'mozRequestFullScreen', 'msRequestFullscreen']
    .forEach(p => { if (Element.prototype[p]) Element.prototype[p] = blockFS; });
} catch(e) {}
try { if (document.exitFullscreen) document.exitFullscreen = () => {}; } catch(e) {}

// L11: Block VIP events
const bve = (e) => { e.stopImmediatePropagation(); e.preventDefault(); };
try {
  window.addEventListener('onVipLimit', bve, true);
  window.addEventListener('onGuestLimit', bve, true);
} catch(e) {}

console.log('[OLM v1.0.0] Anti-detect installed — 11 layers');
})();
"""

# ═══════════════════════════════════════════════════════════════
# AUTOFILL JS — text-matching (khớp 100% userscript)
# ═══════════════════════════════════════════════════════════════
AUTOFILL_JS = r"""
(function() {
'use strict';
if (window.__olm_autofill_v19) return;
window.__olm_autofill_v19 = true;

const fireInput = (el) => {
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
};

const findAnswerForQuestion = (questionText, type) => {
  const captured = window.__OLM_CAPTURED_QUESTIONS || [];
  for (const q of captured) {
    const content = (q && q.p && q.p.content) || '';
    if (!content) continue;
    if (questionText.includes(content.substring(0, 40))) {
      if (type === 'text' || type === 'fill') {
        if (q.correctAnswer) return q.correctAnswer;
        if (q.correctAnswers && q.correctAnswers.length) return q.correctAnswers[0];
      }
      if (type === 'radio') {
        if (q.correctIndex !== undefined) return String.fromCharCode(65 + parseInt(q.correctIndex));
        if (q.correctAnswers && q.correctAnswers.length) return q.correctAnswers[0];
      }
      if (type === 'checkbox') {
        if (q.correctAnswers && Array.isArray(q.correctAnswers)) return q.correctAnswers;
      }
    }
  }
  return null;
};

const autoAnswerAndFill = () => {
  try {
    document.querySelectorAll(
      'input[type="text"], input[type="number"], textarea'
    ).forEach(input => {
      if (input.value.trim() !== '') return;
      const parent = input.closest(
        '.question-item, .quiz-question, .cau-hoi, [data-question-id]'
      );
      if (!parent) return;
      const ans = findAnswerForQuestion(parent.innerText.trim(), 'text');
      if (ans) { input.value = ans; fireInput(input); }
    });
  } catch(e) {}

  try {
    const groups = new Map();
    document.querySelectorAll('input[type="radio"]').forEach(r => {
      const n = r.getAttribute('name');
      if (n) groups.set(n, (groups.get(n) || []).concat(r));
    });
    groups.forEach((group, name) => {
      const parent = group[0].closest('.question-item, .quiz-question, .cau-hoi');
      if (!parent) return;
      const letter = findAnswerForQuestion(parent.innerText.trim(), 'radio');
      if (letter) {
        const target = group.find(r => r.value.toUpperCase() === letter.toUpperCase());
        if (target && !target.checked) { target.checked = true; fireInput(target); }
      }
    });
  } catch(e) {}

  try {
    const cg = new Map();
    document.querySelectorAll('input[type="checkbox"]').forEach(c => {
      const n = c.getAttribute('name');
      if (n) cg.set(n, (cg.get(n) || []).concat(c));
    });
    cg.forEach((group, name) => {
      const parent = group[0].closest('.question-item, .quiz-question, .cau-hoi');
      if (!parent) return;
      const ans = findAnswerForQuestion(parent.innerText.trim(), 'checkbox');
      if (Array.isArray(ans)) {
        ans.forEach((val, idx) => {
          if (val === '1' && group[idx] && !group[idx].checked) {
            group[idx].checked = true; fireInput(group[idx]);
          }
        });
      } else if (ans === '1' && group[0] && !group[0].checked) {
        group[0].checked = true; fireInput(group[0]);
      }
    });
  } catch(e) {}
};

window.__olm_autofill_run = autoAnswerAndFill;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => setTimeout(autoAnswerAndFill, 1500));
} else {
  setTimeout(autoAnswerAndFill, 1500);
}

try {
  const obs = new MutationObserver(() => autoAnswerAndFill());
  if (document.body) obs.observe(document.body, { childList: true, subtree: true });
} catch(e) {}

console.log('[OLM v1.0.0] Auto-fill installed');
})();
"""

def _msgbox(title: str, msg: str, style: int = 0) -> int:
    if sys.platform != "win32":
        print(f"[{title}] {msg}"); return 1
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), style)
    except Exception:
        print(f"[{title}] {msg}"); return 1

def _log_crash(tb: str) -> None:
    try: CRASH_F.write_text(tb, encoding="utf-8")
    except Exception: pass

def _chmod_private(p: Path) -> None:
    try:
        if sys.platform != "win32" and p.exists(): p.chmod(0o600)
    except Exception: pass

_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_ready = threading.Event()

def _start_bg_loop() -> None:
    global _bg_loop
    _bg_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_bg_loop)
    _bg_ready.set()
    _bg_loop.run_forever()

threading.Thread(target=_start_bg_loop, daemon=True, name="olm-bg").start()
_bg_ready.wait()

def run_async(coro, timeout: float = 300):
    fut = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return fut.result(timeout=timeout)

def get_hwid() -> str:
    parts: List[str] = []
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
            guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            parts.append(str(guid))
        except Exception: pass
    for fn in (lambda: str(uuid.getnode()), lambda: platform.node(), lambda: platform.machine()):
        try: parts.append(fn())
        except Exception: pass
    raw = "|".join(parts) or str(uuid.uuid4())
    return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()

def b64x_decode(encoded: str) -> str:
    if not encoded: return ""
    try:
        raw = base64.b64decode(encoded)
        out = bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw))
        return out.decode("utf-8", errors="replace")
    except Exception: return ""

def try_json(s):
    try: return json.loads(s)
    except Exception: return None

def extract_id_from_input(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s: return None
    if re.fullmatch(r"\d{6,}", s): return s
    for pat in (r"/chu-de/(\d{6,})", r"/bai-tap/(\d{6,})", r"/lam-bai/(\d{6,})",
                r"[?&]id_cate=(\d{6,})", r"[?&]idCate=(\d{6,})"):
        m = re.search(pat, s, re.I)
        if m: return m.group(1)
    m = re.search(r"\b(\d{6,})\b", s)
    return m.group(1) if m else None

def _port_open(host="127.0.0.1", port=CDP_PORT, timeout=0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout): return True
    except Exception: return False

def _cdp_available() -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as r:
            return {"available": True, "browser": json.loads(r.read()).get("Browser", "?")}
    except Exception: return {"available": False}

def _find_chrome() -> Optional[str]:
    for c in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]:
        if c and os.path.exists(c): return c
    return None

def _launch_chrome() -> Dict[str, Any]:
    if _port_open(): return {"ok": True, "already": True}
    exe = _find_chrome()
    if not exe: return {"ok": False, "error": "Không tìm thấy Chrome/Edge"}
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_PROFILE}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=AutomationControlled,Translate,OptimizationHints",
            "--disable-infobars", "--no-service-autorun",
            "--password-store=basic", "--use-mock-keychain", OLM_BASE]
    try:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP \
            if sys.platform == "win32" else 0
        subprocess.Popen(args, creationflags=flags, close_fds=True)
    except Exception as e: return {"ok": False, "error": f"Launch lỗi: {e}"}
    for _ in range(40):
        if _port_open(): return {"ok": True, "already": False, "path": exe}
        time.sleep(0.5)
    return {"ok": False, "error": "Chrome không phản hồi CDP"}

def _find_chromium_exe() -> Optional[Path]:
    if not BROWSERS_DIR.exists(): return None
    for name in ["chrome.exe", "headless_shell.exe", "chrome", "headless_shell"]:
        for p in BROWSERS_DIR.rglob(name):
            if p.is_file(): return p
    return None

def check_chromium() -> Dict[str, Any]:
    if not HAS_PW: return {"ok": False, "installed": False, "error": "Playwright chưa cài"}
    exe = _find_chromium_exe()
    if exe: return {"ok": True, "installed": True, "path": str(exe)}
    return {"ok": True, "installed": False}

def install_chromium(progress_cb: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    if not HAS_PW: return {"ok": False, "error": "Playwright chưa cài"}
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except ImportError as e: return {"ok": False, "error": f"Import driver fail: {e}"}
    try: driver_executable, driver_cli = compute_driver_executable()
    except Exception as e: return {"ok": False, "error": f"Driver fail: {e}"}
    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    env.setdefault("PLAYWRIGHT_SKIP_BROWSER_GC", "1")
    if progress_cb: progress_cb("Đang tải Chromium (~150MB)...")
    try:
        cf = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [str(driver_executable), str(driver_cli), "install", "chromium"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=cf, text=True, encoding="utf-8", errors="replace")
        out: List[str] = []
        start = time.time()
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                out.append(line.strip())
                if progress_cb: progress_cb(line.strip()[:200])
            if proc.poll() is not None: break
            if time.time() - start > 900:
                proc.kill()
                return {"ok": False, "error": "Timeout (>15 phút)"}
            if not line: time.sleep(0.1)
        if proc.returncode != 0:
            return {"ok": False, "error": f"Exit {proc.returncode}"}
        exe = _find_chromium_exe()
        if exe: return {"ok": True, "path": str(exe)}
        return {"ok": False, "error": "Không tìm thấy exe sau khi cài"}
    except Exception as e: return {"ok": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════════
# SUPABASE + LICENSE
# ═══════════════════════════════════════════════════════════════
class SupabaseClient:
    def __init__(self, url: str, anon_key: str):
        self.url = url.rstrip("/")
        self.anon_key = anon_key
    def _req(self, method, path, body=None, prefer="") -> Tuple[int, Any]:
        url = f"{self.url}/rest/v1/{path}"
        headers = {"apikey": self.anon_key,
                   "Authorization": f"Bearer {self.anon_key}",
                   "Content-Type": "application/json"}
        if prefer: headers["Prefer"] = prefer
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                txt = r.read().decode("utf-8", errors="replace")
                try: return r.status, (json.loads(txt) if txt else None)
                except Exception: return r.status, txt
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", errors="replace")
            try: return e.code, (json.loads(txt) if txt else None)
            except Exception: return e.code, txt
        except Exception as e: return 0, str(e)
    def select(self, table, params=""):
        return self._req("GET", f"{table}?{params}" if params else table)
    def patch(self, table, params, body):
        return self._req("PATCH", f"{table}?{params}", body=body, prefer="return=representation")
    def is_configured(self) -> bool:
        return ("YOUR-PROJECT" not in self.url and "YOUR-ANON-KEY" not in self.anon_key
                and self.url.startswith("http"))

class LicenseManager:
    def __init__(self):
        self.hwid = get_hwid()
        self.sb = SupabaseClient(SUPABASE_URL, SUPABASE_ANON_KEY)
        self.cache = self._load_cache()
    def _load_cache(self):
        try: return json.loads(LICENSE_F.read_text(encoding="utf-8"))
        except Exception: return {}
    def _save_cache(self):
        try:
            LICENSE_F.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
            _chmod_private(LICENSE_F)
        except Exception: pass
    def get_hwid(self) -> str: return self.hwid
    def _find_active_by_hwid(self):
        code, rows = self.sb.select("licenses",
            f"hwid=eq.{urllib.parse.quote(self.hwid)}&revoked=eq.false&select=*")
        if code != 200 or not isinstance(rows, list): return None
        now = datetime.now(timezone.utc)
        for r in rows:
            exp = r.get("expires_at")
            if not exp: continue
            try:
                e = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if e > now: return r
            except Exception: continue
        return None
    def validate(self):
        if not self.sb.is_configured():
            return {"ok": False, "reason": "Supabase chưa cấu hình", "hwid": self.hwid}
        row = self._find_active_by_hwid()
        if not row:
            ce = self.cache.get("expires_at")
            if ce:
                try:
                    e = datetime.fromisoformat(ce.replace("Z", "+00:00"))
                    if e > datetime.now(timezone.utc):
                        secs = int((e - datetime.now(timezone.utc)).total_seconds())
                        return {"ok": True, "cached": True, "seconds_left": secs,
                                "hwid": self.hwid, **self.cache}
                except Exception: pass
            return {"ok": False, "reason": "Chưa kích hoạt / hết hạn", "hwid": self.hwid}
        self.cache = {"key": row.get("key"), "expires_at": row.get("expires_at"),
                      "key_type": row.get("key_type"),
                      "duration_days": row.get("duration_days"),
                      "activated_at": row.get("activated_at")}
        self._save_cache()
        try:
            e = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            secs = int((e - datetime.now(timezone.utc)).total_seconds())
        except Exception: secs = 0
        return {"ok": True, "seconds_left": secs, "hwid": self.hwid, **self.cache}
    def activate(self, key: str):
        if not self.sb.is_configured():
            return {"ok": False, "error": "Supabase chưa cấu hình"}
        key = (key or "").strip()
        if not key: return {"ok": False, "error": "Key trống"}
        existing = self._find_active_by_hwid()
        if existing and existing.get("key") != key:
            return {"ok": False, "error": f"Máy đã khóa với key {existing.get('key')}."}
        code, rows = self.sb.select("licenses", f"key=eq.{urllib.parse.quote(key)}&select=*")
        if code != 200 or not isinstance(rows, list) or not rows:
            return {"ok": False, "error": "Key không tồn tại"}
        row = rows[0]
        if row.get("revoked"): return {"ok": False, "error": "Key đã bị hủy"}
        if row.get("hwid") and row["hwid"] != self.hwid:
            return {"ok": False, "error": "Key đã khóa máy khác"}
        if row.get("hwid") == self.hwid and row.get("expires_at"):
            try:
                e = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                if e > datetime.now(timezone.utc):
                    self.cache = {"key": key, "expires_at": row["expires_at"],
                                  "key_type": row.get("key_type"),
                                  "duration_days": row.get("duration_days"),
                                  "activated_at": row.get("activated_at")}
                    self._save_cache()
                    return {"ok": True, "reactivated": True,
                            "expires_at": row["expires_at"], "key": key,
                            "key_type": row.get("key_type"),
                            "days": row.get("duration_days")}
            except Exception: pass
        days = int(row.get("duration_days") or 1)
        now = datetime.now(timezone.utc)
        exp = now + timedelta(days=days)
        body = {"hwid": self.hwid, "activated_at": now.isoformat(), "expires_at": exp.isoformat()}
        code, _ = self.sb.patch("licenses", f"key=eq.{urllib.parse.quote(key)}", body)
        if code not in (200, 204):
            return {"ok": False, "error": f"Lỗi cập nhật ({code})"}
        self.cache = {"key": key, "expires_at": exp.isoformat(),
                      "key_type": row.get("key_type"),
                      "duration_days": days, "activated_at": now.isoformat()}
        self._save_cache()
        return {"ok": True, "expires_at": exp.isoformat(), "key": key,
                "key_type": row.get("key_type"), "days": days}
    def deactivate(self):
        if not self.sb.is_configured():
            return {"ok": False, "error": "Supabase chưa cấu hình"}
        row = self._find_active_by_hwid()
        if not row:
            self.cache = {}; self._save_cache()
            return {"ok": True, "message": "Không có key nào đang khóa"}
        body = {"hwid": None, "activated_at": None, "expires_at": None, "revoked": True}
        code, _ = self.sb.patch("licenses", f"key=eq.{urllib.parse.quote(row['key'])}", body)
        self.cache = {}; self._save_cache()
        if code not in (200, 204):
            return {"ok": False, "error": f"Lỗi hủy ({code})"}
        return {"ok": True, "message": f"Đã hủy key {row['key']}"}

# ═══════════════════════════════════════════════════════════════
# OLM SESSION
# ═══════════════════════════════════════════════════════════════
class OLMSession:
    def __init__(self):
        self.cookies: Dict[str, str] = {}
        self.user_id: Optional[str] = None
        self.username: Optional[str] = None
        self._csrf: Optional[str] = None
    @classmethod
    def load(cls) -> "OLMSession":
        s = cls()
        if SESSION_F.exists():
            try:
                d = json.loads(SESSION_F.read_text(encoding="utf-8"))
                s.cookies = d.get("cookies", {})
                s.user_id = d.get("user_id")
                s.username = d.get("username")
            except Exception: pass
        return s
    def save(self) -> None:
        try:
            SESSION_F.write_text(json.dumps({
                "cookies": self.cookies, "user_id": self.user_id, "username": self.username,
            }, ensure_ascii=False), encoding="utf-8")
            _chmod_private(SESSION_F)
        except Exception: pass
    def clear(self) -> None:
        self.cookies = {}; self.user_id = None; self.username = None; self._csrf = None
        try:
            if SESSION_F.exists(): SESSION_F.unlink()
        except Exception: pass
    def set_cookies(self, raw: str) -> None:
        self.cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part: continue
            n, v = part.split("=", 1)
            self.cookies[n.strip()] = v.strip()
        self._extract_user(); self._csrf = None
    def set_cookie_dict(self, d: Dict[str, str]) -> None:
        self.cookies = dict(d); self._extract_user(); self._csrf = None
    def _extract_user(self) -> None:
        raw = self.cookies.get("user")
        if raw:
            try:
                u = json.loads(urllib.parse.unquote(raw))
                self.user_id = str(u.get("_id") or u.get("id") or "")
                self.username = u.get("username") or ""
            except Exception: pass
    @staticmethod
    def _extract_uid_static(cd: Dict[str, str]) -> Optional[str]:
        raw = cd.get("user")
        if not raw: return None
        try:
            u = json.loads(urllib.parse.unquote(raw))
            return str(u.get("_id") or u.get("id") or "") or None
        except Exception: return None
    @staticmethod
    def _extract_uname_static(cd: Dict[str, str]) -> Optional[str]:
        raw = cd.get("user")
        if not raw: return None
        try: return json.loads(urllib.parse.unquote(raw)).get("username")
        except Exception: return None
    def has_auth(self) -> bool:
        keys = {k.lower() for k in self.cookies.keys()}
        has_s = any(k in keys for k in ("onlinemath_session", "laravel_session"))
        has_p = ("user" in keys or "refresh_token" in keys
                 or any(k.startswith("remember_web_") for k in keys))
        return has_s and has_p
    def csrf(self) -> str:
        if self._csrf: return self._csrf
        v = self.cookies.get("XSRF-TOKEN") or self.cookies.get("X-CSRF-TOKEN") or ""
        self._csrf = urllib.parse.unquote(v)
        return self._csrf
    async def client(self) -> CurlAsyncSession:
        return CurlAsyncSession(
            base_url=OLM_BASE, cookies=self.cookies, timeout=30.0,
            impersonate=IMPERSONATE,
            headers={"User-Agent": UA,
                     "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            allow_redirects=True)
    async def request(self, method: str, url: str, **kw):
        async with await self.client() as c:
            r = await c.request(method, url, **kw)
            try:
                jar = c.cookies
                newc = jar.get_dict() if hasattr(jar, "get_dict") else dict(jar)
                for n, v in newc.items():
                    if n != "__cflb": self.cookies[n] = v
            except Exception: pass
            try:
                ct = r.headers.get("content-type", "")
                if "html" in ct and r.text and "<meta" in r.text:
                    m = re.search(r'name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)', r.text)
                    if not m:
                        m = re.search(r'content=["\']([^"\']+)["\'][^>]*name=["\']csrf-token', r.text)
                    if m: self._csrf = m.group(1)
            except Exception: pass
            self.save()
            return r
    async def refresh_csrf(self, id_cate: Optional[str] = None) -> str:
        path = _url_v1(f"/chu-de/{id_cate}") if id_cate else "/"
        try:
            r = await self.request("GET", path)
            txt = r.text or ""
            m = re.search(r'name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)', txt)
            if not m:
                m = re.search(r'content=["\']([^"\']+)["\'][^>]*name=["\']csrf-token', txt)
            if m:
                self._csrf = m.group(1); return self._csrf
        except Exception: pass
        return self.csrf()

# ═══════════════════════════════════════════════════════════════
# CDP MANAGER
# ═══════════════════════════════════════════════════════════════
class CDPManager:
    def __init__(self):
        self.pw = None; self.browser = None; self._alock = None
    async def _lock(self):
        if self._alock is None: self._alock = asyncio.Lock()
        return self._alock
    async def attach(self):
        lock = await self._lock()
        async with lock:
            if self.browser is not None:
                try:
                    _ = self.browser.contexts
                    return {"ok": True, "browser": self.browser, "reused": True}
                except Exception: self.browser = None
            if not HAS_PW: return {"ok": False, "error": "Playwright chưa cài"}
            if not _cdp_available().get("available"):
                return {"ok": False, "error": "CDP không khả dụng"}
            if self.pw is None: self.pw = await async_playwright().start()
            try:
                self.browser = await self.pw.chromium.connect_over_cdp(CDP_URL, timeout=15000)
            except Exception as e:
                return {"ok": False, "error": f"Attach lỗi: {e}"}
            return {"ok": True, "browser": self.browser}
    async def get_olm_page(self):
        r = await self.attach()
        if not r.get("ok"): return None, r.get("error", "Attach failed")
        browser = r["browser"]
        if not browser.contexts: return None, "Chrome chưa có context"
        ctx = browser.contexts[0]
        page = None
        for p in ctx.pages:
            try:
                if "olm.vn" in (p.url or ""):
                    page = p; break
            except Exception: continue
        if not page:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        return page, None
    async def sync_cookies_to_session(self, sess: OLMSession) -> None:
        r = await self.attach()
        if not r.get("ok"): return
        browser = r["browser"]
        if not browser.contexts: return
        ctx = browser.contexts[0]
        try: cookies = await ctx.cookies()
        except Exception: return
        for c in cookies:
            try:
                if "olm.vn" in (c.get("domain") or ""):
                    sess.cookies[c["name"]] = c["value"]
            except Exception: continue
        sess._extract_user(); sess.save()

# ═══════════════════════════════════════════════════════════════
# CHROME COOKIE GRABBER
# ═══════════════════════════════════════════════════════════════
class ChromeCookieGrabber:
    def __init__(self, cdp_mgr: CDPManager):
        self.cdp = cdp_mgr
    async def grab(self):
        if not HAS_PW: return {"ok": False, "error": "Playwright chưa cài"}
        if not _port_open():
            r = _launch_chrome()
            if not r.get("ok"): return {"ok": False, "error": r.get("error", "Không mở được Chrome")}
            await asyncio.sleep(2)
        page, err = await self.cdp.get_olm_page()
        if err: return {"ok": False, "error": f"Không attach CDP: {err}"}
        try: cur_url = page.url or ""
        except Exception: cur_url = ""
        if "olm.vn" not in cur_url:
            try: await page.goto(OLM_BASE, wait_until="domcontentloaded", timeout=30000)
            except Exception: pass
            await asyncio.sleep(3)
        try:
            ctx = self.cdp.browser.contexts[0]
            cookies = await ctx.cookies()
        except Exception as e: return {"ok": False, "error": f"Lỗi đọc cookies: {e}"}
        cd = {}
        for c in cookies:
            try:
                if "olm.vn" in (c.get("domain") or ""):
                    cd[c["name"]] = c["value"]
            except Exception: continue
        keys = {k.lower() for k in cd.keys()}
        has_s = any(k in keys for k in ("onlinemath_session", "laravel_session"))
        has_p = ("user" in keys or "refresh_token" in keys
                 or any(k.startswith("remember_web_") for k in keys))
        if not (has_s and has_p):
            return {"ok": False, "waiting_login": True,
                    "error": "Chrome chưa login OLM.", "cookies": sorted(keys)}
        return {"ok": True, "cookies": cd,
                "user_id": OLMSession._extract_uid_static(cd),
                "username": OLMSession._extract_uname_static(cd)}

# ═══════════════════════════════════════════════════════════════
# === v19.1 - PORT FROM USERSCRIPT ===
# QUESTION PARSER — 12+ Q_TYPES (khớp 100% userscript)
# ═══════════════════════════════════════════════════════════════
def _collect_text(node, out, depth=0):
    if not node or depth > 20: return
    if isinstance(node, dict):
        t = node.get("text")
        if isinstance(t, str) and t.strip(): out.append(t.strip())
        ch = node.get("children")
        if isinstance(ch, list):
            for c in ch: _collect_text(c, out, depth + 1)
        else:
            for k, v in node.items():
                if k not in ("text", "children") and isinstance(v, (dict, list)):
                    _collect_text(v, out, depth + 1)
    elif isinstance(node, list):
        for c in node: _collect_text(c, out, depth + 1)

def find_nodes(node, type_, out):
    """Port từ findAllNodes trong userscript — đệ quy toàn bộ tree."""
    if not node: return
    if isinstance(node, dict):
        if node.get("type") == type_: out.append(node)
        ch = node.get("children")
        if isinstance(ch, list):
            for c in ch: find_nodes(c, type_, out)
        else:
            for k, v in node.items():
                if k not in ("type", "children"): find_nodes(v, type_, out)

def find_all_nodes_by_name(node, name, out):
    """Helper: tìm tất cả olm-list theo name (link-list, quiz-list...)."""
    if not node: return
    if isinstance(node, dict):
        if node.get("type") == "olm-list" and node.get("name") == name:
            out.append(node)
        ch = node.get("children")
        if isinstance(ch, list):
            for c in ch: find_all_nodes_by_name(c, name, out)
        else:
            for k, v in node.items():
                if k not in ("type", "children"): find_all_nodes_by_name(v, name, out)

def _opt_text(child) -> str:
    if not child: return ""
    t = child.get("text")
    if isinstance(t, str) and t.strip(): return t.strip()[:300]
    txts = []; _collect_text(child, txts)
    if txts:
        if len(txts) > 1 and re.fullmatch(r'[A-Z]\.', txts[0] or ""):
            return " ".join(txts[1:])[:300]
        return " ".join(txts)[:300]
    return ""

def extract_questions(data) -> List[dict]:
    """
    PORT 100% extractQuestionData từ userscript.
    Hỗ trợ đầy đủ các q_type: 1, 2, 3, 5, 6, 9, 10, 11, 13, 20, 21, 22.
    """
    if not isinstance(data, list): return []
    out = []
    for q in data:
        try:
            jc = q.get("json_content")
            if not jc or not q.get("id"): continue
            root_data = try_json(b64x_decode(jc))
            if not root_data or "root" not in root_data: continue
            qtype = int(q.get("q_type") or 1)
            base = {"id": q["id"], "q_type": qtype,
                    "type_label": QTYPE_LABEL.get(qtype, f"Type {qtype}"),
                    "max_score": q.get("score") or 1}
            text_parts = []; _collect_text(root_data["root"], text_parts)
            base["text"] = re.sub(r'\s+', ' ', " ".join(text_parts[:4])).strip()[:200]
            base["text_all"] = text_parts[:20]
            all_lists = []; find_nodes(root_data["root"], "olm-list", all_lists)
            for l in all_lists:
                if l.get("name") in ("quiz-list", "true-false"):
                    ch = l.get("children") or []
                    if ch:
                        base["options"] = [_opt_text(c) for c in ch]
                        base["optionCount"] = len(ch)
                        break

            # ─── q_type 5: ordering ───
            if qtype == 5:
                sort_list = []
                find_nodes(root_data["root"], "olm-list", sort_list)
                if sort_list and sort_list[0].get("children"):
                    n = len(sort_list[0]["children"])
                    order = list(range(n))
                    out.append({**base, "correctAnswers": [str(x) for x in order],
                                "order": order, "optionCount": n}); continue

            # ─── q_type 9: underline ───
            if qtype == 9:
                ul = []; find_nodes(root_data["root"], "under-line", ul)
                idx = []
                for i, n in enumerate(ul):
                    if n.get("correct") is True: idx.append(i)
                if idx:
                    out.append({**base, "correctAnswers": idx}); continue

            # ─── q_type 21/22: group sub-answers ───
            if qtype in (21, 22):
                html_dec = b64x_decode(q.get("content") or "")
                list_idq = re.findall(r'<hr id="([^"]+)"', html_dec) if html_dec else []
                sa, st, sl, soc, so = [], [], [], [], []
                def proc(nodes, depth=0):
                    if not isinstance(nodes, list) or depth > 10: return
                    for n in nodes:
                        if not isinstance(n, dict): continue
                        ntype = n.get("type"); nname = n.get("name", "")
                        if ntype == "olm-list":
                            nc = len(n.get("children") or [])
                            order = n.get("order") or list(range(nc))
                            if nname == "true-false":
                                tf = ["1" if it.get("correct") is True else "0"
                                      for it in n["children"]]
                                sa.append(tf); st.append(13); sl.append("")
                                soc.append(nc); so.append(order)
                            else:
                                cf = [str(i) for i, it in enumerate(n["children"])
                                      if it.get("correct") is True]
                                if not cf: cf = ["0"]
                                sa.append(cf); st.append(1)
                                sl.append(chr(65 + int(cf[0])))
                                soc.append(nc); so.append(order)
                        elif ntype in ("paragraph", "extended-text"):
                            inps = []
                            find_nodes(n, "olm-input-text", inps)
                            find_nodes(n, "fillme-input", inps)
                            if inps:
                                vals = []
                                for x in inps:
                                    if x.get("name") == "selecttext": vals.append("0")
                                    else:
                                        vals.append((x.get("content") or "").split("||")[0])
                                sa.append(vals); st.append(11); sl.append("")
                                soc.append(4); so.append([0, 1, 2, 3])
                        if n.get("children"): proc(n["children"], depth + 1)
                proc(root_data["root"].get("children") or [])
                if sa:
                    out.append({**base, "sub_answers": sa, "sub_types": st,
                                "sub_labels": sl, "sub_option_counts": soc,
                                "sub_orders": so, "list_ids": list_idq}); continue

            # ─── q_type 20: sort paragraph ───
            if qtype == 20:
                li = []; find_nodes(root_data["root"], "olm-list-item", li)
                if li and li[0].get("children") and li[0]["children"][0].get("text"):
                    n = len(li[0]["children"][0]["text"].split("||"))
                    idx = list(range(n))
                    out.append({**base, "correctAnswers": idx, "order": idx,
                                "optionCount": n}); continue

            # ─── q_type 3/11: fill pool + select ───
            if qtype in (3, 11):
                inp = []; find_nodes(root_data["root"], "olm-input-text", inp)
                if inp:
                    pool = 0; ci = []
                    for n in inp:
                        if qtype == 11:
                            ci.append("0")
                        else:
                            ci.append(str(pool))
                            pool += len((n.get("content") or "").split("||"))
                    size = len(inp) if qtype == 11 else pool
                    out.append({**base, "correctAnswers": ci,
                                "order": list(range(size)), "optionCount": size}); continue

            # ─── q_type 6: matching link-list ───
            if qtype == 6:
                lst = next((n for n in all_lists if n.get("name") == "link-list"), None)
                if lst and lst.get("children"):
                    n = len(lst["children"])
                    out.append({**base, "correctAnswers": [str(x) for x in range(n)],
                                "order": lst.get("order"), "optionCount": n}); continue

            # ─── q_type 10: group drag ───
            if qtype == 10:
                lst = next((n for n in all_lists if n.get("name") == "group-list"), None)
                if lst and lst.get("children"):
                    oi = 0; ai = []
                    for item in lst["children"]:
                        grp = []; nodes = []
                        find_nodes(item, "position-column", nodes)
                        for n in nodes:
                            if n.get("position") == "group":
                                grp.append(oi); oi += 1
                        if grp: ai.append(grp)
                    out.append({**base, "answerIndices": ai,
                                "order": lst.get("order"), "optionCount": oi}); continue

            # ─── q_type 2: fill 1 ô ───
            if qtype == 2:
                inp = []; find_nodes(root_data["root"], "fillme-input", inp)
                if inp:
                    val = (inp[0].get("content") or "").split("||")[0]
                    out.append({**base, "correctAnswer": val,
                                "correctAnswers": [val]}); continue

            # ─── Fallback: quiz-list / true-false (q_type 1, 13) ───
            lst = next((n for n in all_lists
                        if n.get("name") in ("quiz-list", "true-false")), None)
            if lst and lst.get("children"):
                nc = len(lst["children"])
                order = lst.get("order") or list(range(nc))
                opts = [_opt_text(c) for c in lst["children"]]
                base["options"] = opts
                qo = []
                for p in text_parts:
                    if opts and p == opts[0]: break
                    qo.append(p)
                base["question_text"] = " ".join(qo)[:500]
                expl = ""
                for k, p in enumerate(text_parts):
                    if "hướng dẫn giải" in p.lower():
                        expl = " ".join(text_parts[k + 1:k + 6])[:500]; break
                base["explanation"] = expl
                cf_flags = ["1" if it.get("correct") else "0" for it in lst["children"]]
                n_true = sum(1 for f in cf_flags if f == "1")
                # PORT: multi_select detection (>=2 true, >=3 options, true-false)
                is_multi = (qtype == 13 and n_true >= 2 and nc >= 3
                            and lst.get("name") == "true-false")
                if is_multi:
                    out.append({**base, "correctAnswers": cf_flags,
                                "multi_select": True,
                                "order": order, "optionCount": nc})
                elif qtype == 13 or lst.get("name") == "true-false":
                    out.append({**base, "correctAnswers": cf_flags,
                                "order": order, "optionCount": nc})
                else:
                    ci = [str(i) for i, it in enumerate(lst["children"]) if it.get("correct")]
                    if not ci: ci = ["0"]
                    out.append({**base, "correctIndex": ci[0], "correctAnswers": ci,
                                "correctLabel": chr(65 + int(ci[0])),
                                "order": order, "optionCount": nc})
        except Exception: continue
    return out

# ═══════════════════════════════════════════════════════════════
# === v19.1 - PORT FROM USERSCRIPT ===
# BUILD CHOOSE LABEL / DATA LOG / CHOOSE LOG
# ═══════════════════════════════════════════════════════════════
def _build_choose_label(q: dict):
    """
    Port logic userscript để label gửi lên data_log khớp 100%.
    - q_type 13 multi_select: trả list index của các vị trí '1'.
    - q_type 13 single: trả '0'/'1'.
    - q_type 5/6/3/11: trả list int.
    - q_type còn lại: trả chữ A/B/C... hoặc 'A' fallback.
    """
    qt = q.get("q_type")
    if qt == 13:
        if q.get("multi_select"):
            ca = q.get("correctAnswers") or []
            idxs = [i for i, v in enumerate(ca) if v == '1']
            return idxs or [0]
        ca = q.get("correctAnswers") or ["1"]
        return ca[0] if ca[0] in ("0", "1") else "0"
    if qt in (5, 6):
        ca = q.get("correctAnswers") or []
        return [int(x) for x in ca] if ca else [0]
    if qt in (3, 11):
        ca = q.get("correctAnswers") or []
        return [int(x) for x in ca] if ca else [0]
    if q.get("correctLabel"):
        return q["correctLabel"]
    if q.get("correctIndex") is not None:
        try: return chr(65 + int(q["correctIndex"]))
        except Exception: pass
    ca = q.get("correctAnswers") or []
    if ca:
        v = ca[0]
        if isinstance(v, str) and re.match(r'^[A-Z]$', v): return v
        try: return chr(65 + int(v))
        except Exception: pass
    return "A"

def _build_choose_log(questions, step_ms):
    """choose_log: [[{ind, t, l}, ...]] — nested array."""
    inner = []
    for i, q in enumerate(questions):
        inner.append({"ind": i, "t": step_ms * (i + 1), "l": _build_choose_label(q)})
    return [inner]

def _build_data_log(questions, n_correct, per_q_max):
    """data_log: [{_id, nx, _score, iframe, count_redo, correct, user_answer, choose}]"""
    dl = []
    for i, q in enumerate(questions):
        is_correct = i < n_correct
        label = _build_choose_label(q)
        dl.append({
            "_id": str(q["id"]), "nx": i,
            "_score": per_q_max if is_correct else 0,
            "iframe": False, "count_redo": 0,
            "correct": 1 if is_correct else 0,
            "user_answer": label if is_correct else None,
            "choose": label,
        })
    return dl

def _build_answer_strings(questions, n_correct):
    """ans / user_ans: chuỗi ngăn cách bởi '|'."""
    ans_parts = []; user_parts = []
    for i, q in enumerate(questions):
        l = _build_choose_label(q)
        l_str = ",".join(str(x) for x in l) if isinstance(l, list) else str(l)
        ans_parts.append(l_str)
        user_parts.append(l_str if i < n_correct else "")
    return "|".join(ans_parts), "|".join(user_parts)

# ═══════════════════════════════════════════════════════════════
# OLM CLIENT
# ═══════════════════════════════════════════════════════════════
CACHE_TTL_SEC = 3600          # 1h
CACHE_CLEAN_SEC = 86400       # 24h auto-clean

class OLMClient:
    def __init__(self, sess: OLMSession, cdp_mgr: CDPManager):
        self.sess = sess; self.cdp = cdp_mgr
        self._hl_pw = None; self._hl_browser = None
        self.prefer_cdp = False
        self._qcache: Dict[str, dict] = {}
        self._load_qcache()

    def _load_qcache(self):
        try:
            if Q_CACHE_F.exists():
                d = json.loads(Q_CACHE_F.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    # Auto-clean cache > 24h
                    now = time.time()
                    cleaned = {}
                    for k, v in d.items():
                        if isinstance(v, dict) and now - v.get("ts", 0) < CACHE_CLEAN_SEC:
                            cleaned[k] = v
                    self._qcache = cleaned
                    if len(cleaned) != len(d): self._save_qcache()
        except Exception: pass

    def _save_qcache(self):
        try:
            Q_CACHE_F.write_text(json.dumps(self._qcache, ensure_ascii=False),
                                 encoding="utf-8")
        except Exception: pass

    async def _ensure_headless(self):
        if not HAS_PW: raise ChromiumMissing("Playwright chưa cài")
        exe = _find_chromium_exe()
        if not exe: raise ChromiumMissing("CHROMIUM_MISSING: Chưa có Chromium.")
        if self._hl_browser is not None:
            try:
                _ = self._hl_browser.contexts
                return self._hl_browser
            except Exception: self._hl_browser = None
        if self._hl_pw is None: self._hl_pw = await async_playwright().start()
        try:
            self._hl_browser = await self._hl_pw.chromium.launch(
                headless=True, executable_path=str(exe),
                args=["--disable-blink-features=AutomationControlled",
                      "--disable-features=AutomationControlled,Translate",
                      "--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-gpu", "--no-first-run",
                      "--no-default-browser-check", "--disable-infobars",
                      "--mute-audio"])
        except Exception as e:
            raise ChromiumMissing(f"Không mở được chromium: {e}")
        return self._hl_browser

    async def _new_headless_context(self):
        b = await self._ensure_headless()
        ctx = await b.new_context(user_agent=UA, locale="vi-VN",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"})
        try: await ctx.add_init_script(ANTI_DETECT_JS)
        except Exception: pass
        try: await ctx.add_init_script(AUTOFILL_JS)
        except Exception: pass
        cookies = [{"name": k, "value": v, "domain": ".olm.vn", "path": "/"}
                   for k, v in self.sess.cookies.items()]
        if cookies:
            try: await ctx.add_cookies(cookies)
            except Exception: pass
        return ctx

    async def _page(self):
        if self.prefer_cdp or _cdp_available().get("available"):
            page, err = await self.cdp.get_olm_page()
            if not err and page is not None:
                try: await page.add_init_script(ANTI_DETECT_JS)
                except Exception: pass
                try: await page.evaluate(ANTI_DETECT_JS)
                except Exception: pass
                try: await page.evaluate(AUTOFILL_JS)
                except Exception: pass
                async def _cleanup_cdp():
                    try: await self.cdp.sync_cookies_to_session(self.sess)
                    except Exception: pass
                return _cleanup_cdp, page
        ctx = await self._new_headless_context()
        page = await ctx.new_page()
        async def _cleanup_hl():
            try: await ctx.close()
            except Exception: pass
        return _cleanup_hl, page

    async def close(self):
        try:
            if self._hl_browser: await self._hl_browser.close()
        except Exception: pass
        self._hl_browser = None
        try:
            if self._hl_pw: await self._hl_pw.stop()
        except Exception: pass
        self._hl_pw = None

    async def _goto(self, page, url, timeout=60000, wait_cf=45):
        url = _url_v1(url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except Exception as e:
            raise OLMError(f"goto: {e}") from e
        start = time.time()
        while time.time() - start < wait_cf:
            try:
                title = (await page.title()) or ""
                cur = page.url or ""
            except Exception:
                await asyncio.sleep(1); continue
            in_cf = ("just a moment" in title.lower()
                     or "cloudflare" in title.lower()
                     or "challenges.cloudflare.com" in cur
                     or "attention required" in title.lower())
            if not in_cf:
                return {"ok": True, "url": cur}
            await asyncio.sleep(1.5)
        raise CloudflareBlock("CF_BLOCK: Cloudflare timeout")

    # ═══════════════════════════════════════════════════════════
    # SCAN ASSIGNMENTS — hỗ trợ CẢ v1 và v2
    # ═══════════════════════════════════════════════════════════
    async def scan_assignments(self) -> List[dict]:
        JS_SCAN = r"""() => {
            const out = []; const seen = new Set();
            const extractId = (h) => {
                const m = (h || '').match(/(?:\/chu-de\/|\/bai-tap\/|\/lam-bai\/)(\d{6,})/);
                return m ? m[1] : null;
            };
            const isDone = (el) => {
                if (!el) return false;
                const cl = el.className || '';
                if (/\b(done|completed|finished|đã-làm)\b/i.test(cl)) return true;
                for (const attr of ['data-done', 'data-completed', 'data-finished']) {
                    const v = el.getAttribute(attr);
                    if (v === '1' || v === 'true') return true;
                }
                const txt = (el.innerText || '').toLowerCase();
                if (/đã làm|hoàn thành|xem lại|done|completed/i.test(txt)) return true;
                return false;
            };
            const push = (id, title, href, type, done) => {
                if (!id || seen.has(id)) return;
                seen.add(id);
                const t = (title || '').trim().replace(/\s+/g, ' ').slice(0, 150);
                out.push({ id: String(id), title: t || ('Bài ' + id),
                           href: href || '', type: type || null,
                           done: !!done });
            };

            const v1Sels = [
                'table.table-striped tbody tr.my-given-courseware-item',
                'table.table-bordered tbody tr.my-given-courseware-item',
                'table tbody tr.my-given-courseware-item',
                'tr.my-given-courseware-item',
                '.my-given-courseware-item',
                'tr[data-cate]', 'tr[data-id-cate]', 'tr[data-id]'
            ];
            for (const sel of v1Sels) {
                document.querySelectorAll(sel).forEach(tr => {
                    let title = ''; const cells = tr.querySelectorAll('td');
                    if (cells.length > 0) title = (cells[0].innerText || '').trim();
                    let cid = null, href = '', typ = null;
                    tr.querySelectorAll('a[href]').forEach(a => {
                        const id = extractId(a.href);
                        if (id) { cid = id; href = a.href;
                            const t = (a.innerText || '').trim(); if (t) title = t; }
                    });
                    if (!cid) {
                        const dc = tr.getAttribute('data-cate') || tr.getAttribute('data-id-cate')
                            || tr.getAttribute('data-id');
                        if (dc && /^\d{6,}$/.test(dc)) cid = dc;
                    }
                    const dt = tr.getAttribute('data-type');
                    if (dt && /^\d+$/.test(dt)) typ = parseInt(dt);
                    if (cid) push(cid, title, href, typ, isDone(tr));
                });
            }

            const v2Sels = [
                '[class*="assignment-item"]', '[class*="courseware-item"]',
                '[class*="homework-item"]', '[class*="exercise-item"]',
                '[class*="bai-tap-item"]', '[class*="lesson-item"]',
                '[data-assignment-id]', '[data-courseware-id]',
                '[data-homework-id]', '[data-exercise-id]'
            ];
            for (const sel of v2Sels) {
                document.querySelectorAll(sel).forEach(el => {
                    let cid = null, href = '', title = '', typ = null;
                    for (const attr of ['data-assignment-id', 'data-courseware-id',
                                        'data-homework-id', 'data-exercise-id',
                                        'data-id', 'data-cate']) {
                        const v = el.getAttribute(attr);
                        if (v && /^\d{6,}$/.test(v)) { cid = v; break; }
                    }
                    el.querySelectorAll('a[href]').forEach(a => {
                        const id = extractId(a.href);
                        if (id) { cid = cid || id; href = href || a.href;
                            const t = (a.innerText || '').trim(); if (t) title = t; }
                    });
                    if (!title) {
                        const h = el.querySelector('h1,h2,h3,h4,.title,.name');
                        if (h) title = (h.innerText || '').trim();
                    }
                    if (!title) title = (el.innerText || '').trim().split('\n')[0];
                    if (cid) push(cid, title, href, typ, isDone(el));
                });
            }

            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.href || '';
                if (!/(?:\/chu-de\/|\/bai-tap\/|\/lam-bai\/)/.test(h)) return;
                if (/\/bg\/|\/lop\/|khoa-hoc|google|facebook|youtube|cloudflare/i.test(h)) return;
                const id = extractId(h);
                if (id) {
                    const t = (a.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 150);
                    let parent = a.closest('tr, li, div[class*="item"]');
                    push(id, t, h, null, isDone(parent));
                }
            });
            return out;
        }"""
        cleanup, page = await self._page()
        all_items = []; seen_ids = set()
        try:
            urls = [
                f"{OLM_BASE}/bai-tap-duoc-giao?private=1&v=v1",
                f"{OLM_BASE}/bai-tap-duoc-giao?private=1&v=v2",
                f"{OLM_BASE}/bai-tap-duoc-giao?private=1",
                f"{OLM_BASE}/bai-tap-duoc-giao/",
                f"{OLM_BASE}/bai-tap-giao-vien/",
                f"{OLM_BASE}/quan-ly-bai-tap/",
            ]
            for url in urls:
                try: await self._goto(page, url, timeout=60000, wait_cf=45)
                except CloudflareBlock: raise
                except Exception: continue
                try: await page.wait_for_load_state("networkidle", timeout=25000)
                except Exception: pass
                for sel in ['tr.my-given-courseware-item', 'table.table-striped tbody tr',
                            'table tbody tr', '.my-given-courseware-item',
                            'a[href*="/chu-de/"]', 'a[href*="/bai-tap/"]',
                            'a[href*="/lam-bai/"]',
                            '[class*="assignment-item"]', '[class*="courseware-item"]',
                            '[data-assignment-id]', '[data-courseware-id]']:
                    try:
                        await page.wait_for_selector(sel, timeout=6000); break
                    except Exception: continue
                for _ in range(8):
                    try: await page.evaluate("window.scrollBy(0, 900)")
                    except Exception: break
                    await asyncio.sleep(0.5)
                try: await page.evaluate("window.scrollTo(0, 0)")
                except Exception: pass
                await asyncio.sleep(1.5)
                try: data = await page.evaluate(JS_SCAN)
                except Exception: data = []
                if data:
                    for it in data:
                        if it["id"] not in seen_ids:
                            seen_ids.add(it["id"]); all_items.append(it)
                    if all_items: return all_items
            for u in ["/bai-tap-duoc-giao?private=1&v=v1",
                      "/bai-tap-duoc-giao?private=1&v=v2",
                      "/bai-tap-duoc-giao/"]:
                try:
                    r = await self.sess.request("GET", u)
                    if r.status_code != 200: continue
                    html = r.text or ""
                    if len(html) < 500: continue
                    items = self._parse_assignment_html(html)
                    if items: return items
                except Exception: continue
            return []
        finally:
            try: await cleanup()
            except Exception: pass

    def _parse_assignment_html(self, html):
        out = []; seen = set()
        P = re.compile(r'/(?:chu-de|bai-tap|lam-bai)/(\d{6,})')
        for m in re.finditer(r'<(?:tr|div|li)[^>]*data-(?:cate|id-cate|id)="(\d{6,})"', html, re.I):
            cid = m.group(1)
            if cid in seen: continue
            seen.add(cid)
            out.append({"id": cid, "title": f"Bài {cid}", "href": "", "type": None, "done": False})
        for m in re.finditer(
                r'href=["\']([^"\']*(?:/chu-de/|/bai-tap/|/lam-bai/)\d{6,}[^"\']*)["\']'
                r'[^>]*>([^<]*)', html, re.I):
            href = m.group(1)
            title = re.sub(r'\s+', ' ', (m.group(2) or "").strip())[:150]
            mid = P.search(href)
            if not mid: continue
            cid = mid.group(1)
            if cid in seen: continue
            seen.add(cid)
            if href.startswith("/"): href = OLM_BASE + href
            out.append({"id": cid, "title": title or f"Bài {cid}", "href": href,
                        "type": None, "done": False})
        return out

    async def _extract_data_cate(self, page) -> dict:
        dc = None
        try: dc = await page.evaluate("() => window.data_cate || null")
        except Exception: pass
        if not dc:
            try:
                dc = await page.evaluate("""() => {
                    const c = window.CATE_UI;
                    if (c && c.getData) return {
                        id_category: c.getData('id_category'),
                        id_grade: c.getData('id_grade'),
                        id_courseware: c.getData('id_courseware'),
                        id_group: c.getData('id_group'),
                        id_school: c.getData('id_school'),
                        type: c.getData('type'),
                        type_vip: c.getData('type_vip'),
                        id_user: c.getData('id_user'),
                    };
                    return null;
                }""")
            except Exception: pass
        if not dc:
            try:
                scripts = await page.evaluate("() => [...document.scripts].map(s=>s.textContent).join('\\n')")
                m = re.search(r'var\s+data_cate\s*=\s*(\{.*?\});', scripts, re.S)
                if m: dc = try_json(m.group(1))
            except Exception: pass
        return dc or {}

    async def _detect_exam_type(self, page) -> int:
        try:
            t = await page.evaluate("""() => {
                const c = window.CATE_UI, d = window.data_cate;
                if (c && c.getData) return parseInt(c.getData('type')) || 0;
                if (d && d.type) return parseInt(d.type) || 0;
                return 0;
            }""")
            return int(t or 0)
        except Exception: return 0

    async def fetch_questions(self, id_cate: str, force: bool = False) -> Tuple[List[dict], dict]:
        """Get answers — works regardless of done state. Cache enabled."""
        # Check cache first (key = id_cate)
        if not force and id_cate in self._qcache:
            cached = self._qcache[id_cate]
            ts = cached.get("ts", 0)
            if time.time() - ts < CACHE_TTL_SEC:
                return cached.get("questions", []), cached.get("data_cate", {})

        cleanup, page = await self._page()
        captured = {"body": None}
        data_cate: dict = {}
        try:
            async def on_resp(resp):
                try:
                    u = resp.url.lower()
                    if ("get-question-of-ids" in u or "get-crt-ans" in u) and not captured["body"]:
                        captured["body"] = await resp.text()
                except Exception: pass
            page.on("response", lambda r: asyncio.create_task(on_resp(r)))
            url_v1 = _url_v1(f"{OLM_BASE}/chu-de/{id_cate}")
            await self._goto(page, url_v1, timeout=60000, wait_cf=45)
            await asyncio.sleep(2)
            for _ in range(60):
                if captured["body"]: break
                await asyncio.sleep(0.5)
            data_cate = await self._extract_data_cate(page)
            exam_type = await self._detect_exam_type(page)
            if not data_cate:
                raise V1Required("V1_REQUIRED: Không tìm thấy window.data_cate.")
            if exam_type: data_cate["type"] = exam_type
            if not captured["body"]:
                try:
                    txt = await page.evaluate("""async (id) => {
                        try {
                            const r = await fetch(
                                '/course/teacher-categories/' + id + '/get-crt-ans-file?t=' + Date.now(),
                                {credentials: 'include',
                                 headers: {'X-Requested-With': 'XMLHttpRequest'}});
                            if (r.ok) return await r.text();
                        } catch(e) {}
                        return null;
                    }""", id_cate)
                    if txt: captured["body"] = txt
                except Exception: pass
        finally:
            try: await cleanup()
            except Exception: pass

        if not captured["body"]:
            try:
                r = await self.sess.request("GET",
                    f"/course/teacher-categories/{id_cate}"
                    f"/get-crt-ans-file?t={int(time.time()*1000)}",
                    headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code == 200 and r.text:
                    captured["body"] = r.text
            except Exception: pass

        if not captured["body"]:
            return [], data_cate

        body = captured["body"]
        data = try_json(body)
        if not data: data = try_json(b64x_decode(body))
        arr = None
        if isinstance(data, list): arr = data
        elif isinstance(data, dict):
            arr = (data.get("data") or data.get("result") or data.get("questions"))
        if not isinstance(arr, list): return [], data_cate
        qs = extract_questions(arr)
        dc = data_cate or {}
        title = (dc.get("title") or dc.get("name") or dc.get("title_cate") or "")
        if not title:
            try:
                title = await page.evaluate("""() => {
                    const h1 = document.querySelector('h1, .title, .page-title, [class*=title]');
                    if (h1 && h1.innerText) return h1.innerText.trim();
                    return (document.title || '').replace(/\\s*[-|].*$/, '').trim();
                }""")
            except Exception: pass
        if title: dc["_title"] = title
        exam_type = int(dc.get("type") or 3)
        dc["_exam_type"] = exam_type
        dc["_type_label"] = EXAM_TYPE_LABEL.get(exam_type, f"Loại {exam_type}")

        # Save cache
        self._qcache[id_cate] = {
            "ts": time.time(),
            "questions": qs,
            "data_cate": dc,
        }
        self._save_qcache()
        return qs, dc

    async def _submit_via_browser(self, page, id_cate, payload):
        try:
            # Block log=tab
            if payload.get("log") == "tab":
                return {"ok": True, "blocked": True, "reason": "log=tab blocked"}
            result = await page.evaluate("""async (args) => {
                const [idCate, payload] = args;
                try {
                    let csrf = '';
                    const cookies = document.cookie.split(';');
                    for (const c of cookies) {
                        const t = c.trim();
                        if (t.startsWith('XSRF-TOKEN=')) {
                            csrf = decodeURIComponent(t.substring(11)); break;
                        }
                    }
                    const params = new URLSearchParams();
                    for (const [k, v] of Object.entries(payload)) params.append(k, v);
                    const r = await fetch('/course/teacher-static', {
                        method: 'POST', credentials: 'include',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-CSRF-TOKEN': csrf,
                            'Accept': 'application/json, text/plain, */*',
                            'Referer': 'https://olm.vn/chu-de/' + idCate + '?v=v1',
                            'Origin': 'https://olm.vn'
                        },
                        body: params.toString()
                    });
                    const text = await r.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch(e) {}
                    return { status: r.status, body: text.slice(0, 400), json: json };
                } catch(e) { return { status: 0, error: String(e) }; }
            }""", [id_cate, payload])
            status = result.get("status", 0)
            j = result.get("json")
            ok = bool(j.get("ok") or j.get("success")) or status == 200 if isinstance(j, dict) else status == 200
            return {"ok": ok, "status": status,
                    "response": (j if isinstance(j, dict) else (result.get("body") or "")[:400]),
                    "method": "browser_evaluate"}
        except Exception as e:
            return {"ok": False, "error": f"browser submit lỗi: {e}"}

    async def _submit_via_dom_fill(self, page, id_cate, questions):
        """
        PORT 100% từ userscript autoAnswerAndFill:
        - Normalize text (lowercase + collapse whitespace).
        - Match 40 ký tự đầu của question_text với parent.innerText.
        - Fire CẢ 2 event 'input' + 'change' với bubbles=true.
        - Hỗ trợ multi_select (q13), fill pool (q3/11).
        """
        try:
            # Bước 1: Force re-run auto-fill đã inject
            try:
                rerun = await page.evaluate("""() => {
                    if (typeof window.__olm_autofill_run === 'function') {
                        try { window.__olm_autofill_run(); return { ok: true }; }
                        catch(e) { return { ok: false, error: String(e) }; }
                    }
                    return { ok: false, error: 'no_autofill_fn' };
                }""")
            except Exception:
                rerun = {"ok": False}

            await asyncio.sleep(1.5)

            # Bước 2: Explicit text-matching fill (khớp 100% userscript)
            js_questions = []
            for q in questions:
                label = _build_choose_label(q)
                qtext = (q.get("question_text") or q.get("text") or "")[:80]
                js_questions.append({
                    "id": str(q["id"]),
                    "text": qtext,
                    "choose_label": label,
                    "type": q.get("q_type"),
                })

            result = await page.evaluate("""(questions) => {
                const fireInput = (el) => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                };
                const normalize = (s) => String(s||'').toLowerCase().replace(/\\s+/g,' ').trim();
                const filled = { text: 0, radio: 0, checkbox: 0, errors: [] };

                // ─── 2.1: Text inputs (fill pool cho q3/11 cũng đi qua đây) ───
                document.querySelectorAll(
                    'input[type="text"], input[type="number"], textarea'
                ).forEach(input => {
                    if (input.value.trim() !== '') return;
                    const parent = input.closest(
                        '.question-item, .quiz-question, .cau-hoi, [data-question-id]'
                    );
                    if (!parent) return;
                    const pn = normalize(parent.innerText);
                    for (const q of questions) {
                        const qn = normalize(q.text);
                        if (qn && pn.includes(qn.substring(0, 40))) {
                            let v;
                            if (Array.isArray(q.choose_label)) {
                                // fill pool: gán tuần tự theo index input trong parent
                                const sib = Array.from(parent.querySelectorAll(
                                    'input[type="text"], input[type="number"], textarea'
                                ));
                                const idx = sib.indexOf(input);
                                v = q.choose_label[Math.max(0, idx)] !== undefined
                                    ? q.choose_label[Math.max(0, idx)]
                                    : q.choose_label[0];
                            } else {
                                v = q.choose_label;
                            }
                            input.value = String(v);
                            fireInput(input);
                            filled.text++;
                            break;
                        }
                    }
                });

                // ─── 2.2: Radio ───
                const rg = new Map();
                document.querySelectorAll('input[type="radio"]').forEach(r => {
                    const n = r.getAttribute('name');
                    if (n) rg.set(n, (rg.get(n) || []).concat(r));
                });
                rg.forEach((group, name) => {
                    const parent = group[0].closest('.question-item, .quiz-question, .cau-hoi');
                    if (!parent) return;
                    const pn = normalize(parent.innerText);
                    for (const q of questions) {
                        const qn = normalize(q.text);
                        if (qn && pn.includes(qn.substring(0, 40))) {
                            let label = q.choose_label;
                            let idx = 0;
                            if (typeof label === 'string' && /^[A-Z]$/.test(label)) {
                                idx = label.charCodeAt(0) - 65;
                            } else if (typeof label === 'number') {
                                idx = label;
                            } else if (Array.isArray(label)) {
                                idx = label[0];
                            }
                            if (group[idx] && !group[idx].checked) {
                                group[idx].checked = true;
                                fireInput(group[idx]);
                                filled.radio++;
                            }
                            break;
                        }
                    }
                });

                // ─── 2.3: Checkbox (hỗ trợ multi_select q13) ───
                const cg = new Map();
                document.querySelectorAll('input[type="checkbox"]').forEach(c => {
                    const n = c.getAttribute('name');
                    if (n) cg.set(n, (cg.get(n) || []).concat(c));
                });
                cg.forEach((group, name) => {
                    const parent = group[0].closest('.question-item, .quiz-question, .cau-hoi');
                    if (!parent) return;
                    const pn = normalize(parent.innerText);
                    for (const q of questions) {
                        const qn = normalize(q.text);
                        if (qn && pn.includes(qn.substring(0, 40))) {
                            const label = q.choose_label;
                            if (Array.isArray(label)) {
                                label.forEach(i => {
                                    if (group[i] && !group[i].checked) {
                                        group[i].checked = true;
                                        fireInput(group[i]);
                                    }
                                });
                            }
                            filled.checkbox++;
                            break;
                        }
                    }
                });

                return { ok: true, filled };
            }""", js_questions)

            await asyncio.sleep(1.5)

            # Bước 3: Trigger native submit
            native = await page.evaluate("""async (idCate) => {
                try {
                    const fns = ['submitQuiz', 'submit_exam', 'submitExercise', 'submitAnswer'];
                    for (const fn of fns) {
                        if (typeof window[fn] === 'function') {
                            try { await window[fn](); return { method: fn, ok: true }; }
                            catch(e) { return { method: fn, ok: false, error: String(e) }; }
                        }
                    }
                    const btns = document.querySelectorAll(
                        'button.submit, .btn-submit, #btn-submit, ' +
                        '[data-action="submit"], button[type="submit"]');
                    for (const btn of btns) {
                        if (/nộp|gửi|làm bài|submit/i.test(btn.innerText || '')) {
                            btn.click(); return { method: 'click', ok: true };
                        }
                    }
                    return { method: null, ok: false, error: 'no_submit_button' };
                } catch(e) { return { ok: false, error: String(e) }; }
            }""", id_cate)
            return {"ok": True, "fill": result, "rerun": rerun, "native": native,
                    "method": "dom_fill"}
        except Exception as e:
            return {"ok": False, "error": f"DOM fill lỗi: {e}"}

    async def submit(self, id_cate: str, mode: str, custom: float,
                     time_spent: int, force_redo: bool = False) -> dict:
        if not self.sess.has_auth():
            return {"ok": False, "error": "Chưa đăng nhập"}
        if not self.sess.user_id:
            return {"ok": False, "error": "user_id rỗng"}

        # Fetch câu hỏi TRƯỚC (cần cho cả delete và submit)
        questions, dc = await self.fetch_questions(id_cate, force=force_redo)
        if not questions:
            return {"ok": False, "error": "Không lấy được câu hỏi"}

        # XÓA BÀI CŨ TRƯỚC KHI SUBMIT
        delete_result = None
        try:
            delete_result = await self.delete_work(id_cate)
        except Exception as e:
            delete_result = {"ok": False, "error": str(e)}

        N = len(questions)
        try: custom = float(custom)
        except Exception: custom = 9.0
        if mode == "full": n_correct = N
        elif mode == "minus1": n_correct = max(0, N - 1)
        else:
            c = max(0.0, min(10.0, custom))
            n_correct = max(0, min(N, round(c / 10.0 * N)))
        n_wrong = N - n_correct
        score = round(n_correct * 10.0 / N, 2) if N else 0
        per_q_max = round(10.0 / N, 4)
        step_ms = max(1500, (int(time_spent) * 1000) // max(1, N))

        csrf = await self.sess.refresh_csrf(id_cate)
        if not csrf:
            return {"ok": False, "error": "Không refresh được CSRF"}

        now = int(time.time())
        data_log = _build_data_log(questions, n_correct, per_q_max)
        choose_log = _build_choose_log(questions, step_ms)
        ans_str, user_ans_str = _build_answer_strings(questions, n_correct)

        exam_type = int(dc.get("type") or dc.get("_exam_type") or 3)
        type_exam = str(exam_type)

        payload = {
            "id_user": str(self.sess.user_id or dc.get("id_user") or ""),
            "id_cate": str(dc.get("id_category") or id_cate),
            "id_grade": str(dc.get("id_grade") or "7"),
            "id_courseware": str(dc.get("id_courseware") or ""),
            "id_group": str(dc.get("id_group") or "0"),
            "id_school": str(dc.get("id_school") or "0"),
            "type_vip": str(dc.get("type_vip") or "0"),
            "time_spent": str(int(time_spent)),
            "total_time": str(int(time_spent)),
            "current_time": str(now),
            "tl_score": "0", "tn_score": str(score), "score": str(score),
            "max_score": "10", "correct": str(n_correct),
            "wrong": str(n_wrong), "count_problems": str(N), "totalq": str(N),
            "ended": "1", "missed": "0", "date_end": str(now),
            "type_exam": type_exam, "save_star": "1",
            "data_log": json.dumps(data_log, separators=(",", ":")),
            "time_init": str(now - int(time_spent)),
            "name_user": self.sess.username or "0",
            "times": "1", "time_stored": str(now),
            "choose_log": json.dumps(choose_log, separators=(",", ":")),
            "ans": ans_str,
            "user_ans": user_ans_str,
        }

        # BLOCK log=tab (payload check)
        if payload.get("log") == "tab":
            return {"ok": True, "blocked": True, "reason": "log=tab blocked"}

        referer_v1 = f"{OLM_BASE}/chu-de/{id_cate}{V1_SUFFIX}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf,
            "Accept": "application/json, text/plain, */*",
            "Referer": referer_v1, "Origin": OLM_BASE,
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        }

        # Attempt 1: HTTP post
        status_code = 0; body = ""; j = None
        try:
            r = await self.sess.request("POST", "/course/teacher-static",
                                        data=payload, headers=headers)
            status_code = r.status_code
            body = r.text or ""
            j = try_json(body)
        except Exception as e:
            body = f"POST exception: {e}"

        ok = bool((isinstance(j, dict) and (j.get("ok") or j.get("success"))) or status_code == 200)

        # Attempt 2: DOM-fill + native submit + browser_evaluate
        if not ok:
            try:
                cleanup, page = await self._page()
                try:
                    url_v1 = _url_v1(f"{OLM_BASE}/chu-de/{id_cate}")
                    await self._goto(page, url_v1, timeout=60000, wait_cf=45)
                    await asyncio.sleep(3)
                    dom_res = await self._submit_via_dom_fill(page, id_cate, questions)
                    try:
                        r2 = await self.sess.request("POST", "/course/teacher-static",
                                                      data=payload, headers=headers)
                        if r2.status_code == 200:
                            return {"ok": True, "status": r2.status_code,
                                    "response": try_json(r2.text or "") or (r2.text or "")[:400],
                                    "questions": N, "correct": n_correct,
                                    "wrong": n_wrong, "score": score,
                                    "type_exam": type_exam,
                                    "delete_before": delete_result,
                                    "dom_fill": dom_res.get("fill"),
                                    "method": "dom_fill+http"}
                    except Exception: pass
                    br_res = await self._submit_via_browser(page, id_cate, payload)
                    if br_res.get("ok"):
                        return {"ok": True, "status": br_res.get("status", 200),
                                "response": br_res.get("response"),
                                "questions": N, "correct": n_correct,
                                "wrong": n_wrong, "score": score,
                                "type_exam": type_exam,
                                "delete_before": delete_result,
                                "dom_fill": dom_res.get("fill"),
                                "method": "dom_fill+browser"}
                finally:
                    try: await cleanup()
                    except Exception: pass
            except Exception: pass

        return {"ok": ok, "status": status_code,
                "response": (j if isinstance(j, dict) else body[:400]),
                "questions": N, "correct": n_correct, "wrong": n_wrong,
                "score": score, "type_exam": type_exam,
                "delete_before": delete_result,
                "method": "http"}

    async def delete_work(self, id_cate: str) -> dict:
        sess = self.sess
        await sess.refresh_csrf(id_cate)
        csrf = sess.csrf()
        headers = {"X-Requested-With": "XMLHttpRequest"}
        if csrf: headers["X-CSRF-TOKEN"] = csrf
        endpoints = [
            ("DELETE", f"/course/teacher-static?id_cate={id_cate}&id_user={sess.user_id}", None),
            ("DELETE", f"/course/teacher-static?id_cate={id_cate}", None),
            ("POST", f"/course/teacher-categories/{id_cate}/delete-record", {}),
            ("POST", "/course/teacher-static/delete",
             {"id_cate": id_cate, "id_user": sess.user_id or ""}),
        ]
        last_err = "Không xóa được"
        for method, url, data in endpoints:
            try:
                r = await sess.request(method, url, headers=headers, data=data)
                if 200 <= r.status_code < 300:
                    return {"ok": True, "method": method, "url": url,
                            "status": r.status_code, "body": (r.text or "")[:200]}
                last_err = f"{method} {url} → {r.status_code}"
            except Exception as e:
                last_err = str(e); continue
        return {"ok": False, "error": last_err}

    async def download_word(self, id_cate: str) -> dict:
        """8 fallback chains — works regardless of done state."""
        try: await self.sess.refresh_csrf(id_cate)
        except Exception: pass
        csrf = self.sess.csrf()
        referer_v1 = f"{OLM_BASE}/chu-de/{id_cate}{V1_SUFFIX}"
        headers_post = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Referer": referer_v1, "Origin": OLM_BASE,
        }
        if csrf: headers_post["X-CSRF-TOKEN"] = csrf

        def _is_docx(b): return bool(b) and len(b) >= 2 and b[:2] == b"PK"
        def _looks_word(ct):
            ct = (ct or "").lower()
            return "word" in ct or "officedocument" in ct or "octet-stream" in ct

        async def _handle(r, mn):
            ct = (r.headers.get("content-type") or "").lower()
            if r.status_code != 200: return None
            if _looks_word(ct) and _is_docx(r.content):
                return {"ok": True, "content": r.content, "ctype": ct, "method": mn}
            j = try_json(r.text or "")
            if isinstance(j, dict):
                fu = j.get("file") or j.get("url") or j.get("link")
                if fu:
                    if fu.startswith("/"): fu = OLM_BASE + fu
                    try:
                        rr = await self.sess.request("GET", fu)
                        if rr.status_code == 200 and _is_docx(rr.content):
                            return {"ok": True, "content": rr.content,
                                    "ctype": rr.headers.get("content-type", ""),
                                    "method": mn + "_follow"}
                    except Exception: pass
            txt = (r.text or "").strip()
            if txt and len(txt) > 32:
                try:
                    if txt.startswith('"'): txt = json.loads(txt)
                except Exception: pass
                try:
                    dec = base64.b64decode(txt)
                    if _is_docx(dec):
                        return {"ok": True, "content": dec, "method": mn + "_b64",
                                "ctype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                except Exception: pass
            return None

        # Step 1-3: POST variants
        for body, mn in [
            ({"id_cate": id_cate, "showAns": "1", "questionNotAppproved": "0"}, "post_direct"),
            ({"id_cate": id_cate, "showAns": "1"}, "post_no_approved"),
            ({"id_cate": id_cate, "showAns": "1", "redo": "1"}, "post_redo"),
        ]:
            try:
                r = await self.sess.request("POST", "/download-word-for-user",
                                            data=body, headers=headers_post)
                got = await _handle(r, mn)
                if got: return got
            except Exception: pass

        # Step 4-6: GET variants
        for path, mn in [
            (f"/download-word-for-user?id_cate={id_cate}&showAns=1&questionNotAppproved=0", "get_query"),
            (f"/course/teacher-categories/{id_cate}/get-crt-ans-file?t={int(time.time()*1000)}", "get_crt_ans_file"),
            (f"/download-word-for-user?id_cate={id_cate}&showAns=1&redo=1", "get_redo"),
        ]:
            try:
                r = await self.sess.request("GET", path,
                    headers={"Accept": "*/*", "X-Requested-With": "XMLHttpRequest"})
                got = await _handle(r, mn)
                if got: return got
            except Exception: pass

        # Step 7: browser
        if HAS_PW:
            try:
                r = await self._word_via_browser(id_cate)
                if r.get("ok"): return r
            except CloudflareBlock:
                return {"ok": False, "cf": True, "error": "Cloudflare chặn."}
            except Exception: pass

        # Step 8: render internal fallback
        try:
            qs, dc = await self.fetch_questions(id_cate, force=True)
            if qs:
                title = (dc or {}).get("_title") or (dc or {}).get("title") \
                        or (dc or {}).get("name") or f"Bài {id_cate}"
                return {"ok": True, "content": _make_docx(id_cate, qs, title),
                        "ctype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "title": title, "generated": True, "method": "render_internal"}
        except Exception: pass

        if not _find_chromium_exe():
            return {"ok": False, "chromium_missing": True,
                    "error": "Không lấy được Word và chưa có Chromium."}
        return {"ok": False, "error": "Không lấy được Word qua mọi fallback"}

    async def _word_via_browser(self, id_cate: str) -> dict:
        cleanup, page = await self._page()
        try:
            url_v1 = _url_v1(f"{OLM_BASE}/chu-de/{id_cate}")
            await self._goto(page, url_v1, timeout=60000, wait_cf=45)
            await asyncio.sleep(2)
            try:
                r = await page.evaluate("""async (id) => {
                    const urls = [
                        '/download-word-for-user?id_cate=' + id + '&showAns=1&questionNotAppproved=0',
                        '/download-word-for-user?id_cate=' + id + '&showAns=1&redo=1'
                    ];
                    for (const url of urls) {
                        try {
                            const r = await fetch(url,
                                {credentials: 'include',
                                 headers: {'X-Requested-With': 'XMLHttpRequest'}});
                            if (r.status !== 200) continue;
                            const buf = await r.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            if (bytes[0] !== 0x50 || bytes[1] !== 0x4B) continue;
                            let bin = '';
                            const chunk = 8192;
                            for (let i = 0; i < bytes.length; i += chunk)
                                bin += String.fromCharCode.apply(
                                    null, bytes.subarray(i, i + chunk));
                            return {status: 200, b64: btoa(bin),
                                    ct: r.headers.get('content-type') || ''};
                        } catch(e) {}
                    }
                    return {status: 0};
                }""", id_cate)
                if r and r.get("status") == 200 and r.get("b64"):
                    content = base64.b64decode(r["b64"])
                    if content[:2] == b"PK":
                        return {"ok": True, "content": content,
                                "ctype": r.get("ct") or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "method": "browser_evaluate"}
            except Exception: pass
            return {"ok": False, "error": "Không tải được qua browser"}
        finally:
            try: await cleanup()
            except Exception: pass

# ═══════════════════════════════════════════════════════════════
# WORD GENERATOR — header/footer chuẩn userscript
# ═══════════════════════════════════════════════════════════════
def _make_docx(id_cate, questions, title=None) -> bytes:
    def esc(s):
        return (str(s or "").replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;"))
    header_title = title or f"Bài {id_cate}"
    def P(text, *, bold=False, italic=False, size=22,
          color=None, align=None, spacing_after=100):
        rpr = ['<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>',
               f'<w:sz w:val="{size}"/>']
        if bold: rpr.append('<w:b/>')
        if italic: rpr.append('<w:i/>')
        if color: rpr.append(f'<w:color w:val="{color}"/>')
        ppr = [f'<w:spacing w:after="{spacing_after}"/>']
        if align: ppr.append(f'<w:jc w:val="{align}"/>')
        return (f'<w:p><w:pPr>{"".join(ppr)}</w:pPr>'
                f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>'
                f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>')
    body = P(f"ĐÁP ÁN {header_title.upper()}", bold=True, size=32,
             color="1F4E79", align="center", spacing_after=200)
    body += P(f"Tổng: {len(questions)} câu", italic=True, size=20,
              color="666666", align="center", spacing_after=300)
    for i, q in enumerate(questions):
        qt = q.get("q_type")
        qtext = q.get("question_text") or q.get("text", "")
        opts = q.get("options") or []
        type_lbl = q.get("type_label", "")
        score = q.get("max_score", 1)
        # Header câu: Câu N [Type] (Xđ): text
        body += P(f"Câu {i+1} [{type_lbl}] ({score}đ): {qtext}",
                  bold=True, size=24, spacing_after=60)
        if qt == 13 and q.get("multi_select"):
            ca = q.get("correctAnswers") or []
            idxs = [k for k, v in enumerate(ca) if v == '1']
            for k, o in enumerate(opts):
                is_ok = k in idxs
                body += P(f"    {chr(65+k)}. {o}{'  ✓' if is_ok else ''}",
                          size=22, color="008000" if is_ok else "000000",
                          bold=is_ok, spacing_after=40)
            body += P("    → Đáp án (chọn nhiều): " + ", ".join(chr(65 + k) for k in idxs),
                      bold=True, size=22, color="008000", spacing_after=200)
        elif qt == 13:
            ca = q.get("correctAnswers") or []
            for k, o in enumerate(opts):
                val = ca[k] if k < len(ca) else "0"
                is_ok = val == "1"
                body += P(f"    {k+1}. {o}", size=22, spacing_after=30)
                body += P(f"        → {'Đúng' if val == '1' else 'Sai'}",
                          size=20, color="008000" if is_ok else "C00000",
                          italic=True, spacing_after=60)
            ans_tf = ", ".join(["Đ" if (k < len(ca) and ca[k] == '1') else "S"
                                for k in range(len(opts))])
            body += P(f"    → Đáp án: {ans_tf}", bold=True, size=22,
                      color="008000", spacing_after=200)
        elif qt in (2, 3, 11):
            vals = q.get("correctAnswers") or ([q.get("correctAnswer")] if q.get("correctAnswer") else [])
            for k, o in enumerate(opts):
                body += P(f"    {chr(65+k)}. {o}", size=22, spacing_after=40)
            if vals:
                body += P(f"    → Đáp án: {', '.join(map(str, vals))}",
                          bold=True, size=22, color="008000", spacing_after=200)
        elif qt == 5:
            body += P("    → Sắp xếp theo đúng thứ tự 1, 2, 3, ...", size=22,
                      color="008000", spacing_after=200)
        elif qt == 6:
            body += P("    → Nối cặp tương ứng theo thứ tự", size=22,
                      color="008000", spacing_after=200)
        elif qt == 9:
            ul = q.get("correctAnswers") or []
            body += P(f"    → Gạch chân: {', '.join(map(str, ul))}", size=22,
                      color="008000", spacing_after=200)
        elif qt == 10:
            body += P(f"    → Nhóm: {q.get('answerIndices') or []}", size=22,
                      color="008000", spacing_after=200)
        elif qt in (21, 22):
            for k, sa in enumerate(q.get("sub_answers") or []):
                body += P(f"    Phần {k+1}: {sa}", size=22, spacing_after=60)
        else:
            labels = set()
            if q.get("correctLabel"): labels.add(q["correctLabel"])
            for v in (q.get("correctAnswers") or []):
                if isinstance(v, str) and re.match(r'^[A-Z]$', v): labels.add(v)
            for k, o in enumerate(opts):
                lb = chr(65+k); is_ok = lb in labels
                body += P(f"    {lb}. {o}{'  ✓' if is_ok else ''}", size=22,
                          color="008000" if is_ok else "000000",
                          bold=is_ok, spacing_after=40)
            if labels:
                body += P(f"    → Đáp án: {', '.join(sorted(labels))}",
                          bold=True, size=22, color="008000", spacing_after=200)
        if q.get("explanation"):
            body += P(f"    💡 {q['explanation']}", italic=True, size=20,
                      color="666666", spacing_after=100)
        body += P("", size=20, spacing_after=200)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body></w:document>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document_xml)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════
# ANSWERS HTML
# ═══════════════════════════════════════════════════════════════
def answers_html(id_skill, questions) -> str:
    def esc(s):
        return (str(s or "").replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;"))
    rows = []
    for i, q in enumerate(questions):
        t = q.get("type_label", "")
        text = esc(q.get("question_text") or q.get("text", ""))
        opts = q.get("options") or []
        expl = esc(q.get("explanation") or "")
        correct_label = q.get("correctLabel")
        correct_index = None
        if correct_label:
            try: correct_index = ord(correct_label) - 65
            except Exception: pass
        if not opts:
            ta = q.get("text_all") or []
            opts = [x for x in ta if x and x.strip()][:8]
        opt_html = ""
        if opts:
            items = []
            for k, o in enumerate(opts):
                lb = chr(65 + k)
                cls = "correct" if correct_label == lb else ""
                if q.get("multi_select") and q.get("correctAnswers"):
                    ca = q["correctAnswers"]
                    if k < len(ca) and ca[k] == '1': cls = "correct"
                items.append(f'<div class="opt {cls}">'
                             f'<span class="olb">{lb}.</span>'
                             f'<span class="otx">{esc(o)}</span></div>')
            opt_html = f'<div class="opts">{"".join(items)}</div>'
        ans_line = ""
        if q.get("multi_select") and q.get("correctAnswers"):
            ca = q["correctAnswers"]
            labels = [chr(65 + k) for k, v in enumerate(ca) if v == '1']
            ans_line = (f'<div class="ansbox"><span class="anslbl">'
                        f'Đáp án (chọn nhiều):</span> '
                        f'<b class="anslabel">{", ".join(labels)}</b></div>')
        elif q.get("q_type") == 13:
            tfs = q.get("correctAnswers") or []
            tf_html = "<br>".join(
                [f"Mệnh đề {k+1}: <b>{'Đúng' if v == '1' else 'Sai'}</b>"
                 for k, v in enumerate(tfs)])
            ans_line = (f'<div class="ansbox"><span class="anslbl">Đáp án:</span>'
                        f'<div>{tf_html}</div></div>')
        elif q.get("q_type") in (21, 22) and q.get("sub_answers"):
            parts = []
            for k, sa in enumerate(q["sub_answers"]):
                st = ((q.get("sub_types") or [1])[k] if k < len(q.get("sub_types") or []) else 1)
                if st == 13:
                    txt = ", ".join(["Đúng" if v == "1" else "Sai" for v in sa])
                elif isinstance(sa, list):
                    txt = ", ".join(map(str, sa))
                else: txt = str(sa)
                parts.append(f'<div class="sub-item"><b>Phần {k+1}:</b> '
                             f'<span>{esc(txt)}</span></div>')
            ans_line = (f'<div class="ansbox sub-ans">'
                        f'<span class="anslbl">Đáp án chi tiết:</span>'
                        f'{"".join(parts)}</div>')
        elif q.get("q_type") == 20 and q.get("correctAnswers"):
            ca = q["correctAnswers"]
            parts = [f'<div class="sub-item">{k+1}. {esc(v)}</div>'
                     for k, v in enumerate(ca)]
            ans_line = (f'<div class="ansbox sub-ans">'
                        f'<span class="anslbl">Đáp án (thứ tự):</span>'
                        f'{"".join(parts)}</div>')
        elif q.get("q_type") == 6:
            ans_line = ('<div class="ansbox"><span class="anslbl">Đáp án:</span> '
                        'Nối theo thứ tự A-1, B-2, C-3, ...</div>')
        elif q.get("q_type") == 5:
            ans_line = ('<div class="ansbox"><span class="anslbl">Đáp án:</span> '
                        'Sắp xếp theo thứ tự 1, 2, 3, ...</div>')
        elif q.get("q_type") == 9 and q.get("correctAnswers"):
            ans_line = (f'<div class="ansbox"><span class="anslbl">Đáp án:</span> '
                        f'Gạch chân vị trí {", ".join(map(str, q["correctAnswers"]))}</div>')
        elif correct_label:
            extra = ""
            if correct_index is not None and 0 <= correct_index < len(opts):
                c = opts[correct_index]
                if c and c.strip(): extra = f' — {esc(c)}'
            ans_line = (f'<div class="ansbox">'
                        f'<span class="anslbl">Đáp án đúng:</span> '
                        f'<b class="anslabel">{correct_label}</b>{extra}</div>')
        elif q.get("correctAnswer"):
            ans_line = (f'<div class="ansbox"><span class="anslbl">Đáp án:</span> '
                        f'<b>{esc(q["correctAnswer"])}</b></div>')
        elif q.get("correctAnswers"):
            ans_line = (f'<div class="ansbox"><span class="anslbl">Đáp án:</span> '
                        f'<b>{esc(", ".join(map(str, q["correctAnswers"])))}</b></div>')
        exp_html = ""
        if expl:
            exp_html = (f'<div class="exp">'
                        f'<span class="explbl">💡 Hướng dẫn:</span>'
                        f'<div class="exptx">{expl}</div></div>')
        rows.append(
            f'<div class="qitem"><div class="qhead">'
            f'<span class="qnum">Câu {i+1}</span>'
            f'<span class="qtype">{esc(t)}</span>'
            f'<span class="qscore">{q.get("max_score", 1)}đ</span></div>'
            f'<div class="qtext">{text}</div>'
            f'{opt_html}{ans_line}{exp_html}</div>')
    return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<title>Đáp án bài {id_skill}</title>
<script>window.MathJax={{tex:{{inlineMath:[['$','$']]}},svg:{{fontCache:'global'}}}};</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js" async></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:transparent;color:#e8eaed;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;padding:20px 26px;line-height:1.55}}
h1{{font-size:15px;margin-bottom:16px;font-weight:700;background:linear-gradient(135deg,#ff3366,#7c3aed 50%,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.qitem{{background:linear-gradient(135deg,rgba(20,24,29,.9),rgba(20,24,29,.6));border:1px solid #1e232c;border-radius:12px;padding:16px 18px;margin-bottom:14px;border-left:3px solid #7c3aed}}
.qhead{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:10px;flex-wrap:wrap}}
.qnum{{color:#ff3366;border:1px solid rgba(255,51,102,.3);padding:3px 10px;border-radius:6px;font-size:11px;font-weight:700}}
.qtype{{font-size:11px;color:#5a6371;border:1px solid #1e232c;padding:2px 8px;border-radius:5px}}
.qscore{{font-size:11px;color:#a78bfa;border:1px solid rgba(124,58,237,.3);padding:2px 8px;border-radius:5px}}
.qtext{{color:#e8eaed;margin-bottom:12px;font-size:13.5px}}
.opts{{display:flex;flex-direction:column;gap:6px;margin-bottom:12px}}
.opt{{padding:8px 12px;border-radius:8px;background:rgba(7,8,11,.6);border:1px solid #1e232c;display:flex;gap:10px;font-size:13px}}
.opt.correct{{background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.35);color:#6ee7b7}}
.olb{{font-weight:600;min-width:22px;color:#5a6371}}
.opt.correct .olb{{color:#10b981}}
.otx{{flex:1;color:#98a1b0}}
.opt.correct .otx{{color:#d1fae5}}
.ansbox{{background:rgba(16,185,129,.1);border-left:3px solid #10b981;padding:10px 14px;border-radius:6px;margin-top:10px;font-size:13px}}
.ansbox.sub-ans{{display:flex;flex-direction:column;gap:6px}}
.sub-item{{padding:6px 10px;background:rgba(0,0,0,.3);border-left:2px solid #10b981;border-radius:4px;font-family:'SF Mono',Consolas,monospace;font-size:12.5px}}
.anslbl{{color:#10b981;font-weight:700;margin-right:6px}}
.anslabel{{background:#10b981;color:#0b0d10;padding:2px 10px;border-radius:5px;font-weight:700}}
.exp{{background:linear-gradient(135deg,rgba(255,51,102,.08),rgba(124,58,237,.08));border-left:3px solid #ff3366;padding:10px 14px;border-radius:6px;margin-top:10px}}
.explbl{{color:#ff3366;font-weight:700;display:block;margin-bottom:4px;font-size:12px}}
.exptx{{color:#98a1b0;font-size:12.5px}}
</style></head><body>
<h1>Đáp án — Bài {id_skill} · {len(questions)} câu</h1>
{"".join(rows)}</body></html>"""

# ═══════════════════════════════════════════════════════════════
# OLM APP (BRIDGE)
# ═══════════════════════════════════════════════════════════════
class OLMApp:
    def __init__(self):
        self.sess = OLMSession.load()
        self.cdp = CDPManager()
        self.client = OLMClient(self.sess, self.cdp)
        self.lic = LicenseManager()
        self.telemetry = {"hook_hits": 0, "qtype_dist": {}, "dom_fill_log": []}

    def lic_hwid(self): return self.lic.get_hwid()

    def lic_status(self):
        try:
            r = self.lic.validate(); r["hwid"] = self.lic.get_hwid(); return r
        except Exception as e:
            return {"ok": False, "error": str(e), "hwid": self.lic.get_hwid(),
                    "reason": "Lỗi kiểm tra license"}

    def lic_activate(self, key):
        try: return self.lic.activate(key)
        except Exception as e: return {"ok": False, "error": str(e)}

    def lic_deactivate(self):
        try: return self.lic.deactivate()
        except Exception as e: return {"ok": False, "error": str(e)}

    def copy_to_clipboard(self, text):
        text = str(text or "")
        try:
            import tkinter
            r = tkinter.Tk(); r.withdraw()
            r.clipboard_clear(); r.clipboard_append(text)
            r.update(); r.destroy()
            return {"ok": True, "method": "tkinter"}
        except Exception: pass
        try:
            if sys.platform == "win32":
                p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                p.communicate(text.encode("utf-16le"))
                return {"ok": True, "method": "clip"}
            elif sys.platform == "darwin":
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
                return {"ok": True, "method": "pbcopy"}
            else:
                p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
                return {"ok": True, "method": "xclip"}
        except Exception as e: return {"ok": False, "error": str(e)}

    def chromium_status(self):
        try: return check_chromium()
        except Exception as e: return {"ok": False, "error": str(e)}

    def chromium_install(self):
        try: return install_chromium()
        except Exception as e: return {"ok": False, "error": str(e)}

    def chrome_open(self):
        try: return _launch_chrome()
        except Exception as e: return {"ok": False, "error": str(e)}

    def chrome_grab_cookies(self):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            grabber = ChromeCookieGrabber(self.cdp)
            r = run_async(grabber.grab(), timeout=120)
            if not r.get("ok"): return r
            self.sess.set_cookie_dict(r["cookies"]); self.sess.save()
            self.client = OLMClient(self.sess, self.cdp)
            return {"ok": True, "user_id": self.sess.user_id,
                    "username": self.sess.username, "count": len(r["cookies"])}
        except Exception as e: return {"ok": False, "error": str(e)}

    def set_cookies(self, ck):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            self.sess.set_cookies(ck)
            if not self.sess.has_auth():
                return {"ok": False, "error": "Cookie thiếu session/user"}
            self.sess.save()
            self.client = OLMClient(self.sess, self.cdp)
            return {"ok": True, "user_id": self.sess.user_id, "username": self.sess.username}
        except Exception as e: return {"ok": False, "error": str(e)}

    def get_status(self):
        try:
            if not self.sess.has_auth(): return {"ok": False}
            return {"ok": True, "user_id": self.sess.user_id, "username": self.sess.username}
        except Exception as e: return {"ok": False, "error": str(e)}

    def logout(self):
        try:
            self.sess.clear()
            self.sess = OLMSession()
            self.client = OLMClient(self.sess, self.cdp)
            return {"ok": True}
        except Exception as e: return {"ok": False, "error": str(e)}

    def _handle_err(self, e: Exception) -> dict:
        if isinstance(e, CloudflareBlock) or "CF_BLOCK" in str(e):
            return {"ok": False, "cf": True,
                    "error": "Cloudflare chặn. Bấm '🌐 Chrome' để giải."}
        if isinstance(e, ChromiumMissing) or "CHROMIUM_MISSING" in str(e):
            return {"ok": False, "chromium_missing": True,
                    "error": "Chưa có Chromium. Bấm 'Cài Chromium' để tải."}
        if isinstance(e, V1Required) or "V1_REQUIRED" in str(e):
            return {"ok": False, "v1_required": True,
                    "error": "Giao diện v2 — cần ?v=v1. Thử lại."}
        return {"ok": False, "error": str(e)}

    def scan(self):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            items = run_async(self.client.scan_assignments(), timeout=240)
            return {"ok": True, "count": len(items), "items": items}
        except Exception as e: return self._handle_err(e)

    def add_manual(self, input_value):
        try:
            cid = extract_id_from_input(input_value)
            if not cid: return {"ok": False, "error": "Không nhận diện được ID/link."}
            title = f"Bài {cid}"; type_label = ""; exam_type = 0
            try:
                if self.lic.validate().get("ok") and self.sess.has_auth():
                    qs, dc = run_async(self.client.fetch_questions(cid), timeout=60)
                    dc = dc or {}
                    t = (dc.get("_title") or dc.get("title") or dc.get("name"))
                    if t: title = t
                    type_label = dc.get("_type_label") or ""
                    exam_type = int(dc.get("type") or 0)
            except Exception: pass
            return {"ok": True, "count": 1,
                    "items": [{"id": cid, "title": title, "href": "",
                               "type_label": type_label, "type": exam_type,
                               "done": False}]}
        except Exception as e: return {"ok": False, "error": str(e)}

    def get_questions(self, id_skill):
        try:
            qs, dc = run_async(self.client.fetch_questions(id_skill), timeout=180)
            dc = dc or {}; qs = qs or []
            tc = {}
            for q in qs:
                k = q.get("type_label") or f"Type {q.get('q_type')}"
                tc[k] = tc.get(k, 0) + 1
            self.telemetry["qtype_dist"] = tc
            return {"ok": True, "questions": qs, "count": len(qs),
                    "title": (dc.get("_title") or dc.get("title") or dc.get("name") or ""),
                    "type_label": dc.get("_type_label") or "",
                    "type": int(dc.get("type") or 0),
                    "type_counts": tc}
        except Exception as e: return self._handle_err(e)

    def get_answers_html(self, id_skill):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            qs, dc = run_async(self.client.fetch_questions(id_skill), timeout=180)
            if not qs: return {"ok": False, "error": "Không lấy được câu hỏi"}
            html = answers_html(id_skill, qs)
            return {"ok": True, "html": html, "questions": len(qs),
                    "title": (dc or {}).get("_title") or "",
                    "type_label": (dc or {}).get("_type_label") or "",
                    "json": json.dumps(qs, ensure_ascii=False, indent=2)}
        except Exception as e: return self._handle_err(e)

    def submit(self, id_skill, mode="minus1", custom=9.0, time_spent=300, force_redo=False):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            r = run_async(
                self.client.submit(id_skill, mode, float(custom),
                                    int(time_spent), bool(force_redo)),
                timeout=600)
            # Telemetry: log dom fill result
            if isinstance(r, dict) and r.get("dom_fill"):
                self.telemetry["dom_fill_log"].append(r["dom_fill"])
                if len(self.telemetry["dom_fill_log"]) > 100:
                    self.telemetry["dom_fill_log"] = self.telemetry["dom_fill_log"][-50:]
            return r
        except Exception as e: return self._handle_err(e)

    def delete_work(self, id_cate):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            return run_async(self.client.delete_work(id_cate), timeout=120)
        except Exception as e: return self._handle_err(e)

    def download_word(self, id_cate):
        try:
            if not self.lic.validate().get("ok"):
                return {"ok": False, "error": "License không hợp lệ"}
            r = run_async(self.client.download_word(id_cate), timeout=180)
            if not r.get("ok"): return r
            title = r.get("title") or ""
            type_label = ""
            try:
                qs, dc = run_async(self.client.fetch_questions(id_cate), timeout=120)
                dc = dc or {}
                if not title:
                    title = (dc.get("_title") or dc.get("title") or dc.get("name") or "")
                type_label = dc.get("_type_label") or ""
            except Exception: pass
            title = title or f"Bài {id_cate}"
            base = f"Đáp án {title}"
            if type_label: base += f" [{type_label}]"
            safe = re.sub(r'[<>:"/\\|?*\n\r\t]+', ' ', base).strip()[:120] or f"Đáp án Bài {id_cate}"
            fname = f"{safe}.docx"
            out = DOWNLOAD_DIR / fname
            n = 1
            while out.exists():
                out = DOWNLOAD_DIR / f"{safe} ({n}).docx"; n += 1
            content = r["content"]
            out.write_bytes(content)
            return {"ok": True, "path": str(out), "filename": out.name,
                    "size": len(content), "method": r.get("method", ""),
                    "generated": bool(r.get("generated")),
                    "title": title, "type_label": type_label}
        except Exception as e: return self._handle_err(e)

    def open_path(self, path):
        try:
            if sys.platform == "win32": os.startfile(path)
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e: return {"ok": False, "error": str(e)}

    def get_telemetry(self):
        return {"ok": True, "data": self.telemetry}

# ═══════════════════════════════════════════════════════════════
# UI HTML — NATIVE APP EDITION v19.1
# ═══════════════════════════════════════════════════════════════
INDEX_HTML = r"""<!DOCTYPE html><html lang="vi"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no,maximum-scale=1">
<title>OLM Tool Pro v1.0.0</title>
<style>
:root{
  --bg:#050609;--bg2:#0a0c11;--bg3:#0f1116;
  --panel:#0d1017;--panel2:#131822;--panel3:#1a2029;--panel4:#222a36;
  --bd:#1a1f2a;--bd2:#252c3a;--bd3:#333c4e;
  --tx:#eef2f8;--tx2:#9aa5b8;--dim:#5d6878;--mute:#3d4653;
  --p1:#ff3d6e;--p2:#8b5cf6;--p3:#06b6d4;--p4:#fbbf24;
  --ok:#10b981;--ok2:#34d399;--warn:#f59e0b;--err:#ef4444;--err2:#f87171;
  --grad:linear-gradient(135deg,#ff3d6e 0%,#8b5cf6 100%);
  --grad3:linear-gradient(120deg,#ff3d6e 0%,#8b5cf6 50%,#06b6d4 100%);
  --grad-soft:linear-gradient(135deg,rgba(255,61,110,.13),rgba(139,92,246,.13));
  --shadow1:0 2px 8px rgba(0,0,0,.3);
  --shadow2:0 8px 24px rgba(0,0,0,.5);
  --shadow3:0 20px 60px rgba(0,0,0,.7);
  --glow1:0 8px 30px rgba(255,61,110,.25);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{
  height:100%;width:100%;background:var(--bg);color:var(--tx);
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;
  font-size:14px;overflow:hidden;
  user-select:none;-webkit-user-select:none;-moz-user-select:none;-ms-user-select:none;
  -webkit-touch-callout:none;
  touch-action:manipulation;
  -ms-content-zooming:none;
  -ms-touch-action:manipulation;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
  font-feature-settings:'cv11','ss01';
  position:fixed;inset:0;
}
html{ -webkit-text-size-adjust:100%; text-size-adjust:100%; }
body{ -webkit-text-size-adjust:none; text-size-adjust:none; }

body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(800px circle at 5% 2%,rgba(255,61,110,.13),transparent 45%),
    radial-gradient(900px circle at 95% 98%,rgba(139,92,246,.13),transparent 48%),
    radial-gradient(600px circle at 50% 50%,rgba(6,182,212,.04),transparent 60%);}
input,textarea,button,select{font-family:inherit}
input,textarea{-webkit-user-select:text;user-select:text;-webkit-user-modify:read-write}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:6px;border:2px solid var(--bg)}
::-webkit-scrollbar-thumb:hover{background:var(--bd3)}

#app{position:relative;z-index:1;display:flex;flex-direction:column;height:100vh;width:100vw;overflow:hidden}

.topbar{
  display:flex;align-items:center;gap:14px;padding:10px 20px;
  background:rgba(10,12,17,.85);backdrop-filter:blur(24px);
  border-bottom:1px solid var(--bd);z-index:20;
  min-height:58px;max-height:58px;
  -webkit-app-region:drag;flex-shrink:0;
}
.brand{display:flex;align-items:center;gap:11px;font-weight:700;font-size:14px;flex-shrink:0}
.brand-icon{
  width:34px;height:34px;border-radius:10px;background:var(--grad);
  display:grid;place-items:center;color:#fff;font-size:17px;
  box-shadow:var(--glow1);flex-shrink:0;
  animation:brandGlow 4s ease-in-out infinite;
}
@keyframes brandGlow{
  0%,100%{box-shadow:0 8px 30px rgba(255,61,110,.28)}
  50%{box-shadow:0 8px 30px rgba(139,92,246,.28)}
}
.brand-name{
  background:var(--grad3);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text;
  background-size:200% 200%;animation:gradFlow 7s ease infinite;
  white-space:nowrap;letter-spacing:-.02em;
}
@keyframes gradFlow{
  0%,100%{background-position:0% 50%}
  50%{background-position:100% 50%}
}
.brand-ver{
  font-size:9.5px;color:var(--dim);font-weight:600;
  padding:3px 7px;border:1px solid var(--bd);border-radius:5px;
  font-family:'SF Mono',Consolas,monospace;letter-spacing:.4px;
  background:var(--panel);flex-shrink:0;
}
.spacer{flex:1;min-width:0}
.topbar-actions{display:flex;gap:6px;align-items:center;flex-wrap:nowrap;-webkit-app-region:no-drag;flex-shrink:0}

.chip{
  display:flex;align-items:center;gap:7px;padding:6px 11px;
  background:var(--panel);border:1px solid var(--bd);border-radius:9px;
  font-size:11.5px;color:var(--tx2);font-weight:500;
  transition:all .18s ease;white-space:nowrap;
}
.chip:hover{border-color:var(--bd2);background:var(--panel2)}
.chip .dot{
  width:7px;height:7px;border-radius:50%;background:var(--err);
  flex-shrink:0;transition:all .3s ease;
}
.chip .dot.on{background:var(--ok);
  box-shadow:0 0 0 4px rgba(16,185,129,.16);animation:dotPulse 2s infinite}
@keyframes dotPulse{
  0%,100%{box-shadow:0 0 0 4px rgba(16,185,129,.16)}
  50%{box-shadow:0 0 0 9px rgba(16,185,129,.04)}
}

.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:6px;
  padding:8px 13px;border-radius:9px;border:1px solid var(--bd2);
  background:var(--panel);color:var(--tx);font-size:12.5px;font-weight:500;
  cursor:pointer;transition:all .18s cubic-bezier(.4,0,.2,1);
  white-space:nowrap;outline:none;letter-spacing:.01em;
}
.btn:hover:not(:disabled){
  background:var(--panel3);border-color:var(--bd3);
  transform:translateY(-1px);box-shadow:var(--shadow1);
}
.btn:active:not(:disabled){transform:translateY(0);box-shadow:none}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important}
.btn-primary{background:var(--grad);border-color:transparent;color:#fff;font-weight:600;box-shadow:var(--glow1)}
.btn-primary:hover:not(:disabled){box-shadow:0 12px 36px rgba(255,61,110,.42)}
.btn-danger{background:linear-gradient(135deg,#7f1d1d,#b91c1c);border-color:transparent;color:#fff;font-weight:600}
.btn-success{background:linear-gradient(135deg,#065f46,#059669);border-color:transparent;color:#fff;font-weight:600}
.btn-warning{background:linear-gradient(135deg,#78350f,#d97706);border-color:transparent;color:#fff;font-weight:600}
.btn-ghost{background:transparent;border-style:dashed;color:var(--tx2)}
.btn-ghost:hover:not(:disabled){background:var(--panel);color:var(--tx)}
.btn-sm{padding:6px 11px;font-size:11.5px;border-radius:8px;gap:5px}
.btn-xs{padding:4px 8px;font-size:10.5px;border-radius:6px;gap:4px}
.btn-lg{padding:13px 24px;font-size:13.5px;border-radius:11px}

.login-wrap{
  flex:1;display:flex;align-items:center;justify-content:center;
  padding:20px;overflow:hidden;position:relative;
}
.blob{position:absolute;width:520px;height:520px;border-radius:50%;
  filter:blur(120px);opacity:.35;pointer-events:none;z-index:0;
  animation:blobFloat 22s ease-in-out infinite}
.blob.b1{background:radial-gradient(circle,#ff3d6e,transparent 70%);top:-18%;left:-10%}
.blob.b2{background:radial-gradient(circle,#8b5cf6,transparent 70%);bottom:-18%;right:-10%;animation-delay:-8s}
@keyframes blobFloat{
  0%,100%{transform:translate(0,0) scale(1)}
  33%{transform:translate(40px,-50px) scale(1.1)}
  66%{transform:translate(-40px,50px) scale(.92)}
}
.login-card{
  position:relative;z-index:1;width:100%;max-width:600px;
  max-height:calc(100vh - 120px);
  background:rgba(13,16,23,.9);backdrop-filter:blur(28px);
  border:1px solid var(--bd);border-radius:22px;padding:32px;
  box-shadow:var(--shadow3),inset 0 1px 0 rgba(255,255,255,.04);
  overflow:hidden;
}
.login-card::before{
  content:'';position:absolute;inset:0;border-radius:22px;padding:1px;
  background:linear-gradient(135deg,
    rgba(255,61,110,.5),transparent 35%,transparent 65%,rgba(139,92,246,.5));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;
}
.login-card h1{
  font-size:24px;font-weight:700;margin-bottom:8px;
  background:var(--grad3);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text;
  background-size:200% 200%;animation:gradFlow 7s ease infinite;
  letter-spacing:-.02em;
}
.login-card .sub{color:var(--tx2);font-size:13px;margin-bottom:20px;line-height:1.6}
.steps{display:flex;flex-direction:column;gap:8px;margin-bottom:18px}
.step{
  display:flex;gap:12px;padding:11px 14px;
  background:rgba(5,6,9,.55);border:1px solid var(--bd);border-radius:11px;
  transition:all .22s cubic-bezier(.4,0,.2,1);
}
.step:hover{border-color:var(--bd2);background:var(--panel2);transform:translateX(4px)}
.step-num{
  width:24px;height:24px;border-radius:7px;background:var(--grad-soft);
  border:1px solid rgba(255,61,110,.32);color:var(--p1);
  font-size:11px;font-weight:700;display:grid;place-items:center;
  flex-shrink:0;font-family:'SF Mono',Consolas,monospace;
}
.step-text{flex:1;line-height:1.5;color:var(--tx2);font-size:12.5px}
.step-text b{color:var(--tx);font-weight:600}
.field{margin-bottom:14px}
.field label{display:block;color:var(--tx2);font-size:10.5px;font-weight:700;
  margin-bottom:6px;letter-spacing:.6px;text-transform:uppercase}
.field textarea{
  width:100%;background:rgba(5,6,9,.78);
  border:1px solid var(--bd2);color:var(--tx);font-size:12px;
  padding:11px 13px;border-radius:10px;outline:none;transition:all .2s ease;
  min-height:70px;resize:none;
  font-family:'SF Mono',Consolas,monospace;line-height:1.5;
}
.field textarea:focus{border-color:var(--p1);background:rgba(5,6,9,.92);
  box-shadow:0 0 0 3px rgba(255,61,110,.13)}

.msg{
  padding:11px 15px;border-radius:11px;font-size:12.5px;line-height:1.55;
  display:flex;gap:10px;align-items:flex-start;border:1px solid var(--bd);
  margin-top:12px;animation:msgIn .25s cubic-bezier(.4,0,.2,1);
}
@keyframes msgIn{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:translateY(0)}}
.msg::before{font-weight:700;flex-shrink:0;font-size:14px;line-height:1.2}
.msg.ok{background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.3);color:#6ee7b7}
.msg.ok::before{content:'✓';color:var(--ok)}
.msg.err{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.3);color:#fca5a5}
.msg.err::before{content:'⚠';color:var(--err)}
.msg.warn{background:rgba(245,158,11,.08);border-color:rgba(245,158,11,.3);color:#fcd34d}
.msg.warn::before{content:'◐';color:var(--warn)}
.msg.info{background:rgba(6,182,212,.06);border-color:rgba(6,182,212,.25);color:#7dd3fc}
.msg.info::before{content:'ℹ';color:var(--p3)}

.lic-info{background:rgba(5,6,9,.5);border:1px solid var(--bd);border-radius:13px;padding:14px;margin-bottom:14px}
.lic-info-row{
  display:flex;justify-content:space-between;align-items:center;
  padding:7px 0;font-size:12px;gap:10px;
  border-bottom:1px dashed rgba(255,255,255,.05);
}
.lic-info-row:last-child{border-bottom:none}
.lic-info-row .lbl{color:var(--dim);font-weight:600;flex-shrink:0;font-size:11px}
.lic-info-row .val{color:var(--tx);font-family:'SF Mono',Consolas,monospace;
  font-size:11px;word-break:break-all;text-align:right;flex:1}

.content{flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.config-bar{
  display:flex;gap:12px;align-items:center;padding:12px 20px;
  background:rgba(10,12,17,.55);backdrop-filter:blur(20px);
  border-bottom:1px solid var(--bd);flex-wrap:wrap;min-height:56px;
  flex-shrink:0;
}
.config-bar label{
  display:flex;align-items:center;gap:7px;
  color:var(--tx2);font-size:12px;font-weight:500;
}
.config-bar select,.config-bar input{
  background:var(--panel);border:1px solid var(--bd2);
  border-radius:8px;color:var(--tx);font-size:12px;
  padding:7px 11px;outline:none;transition:all .15s ease;font-weight:500;
}
.config-bar select:focus,.config-bar input:focus{
  border-color:var(--p1);box-shadow:0 0 0 3px rgba(255,61,110,.13);
}
.config-bar input[type=number]{width:72px}

.main{flex:1;display:grid;grid-template-columns:1fr 380px;overflow:hidden;min-height:0}
@media(max-width:1100px){.main{grid-template-columns:1fr}}

.list-panel{overflow-y:auto;padding:16px 20px}
.empty-state{
  padding:60px 20px;text-align:center;color:var(--dim);
  border:2px dashed var(--bd);border-radius:18px;
  background:rgba(13,16,23,.32);
}
.empty-state .icon{font-size:56px;margin-bottom:14px;opacity:.32;
  animation:emptyFloat 3.2s ease-in-out infinite}
@keyframes emptyFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.empty-state p{margin-bottom:16px;font-size:13.5px;line-height:1.6}

.card{
  background:linear-gradient(135deg,rgba(13,16,23,.94),rgba(13,16,23,.68));
  border:1px solid var(--bd);border-radius:14px;padding:14px 16px;
  margin-bottom:10px;position:relative;overflow:hidden;
  transition:all .22s cubic-bezier(.4,0,.2,1);
}
.card::before{
  content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
  background:var(--grad);opacity:.65;transition:opacity .22s;
}
.card:hover{border-color:var(--bd2);transform:translateY(-2px);box-shadow:var(--shadow2)}
.card:hover::before{opacity:1}
.card.done{opacity:.85}
.card.done::before{background:var(--ok);opacity:1}
.card.fail::before{background:var(--err);opacity:1}
.card.working::before{background:var(--p3);opacity:1;animation:barGlow 1.4s ease-in-out infinite}
@keyframes barGlow{50%{opacity:.3}}

.card-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:9px}
.card-idx{
  display:inline-grid;place-items:center;width:26px;height:26px;
  border-radius:8px;background:var(--grad-soft);
  border:1px solid rgba(255,61,110,.28);color:var(--p1);
  font-size:11.5px;font-weight:700;flex-shrink:0;
  font-family:'SF Mono',Consolas,monospace;
}
.card-title{
  flex:1;font-weight:600;color:var(--tx);
  overflow:hidden;text-overflow:ellipsis;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  min-width:0;font-size:13.5px;line-height:1.35;white-space:normal;
  cursor:default;
}
.card-id{
  font-family:'SF Mono',Consolas,monospace;font-size:10.5px;
  color:var(--dim);background:var(--bg2);
  padding:3px 9px;border-radius:6px;border:1px solid var(--bd);
}
.type-badge{
  display:inline-block;padding:2px 7px;margin:2px 3px 2px 0;
  background:rgba(139,92,246,.12);color:#a78bfa;
  border:1px solid rgba(139,92,246,.25);border-radius:5px;
  font-size:10px;font-weight:600;font-family:'SF Mono',Consolas,monospace;
}
.badge-done{
  display:inline-block;padding:2px 8px;margin:2px 3px 2px 0;
  background:rgba(16,185,129,.15);color:#34d399;
  border:1px solid rgba(16,185,129,.35);border-radius:5px;
  font-size:10px;font-weight:700;font-family:'SF Mono',Consolas,monospace;
}
.card-types{
  font-size:10.5px;color:var(--tx2);margin-bottom:11px;
  font-family:'SF Mono',Consolas,monospace;line-height:1.5;word-break:break-word;
}
.card-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.card-actions .num-input{
  width:58px;background:var(--bg2);border:1px solid var(--bd2);
  border-radius:7px;color:var(--tx);font-size:11px;
  padding:6px 8px;outline:none;text-align:center;
  font-family:'SF Mono',Consolas,monospace;font-weight:500;
}
.card-actions .num-input:focus{border-color:var(--p1);box-shadow:0 0 0 3px rgba(255,61,110,.1)}
.card-actions label{color:var(--dim);font-size:10.5px;font-weight:600}
.card-status{
  font-size:11px;margin-top:10px;padding-top:9px;
  border-top:1px dashed var(--bd);color:var(--dim);
  min-height:16px;font-family:'SF Mono',Consolas,monospace;
  line-height:1.5;word-break:break-word;
}
.card-status.ok{color:var(--ok)}
.card-status.err{color:var(--err)}
.card-status.warn{color:var(--warn)}
.card-status.working{color:var(--p3);animation:sPulse 1.5s infinite}
@keyframes sPulse{50%{opacity:.55}}

.log-panel{
  display:flex;flex-direction:column;
  background:rgba(10,12,17,.55);backdrop-filter:blur(20px);
  overflow:hidden;min-height:0;border-left:1px solid var(--bd);
}
.log-header{
  padding:13px 16px;border-bottom:1px solid var(--bd);
  display:flex;align-items:center;gap:9px;font-size:10.5px;
  font-weight:700;color:var(--tx2);letter-spacing:.8px;text-transform:uppercase;
}
.log-header .dot{width:7px;height:7px;border-radius:50%;background:var(--p1);
  animation:pulse 2s ease-in-out infinite}
@keyframes pulse{
  0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(255,61,110,.4)}
  50%{opacity:.7;box-shadow:0 0 0 6px rgba(255,61,110,0)}
}
.log-header .clear{
  margin-left:auto;background:transparent;border:none;
  color:var(--dim);cursor:pointer;font-size:10px;
  padding:4px 9px;border-radius:5px;font-weight:700;
  letter-spacing:.5px;transition:all .15s ease;
}
.log-header .clear:hover{background:var(--panel);color:var(--tx)}
.log-body{
  flex:1;overflow-y:auto;padding:11px 15px;
  font-family:'SF Mono',Consolas,monospace;font-size:10.5px;line-height:1.65;
}
.log-line{
  padding:3px 0;color:var(--tx2);
  border-bottom:1px solid rgba(255,255,255,.025);
  word-break:break-word;display:flex;gap:8px;
}
.log-line .ts{color:var(--dim);flex-shrink:0}
.log-line .msg{flex:1}
.log-line.ok .msg{color:var(--ok2)}
.log-line.err .msg{color:var(--err2)}
.log-line.warn .msg{color:var(--warn)}
.log-line.work .msg{color:var(--p3)}
.progress-bar{height:3px;background:var(--bg2);position:relative;
  overflow:hidden;flex-shrink:0;border-bottom:1px solid var(--bd)}
.progress-fill{position:absolute;left:0;top:0;bottom:0;width:0;
  background:var(--grad);transition:width .3s ease;
  box-shadow:0 0 12px rgba(255,61,110,.6)}

.modal{
  position:fixed;inset:0;background:rgba(2,3,5,.85);
  display:none;align-items:center;justify-content:center;
  z-index:1000;backdrop-filter:blur(14px);animation:fadeIn .22s ease;
}
.modal.show{display:flex}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modal-box{
  background:rgba(13,16,23,.97);border:1px solid var(--bd);
  border-radius:16px;padding:24px;max-width:480px;width:92%;
  box-shadow:var(--shadow3);animation:slideUp .28s cubic-bezier(.4,0,.2,1);
}
@keyframes slideUp{from{transform:translateY(28px);opacity:0}to{transform:translateY(0);opacity:1}}
.modal-box h3{font-size:16.5px;margin-bottom:10px;color:var(--tx);
  font-weight:700;display:flex;align-items:center;gap:8px}
.modal-box p{color:var(--tx2);font-size:12.5px;margin-bottom:16px;line-height:1.6}
.modal-input{
  width:100%;background:rgba(5,6,9,.82);
  border:1px solid var(--bd2);border-radius:10px;color:var(--tx);
  font-family:'SF Mono',Consolas,monospace;font-size:12.5px;
  padding:11px 13px;outline:none;margin-bottom:14px;
  transition:all .2s ease;
}
.modal-input:focus{border-color:var(--p1);box-shadow:0 0 0 3px rgba(255,61,110,.13)}
.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:6px;flex-wrap:wrap}

.answers-modal{
  position:fixed;inset:0;background:rgba(2,3,5,.97);
  display:none;flex-direction:column;z-index:1100;
  backdrop-filter:blur(18px);animation:fadeIn .22s ease;
}
.answers-modal.show{display:flex}
.answers-modal-head{
  display:flex;align-items:center;gap:12px;
  padding:14px 22px;background:rgba(10,12,17,.94);
  border-bottom:1px solid var(--bd);flex-shrink:0;flex-wrap:wrap;
}
.answers-modal-head .title{
  font-size:14.5px;font-weight:700;
  background:var(--grad3);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text;
  background-size:200% 200%;animation:gradFlow 7s ease infinite;
}
.answers-modal-head .sub{
  color:var(--dim);font-size:11px;
  font-family:'SF Mono',Consolas,monospace;
  padding:4px 10px;background:var(--bg2);
  border:1px solid var(--bd);border-radius:6px;
}
.answers-modal-body{flex:1;overflow-y:auto;padding:0;min-height:0}
.answers-modal-body iframe{width:100%;height:100%;border:none;
  background:transparent;display:block}

.toast-wrap{
  position:fixed;bottom:20px;right:20px;display:flex;
  flex-direction:column;gap:9px;z-index:1200;pointer-events:none;max-width:380px;
}
.toast{
  background:rgba(13,16,23,.97);backdrop-filter:blur(18px);
  border:1px solid var(--bd);border-radius:11px;
  padding:12px 15px;font-size:12.5px;min-width:230px;
  box-shadow:0 20px 55px rgba(0,0,0,.6);
  animation:toastIn .32s cubic-bezier(.4,0,.2,1);
  pointer-events:auto;display:flex;gap:10px;align-items:flex-start;line-height:1.45;
}
.toast::before{content:'';width:3px;border-radius:2px;flex-shrink:0;align-self:stretch}
.toast.ok::before{background:var(--ok)}
.toast.err::before{background:var(--err)}
.toast.warn::before{background:var(--warn)}
.toast.info::before{background:var(--grad)}
@keyframes toastIn{from{transform:translateX(120%);opacity:0}to{transform:translateX(0);opacity:1}}

.spin{display:inline-block;width:13px;height:13px;
  border:2px solid rgba(255,255,255,.18);
  border-top-color:#fff;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.overlay{
  position:fixed;inset:0;background:rgba(2,3,5,.85);
  display:none;align-items:center;justify-content:center;
  z-index:2000;backdrop-filter:blur(10px);
  flex-direction:column;gap:16px;
}
.overlay.show{display:flex;animation:fadeIn .22s}
.overlay .spinner-lg{
  width:48px;height:48px;
  border:4px solid rgba(255,61,110,.18);
  border-top-color:var(--p1);border-radius:50%;animation:spin 1s linear infinite;
}
.overlay .msg{color:var(--tx);font-size:13.5px;font-weight:500;
  text-align:center;max-width:80%;border:none;background:none;margin:0;padding:0}
.overlay .msg::before{display:none}

.hidden{display:none!important}
</style></head><body>

<div id="app">
  <div class="topbar">
    <div class="brand">
      <div class="brand-icon">◆</div>
      <span class="brand-name">OLM Tool Pro</span>
      <span class="brand-ver">v1.0.0 by Crayz</span>
    </div>
    <div class="spacer"></div>
    <div class="topbar-actions">
      <div class="chip" id="licChip" style="display:none">
        <span class="dot on"></span>
        <span id="licChipText">License</span>
      </div>
      <div class="chip">
        <span class="dot" id="statusDot"></span>
        <span id="statusText">Chưa kết nối</span>
      </div>
      <button class="btn btn-ghost btn-sm hidden" id="btnInstallChromium">📦 Chromium</button>
      <button class="btn btn-ghost btn-sm hidden" id="btnOpenChrome">🌐 Chrome</button>
      <button class="btn btn-ghost btn-sm hidden" id="btnReGrab">🍪 Cookies</button>
      <button class="btn btn-ghost btn-sm" id="btnLicense">🔑</button>
      <button class="btn btn-ghost btn-sm hidden" id="btnLogout">⏻</button>
    </div>
  </div>

  <div class="login-wrap" id="loginView">
    <div class="blob b1"></div><div class="blob b2"></div>
    <div class="login-card">
      <h1 id="loginTitle">Chào mừng</h1>
      <p class="sub" id="loginSub">Dán cookies OLM hoặc lấy trực tiếp từ Chrome để bắt đầu.</p>
      <div id="licenseBlock" class="hidden"><div class="lic-info" id="licInfo"></div></div>
      <div class="steps" id="stepsBlock">
        <div class="step"><div class="step-num">1</div><div class="step-text">Bấm <b>🌐 Lấy từ Chrome</b> — tool tự mở Chrome.</div></div>
        <div class="step"><div class="step-num">2</div><div class="step-text">Login <b>olm.vn</b> trong cửa sổ Chrome, đợi trang load.</div></div>
        <div class="step"><div class="step-num">3</div><div class="step-text">Bấm <b>📥 Lấy cookies</b> — tool tự lưu session.</div></div>
      </div>
      <div class="field">
        <label>Hoặc dán cookies thủ công</label>
        <textarea id="ck" placeholder="onlinemath_session=...; user=...; XSRF-TOKEN=..."></textarea>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary btn-lg" id="btnChrome" style="flex:2;min-width:200px">🌐 Lấy từ Chrome</button>
        <button class="btn btn-lg" id="btnCookie" style="flex:1;min-width:130px">🔗 Kết nối</button>
      </div>
      <div id="chromeHelp" class="hidden"></div>
      <div id="loginMsg"></div>
    </div>
  </div>

  <div class="content hidden" id="dashView">
    <div class="config-bar">
      <label>Chế độ:
        <select id="modeSel">
          <option value="minus1">Sai 1 câu (9/10)</option>
          <option value="full">Full điểm (10/10)</option>
          <option value="custom">Custom điểm</option>
        </select>
      </label>
      <label id="customWrap" class="hidden">Điểm:
        <input type="number" id="customScore" min="0" max="10" step="0.1" value="9">
      </label>
      <label>Giây:
        <input type="number" id="timeSpent" min="10" step="10" value="300">
      </label>
      <button class="btn btn-ghost btn-sm" id="btnScan">🔍 Quét</button>
      <button class="btn btn-ghost btn-sm" id="btnAddId">+ Bài</button>
      <div class="spacer"></div>
      <button class="btn btn-primary btn-sm" id="btnAllSubmit">⚡ Làm tất cả</button>
      <button class="btn btn-danger btn-sm" id="btnAllDelete">🗑 Xóa tất cả</button>
    </div>
    <div class="main">
      <div class="list-panel" id="listPanel">
        <div class="empty-state">
          <div class="icon">📚</div>
          <p>Chưa có bài nào.<br>Bấm <b>Quét</b> để tải danh sách bài GV giao.</p>
        </div>
      </div>
      <div class="log-panel">
        <div class="log-header">
          <span class="dot"></span><span>Log</span>
          <button class="clear" id="btnClearLog">XÓA</button>
        </div>
        <div class="progress-bar hidden" id="bulkProgress">
          <div class="progress-fill" id="bulkFill"></div>
        </div>
        <div class="log-body" id="logBody"></div>
      </div>
    </div>
  </div>
</div>

<div class="modal" id="addIdModal">
  <div class="modal-box">
    <h3>➕ Thêm bài</h3>
    <p>Dán <b>ID</b> hoặc <b>link OLM</b>.</p>
    <input class="modal-input" id="addIdInput" placeholder="1234567 hoặc link olm.vn/chu-de/..." autofocus>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="addIdCancel">Hủy</button>
      <button class="btn btn-primary" id="addIdOk">Thêm</button>
    </div>
  </div>
</div>

<div class="modal" id="licModal">
  <div class="modal-box" style="max-width:520px">
    <h3>🔑 License</h3>
    <div id="licModalBody"></div>
  </div>
</div>

<div class="answers-modal" id="answersModal">
  <div class="answers-modal-head">
    <span class="title" id="ansTitle">Đáp án</span>
    <span class="sub" id="ansSub"></span>
    <div class="spacer"></div>
    <button class="btn btn-ghost btn-sm" id="btnCopyAns">📋 Copy JSON</button>
    <button class="btn btn-primary btn-sm" id="btnCloseAns">✖ Đóng</button>
  </div>
  <div class="answers-modal-body">
    <iframe id="ansFrame" sandbox="allow-scripts"></iframe>
  </div>
</div>

<div class="overlay" id="overlay">
  <div class="spinner-lg"></div>
  <div class="msg" id="overlayMsg">Đang xử lý...</div>
</div>

<div class="toast-wrap" id="toastWrap"></div>

<script>
document.addEventListener('wheel', e => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && (e.key === '+' || e.key === '-' || e.key === '=' || e.key === '0')) {
    e.preventDefault();
  }
});
document.addEventListener('gesturestart', e => e.preventDefault());
document.addEventListener('gesturechange', e => e.preventDefault());
document.addEventListener('gestureend', e => e.preventDefault());
let __lastTouchEnd = 0;
document.addEventListener('touchend', e => {
  const now = Date.now();
  if (now - __lastTouchEnd <= 300) e.preventDefault();
  __lastTouchEnd = now;
}, false);

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const api = () => window.pywebview.api;

let ASSIGN = [];
let BULK_RUNNING = false;
let ansJSONCache = "";
const MODE = { m: 'minus1', c: 9, t: 300 };

function esc(s){
  return String(s||'').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]);
}
function toast(msg, kind='info', duration=3500){
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = `<span style="flex:1">${esc(msg)}</span>`;
  $('#toastWrap').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'all .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(120%)';
    setTimeout(() => el.remove(), 320);
  }, duration);
}
function log(msg, kind='info'){
  const body = $('#logBody');
  if (!body) return;
  const t = new Date().toLocaleTimeString('vi-VN');
  const line = document.createElement('div');
  line.className = 'log-line ' + kind;
  line.innerHTML = `<span class="ts">${t}</span><span class="msg">${esc(msg)}</span>`;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}
function setStatus(ok, text){
  const d = $('#statusDot');
  d.className = 'dot' + (ok ? ' on' : '');
  $('#statusText').textContent = text || (ok ? 'Đã kết nối' : 'Chưa kết nối');
}
function loginMsg(html, kind='info'){
  $('#loginMsg').innerHTML = html ? `<div class="msg ${kind}">${html}</div>` : '';
}
function setStat(id, txt, kind){
  const el = document.querySelector(`[data-stat="${id}"]`);
  if (el) { el.textContent = txt; el.className = 'card-status ' + (kind||''); }
}
function setCardState(id, state){
  const c = document.querySelector(`[data-card="${id}"]`);
  if (!c) return;
  c.classList.remove('done','fail','working');
  if (state) c.classList.add(state);
}
function formatLeft(sec){
  sec = Math.max(0, sec|0);
  const d = Math.floor(sec/86400);
  const h = Math.floor((sec%86400)/3600);
  const m = Math.floor((sec%3600)/60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
function showOverlay(msg){ $('#overlayMsg').textContent = msg || 'Đang xử lý...'; $('#overlay').classList.add('show'); }
function hideOverlay(){ $('#overlay').classList.remove('show'); }
function updateLicChip(info){
  const chip = $('#licChip');
  const txt = $('#licChipText');
  chip.style.display = '';
  const dot = chip.querySelector('.dot');
  if (!info || !info.ok){ dot.className = 'dot'; txt.textContent = 'Chưa kích hoạt'; return; }
  dot.className = 'dot on';
  txt.textContent = `${formatLeft(info.seconds_left||0)} · ${info.key_type||'?'}`;
}

async function copyTextRobust(text){
  if (!text) return false;
  try { const r = await api().copy_to_clipboard(text); if (r && r.ok) return true; } catch(e){}
  try {
    if (navigator.clipboard && navigator.clipboard.writeText){
      await navigator.clipboard.writeText(text); return true;
    }
  } catch(e){}
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly','');
    ta.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0;';
    document.body.appendChild(ta);
    ta.focus(); ta.select(); ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch(e){}
  return false;
}

function resetUI(){
  ASSIGN = []; BULK_RUNNING = false; ansJSONCache = '';
  $('#answersModal').classList.remove('show');
  $('#licModal').classList.remove('show');
  $('#addIdModal').classList.remove('show');
  hideOverlay();
  $('#dashView').classList.add('hidden');
  $('#loginView').style.display = 'flex';
  $('#loginView').classList.remove('hidden');
  $('#btnLogout').classList.add('hidden');
  $('#btnReGrab').classList.add('hidden');
  $('#btnOpenChrome').classList.add('hidden');
  $('#btnInstallChromium').classList.add('hidden');
  $('#licChip').style.display = 'none';
  setStatus(false, 'Chưa kết nối');
  $('#ck').value = '';
  $('#loginMsg').innerHTML = '';
  $('#chromeHelp').classList.add('hidden');
  $('#chromeHelp').innerHTML = '';
  $('#loginTitle').textContent = 'Chào mừng';
  $('#loginSub').textContent = 'Dán cookies OLM hoặc lấy trực tiếp từ Chrome để bắt đầu.';
  $('#licenseBlock').classList.add('hidden');
  $('#stepsBlock').classList.remove('hidden');
  $('#btnCookie').disabled = false;
  $('#btnChrome').disabled = false;
  bootstrap();
}

async function bootstrap(){
  try {
    const lic = await api().lic_status();
    if (!lic.ok){ showLicenseRequired(lic); checkChromiumAndUpdateUI(); return; }
    updateLicChip(lic);
    $('#licenseBlock').classList.remove('hidden');
    renderLicInfo(lic);
    const me = await api().get_status();
    if (me.ok){ onLoggedIn({ user_id: me.user_id, username: me.username });
      checkChromiumAndUpdateUI(); return; }
    loginMsg(`License OK — còn <b>${formatLeft(lic.seconds_left)}</b>.<br>` +
             `Bấm <b>🌐 Lấy từ Chrome</b> để bắt đầu.`, 'ok');
    checkChromiumAndUpdateUI();
  } catch(e){
    loginMsg('Lỗi khởi tạo: ' + esc(e.message||String(e)), 'err');
  }
}

async function checkChromiumAndUpdateUI(){
  try {
    const r = await api().chromium_status();
    if (r.ok && !r.installed) $('#btnInstallChromium').classList.remove('hidden');
  } catch(e){}
}

function renderLicInfo(lic){
  $('#licInfo').innerHTML = `
    <div class="lic-info-row"><span class="lbl">Loại key</span>
      <span class="val">${esc(lic.key_type||'-')} (${lic.duration_days||'?'} ngày)</span></div>
    <div class="lic-info-row"><span class="lbl">Key</span>
      <span class="val">${esc(lic.key||'-')}</span></div>
    <div class="lic-info-row"><span class="lbl">Còn lại</span>
      <span class="val" style="color:var(--p1)">${formatLeft(lic.seconds_left||0)}</span></div>
    <div class="lic-info-row"><span class="lbl">HWID</span>
      <span class="val">${esc(lic.hwid||'-')}</span></div>
  `;
}

function showLicenseRequired(lic){
  $('#stepsBlock').classList.add('hidden');
  $('#licenseBlock').classList.add('hidden');
  $('#loginTitle').textContent = 'Cần kích hoạt License';
  $('#loginSub').textContent = 'Nhập key để sử dụng tool.';
  loginMsg(
    `HWID máy: <code style="color:var(--p1)">${esc(lic.hwid||'?')}</code><br>` +
    `${esc(lic.reason||lic.error||'')}`, 'warn');
  $('#btnCookie').disabled = true;
  $('#btnChrome').disabled = true;
  setTimeout(openLicenseModal, 500);
}

function onLoggedIn(info){
  setStatus(true, `UID #${info.user_id}`);
  $('#btnLogout').classList.remove('hidden');
  $('#btnReGrab').classList.remove('hidden');
  $('#btnOpenChrome').classList.remove('hidden');
  $('#loginView').style.display = 'none';
  $('#dashView').classList.remove('hidden');
  log(`Đăng nhập OLM OK — UID ${info.user_id} (${info.username||''})`, 'ok');
  scanAssignments();
}

async function openLicenseModal(){
  const st = await api().lic_status();
  const hwid = await api().lic_hwid();
  let body = '';
  if (st.ok){
    body = `
      <div class="lic-info">
        <div class="lic-info-row"><span class="lbl">Trạng thái</span>
          <span class="val" style="color:var(--ok)">● Đang hoạt động</span></div>
        <div class="lic-info-row"><span class="lbl">Key</span>
          <span class="val">${esc(st.key||'-')}</span></div>
        <div class="lic-info-row"><span class="lbl">Loại</span>
          <span class="val">${esc(st.key_type||'-')} (${st.duration_days||'?'} ngày)</span></div>
        <div class="lic-info-row"><span class="lbl">Còn lại</span>
          <span class="val" style="color:var(--p1)">${formatLeft(st.seconds_left||0)}</span></div>
        <div class="lic-info-row"><span class="lbl">HWID</span>
          <span class="val">${esc(hwid)}</span></div>
      </div>
      <p style="color:var(--dim);font-size:12px">Hủy key sẽ giải phóng máy, key chết vĩnh viễn.</p>
      <div class="modal-actions">
        <button class="btn btn-ghost" onclick="closeLicModal()">Đóng</button>
        <button class="btn btn-danger" onclick="doDeactivate()">🔓 Hủy key</button>
      </div>`;
  } else {
    body = `
      <p>Nhập key để kích hoạt. Key sẽ <b>khóa vĩnh viễn</b> với máy này.</p>
      <div class="lic-info">
        <div class="lic-info-row"><span class="lbl">HWID máy bạn</span>
          <span class="val">${esc(hwid)}</span></div>
      </div>
      <input class="modal-input" id="licKeyInput"
        placeholder="OLM-XXXX-XXXX-XXXX" autofocus>
      <div id="licModalMsg"></div>
      <div class="modal-actions" style="margin-top:16px">
        <button class="btn btn-ghost" onclick="closeLicModal()">Đóng</button>
        <button class="btn btn-primary" onclick="doActivate()">🔑 Kích hoạt</button>
      </div>`;
  }
  $('#licModalBody').innerHTML = body;
  $('#licModal').classList.add('show');
  setTimeout(() => { const i = $('#licKeyInput'); if (i) i.focus(); }, 80);
}
window.openLicenseModal = openLicenseModal;
function closeLicModal(){ $('#licModal').classList.remove('show'); }
window.closeLicModal = closeLicModal;

async function doActivate(){
  const key = ($('#licKeyInput').value || '').trim();
  const msg = $('#licModalMsg');
  if (!key){ msg.innerHTML = '<div class="msg err">Nhập key</div>'; return; }
  msg.innerHTML = '<div class="msg info"><span class="spin"></span> Đang kích hoạt…</div>';
  const r = await api().lic_activate(key);
  if (r.ok){
    msg.innerHTML = `<div class="msg ok">Kích hoạt thành công! Hết hạn sau ${r.days||1} ngày.</div>`;
    setTimeout(() => { closeLicModal(); resetUI(); }, 1200);
  } else msg.innerHTML = `<div class="msg err">${esc(r.error||'Lỗi')}</div>`;
}
window.doActivate = doActivate;

async function doDeactivate(){
  if (!confirm('Hủy key? Sau khi hủy, key sẽ hết hiệu lực VĨNH VIỄN.')) return;
  closeLicModal();
  const r = await api().lic_deactivate();
  if (r.ok){ toast('Đã hủy key thành công', 'ok'); setTimeout(() => resetUI(), 400); }
  else toast(r.error || 'Lỗi hủy', 'err');
}
window.doDeactivate = doDeactivate;
$('#btnLicense').onclick = openLicenseModal;

$('#btnInstallChromium').onclick = async () => {
  if (!confirm('Tải Chromium (~150MB)? Quá trình mất 2-5 phút.')) return;
  $('#btnInstallChromium').disabled = true;
  showOverlay('Đang tải Chromium…');
  try {
    const r = await api().chromium_install();
    hideOverlay();
    if (r.ok){
      toast('Đã cài Chromium thành công!', 'ok', 4000);
      $('#btnInstallChromium').classList.add('hidden');
    } else toast('Lỗi cài Chromium: ' + (r.error||''), 'err', 6000);
  } catch(e){ hideOverlay(); toast('Lỗi: ' + (e.message||e), 'err'); }
  finally { $('#btnInstallChromium').disabled = false; }
};

$('#btnChrome').onclick = async () => {
  const help = $('#chromeHelp');
  help.classList.remove('hidden');
  $('#btnChrome').disabled = true;
  const renderWait = (extra='') => {
    help.innerHTML =
      `<div class="msg info" style="margin-top:10px">
        <div>
          <b>Chrome đang mở.</b> Login OLM, đợi load xong rồi bấm <b>Lấy cookies</b>.${extra}
          <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-primary btn-sm" id="btnDoGrab">📥 Lấy cookies</button>
            <button class="btn btn-ghost btn-sm" id="btnCancelGrab">Hủy</button>
          </div>
        </div>
      </div>`;
    $('#btnDoGrab').onclick = doGrab;
    $('#btnCancelGrab').onclick = () => {
      help.classList.add('hidden'); help.innerHTML = '';
      $('#btnChrome').disabled = false;
    };
  };
  const doGrab = async () => {
    help.innerHTML = `<div class="msg info"><span class="spin"></span> Đang đọc cookies…</div>`;
    const r = await api().chrome_grab_cookies();
    if (r.ok){
      help.innerHTML =
        `<div class="msg ok">
          ✓ Đã lấy <b>${r.count}</b> cookies. User: <b>${esc(r.username||'')}</b>
        </div>`;
      setTimeout(() => {
        help.classList.add('hidden');
        onLoggedIn({ user_id: r.user_id, username: r.username });
      }, 900);
    } else if (r.waiting_login){
      renderWait('<br><b style="color:var(--warn)">⚠ Chrome chưa login OLM.</b>');
    } else {
      help.innerHTML =
        `<div class="msg err">✖ ${esc(r.error||'Lỗi')}
          <div style="margin-top:10px">
            <button class="btn btn-primary btn-sm" id="btnRetryGrab">Thử lại</button>
          </div>
        </div>`;
      $('#btnRetryGrab').onclick = doGrab;
    }
  };
  try {
    help.innerHTML = `<div class="msg info" style="margin-top:10px"><span class="spin"></span> Đang mở Chrome…</div>`;
    const open = await api().chrome_open();
    if (!open.ok && !open.already){
      help.innerHTML = `<div class="msg err">✖ ${esc(open.error||'Không mở được')}</div>`;
      $('#btnChrome').disabled = false;
      return;
    }
    renderWait();
  } catch(e){ help.innerHTML = `<div class="msg err">✖ ${esc(e.message||String(e))}</div>`; }
  finally { $('#btnChrome').disabled = false; }
};

$('#btnReGrab').onclick = async () => {
  if (!confirm('Lấy cookies mới từ Chrome?')) return;
  const r = await api().chrome_open();
  if (!r.ok && !r.already){ toast(r.error || 'Không mở được Chrome', 'err'); return; }
  toast('Login OLM, rồi bấm lại nút Cookies.', 'info', 6000);
  $('#btnReGrab').onclick = async () => {
    const g = await api().chrome_grab_cookies();
    if (g.ok){
      toast(`Đã cập nhật cookies (${g.count}).`, 'ok');
      setTimeout(() => {
        resetUI();
        setTimeout(() => onLoggedIn({ user_id: g.user_id, username: g.username }), 100);
      }, 800);
    } else if (g.waiting_login) toast('Chưa login OLM.', 'warn', 5000);
    else toast(g.error || 'Lỗi', 'err');
  };
};

$('#btnOpenChrome').onclick = async () => {
  const r = await api().chrome_open();
  if (r.ok || r.already) toast('Chrome đã mở.', 'ok', 5000);
  else toast(r.error || 'Không mở được Chrome', 'err');
};

$('#btnCookie').onclick = async () => {
  const ck = $('#ck').value.trim();
  if (!ck){ loginMsg('Chưa nhập cookies', 'warn'); return; }
  loginMsg('<span class="spin"></span> Đang xác thực…', 'info');
  $('#btnCookie').disabled = true;
  try {
    const r = await api().set_cookies(ck);
    if (r.ok){
      loginMsg('Kết nối thành công!', 'ok');
      const me = await api().get_status();
      setTimeout(() => onLoggedIn({ user_id: me.user_id, username: me.username }), 300);
    } else loginMsg(esc(r.error||'Không kết nối được'), 'err');
  } catch(e){ loginMsg('Lỗi: ' + esc(e.message||String(e)), 'err'); }
  finally { $('#btnCookie').disabled = false; }
};

$('#btnLogout').onclick = async () => {
  if (!confirm('Đăng xuất khỏi OLM (giữ license)?')) return;
  try {
    await api().logout();
    toast('Đã đăng xuất', 'ok');
    setTimeout(() => resetUI(), 400);
  } catch(e){ toast('Lỗi: ' + (e.message||e), 'err'); }
};

$('#modeSel').onchange = e => {
  MODE.m = e.target.value;
  if (MODE.m === 'custom') $('#customWrap').classList.remove('hidden');
  else $('#customWrap').classList.add('hidden');
  renderList();
};
$('#customScore').oninput = e => MODE.c = Math.max(0, Math.min(10, parseFloat(e.target.value)||0));
$('#timeSpent').oninput = e => {
  MODE.t = Math.max(10, parseInt(e.target.value)||300);
  $$('input[data-time]').forEach(el => el.value = MODE.t);
};

async function scanAssignments(){
  log('Quét bài GV giao…', 'work');
  $('#listPanel').innerHTML = '<div class="empty-state"><div class="icon">⏳</div><p>Đang quét…</p></div>';
  try {
    const r = await api().scan();
    if (!r.ok){
      if (r.cf){
        log('Cloudflare chặn.', 'warn');
        $('#listPanel').innerHTML =
          `<div class="empty-state"><div class="icon">🛡️</div>
            <p>Cloudflare đang chặn.<br>Bấm <b>🌐 Chrome</b> để giải CF.</p>
            <button class="btn btn-ghost" onclick="scanAssignments()">Thử lại</button>
          </div>`;
        return;
      }
      if (r.chromium_missing){
        $('#btnInstallChromium').classList.remove('hidden');
        $('#listPanel').innerHTML =
          `<div class="empty-state"><div class="icon">📦</div>
            <p>Cần cài <b>Chromium</b> (~150MB).</p>
          </div>`;
        return;
      }
      throw new Error(r.error || 'Scan failed');
    }
    ASSIGN = r.items || [];
    renderList();
    if (r.count === 0){
      log('Không tìm thấy bài nào.', 'warn');
      log('  ↳ Kiểm tra: đã login OLM chưa?', 'warn');
    } else log(`Tìm ${r.count} bài GV giao.`, 'ok');

    for (let i = 0; i < ASSIGN.length; i++){
      const a = ASSIGN[i];
      try {
        const qr = await api().get_questions(a.id);
        if (!qr.ok) continue;
        if (qr.title && (a.title === `Bài ${a.id}` || !a.title)){
          a.title = qr.title;
          const titleEl = document.querySelector(`[data-card="${a.id}"] .card-title`);
          if (titleEl) titleEl.textContent = qr.title;
        }
        if (qr.type_label){
          a.type_label = qr.type_label;
          const badge = document.querySelector(`[data-typelabel="${a.id}"]`);
          if (badge){ badge.textContent = qr.type_label; badge.style.display = ''; }
        }
        if (qr.count !== undefined){
          const t = qr.type_counts || {};
          a._types = t;
          a._count = qr.count;
          const el = document.querySelector(`[data-types="${a.id}"]`);
          if (el) el.innerHTML =
            `<b style="color:var(--p1)">${qr.count} câu</b> · ` +
            Object.entries(t).map(([k,v]) =>
              `<span class="type-badge">${esc(k)} × ${v}</span>`
            ).join(' ');
        }
      } catch(e){}
    }
  } catch(e){
    log('Lỗi quét: ' + (e.message||e), 'err');
    $('#listPanel').innerHTML =
      `<div class="empty-state"><div class="icon">✖</div>
        <p>${esc(e.message||String(e))}</p>
        <button class="btn btn-ghost" onclick="scanAssignments()">Thử lại</button>
      </div>`;
  }
}
window.scanAssignments = scanAssignments;
$('#btnScan').onclick = scanAssignments;

function renderList(){
  const panel = $('#listPanel');
  if (!ASSIGN.length){
    panel.innerHTML =
      '<div class="empty-state"><div class="icon">📚</div>' +
      '<p>Không có bài. Bấm <b>Quét</b> hoặc <b>+ Bài</b>.</p></div>';
    return;
  }
  panel.innerHTML = ASSIGN.map((a, i) => {
    const initScore = MODE.m === 'custom' ? MODE.c : '';
    const doneBadge = a.done
      ? '<span class="badge-done">✓ ĐÃ LÀM</span>'
      : '';
    return `<div class="card${a.done ? ' done' : ''}" data-card="${a.id}">
      <div class="card-head">
        <span class="card-idx">${i+1}</span>
        <span class="card-title" title="${esc(a.title)}">${esc(a.title)}</span>
        ${doneBadge}
        <span class="type-badge" data-typelabel="${a.id}"
          style="${a.type_label ? '' : 'display:none'}">
          ${esc(a.type_label || '')}</span>
        <span class="card-id">${esc(a.id)}</span>
      </div>
      <div class="card-types" data-types="${a.id}">
        ${a._types
          ? `<b style="color:var(--p1)">${a._count||Object.values(a._types).reduce((s,v)=>s+v,0)} câu</b> · ` +
            Object.entries(a._types).map(([k,v])=>
              `<span class="type-badge">${esc(k)} × ${v}</span>`
            ).join(' ')
          : '⏳ Đang tải thông tin bài…'}
      </div>
      <div class="card-actions">
        <label>Điểm</label>
        <input type="number" class="num-input" data-score="${a.id}"
          min="0" max="10" step="0.1" value="${initScore}" placeholder="auto">
        <label>Giây</label>
        <input type="number" class="num-input" data-time="${a.id}"
          min="10" step="10" value="${MODE.t}">
        <button class="btn btn-primary btn-sm" data-act="do" data-id="${a.id}">⚡ Làm</button>
        <button class="btn btn-danger btn-sm" data-act="del" data-id="${a.id}">🗑</button>
        <button class="btn btn-ghost btn-sm" data-act="ans" data-id="${a.id}">📋 Đáp án</button>
        <button class="btn btn-ghost btn-sm" data-act="word" data-id="${a.id}">📥 Word</button>
      </div>
      <div class="card-status" data-stat="${a.id}"></div>
    </div>`;
  }).join('');
  panel.querySelectorAll('button[data-act]').forEach(b => b.onclick = onCardAction);
}

async function onCardAction(e){
  const btn = e.currentTarget;
  const act = btn.dataset.act;
  const id = btn.dataset.id;

  if (act === 'ans'){
    setStat(id, '⏳ Đang tải đáp án…', 'working');
    setCardState(id, 'working');
    const r = await api().get_answers_html(id);
    setCardState(id, '');
    if (r.ok){
      setStat(id, `✔ Đã tải ${r.questions} câu đáp án`, 'ok');
      ansJSONCache = r.json || '';
      const tl = r.type_label ? ` · ${r.type_label}` : '';
      $('#ansTitle').textContent = `Đáp án — Bài ${id}`;
      $('#ansSub').textContent = `${r.questions} câu${r.title ? ' · ' + r.title : ''}${tl}`;
      $('#ansFrame').srcdoc = r.html;
      $('#answersModal').classList.add('show');
      log(`Mở đáp án ${id} (${r.questions} câu)`, 'ok');
    } else if (r.cf){ setStat(id, '🛡 CF chặn', 'warn'); }
    else if (r.chromium_missing){
      setStat(id, '📦 Chưa có Chromium', 'warn');
      $('#btnInstallChromium').classList.remove('hidden');
    } else if (r.v1_required){ setStat(id, '🔀 Cần v1', 'warn'); }
    else { setStat(id, '✖ ' + (r.error||''), 'err'); toast(r.error || 'Lỗi', 'err'); }
    return;
  }

  if (act === 'word'){
    setStat(id, '⏳ Đang tải Word…', 'working');
    setCardState(id, 'working');
    const r = await api().download_word(id);
    setCardState(id, '');
    if (r.ok){
      const suffix = r.generated ? ' (render)' : '';
      setStat(id, `✔ Đã lưu: ${r.filename}${suffix}`, 'ok');
      log(`Word ${id} → ${r.filename}${suffix}`, 'ok');
      toast('Đã lưu: ' + r.filename, 'ok');
      api().open_path(r.path);
    } else {
      setStat(id, '✖ ' + (r.error||''), 'err');
      toast(r.error || 'Lỗi Word', 'err');
    }
    return;
  }

  if (act === 'del'){
    if (!confirm(`Xóa bài làm của "${id}"?`)) return;
    setStat(id, '⏳ Đang xóa…', 'working');
    const r = await api().delete_work(id);
    if (r.ok){
      setStat(id, '✔ Đã xóa bài làm', 'ok');
      toast('Đã xóa bài làm', 'ok');
      const a = ASSIGN.find(x => x.id === id);
      if (a){ a.done = false; renderList(); }
    } else {
      setStat(id, '✖ ' + (r.error||'Lỗi'), 'err');
      toast(r.error || 'Lỗi', 'err');
    }
    return;
  }

  if (act === 'do'){ await doSubmit(id, btn, false); return; }
}

async function doSubmit(id, btn){
  const scoreEl = document.querySelector(`input[data-score="${id}"]`);
  const timeEl = document.querySelector(`input[data-time="${id}"]`);
  const custom = scoreEl && scoreEl.value ? parseFloat(scoreEl.value) : MODE.c;
  const t = timeEl && timeEl.value ? parseInt(timeEl.value) : MODE.t;
  const mode = MODE.m;
  const eff_mode = (scoreEl && scoreEl.value !== '') ? 'custom'
                   : (mode === 'custom' ? 'custom' : mode);

  if (btn) btn.disabled = true;
  setStat(id, `⏳ Đang làm…`, 'working');
  setCardState(id, 'working');
  log(`Làm ${id} (mode=${eff_mode}, t=${t}s)`, 'work');

  try {
    const r = await api().submit(id, eff_mode, custom, t, false);
    if (r.ok){
      const ok = r.status === 200;
      const mtd = r.method ? ` [${r.method}]` : '';
      const dl = (r.delete_before && r.delete_before.ok) ? ' ✓del' : '';
      setStat(id, `✔ ${r.questions} câu · ${r.score}đ${mtd}${dl}`,
              ok ? 'ok' : 'warn');
      log(`Xong ${id}: ${r.questions} câu, đúng ${r.correct}, ${r.score}đ${mtd}${dl}`,
          ok ? 'ok' : 'warn');
      setCardState(id, ok ? 'done' : 'fail');
      const a = ASSIGN.find(x => x.id === id);
      if (a){ a.done = true; }
      return true;
    }
    if (r.cf){ setStat(id, '🛡 CF chặn', 'warn'); setCardState(id, 'fail'); return false; }
    if (r.chromium_missing){
      setStat(id, '📦 Chưa có Chromium', 'warn');
      $('#btnInstallChromium').classList.remove('hidden');
      setCardState(id, 'fail'); return false;
    }
    if (r.v1_required){ setStat(id, '🔀 Cần v1', 'warn'); setCardState(id, 'fail'); return false; }
    setStat(id, '✖ ' + (r.error||''), 'err');
    log(`Lỗi ${id}: ${r.error||''}`, 'err');
    setCardState(id, 'fail');
    return false;
  } catch(e){
    setStat(id, '✖ ' + String(e.message||e).slice(0,100), 'err');
    log(`Lỗi ${id}: ${e.message||e}`, 'err');
    setCardState(id, 'fail');
    return false;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function bulkRun(kind){
  if (BULK_RUNNING){ toast('Đang chạy tác vụ khác', 'warn'); return; }
  if (!ASSIGN.length){ toast('Chưa có bài nào', 'warn'); return; }
  const labels = {
    submit: `Làm TẤT CẢ ${ASSIGN.length} bài?`,
    delete: `Xóa bài làm của TẤT CẢ ${ASSIGN.length} bài?`,
  };
  if (!confirm(labels[kind])) return;

  BULK_RUNNING = true;
  const btns = { submit: $('#btnAllSubmit'), delete: $('#btnAllDelete') };
  const orig = btns[kind].innerHTML;
  Object.values(btns).forEach(b => b.disabled = true);
  btns[kind].innerHTML = '<span class="spin"></span> Đang chạy';
  $('#bulkProgress').classList.remove('hidden');
  $('#bulkFill').style.width = '0%';

  let ok = 0, fail = 0;
  const titles = { submit: 'BẮT ĐẦU LÀM TẤT CẢ', delete: 'XÓA TẤT CẢ' };
  log(`═══ ${titles[kind]} (${ASSIGN.length} bài) ═══`, 'work');

  for (let i = 0; i < ASSIGN.length; i++){
    const a = ASSIGN[i];
    log(`[${i+1}/${ASSIGN.length}] Bài ${a.id}`, 'work');
    $('#bulkFill').style.width = `${Math.round((i / ASSIGN.length) * 100)}%`;
    try {
      if (kind === 'delete'){
        const r = await api().delete_work(a.id);
        if (r.ok){ ok++; a.done = false; } else fail++;
      } else {
        const success = await doSubmit(a.id, null);
        if (success) ok++; else fail++;
      }
    } catch(e){
      fail++;
      log(`  Lỗi: ${e.message||e}`, 'err');
    }
    if (i < ASSIGN.length - 1) await sleep(kind === 'delete' ? 350 : 700);
  }

  $('#bulkFill').style.width = '100%';
  setTimeout(() => $('#bulkProgress').classList.add('hidden'), 1500);
  log(`═══ HOÀN TẤT: ${ok} OK · ${fail} lỗi ═══`, fail===0 ? 'ok' : 'warn');
  toast(`Xong: ${ok} OK · ${fail} lỗi`, fail===0 ? 'ok' : 'warn', 5000);

  Object.values(btns).forEach(b => b.disabled = false);
  btns[kind].innerHTML = orig;
  BULK_RUNNING = false;
  renderList();
}

$('#btnAllSubmit').onclick = () => bulkRun('submit');
$('#btnAllDelete').onclick = () => bulkRun('delete');

$('#btnClearLog').onclick = () => { $('#logBody').innerHTML = ''; };

$('#btnAddId').onclick = () => {
  $('#addIdInput').value = '';
  $('#addIdModal').classList.add('show');
  setTimeout(() => $('#addIdInput').focus(), 80);
};
$('#addIdCancel').onclick = () => $('#addIdModal').classList.remove('show');
$('#addIdOk').onclick = async () => {
  const v = $('#addIdInput').value.trim();
  if (!v){ toast('Nhập ID hoặc link', 'warn'); return; }
  const btn = $('#addIdOk');
  const orig = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>';
  try {
    const r = await api().add_manual(v);
    if (r.ok){
      const item = r.items[0];
      if (!ASSIGN.find(a => a.id === item.id)){
        ASSIGN.push(item);
        renderList();
        try {
          const qr = await api().get_questions(item.id);
          if (qr.ok){
            const t = qr.type_counts || {};
            const a = ASSIGN.find(x => x.id === item.id);
            if (a){
              a._types = t; a._count = qr.count;
              a.title = qr.title || a.title;
              a.type_label = qr.type_label || a.type_label;
            }
          }
        } catch(e){}
        renderList();
      }
      $('#addIdModal').classList.remove('show');
      toast(`Đã thêm: ${item.title}`, 'ok', 4000);
    } else toast(r.error || 'Không thêm được', 'err');
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
};
$('#addIdInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') $('#addIdOk').click();
  if (e.key === 'Escape') $('#addIdCancel').click();
});

$('#btnCloseAns').onclick = () => $('#answersModal').classList.remove('show');
$('#btnCopyAns').onclick = async () => {
  if (!ansJSONCache){ toast('Không có dữ liệu', 'warn'); return; }
  const ok = await copyTextRobust(ansJSONCache);
  if (ok) toast(`Đã copy JSON (${(ansJSONCache.length/1024).toFixed(1)} KB)`, 'ok');
  else toast('Không copy được.', 'err', 5000);
};

document.addEventListener('keydown', e => {
  if (e.key === 'Escape'){
    $('#answersModal').classList.remove('show');
    $('#licModal').classList.remove('show');
    $('#addIdModal').classList.remove('show');
  }
  if (e.ctrlKey && e.shiftKey){
    if (e.key === 'R' || e.key === 'r'){ e.preventDefault(); scanAssignments(); }
    if (e.key === 'L' || e.key === 'l'){ e.preventDefault(); bulkRun('submit'); }
  }
});

window.addEventListener('pywebviewready', () => {
  if (!document.__booted){ document.__booted = true; bootstrap(); }
});
setTimeout(() => {
  if (window.pywebview && window.pywebview.api && !document.__booted){
    document.__booted = true; bootstrap();
  }
}, 800);
</script>
</body></html>
"""

def main():
    api = OLMApp()
    webview.create_window(
        title="OLM Tool Pro v1.0.0",
        html=INDEX_HTML, js_api=api,
        width=1440, height=920, min_size=(1000, 680),
        text_select=False, confirm_close=False)
    icon_path = None
    if sys.platform == "win32":
        if ICON_ICO.exists(): icon_path = ICON_ICO
        elif ICON_PNG.exists(): icon_path = ICON_PNG
    else:
        if ICON_PNG.exists(): icon_path = ICON_PNG
        elif ICON_ICO.exists(): icon_path = ICON_ICO

    def _start(with_icon):
        try:
            kwargs = {"debug": False, "private_mode": False}
            if with_icon and icon_path is not None:
                try: webview.start(icon=str(icon_path), **kwargs)
                except Exception as e:
                    msg = str(e)
                    if ("icon" in msg.lower() or "picture" in msg.lower()
                            or "ArgumentException" in msg):
                        print(f"[warn] Icon load failed: {msg}")
                        webview.start(**kwargs)
                    else: raise
            else: webview.start(**kwargs)
            return True
        except SystemExit: raise
        except Exception as e:
            print(f"[ERROR] webview.start failed: {e}"); return False

    try:
        if not _start(with_icon=True): print("[ERROR] Không mở được cửa sổ")
    except SystemExit: pass
    except Exception as e:
        tb = traceback.format_exc(); _log_crash(tb)
        _msgbox("OLM Tool Pro — Crash",
                f"Ứng dụng gặp lỗi:\n\n{str(e)[:500]}\n\nLog: {CRASH_F}")

if __name__ == "__main__":
    try: main()
    except SystemExit: pass
    except Exception:
        tb = traceback.format_exc(); _log_crash(tb)
        _msgbox("OLM Tool Pro — Fatal",
                f"Lỗi nghiêm trọng:\n\n{tb[-800:]}")