# -*- coding: utf-8 -*-
import os
import time
import json
import random
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List
from queue import Queue

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
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

# ================== 2. АККАУНТЫ ==================
accounts = [
    {"username": "from1", "password": "2255NNbb"},
    {"username": "from2", "password": "2244NNrr"},
]

# ================== 3. ПУЛ БРАУЗЕРОВ ==================
class BrowserPool:
    def __init__(self):
        self.browsers: List[Dict] = []
        self.lock = Lock()
        self.playwright = None
        self.current_index = 0
        
    def init(self):
        """Инициализация браузеров"""
        print("\n" + "="*60)
        print("🌐 Инициализация пула браузеров...")
        print("="*60)
        
        self.playwright = sync_playwright().start()
        
        for acc in accounts:
            try:
                print(f"\n[BROWSER] Запуск для {acc['username']}...")
                
                browser = self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="ru-RU",
                    timezone_id="Asia/Almaty",
                )
                
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                """)
                
                # Логин
                print(f"[BROWSER] Логин {acc['username']}...")
                page.goto(LOGIN_PAGE, timeout=30000)
                page.wait_for_timeout(2000)
                page.fill(LOGIN_SELECTOR, acc['username'])
                page.wait_for_timeout(400)
                page.fill(PASSWORD_SELECTOR, acc['password'])
                page.wait_for_timeout(400)
                page.click(SIGN_IN_BUTTON_SELECTOR)
                page.wait_for_timeout(3000)
                
                # Проверяем что залогинились
                try:
                    page.wait_for_url("**/dashboard", timeout=10000)
                    print(f"[BROWSER] ✅ {acc['username']} авторизован")
                except:
                    print(f"[BROWSER] ⚠️ {acc['username']} - возможно не перешёл на dashboard")
                
                self.browsers.append({
                    "username": acc['username'],
                    "browser": browser,
                    "context": context,
                    "page": page,
                    "last_used": time.time(),
                    "request_count": 0
                })
                
            except Exception as e:
                print(f"[BROWSER] ❌ Ошибка для {acc['username']}: {e}")
                traceback.print_exc()
        
        print(f"\n[POOL] ✅ Инициализировано {len(self.browsers)} браузеров")
        print("="*60 + "\n")
    
    def get_next_page(self) -> Optional[Dict]:
        """Получить следующий браузер по кругу"""
        with self.lock:
            if not self.browsers:
                return None
            
            browser_data = self.browsers[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.browsers)
            browser_data['last_used'] = time.time()
            browser_data['request_count'] += 1
            
            return browser_data
    
    def request(self, endpoint: str, params: dict = None):
        """Выполнить запрос через браузер"""
        browser_data = self.get_next_page()
        if not browser_data:
            return "❌ Нет доступных браузеров."
        
        page: Page = browser_data['page']
        username = browser_data['username']
        
        try:
            print(f"[REQUEST] {endpoint} | Browser: {username} | Count: {browser_data['request_count']}")
            
            # Устанавливаем Referer
            if "/by-address" in endpoint:
                referer = f"{BASE_URL}/person-search"
            else:
                referer = f"{BASE_URL}/search"
            
            # Делаем запрос через Playwright API
            url = endpoint if endpoint.startswith("http") else BASE_URL + endpoint
            
            response = page.request.get(
                url,
                params=params,
                headers={"Referer": referer}
            )
            
            status = response.status
            print(f"[REQUEST] Status: {status}")
            
            if status == 200:
                print(f"[REQUEST] ✅ Успешно")
                return response
            elif status == 401:
                print(f"[REQUEST] ⚠️ 401 - нужен повторный логин для {username}")
                # Пробуем переавторизоваться
                self._reauth_browser(browser_data)
                # Повторяем запрос
                response = page.request.get(url, params=params, headers={"Referer": referer})
                return response
            elif status == 404:
                print(f"[REQUEST] ⚠️ 404 - не найдено")
                return response
            else:
                print(f"[REQUEST] ⚠️ Неожиданный статус: {status}")
                return response
                
        except Exception as e:
            print(f"[REQUEST] ❌ Error: {e}")
            traceback.print_exc()
            return f"❌ Ошибка запроса: {e}"
    
    def _reauth_browser(self, browser_data: Dict):
        """Переавторизация браузера"""
        try:
            username = browser_data['username']
            page = browser_data['page']
            
            # Находим аккаунт
            acc = next((a for a in accounts if a['username'] == username), None)
            if not acc:
                return
            
            print(f"[REAUTH] Переавторизация {username}...")
            
            # Переходим на страницу логина
            page.goto(LOGIN_PAGE, timeout=30000)
            page.wait_for_timeout(2000)
            page.fill(LOGIN_SELECTOR, acc['username'])
            page.wait_for_timeout(400)
            page.fill(PASSWORD_SELECTOR, acc['password'])
            page.wait_for_timeout(400)
            page.click(SIGN_IN_BUTTON_SELECTOR)
            page.wait_for_timeout(3000)
            
            print(f"[REAUTH] ✅ {username} переавторизован")
            
        except Exception as e:
            print(f"[REAUTH] ❌ Ошибка: {e}")
    
    def close_all(self):
        """Закрыть все браузеры"""
        print("\n[POOL] Закрытие браузеров...")
        for b in self.browsers:
            try:
                b['browser'].close()
            except:
                pass
        if self.playwright:
            self.playwright.stop()
        self.browsers = []
        print("[POOL] ✅ Все браузеры закрыты")
    
    def get_stats(self):
        """Получить статистику браузеров"""
        return {
            "count": len(self.browsers),
            "browsers": [
                {
                    "username": b['username'],
                    "request_count": b['request_count'],
                    "last_used": int(time.time() - b['last_used'])
                }
                for b in self.browsers
            ]
        }

# Глобальный пул
browser_pool = BrowserPool()

# ================== 4. CRM GET ЧЕРЕЗ PLAYWRIGHT ==================
def crm_get(endpoint: str, params: dict = None):
    """Выполнить GET запрос через Playwright"""
    return browser_pool.request(endpoint, params)

# ================== 5. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    """Обработчик очереди запросов"""
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(1.5, 2.0))
        except Exception as e:
            print(f"[WORKER ERROR] {e}")
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
    """Добавить запрос в очередь"""
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

# ================== 6. ALLOWED USERS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    """Загрузить список разрешённых пользователей"""
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
    """Периодическое обновление списка пользователей"""
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 7. ПОИСК ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    
    # resp теперь это Playwright Response объект
    if resp.status == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status != 200:
        return f"❌ Ошибка {resp.status}"
    
    try:
        p = resp.json()
        return (
            f"👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 Дата рождения: {p.get('birthday','')}\n"
            f"🚻 Пол: {p.get('sex','')}\n"
            f"📱 Телефон: {p.get('phone_number','')}\n"
            f"🏠 Адрес: {p.get('address','')}"
        )
    except Exception as e:
        return f"❌ Ошибка обработки ответа: {e}"

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = enqueue_crm_get("/api/v2/person-search/by-phone", params={"phone": clean})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status != 200:
        return f"❌ Ошибка {resp.status}"
    
    try:
        data = resp.json()
        if not data:
            return f"⚠️ Ничего не найдено по номеру {phone}"
        p = data[0] if isinstance(data, list) else data
        return (
            f"👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 Дата рождения: {p.get('birthday','')}\n"
            f"🚻 Пол: {p.get('sex','')}\n"
            f"📱 Телефон: {p.get('phone_number','')}\n"
            f"🏠 Адрес: {p.get('address','')}"
        )
    except Exception as e:
        return f"❌ Ошибка обработки ответа: {e}"

def search_by_fio(text: str):
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}
    
    r = enqueue_crm_get("/api/v2/person-search/smart", params=q)
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status == 404:
        return "⚠️ Ничего не найдено."
    if resp.status != 200:
        return f"❌ Ошибка {resp.status}"
    
    try:
        data = resp.json()
        if not data:
            return "⚠️ Ничего не найдено."
        if isinstance(data, dict):
            data = [data]
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
    except Exception as e:
        return f"❌ Ошибка обработки ответа: {e}"

def search_by_address(address: str):
    params = {"address": address, "exact_match": "false", "limit": 50}
    r = enqueue_crm_get("/api/v2/person-search/by-address", params=params)
    if r["status"] != "ok":
        return "⌛ В очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status != 200:
        return f"❌ Ошибка {resp.status}"
    
    try:
        data = resp.json()
        if isinstance(data, dict):
            data = [data]
        results = []
        for i, p in enumerate(data[:10], start=1):
            results.append(f"{i}. {p.get('snf','')} — {p.get('address','')}")
        return "\n".join(results)
    except Exception as e:
        return f"❌ Ошибка обработки ответа: {e}"

# ================== 8. FLASK + СЕССИИ ==================
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
        print(f"[SESSION] ❌ Попытка перезапуска сессии {user_id}")
        return jsonify({"error": "Сессия уже активна. Повторите позже."}), 403

    if existing and (now - existing["created"]) >= SESSION_TTL:
        del active_sessions[user_id]
        print(f"[SESSION] ⏰ Истекшая сессия {user_id} удалена")

    session_token = f"{user_id}-{int(now)}-{random.randint(1000,9999)}"
    active_sessions[user_id] = {
        "token": session_token,
        "created": now
    }

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
            return jsonify({"error": "Сессия не найдена. Авторизуйтесь заново."}), 403

        if session["token"] != token:
            print(f"[SESSION] ⚠️ Несовпадение токена: uid={uid}")
            return jsonify({"error": "Сессия недействительна."}), 403

        if time.time() - session["created"] > SESSION_TTL:
            del active_sessions[uid]
            print(f"[SESSION] ⏰ Истёк срок сессии {uid}")
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

@app.route('/api/browser-stats', methods=['GET'])
def browser_stats():
    """Статистика браузеров"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(browser_pool.get_stats())

