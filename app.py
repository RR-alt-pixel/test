# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
from threading import Thread, Lock, Event
from typing import Optional, Dict, List, Any
from queue import Queue
from urllib.parse import urlencode

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

TOKENS_FILE = "tokens.json"
TOKENS_LOCK = Lock()

# ================== 2. АККАУНТЫ ==================
accounts = [
    {"username": "klon9", "password": "7755SSaa"},
]

# ================== 3. ПУЛ ==================
pw_sessions: List[Dict[str, Any]] = []
pw_cycle = None
PW_SESSIONS_LOCK = Lock()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
]

class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

# ================== FINGERPRINT GENERATOR ==================
FINGERPRINT_SCRIPT = """
() => {
    // Генерируем Device Fingerprint как на реальном сайте
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 200;
    canvas.height = 50;
    ctx.textBaseline = 'top';
    ctx.font = '14px "Arial"';
    ctx.fillStyle = '#f60';
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('Hello, world!', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('Hello, world!', 4, 17);
    
    const canvasData = canvas.toDataURL();
    
    // Простое хеширование
    let hash = 0;
    for (let i = 0; i < canvasData.length; i++) {
        const char = canvasData.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    
    // Добавляем информацию о браузере
    const info = [
        navigator.userAgent,
        navigator.language,
        screen.width + 'x' + screen.height,
        new Date().getTimezoneOffset(),
        !!window.sessionStorage,
        !!window.localStorage
    ].join('|');
    
    let hash2 = 0;
    for (let i = 0; i < info.length; i++) {
        const char = info.charCodeAt(i);
        hash2 = ((hash2 << 5) - hash2) + char;
        hash2 = hash2 & hash2;
    }
    
    // Комбинируем хеши
    const combined = Math.abs(hash).toString(16) + Math.abs(hash2).toString(16);
    
    // Форматируем как 64-символьный хеш (как в примере)
    const fp = combined.padEnd(64, '0').substring(0, 64);
    
    return fp;
}
"""

# ================== 3.1 TOKENS FILE ==================
def load_tokens_from_file() -> List[Dict]:
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    print(f"[TOKENS] 🔁 Загружено {len(data)} записей.")
                    return data
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
    return []

def save_tokens_to_file():
    try:
        with TOKENS_LOCK:
            tmp = TOKENS_FILE + ".tmp"
            meta = []
            with PW_SESSIONS_LOCK:
                for s in pw_sessions:
                    meta.append({
                        "username": s.get("username"),
                        "user_agent": s.get("user_agent"),
                        "device_fingerprint": s.get("device_fingerprint"),
                        "cookie_header": s.get("cookie_header"),
                        "time": s.get("time"),
                        "session_key": s.get("session_key"),
                    })
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)
            print(f"[TOKENS] 💾 Сохранено {len(meta)} записей.")
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")

# ================== 4. PLAYWRIGHT ==================
class PWManager:
    def __init__(self):
        self.q: Queue = Queue()
        self.thread = Thread(target=self._run, daemon=True)
        self.ready = Event()
        self.started = False

        self._pw = None
        self._browser_by_key: Dict[str, Any] = {}
        self._context_by_key: Dict[str, Any] = {}
        self._page_by_key: Dict[str, Page] = {}
        self._session_meta_by_key: Dict[str, Dict[str, Any]] = {}

    def start(self):
        if not self.started:
            self.started = True
            self.thread.start()

    def _rpc(self, cmd: str, payload: dict = None, timeout: int = 90) -> dict:
        if payload is None:
            payload = {}
        box = {"done": Event(), "resp": None}
        self.q.put((cmd, payload, box))
        ok = box["done"].wait(timeout)
        if not ok:
            return {"ok": False, "error": "timeout"}
        return box["resp"] or {"ok": False, "error": "no_response"}

    def _run(self):
        try:
            self._pw = sync_playwright().start()
            self.ready.set()
            print("[PW] ✅ Playwright thread started")
        except Exception as e:
            print(f"[PW] ❌ failed to start: {e}")
            traceback.print_exc()
            self.ready.set()
            return

        while True:
            cmd, payload, box = self.q.get()
            try:
                if cmd == "init_pool":
                    resp = self._cmd_init_pool(payload)
                elif cmd == "refresh_user":
                    resp = self._cmd_refresh_user(payload)
                elif cmd == "fetch_get":
                    resp = self._cmd_fetch_get(payload)
                elif cmd == "close_key":
                    resp = self._cmd_close_key(payload)
                else:
                    resp = {"ok": False, "error": f"unknown_cmd:{cmd}"}
            except Exception as e:
                resp = {"ok": False, "error": str(e), "trace": traceback.format_exc()}
            finally:
                box["resp"] = resp
                box["done"].set()
                self.q.task_done()

    def _new_session_key(self, username: str) -> str:
        return f"{username}-{int(time.time())}-{random.randint(1000,9999)}"

    # Найдите функцию _login и замените блок логина на этот:

