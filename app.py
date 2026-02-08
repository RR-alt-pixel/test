# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
import hashlib
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

# Фиксированный User-Agent для стабильности
FIXED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

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
    // Пытаемся найти fingerprint в разных местах
    const finders = [
        // 1. В глобальных переменных
        () => {
            const keys = ['deviceFingerprint', '__deviceFingerprint', 'fingerprint', 'device_fingerprint', '__fp', 'fp'];
            for (const key of keys) {
                if (window[key] && typeof window[key] === 'string' && window[key].length >= 64) {
                    return {source: 'window.' + key, value: window[key]};
                }
            }
            return null;
        },
        
        // 2. В localStorage
        () => {
            try {
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && (key.includes('fingerprint') || key.includes('device') || key.includes('fp'))) {
                        const value = localStorage.getItem(key);
                        if (value && value.length >= 64) {
                            return {source: 'localStorage.' + key, value: value};
                        }
                    }
                }
            } catch(e) {}
            return null;
        },
        
        // 3. В sessionStorage
        () => {
            try {
                for (let i = 0; i < sessionStorage.length; i++) {
                    const key = sessionStorage.key(i);
                    if (key && (key.includes('fingerprint') || key.includes('device') || key.includes('fp'))) {
                        const value = sessionStorage.getItem(key);
                        if (value && value.length >= 64) {
                            return {source: 'sessionStorage.' + key, value: value};
                        }
                    }
                }
            } catch(e) {}
            return null;
        },
        
        // 4. В скрытых полях
        () => {
            const inputs = document.querySelectorAll('input[type="hidden"], input[name*="fingerprint"], input[name*="device"]');
            for (const input of inputs) {
                const value = input.value;
                if (value && value.length >= 64) {
                    return {source: 'input.' + (input.name || input.id), value: value};
                }
            }
            return null;
        },
        
        // 5. В meta-тегах
        () => {
            const metas = document.querySelectorAll('meta[name*="fingerprint"], meta[name*="device"]');
            for (const meta of metas) {
                if (meta.content && meta.content.length >= 64) {
                    return {source: 'meta.' + meta.name, value: meta.content};
                }
            }
            return null;
        }
    ];
    
    for (const finder of finders) {
        const result = finder();
        if (result) {
            console.log('Fingerprint найден в:', result.source);
            return result.value;
        }
    }
    
    console.log('Fingerprint не найден, будет создан искусственный');
    return null;
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
                    session_data = s.get("session_data", {})
                    meta.append({
                        "username": s.get("username"),
                        "user_agent": session_data.get("user_agent"),
                        "device_fingerprint": session_data.get("device_fingerprint"),
                        "cookie_header": session_data.get("cookie_header"),
                        "time": s.get("time"),
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
                if cmd == "simple_login":
                    resp = self._cmd_simple_login(payload)
                elif cmd == "api_request_get":
                    resp = self._cmd_api_request_get(payload)
                elif cmd == "get_browser_context":
                    resp = self._cmd_get_browser_context(payload)
                elif cmd == "close_browser":
                    resp = self._cmd_close_browser(payload)
                else:
                    resp = {"ok": False, "error": f"unknown_cmd:{cmd}"}
            except Exception as e:
                resp = {"ok": False, "error": str(e), "trace": traceback.format_exc()}
            finally:
                box["resp"] = resp
                box["done"].set()
                self.q.task_done()

    def _cmd_simple_login(self, payload: dict) -> dict:
        """Логин и получение всех данных"""
        username = payload.get("username")
        password = payload.get("password")
        
        if not self._pw:
            return {"ok": False, "error": "playwright_not_ready"}

        browser = None
        try:
            # Запускаем браузер с детальными настройками
            browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    "--disable-features=BlockInsecurePrivateNetworkRequests",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                ],
                timeout=60000
            )
            
            # Создаём контекст
            context = browser.new_context(
                user_agent=FIXED_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Asia/Almaty",
                ignore_https_errors=True,
                permissions=["geolocation"],
                extra_http_headers={
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                }
            )
            
            page: Page = context.new_page()
            
            # Инжектим скрипты для обхода защиты
            page.add_init_script("""
                // Скрываем автоматизацию
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                
                // Подменяем плагины
                const originalPlugins = navigator.plugins;
                Object.defineProperty(navigator, 'plugins', {
                    get: () => {
                        if (originalPlugins.length === 0) {
                            return [1, 2, 3, 4, 5];
                        }
                        return originalPlugins;
                    }
                });
                
                // Подменяем languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['ru-RU', 'ru', 'en-US', 'en']
                });
                
                // Подменяем permissions API
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({state: Notification.permission}) :
                        originalQuery(parameters)
                );
                
                // Добавляем chrome
                if (!window.chrome) {
                    window.chrome = {runtime: {}};
                }
            """)

            print(f"[PLW-SIMPLE] Переход на {LOGIN_PAGE}")
            
            # Идём на страницу логина
            page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            # Пытаемся найти реальный fingerprint
            device_fp = page.evaluate(FINGERPRINT_EXTRACTOR)
            
            if not device_fp:
                # Генерируем стабильный fingerprint на основе постоянных данных
                fp_seed = f"{FIXED_USER_AGENT}{username}{'1920x1080'}{'Asia/Almaty'}{'ru-RU'}"
                device_fp = hashlib.sha256(fp_seed.encode()).hexdigest()
                print(f"[PLW-SIMPLE] Создан стабильный fingerprint: {device_fp[:20]}...")
            else:
                print(f"[PLW-SIMPLE] Найден реальный fingerprint: {device_fp[:20]}...")
            
            # Заполняем форму
            page.fill(LOGIN_SELECTOR, username)
            page.wait_for_timeout(1000)
            page.fill(PASSWORD_SELECTOR, password)
            page.wait_for_timeout(1000)
            
            # Кликаем кнопку
            page.click(SIGN_IN_BUTTON_SELECTOR)
            
            # Ждём успешного входа
            try:
                page.wait_for_url("**/dashboard**", timeout=15000)
                print(f"[PLW-SIMPLE] ✅ Успешный вход")
            except:
                current_url = page.url
                print(f"[PLW-SIMPLE] Текущий URL: {current_url}")
                if "dashboard" not in current_url:
                    # Проверяем ошибки
                    error_text = page.evaluate("""() => {
                        const errorEl = document.querySelector('[class*="error"], [class*="alert"]');
                        return errorEl ? errorEl.textContent : 'Неизвестная ошибка';
                    }""")
                    raise Exception(f"Ошибка входа: {error_text}")
            
            # Ждём полной загрузки
            page.wait_for_timeout(5000)
            
            # Получаем все куки
            cookies = context.cookies()
            
            # Формируем строку кук
            cookie_parts = []
            for cookie in cookies:
                cookie_parts.append(f"{cookie['name']}={cookie['value']}")
            
            cookie_header = "; ".join(cookie_parts)
            
            # Формируем словарь кук для requests
            cookies_dict = {c['name']: c['value'] for c in cookies}
            
            # Получаем текущий URL и заголовки
            current_url = page.url
            
            print(f"[PLW-SIMPLE] Получено {len(cookies)} кук, текущий URL: {current_url}")
            
            # Сохраняем всё
            session_data = {
                "username": username,
                "user_agent": FIXED_USER_AGENT,
                "device_fingerprint": device_fp,
                "cookie_header": cookie_header,
                "cookies_dict": cookies_dict,
                "cookies": cookies,
                "browser": browser,
                "context": context,
                "page": page,
                "time": int(time.time()),
            }
            
            # Не закрываем браузер! Он нам нужен для запросов
            print(f"[PLW-SIMPLE] ✅ {username} авторизован")
            return {"ok": True, "session_data": session_data}

        except Exception as e:
            print(f"[PLW-SIMPLE] ❌ Ошибка: {e}")
            traceback.print_exc()
            try:
                if browser:
                    browser.close()
            except:
                pass
            return {"ok": False, "error": str(e)}

    def _cmd_api_request_get(self, payload: dict) -> dict:
        """Делаем запрос через Playwright с реальными куками и заголовками"""
        session_data = payload.get("session_data")
        url = payload.get("url")
        
        if not session_data or not url:
            return {"ok": False, "error": "missing_session_data_or_url"}
        
        page = session_data.get("page")
        if not page:
            return {"ok": False, "error": "page_not_available"}
        
        try:
            # Делаем запрос через evaluate с fetch
            js_code = """
            async (args) => {
                const { url, deviceFp, cookies } = args;
                
                try {
                    // Формируем все заголовки как в браузере
                    const headers = {
                        'accept': 'application/json',
                        'accept-encoding': 'gzip, deflate, br, zstd',
                        'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                        'content-type': 'application/json',
                        'priority': 'u=1, i',
                        'referer': 'https://pena.rest/dashboard/search',
                        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
                        'sec-ch-ua-mobile': '?0',
                        'sec-ch-ua-platform': '"Windows"',
                        'sec-fetch-dest': 'empty',
                        'sec-fetch-mode': 'cors',
                        'sec-fetch-site': 'same-origin',
                        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                        'x-device-fingerprint': deviceFp,
                        'x-requested-with': 'XMLHttpRequest'
                    };
                    
                    // Добавляем куки в заголовки
                    if (cookies) {
                        headers['cookie'] = cookies;
                    }
                    
                    console.log('Отправляю запрос на:', url);
                    
                    const response = await fetch(url, {
                        method: 'GET',
                        headers: headers,
                        credentials: 'include', // Важно! Отправляем куки
                        mode: 'cors',
                        cache: 'no-cache'
                    });
                    
                    const text = await response.text();
                    console.log('Статус ответа:', response.status);
                    console.log('Длина ответа:', text.length);
                    
                    let jsonData = null;
                    try {
                        jsonData = JSON.parse(text);
                    } catch(e) {
                        // Не JSON
                    }
                    
                    return {
                        ok: response.ok,
                        status: response.status,
                        text: text,
                        json: jsonData,
                        headers: Object.fromEntries(response.headers.entries())
                    };
                    
                } catch (error) {
                    console.error('Ошибка fetch:', error);
                    return {
                        ok: false,
                        status: 0,
                        text: String(error),
                        json: null,
                        error: String(error)
                    };
                }
            }
            """
            
            result = page.evaluate(js_code, {
                "url": url,
                "deviceFp": session_data.get("device_fingerprint", ""),
                "cookies": session_data.get("cookie_header", "")
            })
            
            return {"ok": True, "result": result}
            
        except Exception as e:
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

    def _cmd_get_browser_context(self, payload: dict) -> dict:
        """Получаем контекст браузера для прямых запросов"""
        session_data = payload.get("session_data")
        if not session_data:
            return {"ok": False, "error": "no_session_data"}
        
        context = session_data.get("context")
        if not context:
            return {"ok": False, "error": "no_context"}
        
        try:
            # Получаем текущие куки
            cookies = context.cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies}
            
            return {
                "ok": True,
                "cookies": cookies_dict,
                "cookies_count": len(cookies),
                "current_url": session_data.get("page", {}).url if session_data.get("page") else "unknown"
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _cmd_close_browser(self, payload: dict) -> dict:
        """Закрываем браузер"""
        session_data = payload.get("session_data")
        if not session_data:
            return {"ok": False, "error": "no_session_data"}
        
        browser = session_data.get("browser")
        if browser:
            try:
                browser.close()
                return {"ok": True, "message": "Browser closed"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True, "message": "No browser to close"}

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(30)

# ================== 5. ПУЛ СЕССИЙ ==================
def init_token_pool_playwright():
    global pw_sessions, pw_cycle

    print("[POOL] 🔄 Логин через Playwright...")
    
    new_sessions = []
    for acc in accounts:
        print(f"[POOL] Логин аккаунта {acc['username']}...")
        
        resp = pw_manager._rpc("simple_login", {
            "username": acc["username"],
            "password": acc["password"]
        }, timeout=180)
        
        if resp.get("ok"):
            session_data = resp.get("session_data", {})
            new_sessions.append({
                "username": acc["username"],
                "password": acc["password"],
                "session_data": session_data,
                "time": int(time.time())
            })
            print(f"[POOL] ✅ Аккаунт {acc['username']} успешно авторизован")
        else:
            print(f"[POOL] ❌ Ошибка авторизации {acc['username']}: {resp.get('error')}")

    with PW_SESSIONS_LOCK:
        pw_sessions = new_sessions
        pw_cycle = itertools.cycle(pw_sessions) if pw_sessions else None

    if pw_sessions:
        print(f"[POOL] ✅ init ok, sessions={len(pw_sessions)}")
        for s in pw_sessions:
            fp = s.get("session_data", {}).get("device_fingerprint", "")[:20]
            cookies_count = len(s.get("session_data", {}).get("cookies", []))
            print(f"[POOL]   - {s['username']}: FP={fp}..., Cookies={cookies_count}")
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
            fp = s.get("session_data", {}).get("device_fingerprint", "")[:20]
            print(f"[POOL] 🔁 Используется сессия {s['username']} (FP: {fp}...)")
            return s
        except StopIteration:
            pw_cycle = itertools.cycle(pw_sessions)
            s = next(pw_cycle)
            return s

def refresh_token_for_username(username: str) -> Optional[Dict]:
    global pw_sessions, pw_cycle
    try:
        print(f"[AUTH] 🔄 Обновление сессии для {username}...")
        
        # Находим аккаунт
        acc = next((a for a in accounts if a["username"] == username), None)
        if not acc:
            print(f"[AUTH] ❌ Аккаунт {username} не найден")
            return None
        
        # Закрываем старый браузер если есть
        with PW_SESSIONS_LOCK:
            old_sess = next((s for s in pw_sessions if s.get("username") == username), None)
            if old_sess and old_sess.get("session_data"):
                pw_manager._rpc("close_browser", {"session_data": old_sess.get("session_data")})
        
        # Логинимся заново
        resp = pw_manager._rpc("simple_login", {
            "username": acc["username"],
            "password": acc["password"]
        }, timeout=120)
        
        if not resp.get("ok"):
            print(f"[AUTH] ❌ refresh failed: {resp.get('error')}")
            return None
        
        session_data = resp.get("session_data", {})
        new_sess = {
            "username": acc["username"],
            "password": acc["password"],
            "session_data": session_data,
            "time": int(time.time())
        }
        
        with PW_SESSIONS_LOCK:
            # Удаляем старую сессию
            pw_sessions = [s for s in pw_sessions if s.get("username") != username]
            # Добавляем новую
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

# ================== 8. CRM GET (ИСПРАВЛЕННАЯ) ==================
def crm_get(endpoint: str, params: dict = None):
    """Делаем запрос через Playwright с полной отладкой"""
    sess = get_next_session()
    if not sess:
        return "❌ Нет сессий Playwright."

    url = _build_url(endpoint, params=params)
    session_data = sess.get("session_data", {})
    username = sess["username"]
    device_fp = session_data.get("device_fingerprint", "")[:20] + "..."

    print(f"[CRM] {username} -> {endpoint} (FP: {device_fp})")
    print(f"[CRM] URL: {url}")

    # Делаем запрос
    resp = pw_manager._rpc("api_request_get", {
        "session_data": session_data,
        "url": url
    }, timeout=60)
    
    if not resp.get("ok"):
        error_msg = resp.get('error', 'unknown')
        print(f"[AUTH] {username} → API error: {error_msg}")
        
        # Пробуем обновить сессию
        new_sess = refresh_token_for_username(username)
        if not new_sess:
            return f"❌ Ошибка CRM: {error_msg}"
        
        # Повторяем запрос
        new_session_data = new_sess.get("session_data", {})
        resp = pw_manager._rpc("api_request_get", {
            "session_data": new_session_data,
            "url": url
        }, timeout=60)
        
        if not resp.get("ok"):
            return f"❌ Ошибка CRM после обновления: {resp.get('error')}"
    
    result = resp.get("result", {})
    status = int(result.get("status", 0) or 0)
    txt = result.get("text", "") or ""
    jsn = result.get("json", None)
    
    # ВЫВОДИМ ПОДРОБНУЮ ИНФОРМАЦИЮ ОБ ОШИБКЕ
    print(f"[CRM] Ответ: {status} ({len(txt)} chars)")
    
    if status in (401, 403):
        print(f"[CRM-DEBUG] Текст ошибки {status}: {txt[:500]}")
        
        # Проверяем, что именно в ответе
        if "fingerprint" in txt.lower():
            print("[CRM-DEBUG] Ошибка связана с fingerprint!")
        if "auth" in txt.lower():
            print("[CRM-DEBUG] Ошибка аутентификации")
        if "csrf" in txt.lower():
            print("[CRM-DEBUG] Ошибка CSRF токена")
        
        print(f"[AUTH] {username} → {status} → Пробуем обновить сессию")
        
        new_sess = refresh_token_for_username(username)
        if new_sess:
            new_session_data = new_sess.get("session_data", {})
            resp2 = pw_manager._rpc("api_request_get", {
                "session_data": new_session_data,
                "url": url
            }, timeout=60)
            
            if resp2.get("ok"):
                result2 = resp2.get("result", {})
                status = int(result2.get("status", 0) or 0)
                txt = result2.get("text", "") or ""
                jsn = result2.get("json", None)
                print(f"[CRM] После обновления: {status}")
                if status in (401, 403):
                    print(f"[CRM-DEBUG] Текст после обновления: {txt[:500]}")
    
    return ResponseLike(status_code=status, text=txt, json_data=jsn)

# ================== 9. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 60

def crm_worker():
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(2.0, 3.0))
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
        f"📱 Телефон: {p.get('phone_number','')}</code>\n"
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
            session_data = s.get("session_data", {})
            sessions_info.append({
                "username": s.get("username"),
                "device_fingerprint": session_data.get("device_fingerprint", "")[:20] + "...",
                "cookie_header_length": len(session_data.get("cookie_header", "")),
                "cookies_count": len(session_data.get("cookies", [])),
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
        init_token_pool_playwright()
        return jsonify({"ok": True, "message": "Весь пул сессий переинициализирован"})

@app.route('/api/debug/test-request', methods=['POST'])
def debug_test_request():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    endpoint = data.get('endpoint', '/api/v3/search/fio')
    params = data.get('params', {'surname': 'ТЕСТ', 'limit': 5})
    
    # Прямой запрос без очереди
    sess = get_next_session()
    if not sess:
        return jsonify({"error": "Нет сессий"})
    
    url = _build_url(endpoint, params)
    session_data = sess.get("session_data", {})
    
    resp = pw_manager._rpc("api_request_get", {
        "session_data": session_data,
        "url": url
    }, timeout=60)
    
    if resp.get("ok"):
        result = resp.get("result", {})
        return jsonify({
            "status": result.get("status"),
            "text_length": len(result.get("text", "")),
            "text_preview": result.get("text", "")[:500],
            "json": result.get("json"),
            "headers": result.get("headers")
        })
    else:
        return jsonify({"error": resp.get("error")})

# ================== 13. ЗАПУСК ==================
print("🚀 Запуск API...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()

# Даём немного времени перед инициализацией
time.sleep(2)

# Удаляем старый tokens.json если есть
try:
    if os.path.exists(TOKENS_FILE):
        os.remove(TOKENS_FILE)
        print(f"[INIT] Удалён старый файл {TOKENS_FILE}")
except:
    pass

# Инициализируем пул сессий
print("[INIT] Инициализация пула сессий...")
init_token_pool_playwright()

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
    print(f"🔧 Тестовый запрос: curl -X POST -H 'Authorization: Bearer {SECRET_TOKEN}' -H 'Content-Type: application/json' -d '{{\"endpoint\":\"/api/v3/search/fio\",\"params\":{{\"surname\":\"ТЕСТ\",\"limit\":2}}}}' http://localhost:5000/api/debug/test-request")
    app.run(host="0.0.0.0", port=5000, debug=False)
