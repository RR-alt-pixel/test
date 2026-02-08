# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
import base64
from threading import Thread, Lock, Event
from typing import Optional, Dict, List, Any
from queue import Queue
from urllib.parse import urlencode, urlparse

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page, BrowserContext

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

# ================== FINGERPRINT EXTRACTOR ==================
FINGERPRINT_EXTRACTOR = """
() => {
    // Ищем fingerprint в разных местах
    let fp = null;
    
    // 1. Проверяем localStorage (самое важное)
    try {
        fp = localStorage.getItem('device_fingerprint') || 
             localStorage.getItem('__device_fingerprint') ||
             localStorage.getItem('fingerprint') ||
             localStorage.getItem('deviceFingerprint');
    } catch(e) {}
    
    // 2. Проверяем sessionStorage
    if (!fp) {
        try {
            fp = sessionStorage.getItem('device_fingerprint') || 
                 sessionStorage.getItem('__device_fingerprint') ||
                 sessionStorage.getItem('fingerprint') ||
                 sessionStorage.getItem('deviceFingerprint');
        } catch(e) {}
    }
    
    // 3. Проверяем глобальные переменные
    if (!fp) {
        if (window.deviceFingerprint) fp = window.deviceFingerprint;
        else if (window.__deviceFingerprint) fp = window.__deviceFingerprint;
        else if (window.fingerprint) fp = window.fingerprint;
    }
    
    // 4. Ищем скрытые поля в форме
    if (!fp) {
        const inputs = document.querySelectorAll('input[type="hidden"]');
        for (let input of inputs) {
            const name = input.name || input.id || '';
            if ((name.includes('fingerprint') || name.includes('device')) && 
                input.value && input.value.length >= 64) {
                fp = input.value;
                break;
            }
        }
    }
    
    // 5. Ищем в URL параметрах
    if (!fp) {
        const urlParams = new URLSearchParams(window.location.search);
        fp = urlParams.get('fingerprint') || urlParams.get('device_fingerprint');
    }
    
    console.log('Найден fingerprint:', fp ? fp.substring(0, 20) + '...' : 'не найден');
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
                elif cmd == "get_page_content":
                    resp = self._cmd_get_page_content(payload)
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

    def _extract_fingerprint_from_network(self, page: Page, timeout: int = 10000) -> Optional[str]:
        """Извлекает fingerprint из перехваченных сетевых запросов"""
        fingerprint = None
        start_time = time.time()
        
        def on_request(request):
            nonlocal fingerprint
            # Проверяем заголовки запроса
            headers = request.headers
            if 'x-device-fingerprint' in headers:
                fp = headers['x-device-fingerprint']
                if fp and len(fp) >= 64:
                    fingerprint = fp
                    print(f"[NETWORK] Найден fingerprint в запросе: {fp[:20]}...")
            
            # Проверяем тело POST запроса
            if request.method == "POST" and request.post_data:
                try:
                    data = json.loads(request.post_data)
                    if 'device_fingerprint' in data:
                        fp = data['device_fingerprint']
                        if fp and len(fp) >= 64:
                            fingerprint = fp
                            print(f"[NETWORK] Найден fingerprint в теле: {fp[:20]}...")
                except:
                    pass
        
        page.on("request", on_request)
        
        # Ждём пока не найдём fingerprint или не истечёт время
        while not fingerprint and (time.time() - start_time) < (timeout / 1000):
            time.sleep(0.1)
        
        page.remove_listener("request", on_request)
        return fingerprint

    def _login(self, username: str, password: str, show_browser: bool = False) -> dict:
        if not self._pw:
            return {"ok": False, "error": "playwright_not_ready"}

        browser = None
        try:
            ua = random.choice(USER_AGENTS)
            
            # ВСЕГДА headless на сервере
            browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process"
                ],
                timeout=60000
            )
            
            # Создаём контекст с правильными настройками
            context = browser.new_context(
                user_agent=ua,
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Asia/Almaty",
                permissions=["geolocation"],
                ignore_https_errors=True,
            )
            
            page: Page = context.new_page()
            
            # Скрываем webdriver
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = {runtime: {}};
            """)

            print(f"[PLW] Переход на {LOGIN_PAGE}")
            
            # Перехватываем ВСЕ запросы для поиска fingerprint
            captured_fingerprint = None
            def capture_fingerprint(request):
                nonlocal captured_fingerprint
                # Проверяем заголовки
                headers = request.headers
                if 'x-device-fingerprint' in headers:
                    fp = headers['x-device-fingerprint']
                    if fp and len(fp) >= 64 and not captured_fingerprint:
                        captured_fingerprint = fp
                        print(f"[NETWORK] Захвачен fingerprint из заголовка: {fp[:20]}...")
                
                # Продолжаем запрос
                request.continue_()
            
            page.route("**/*", capture_fingerprint)
            
            # Загружаем страницу
            page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            # Ищем fingerprint на странице
            print(f"[PLW] Поиск Device Fingerprint на странице...")
            device_fp = page.evaluate(FINGERPRINT_EXTRACTOR)
            
            if not device_fp and captured_fingerprint:
                device_fp = captured_fingerprint
                print(f"[PLW] Используем fingerprint из сетевого запроса")
            
            if not device_fp:
                # Пробуем кликнуть на поле и подождать
                print(f"[PLW] Пробуем активировать скрипты сайта...")
                page.click(LOGIN_SELECTOR)
                page.wait_for_timeout(2000)
                device_fp = page.evaluate(FINGERPRINT_EXTRACTOR)
            
            if not device_fp:
                # Пробуем найти в localStorage более тщательно
                storage_content = page.evaluate("""() => {
                    const items = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        items[key] = localStorage.getItem(key);
                    }
                    return items;
                }""")
                
                print(f"[PLW] Содержимое localStorage: {json.dumps(storage_content, indent=2)}")
                
                # Ищем любой ключ с fingerprint
                for key, value in storage_content.items():
                    if 'fingerprint' in key.lower() and value and len(value) >= 64:
                        device_fp = value
                        print(f"[PLW] Найден fingerprint в localStorage[{key}]: {value[:20]}...")
                        break
            
            if not device_fp:
                # Последняя попытка: делаем скриншот для отладки
                try:
                    page.screenshot(path="debug_no_fingerprint.png")
                    print(f"[PLW] 📸 Скриншот сохранен в debug_no_fingerprint.png")
                except:
                    pass
                return {"ok": False, "error": "fingerprint_not_found", "details": "Не удалось найти fingerprint на сайте"}
            
            print(f"[PLW] Device FP найден: {device_fp[:20]}...")
            
            # Сохраняем fingerprint для использования в запросах
            page.evaluate(f"""
                (fp) => {{
                    try {{
                        localStorage.setItem('device_fingerprint', fp);
                        sessionStorage.setItem('device_fingerprint', fp);
                        window.deviceFingerprint = fp;
                        console.log('Fingerprint сохранен для сессии:', fp.substring(0, 20) + '...');
                    }} catch(e) {{ 
                        console.error('Ошибка сохранения fingerprint:', e); 
                    }}
                }}
            """, device_fp)
            
            # Добавляем скрытое поле в форму если нужно
            page.evaluate(f"""
                (fp) => {{
                    const form = document.querySelector('form');
                    if (form) {{
                        let fpField = form.querySelector('input[name="device_fingerprint"]');
                        if (!fpField) {{
                            fpField = document.createElement('input');
                            fpField.type = 'hidden';
                            fpField.name = 'device_fingerprint';
                            fpField.value = fp;
                            form.appendChild(fpField);
                            console.log('Добавлено поле device_fingerprint в форму');
                        }}
                    }}
                }}
            """, device_fp)
            
            # Заполняем форму логина
            print(f"[PLW] Логин {username}...")
            page.fill(LOGIN_SELECTOR, username)
            page.wait_for_timeout(500)
            page.fill(PASSWORD_SELECTOR, password)
            page.wait_for_timeout(500)
            
            # Отключаем общий перехватчик и устанавливаем специфичный для логина
            page.unroute("**/*", capture_fingerprint)
            
            # Перехватываем только запрос логина чтобы добавить заголовки
            def add_fingerprint_to_login(route, request):
                headers = dict(request.headers)
                headers['x-device-fingerprint'] = device_fp
                headers['origin'] = 'https://pena.rest'
                headers['referer'] = 'https://pena.rest/auth/login'
                
                # Если есть тело запроса, добавляем fingerprint и туда
                if request.method == "POST" and request.post_data:
                    try:
                        data = json.loads(request.post_data)
                        data['device_fingerprint'] = device_fp
                        post_data = json.dumps(data)
                        route.continue_(headers=headers, post_data=post_data)
                        return
                    except:
                        pass
                
                route.continue_(headers=headers)
            
            page.route("**/auth/login", add_fingerprint_to_login)
            
            # Нажимаем кнопку входа
            page.click(SIGN_IN_BUTTON_SELECTOR)
            
            # Ждём успешного входа
            print(f"[PLW] Ожидание dashboard...")
            try:
                page.wait_for_url("**/dashboard**", timeout=25000)
                print(f"[PLW] ✅ Успешный вход в dashboard")
            except Exception as e:
                # Проверяем текущий URL
                current_url = page.url
                print(f"[PLW] Текущий URL: {current_url}")
                
                # Проверяем есть ли ошибки на странице
                page_content = page.content()
                if "неверный" in page_content.lower() or "ошибка" in page_content.lower():
                    error_msg = page_content[:500]
                    raise Exception(f"Ошибка логина: {error_msg}")
                
                if "dashboard" not in current_url:
                    # Делаем скриншот для отладки
                    try:
                        page.screenshot(path="debug_login_failed.png")
                        print(f"[PLW] 📸 Скриншот сохранен в debug_login_failed.png")
                    except:
                        pass
                    raise Exception(f"Не удалось войти в систему. URL: {current_url}")
            
            page.wait_for_timeout(3000)
            page.wait_for_load_state("networkidle", timeout=10000)

            # Получаем cookies
            cookies = context.cookies()
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # Извлекаем и проверяем JWT токен
            access_token_ws = None
            for cookie in cookies:
                if cookie['name'] == 'access_token_ws':
                    access_token_ws = cookie['value']
                    break
            
            if access_token_ws:
                try:
                    # Декодируем JWT чтобы проверить fingerprint
                    jwt_parts = access_token_ws.split('.')
                    if len(jwt_parts) >= 2:
                        # Добавляем padding если нужно
                        payload_encoded = jwt_parts[1]
                        padding = 4 - len(payload_encoded) % 4
                        if padding != 4:
                            payload_encoded += "=" * padding
                        
                        payload_decoded = base64.b64decode(payload_encoded)
                        jwt_data = json.loads(payload_decoded)
                        jwt_fp = jwt_data.get('device_fp_hash')
                        if jwt_fp:
                            print(f"[PLW] JWT device_fp_hash: {jwt_fp[:20]}...")
                            if jwt_fp != device_fp:
                                print(f"[PLW] ⚠️ Fingerprint в JWT не совпадает с нашим!")
                                print(f"[PLW]   Наш: {device_fp[:20]}...")
                                print(f"[PLW]   JWT: {jwt_fp[:20]}...")
                                # Пробуем использовать fingerprint из JWT
                                device_fp = jwt_fp
                except Exception as e:
                    print(f"[PLW] Ошибка декодирования JWT: {e}")
            
            # Проверяем важные cookies
            required_cookies = ['access_token', 'access_token_ws', 'aegis_session', 'csrf_token']
            found_cookies = [c['name'] for c in cookies]
            missing_cookies = [c for c in required_cookies if c not in found_cookies]
            if missing_cookies:
                print(f"[PLW] ⚠️ Отсутствуют важные cookies: {missing_cookies}")
            
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
                "cookies": cookies,  # Сохраняем полные cookies
            }

            print(f"[PLW] ✅ {username} авторизован. key={session_key}")
            print(f"[PLW] Cookie header длина: {len(cookie_header)}")
            print(f"[PLW] Всего cookies: {len(cookies)}")
            
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
            print(f"[POOL] Логин аккаунта {acc['username']}...")
            r = self._login(acc["username"], acc["password"], show_browser=show_browser)
            if r.get("ok"):
                created.append(r)
                print(f"[POOL] ✅ Аккаунт {acc['username']} успешно авторизован")
            else:
                print(f"[POOL] ❌ Ошибка авторизации {acc['username']}: {r.get('error')}")
        return {"ok": True, "created": created}

    def _cmd_refresh_user(self, payload: dict) -> dict:
        username = payload.get("username")
        password = payload.get("password")
        old_key = payload.get("old_session_key")
        show_browser = bool(payload.get("show_browser", False))

        if not username or not password:
            return {"ok": False, "error": "username_or_password_missing"}

        # Закрываем старую сессию если есть
        if old_key:
            self._cmd_close_key({"session_key": old_key})
        
        # Создаём новую
        r = self._login(username, password, show_browser=show_browser)
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
        cookies = meta.get("cookies", [])

        # Делаем запрос через fetch с правильными заголовками
        js = """
        async (args) => {
          const { url, deviceFp, cookies } = args;
          try {
            // Устанавливаем cookies если нужно
            if (cookies && cookies.length > 0) {
              for (const cookie of cookies) {
                try {
                  document.cookie = `${cookie.name}=${cookie.value}; domain=${cookie.domain}; path=${cookie.path}; ${cookie.secure ? 'secure;' : ''} ${cookie.httpOnly ? 'HttpOnly;' : ''}`;
                } catch(e) {
                  console.warn('Не удалось установить cookie', cookie.name, e);
                }
              }
            }
            
            // Получаем актуальный fingerprint
            let actualFp = deviceFp;
            try {
              const stored = localStorage.getItem('device_fingerprint') || 
                             sessionStorage.getItem('device_fingerprint') ||
                             window.deviceFingerprint;
              if (stored) actualFp = stored;
            } catch(e) {
              console.warn('Ошибка получения fingerprint из хранилища:', e);
            }
            
            const headers = {
              'Accept': 'application/json',
              'Content-Type': 'application/json',
              'x-device-fingerprint': actualFp,
              'x-requested-with': 'XMLHttpRequest',
              'referer': 'https://pena.rest/dashboard',
              'origin': 'https://pena.rest'
            };
            
            console.log('Отправка запроса к:', url);
            console.log('Используем fingerprint:', actualFp.substring(0, 20) + '...');
            
            const r = await fetch(url, { 
              method: "GET", 
              credentials: "include",  // ВАЖНО: включаем cookies
              headers: headers,
              mode: "cors"
            });
            
            const txt = await r.text();
            let jsn = null;
            try { 
              jsn = JSON.parse(txt); 
            } catch (e) {
              console.warn('Не удалось распарсить JSON ответ:', e.message);
            }
            
            console.log('Ответ от сервера:', r.status, r.statusText);
            if (!r.ok) {
              console.log('Текст ошибки:', txt.substring(0, 300));
            }
            
            return { ok: r.ok, status: r.status, text: txt, json: jsn };
          } catch (e) {
            console.error('Ошибка при выполнении fetch:', e);
            return { ok: false, status: 0, text: String(e), json: null, error: String(e) };
          }
        }
        """
        out = page.evaluate(js, {"url": url, "deviceFp": device_fp, "cookies": cookies})
        return {"ok": True, "out": out}
    
    def _cmd_get_page_content(self, payload: dict) -> dict:
        """Получает содержимое страницы для отладки"""
        key = payload.get("session_key")
        if not key:
            return {"ok": False, "error": "no_session_key"}
        
        page = self._page_by_key.get(key)
        if not page:
            return {"ok": False, "error": "page_not_found"}
        
        try:
            content = page.content()
            url = page.url
            title = page.title()
            return {"ok": True, "content": content[:5000], "url": url, "title": title}
        except Exception as e:
            return {"ok": False, "error": str(e)}

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(30)