def _login(self, username: str, password: str, show_browser: bool = False) -> dict:
    if not self._pw:
        return {"ok": False, "error": "playwright_not_ready"}

    browser = None
    try:
        ua = random.choice(USER_AGENTS)
        browser = self._pw.chromium.launch(
            headless=not show_browser,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ],
            timeout=60000
        )
        
        context = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
            timezone_id="Asia/Almaty",
        )
        
        page: Page = context.new_page()
        
        # Скрываем webdriver
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)

        print(f"[PLW] Переход на {LOGIN_PAGE}")
        page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        
        # Генерируем Device Fingerprint
        print(f"[PLW] Генерация Device Fingerprint...")
        device_fp = page.evaluate(FINGERPRINT_SCRIPT)
        print(f"[PLW] Device FP: {device_fp}")
        
        # КРИТИЧНО: Находим скрытое поле для fingerprint или устанавливаем его
        # Смотрим, есть ли на странице input для device fingerprint
        page.evaluate(f"""
            () => {{
                // Сохраняем в localStorage/sessionStorage
                try {{
                    localStorage.setItem('deviceFingerprint', '{device_fp}');
                    sessionStorage.setItem('deviceFingerprint', '{device_fp}');
                }} catch(e) {{}}
                
                // Ищем скрытое поле или создаём его
                let fpInput = document.querySelector('input[name="device_fingerprint"]') ||
                              document.querySelector('input[name="deviceFingerprint"]') ||
                              document.querySelector('input[id="device_fingerprint"]');
                
                if (!fpInput) {{
                    // Создаём скрытое поле в форме логина
                    const form = document.querySelector('form');
                    if (form) {{
                        fpInput = document.createElement('input');
                        fpInput.type = 'hidden';
                        fpInput.name = 'device_fingerprint';
                        fpInput.value = '{device_fp}';
                        form.appendChild(fpInput);
                    }}
                }} else {{
                    fpInput.value = '{device_fp}';
                }}
                
                // Также устанавливаем глобальную переменную (если сайт использует)
                window.deviceFingerprint = '{device_fp}';
            }}
        """)
        
        # Заполняем форму
        print(f"[PLW] Логин {username}...")
        page.fill(LOGIN_SELECTOR, username)
        page.wait_for_timeout(500)
        page.fill(PASSWORD_SELECTOR, password)
        page.wait_for_timeout(500)
        
        # Перехватываем запрос на логин и добавляем fingerprint в заголовки
        page.route("**/auth/login", lambda route, request: route.continue_(
            headers={
                **request.headers,
                "x-device-fingerprint": device_fp
            }
        ))
        
        page.click(SIGN_IN_BUTTON_SELECTOR)
        
        # Ждём перенаправления
        print(f"[PLW] Ожидание dashboard...")
        try:
            page.wait_for_url("**/dashboard**", timeout=15000)
        except:
            pass
        
        page.wait_for_timeout(3000)
        page.wait_for_load_state("networkidle", timeout=10000)

        # Получаем cookies
        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        
        user_agent = page.evaluate("() => navigator.userAgent") or ua

        if not cookie_header:
            try:
                browser.close()
            except Exception:
                pass
            return {"ok": False, "error": "no_cookie_header"}

        session_key = self._new_session_key(username)

        self._browser_by_key[session_key] = browser
        self._context_by_key[session_key] = context
        self._page_by_key[session_key] = page
        self._session_meta_by_key[session_key] = {
            "username": username,
            "user_agent": user_agent,
            "device_fingerprint": device_fp,
            "cookie_header": cookie_header,
            "time": int(time.time()),
        }

        print(f"[PLW] ✅ {username} авторизован. key={session_key}")
        return {"ok": True, "session_key": session_key, "meta": self._session_meta_by_key[session_key]}

    except Exception as e:
        print(f"[PLW] ❌ Ошибка логина: {e}")
        traceback.print_exc()
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

        except Exception as e:
            print(f"[PLW] ❌ Ошибка логина: {e}")
            traceback.print_exc()
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            return {"ok": False, "error": str(e)}

    def _cmd_close_key(self, payload: dict) -> dict:
        key = payload.get("session_key")
        if not key:
            return {"ok": False, "error": "no_session_key"}

        b = self._browser_by_key.pop(key, None)
        self._context_by_key.pop(key, None)
        self._page_by_key.pop(key, None)
        self._session_meta_by_key.pop(key, None)

        if b:
            try:
                b.close()
            except Exception:
                pass
        return {"ok": True}

    def _cmd_init_pool(self, payload: dict) -> dict:
        show_browser = bool(payload.get("show_browser", False))
        created = []
        for acc in accounts:
            r = self._login(acc["username"], acc["password"], show_browser=show_browser)
            if r.get("ok"):
                created.append(r)
        return {"ok": True, "created": created}

    def _cmd_refresh_user(self, payload: dict) -> dict:
        username = payload.get("username")
        password = payload.get("password")
        old_key = payload.get("old_session_key")
        show_browser = bool(payload.get("show_browser", False))

        if not username or not password:
            return {"ok": False, "error": "username_or_password_missing"}

        r = self._login(username, password, show_browser=show_browser)
        if r.get("ok") and old_key:
            self._cmd_close_key({"session_key": old_key})
        return r

    def _cmd_fetch_get(self, payload: dict) -> dict:
        key = payload.get("session_key")
        url = payload.get("url")
        if not key or not url:
            return {"ok": False, "error": "missing_key_or_url"}

        page = self._page_by_key.get(key)
        meta = self._session_meta_by_key.get(key)
        if not page or not meta:
            return {"ok": False, "error": "page_not_found_for_key"}

        device_fp = meta.get("device_fingerprint", "")

        # Делаем запрос через fetch с правильными заголовками
        js = """
        async (args) => {
          const { url, deviceFp } = args;
          try {
            const headers = {
              'Accept': 'application/json',
              'Content-Type': 'application/json',
              'x-device-fingerprint': deviceFp
            };
            
            const r = await fetch(url, { 
              method: "GET", 
              credentials: "include",
              headers: headers
            });
            
            const txt = await r.text();
            let jsn = null;
            try { jsn = JSON.parse(txt); } catch (e) {}
            return { ok: r.ok, status: r.status, text: txt, json: jsn };
          } catch (e) {
            return { ok: false, status: 0, text: String(e), json: null, error: String(e) };
          }
        }
        """
        out = page.evaluate(js, {"url": url, "deviceFp": device_fp})
        return {"ok": True, "out": out}

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(30)