@app.route('/api/restart-browsers', methods=['POST'])
def restart_browsers():
    """Перезапустить браузеры"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    def restart_async():
        try:
            print("[RESTART] Перезапуск браузеров...")
            browser_pool.close_all()
            time.sleep(3)
            browser_pool.init()
            print("[RESTART] ✅ Готово")
        except Exception as e:
            print(f"[RESTART] ❌ Ошибка: {e}")
    
    Thread(target=restart_async, daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting..."})

# ================== 9. ЗАПУСК ==================
def init_and_run():
    """Инициализация и запуск"""
    print("=" * 60)
    print("🚀 Запуск сервера с Playwright пулом")
    print("=" * 60)
    
    # Загрузка пользователей
    fetch_allowed_users()
    Thread(target=periodic_fetch, daemon=True).start()
    
    # Инициализация браузеров
    browser_pool.init()
    
    # Очистка сессий
    def cleanup_sessions():
        while True:
            now = time.time()
            expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
            for uid in expired:
                del active_sessions[uid]
                print(f"[SESSION] 🧹 Удалена сессия {uid}")
            time.sleep(300)
    
    Thread(target=cleanup_sessions, daemon=True).start()
    
    # Keep-alive для браузеров
    def keep_alive():
        while True:
            time.sleep(300)
            print(f"[KEEPALIVE] Браузеров: {len(browser_pool.browsers)}")
    
    Thread(target=keep_alive, daemon=True).start()
    
    print("=" * 60)
    print("✅ Сервер готов к работе")
    print("=" * 60)
    
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    try:
        init_and_run()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Остановка сервера...")
        browser_pool.close_all()
    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        traceback.print_exc()
        browser_pool.close_all()