# ================== 5. ПУЛ СЕССИЙ ==================
def init_token_pool_playwright(show_browser: bool = False):
    global pw_sessions, pw_cycle

    print("[POOL] 🔄 Логин через Playwright...")
    resp = pw_manager._rpc("init_pool", {"show_browser": show_browser}, timeout=180)  # Увеличили таймаут

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
            "cookies": meta.get("cookies", []),
            "time": meta.get("time"),
            "session_key": item.get("session_key"),
        })

    with PW_SESSIONS_LOCK:
        pw_sessions = new_sessions
        pw_cycle = itertools.cycle(pw_sessions) if pw_sessions else None

    if pw_sessions:
        save_tokens_to_file()
        print(f"[POOL] ✅ init ok, sessions={len(pw_sessions)}")
        for s in pw_sessions:
            print(f"[POOL]   - {s['username']}: FP={s['device_fingerprint'][:20]}..., Cookies={len(s.get('cookies', []))}")
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
            print(f"[POOL] 🔁 Используется сессия {s['username']} (FP: {s['device_fingerprint'][:20]}...)")
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

        print(f"[AUTH] 🔄 Обновление сессии для {username}...")
        resp = pw_manager._rpc(
            "refresh_user",
            {"username": username, "password": password, "old_session_key": old_key, "show_browser": False},
            timeout=180
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
            "cookies": meta.get("cookies", []),
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
        print(f"[AUTH] ✅ {username} session refreshed.")
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
    device_fp = sess.get("device_fingerprint", "")[:20] + "..." if sess.get("device_fingerprint") else "нет"

    print(f"[CRM] {sess['username']} -> {endpoint}")
    print(f"[CRM] URL: {url}")
    print(f"[CRM] Fingerprint: {device_fp}")
    print(f"[CRM] Cookies count: {len(sess.get('cookies', []))}")

    resp = pw_manager._rpc("fetch_get", {"session_key": key, "url": url}, timeout=60)
    if not resp.get("ok"):
        uname = sess.get("username")
        error_msg = resp.get('error', 'unknown')
        print(f"[AUTH] {uname} → fetch error: {error_msg}")
        
        # Пробуем получить содержимое страницы для отладки
        debug_resp = pw_manager._rpc("get_page_content", {"session_key": key}, timeout=10)
        if debug_resp.get("ok"):
            print(f"[DEBUG] Текущий URL: {debug_resp.get('url')}")
            print(f"[DEBUG] Заголовок: {debug_resp.get('title')}")
        
        # Обновляем сессию
        print(f"[AUTH] Пробуем обновить сессию...")
        new_sess = refresh_token_for_username(uname)
        if not new_sess:
            return f"❌ Ошибка CRM: {error_msg}"
        key2 = new_sess.get("session_key")
        resp = pw_manager._rpc("fetch_get", {"session_key": key2, "url": url}, timeout=60)
        if not resp.get("ok"):
            return f"❌ Ошибка CRM после обновления: {resp.get('error')}"

    out = (resp.get("out") or {})
    status = int(out.get("status", 0) or 0)
    txt = out.get("text", "") or ""
    jsn = out.get("json", None)

    print(f"[CRM] Ответ: {status} ({len(txt)} chars)")

    if status in (401, 403):
        uname = sess["username"]
        print(f"[AUTH] {uname} → {status} → Ошибка аутентификации")
        print(f"[AUTH] Текст ответа: {txt[:500]}")
        
        # Пробуем обновить сессию
        new_sess = refresh_token_for_username(uname)
        if new_sess:
            key2 = new_sess.get("session_key")
            resp2 = pw_manager._rpc("fetch_get", {"session_key": key2, "url": url}, timeout=60)
            if resp2.get("ok"):
                out2 = (resp2.get("out") or {})
                status = int(out2.get("status", 0) or 0)
                txt = out2.get("text", "") or ""
                jsn = out2.get("json", None)
                print(f"[CRM] После обновления: {status}")
            else:
                print(f"[CRM] Ошибка после обновления: {resp2.get('error')}")
    
    return ResponseLike(status_code=status, text=txt, json_data=jsn)

# ================== 9. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 60  # Увеличили таймаут

def crm_worker():
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(2.0, 3.0))  # Увеличили задержку
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
        # Пытаемся получить больше информации об ошибке
        error_text = resp.text
        if "device fingerprint" in error_text.lower():
            return f"❌ Ошибка аутентификации (fingerprint). Пожалуйста, попробуйте позже."
        return f"❌ Ошибка {resp.status_code}: {error_text[:100]}"
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
        error_text = resp.text
        if "device fingerprint" in error_text.lower():
            return f"❌ Ошибка аутентификации (fingerprint). Пожалуйста, попробуйте позже."
        return f"❌ Ошибка {resp.status_code}: {error_text[:100]}"
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
        error_text = resp.text
        if "device fingerprint" in error_text.lower():
            return f"❌ Ошибка аутентификации (fingerprint). Пожалуйста, попробуйте позже."
        return f"❌ Ошибка {resp.status_code}: {error_text[:100]}"
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