# ================== 5. ПУЛ СЕССИЙ ==================
def init_token_pool_playwright(show_browser: bool = False):
    global pw_sessions, pw_cycle

    print("[POOL] 🔄 Логин через Playwright...")
    resp = pw_manager._rpc("init_pool", {"show_browser": show_browser}, timeout=120)

    if not resp.get("ok"):
        print(f"[POOL] ❌ init_pool failed: {resp.get('error')}")
        pw_sessions = []
        pw_cycle = None
        return

    created = resp.get("created", [])
    new_sessions = []
    for item in created:
        meta = item.get("meta", {})
        new_sessions.append({
            "username": meta.get("username"),
            "password": next((a["password"] for a in accounts if a["username"] == meta.get("username")), None),
            "user_agent": meta.get("user_agent"),
            "device_fingerprint": meta.get("device_fingerprint"),
            "cookie_header": meta.get("cookie_header"),
            "time": meta.get("time"),
            "session_key": item.get("session_key"),
        })

    with PW_SESSIONS_LOCK:
        pw_sessions = new_sessions
        pw_cycle = itertools.cycle(pw_sessions) if pw_sessions else None

    if pw_sessions:
        save_tokens_to_file()
        print(f"[POOL] ✅ init ok, sessions={len(pw_sessions)}")
    else:
        print("[POOL] ❌ Пустой пул сессий.")