@app.route('/api/debug/sessions', methods=['GET'])
def debug_sessions():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    with PW_SESSIONS_LOCK:
        sessions_info = []
        for s in pw_sessions:
            sessions_info.append({
                "username": s.get("username"),
                "device_fingerprint": s.get("device_fingerprint", "")[:20] + "...",
                "cookie_header_length": len(s.get("cookie_header", "")),
                "cookies_count": len(s.get("cookies", [])),
                "session_key": s.get("session_key", "")[:20] + "...",
                "time": s.get("time"),
                "age_seconds": int(time.time()) - s.get("time", 0)
            })
    
    return jsonify({
        "active_sessions_count": len(pw_sessions),
        "sessions": sessions_info,
        "queue_size": crm_queue.qsize()
    })

@app.route('/api/debug/force-refresh', methods=['POST'])
def debug_force_refresh():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    username = data.get('username')
    
    if username:
        result = refresh_token_for_username(username)
        if result:
            return jsonify({"ok": True, "message": f"Сессия для {username} обновлена"})
        else:
            return jsonify({"ok": False, "error": f"Не удалось обновить сессию для {username}"})
    else:
        # Переинициализируем весь пул
        init_token_pool_playwright()
        return jsonify({"ok": True, "message": "Весь пул сессий переинициализирован"})

# ================== 13. ЗАПУСК ==================
print("🚀 Запуск API...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()

# Даём немного времени перед инициализацией
time.sleep(3)

# Удаляем старый tokens.json чтобы начать с чистого листа
try:
    if os.path.exists(TOKENS_FILE):
        os.remove(TOKENS_FILE)
        print(f"[INIT] Удалён старый файл {TOKENS_FILE}")
except:
    pass

# Инициализируем пул сессий
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
    print(f"🌐 Сервер запущен на http://0.0.0.0:5000")
    print(f"📊 Для отладки: curl -H 'Authorization: Bearer {SECRET_TOKEN}' http://localhost:5000/api/debug/sessions")
    app.run(host="0.0.0.0", port=5000, debug=False)