def get_next_session() -> Optional[Dict]:
    global pw_sessions, pw_cycle

    if not pw_sessions:
        init_token_pool_playwright()
        with PW_SESSIONS_LOCK:
            if not pw_sessions:
                return None

    with PW_SESSIONS_LOCK:
        if pw_cycle is None:
            pw_cycle = itertools.cycle(pw_sessions)
        try:
            s = next(pw_cycle)
            print(f"[POOL] 🔁 Используется сессия {s['username']}")
            return s
        except StopIteration:
            pw_cycle = itertools.cycle(pw_sessions)
            s = next(pw_cycle)
            return s

def refresh_token_for_username(username: str) -> Optional[Dict]:
    global pw_sessions, pw_cycle
    try:
        with PW_SESSIONS_LOCK:
            old = next((s for s in pw_sessions if s.get("username") == username), None)

        if old:
            password = old.get("password")
            old_key = old.get("session_key")
        else:
            acc = next(a for a in accounts if a["username"] == username)
            password = acc["password"]
            old_key = None

        resp = pw_manager._rpc(
            "refresh_user",
            {"username": username, "password": password, "old_session_key": old_key, "show_browser": False},
            timeout=120
        )

        if not resp.get("ok"):
            print(f"[AUTH] ❌ refresh failed: {resp.get('error')}")
            return None

        meta = resp.get("meta", {})
        new_sess = {
            "username": meta.get("username"),
            "password": password,
            "user_agent": meta.get("user_agent"),
            "device_fingerprint": meta.get("device_fingerprint"),
            "cookie_header": meta.get("cookie_header"),
            "time": meta.get("time"),
            "session_key": resp.get("session_key"),
        }

        with PW_SESSIONS_LOCK:
            replaced = False
            for i, s in enumerate(pw_sessions):
                if s.get("username") == username:
                    pw_sessions[i] = new_sess
                    replaced = True
                    break
            if not replaced:
                pw_sessions.append(new_sess)
            pw_cycle = itertools.cycle(pw_sessions)

        save_tokens_to_file()
        print(f"[AUTH] 🔁 {username} session refreshed.")
        return new_sess

    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        traceback.print_exc()
    return None

# ================== 7. BUILD URL ==================
def _build_url(endpoint: str, params: dict = None) -> str:
    if endpoint.startswith("http"):
        url = endpoint
    else:
        url = API_BASE + endpoint

    if params:
        qs = urlencode(params, doseq=True)
        if "?" in url:
            url = url + "&" + qs
        else:
            url = url + "?" + qs
    return url

# ================== 8. CRM GET ==================
def crm_get(endpoint: str, params: dict = None):
    sess = get_next_session()
    if not sess:
        return "❌ Нет сессий Playwright."

    url = _build_url(endpoint, params=params)
    key = sess.get("session_key")

    resp = pw_manager._rpc("fetch_get", {"session_key": key, "url": url}, timeout=60)
    if not resp.get("ok"):
        uname = sess.get("username")
        print(f"[AUTH] {uname} → fetch error → refresh: {resp.get('error')}")
        new_sess = refresh_token_for_username(uname)
        if not new_sess:
            return f"❌ Ошибка CRM: {resp.get('error')}"
        key2 = new_sess.get("session_key")
        resp = pw_manager._rpc("fetch_get", {"session_key": key2, "url": url}, timeout=60)
        if not resp.get("ok"):
            return f"❌ Ошибка CRM: {resp.get('error')}"

    out = (resp.get("out") or {})
    status = int(out.get("status", 0) or 0)
    txt = out.get("text", "") or ""
    jsn = out.get("json", None)

    if status in (401, 403):
        uname = sess["username"]
        print(f"[AUTH] {uname} → {status} → обновляем сессию")
        new_sess = refresh_token_for_username(uname)
        if new_sess:
            key2 = new_sess.get("session_key")
            resp2 = pw_manager._rpc("fetch_get", {"session_key": key2, "url": url}, timeout=60)
            if resp2.get("ok"):
                out2 = (resp2.get("out") or {})
                status = int(out2.get("status", 0) or 0)
                txt = out2.get("text", "") or ""
                jsn = out2.get("json", None)

    return ResponseLike(status_code=status, text=txt, json_data=jsn)

# ================== 9. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(1.5, 2.0))
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
    result_box = {}
    crm_queue.put((crm_get, (endpoint,), {"params": params}, result_box))
    t0 = time.time()
    while "result" not in result_box and "error" not in result_box:
        if time.time() - t0 > RESULT_TIMEOUT:
            return {"status": "timeout"}
        time.sleep(0.1)
    if "error" in result_box:
        return {"status": "error", "error": result_box["error"]}
    return {"status": "ok", "result": result_box["result"]}

# ================== 10. ALLOWED USERS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ids = [int(i) for i in data.get("allowed_users", [])]
            if ids:
                ALLOWED_USER_IDS = ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH] ✅ {len(ALLOWED_USER_IDS)} пользователей разрешено.")
    except Exception as e:
        print(f"[AUTH ERROR] {e}")

def periodic_fetch():
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 11. ПОИСК ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v3/search/iin", params={"iin": iin})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    p = data[0]
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = enqueue_crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 100})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0]
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_fio(text: str):
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "true", "limit": 100}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "true", "limit": 100}
    r = enqueue_crm_get("/api/v3/search/fio", params=q)
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."
    results = []
    for i, p in enumerate(data[:10], start=1):
        results.append(
            f"{i}. 👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 Дата рождения: {p.get('birthday','')}\n"
            f"🚻 Пол: {p.get('sex','')}\n"
            f"🌍 Национальность: {p.get('nationality','')}"
        )
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

def search_by_address(address: str):
    return "⚠️ Поиск по адресу временно недоступен."

# ================== 12. FLASK ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600

@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.json
    user_id = data.get('telegram_user_id')
    if not user_id:
        return jsonify({"error": "Нет Telegram ID"}), 400
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа"}), 403
    now = time.time()
    existing = active_sessions.get(user_id)
    if existing and (now - existing["created"]) < SESSION_TTL:
        return jsonify({"error": "Сессия уже активна."}), 403
    if existing and (now - existing["created"]) >= SESSION_TTL:
        del active_sessions[user_id]
    session_token = f"{user_id}-{int(now)}-{random.randint(1000,9999)}"
    active_sessions[user_id] = {"token": session_token, "created": now}
    print(f"[SESSION] 🔑 Активирована сессия для {user_id}")
    return jsonify({"session_token": session_token})

@app.before_request
def validate_session():
    if request.path == "/api/search" and request.method == "POST":
        data = request.json or {}
        uid = data.get("telegram_user_id")
        token = data.get("session_token")
        session = active_sessions.get(uid)
        if not session:
            return jsonify({"error": "Сессия не найдена."}), 403
        if session["token"] != token:
            return jsonify({"error": "Сессия недействительна."}), 403
        if time.time() - session["created"] > SESSION_TTL:
            del active_sessions[uid]
            return jsonify({"error": "Сессия истекла."}), 403

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации."}), 403
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа."}), 403
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith(("+", "8", "7")):
        reply = search_by_phone(query)
    elif any(x in query.upper() for x in ["УЛ.", "ПР.", "ДОМ", "РЕСПУБЛИКА"]):
        reply = search_by_address(query)
    else:
        reply = search_by_fio(query)
    return jsonify({"result": reply})

@app.route('/api/queue-size', methods=['GET'])
def queue_size():
    return jsonify({"queue_size": crm_queue.qsize()})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    fetch_allowed_users()
    return jsonify({"ok": True, "count": len(ALLOWED_USER_IDS)})

# ================== 13. ЗАПУСК ==================
print("🚀 Запуск API...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()
init_token_pool_playwright(show_browser=False)

def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
            print(f"[SESSION] 🧹 Удалена сессия {uid}")
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
