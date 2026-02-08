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
from urllib.parse import urlencode, urljoin

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]  # Будет обновлено при запуске

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

# ================== 2. АККАУНТЫ ==================
accounts = [
    {"username": "klon9", "password": "7755SSaa"},
]

# ================== 3. ПУЛ СЕССИЙ ==================
pw_sessions: List[Dict[str, Any]] = []
pw_cycle = None
PW_SESSIONS_LOCK = Lock()

class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

# ================== 4. PLAYWRIGHT MANAGER ==================
class PWManager:
    def __init__(self):
        self._pw = None
        self.ready = Event()
        self.started = False
        
    def start(self):
        """Запускаем Playwright"""
        if not self.started:
            try:
                self._pw = sync_playwright().start()
                self.started = True
                self.ready.set()
                print("[PW] ✅ Playwright запущен")
            except Exception as e:
                print(f"[PW] ❌ Ошибка запуска: {e}")
                traceback.print_exc()
                self.ready.set()
    
    def create_session(self, username: str, password: str) -> Optional[Dict]:
        """Создаем новую сессию"""
        if not self._pw:
            print("[SESSION] ❌ Playwright не инициализирован")
            return None
        
        print(f"[SESSION] Создаем сессию для {username}")
        
        browser = None
        try:
            browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
                timeout=60000
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            
            page = context.new_page()
            
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)
            
            # Логинимся
            print(f"[SESSION] Логин {username}...")
            page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            
            page.fill(LOGIN_SELECTOR, username)
            time.sleep(0.5)
            page.fill(PASSWORD_SELECTOR, password)
            time.sleep(0.5)
            
            page.click(SIGN_IN_BUTTON_SELECTOR)
            time.sleep(3)
            
            # Проверяем успешность
            current_url = page.url
            print(f"[SESSION] Текущий URL: {current_url}")
            
            if "dashboard" not in current_url:
                print("[SESSION] ⚠️ Dashboard не найден, пробуем перейти...")
                page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=10000)
                time.sleep(2)
            
            # Переходим на страницу поиска
            search_url = urljoin(BASE_URL, "/dashboard/search")
            page.goto(search_url, wait_until="networkidle", timeout=30000)
            time.sleep(3)
            
            # Получаем куки
            cookies = context.cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies}
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            print(f"[SESSION] Получено {len(cookies)} кук")
            
            # Генерируем fingerprint
            fingerprint = hashlib.sha256(f"{username}{int(time.time())}{random.randint(1000, 9999)}".encode()).hexdigest()
            print(f"[SESSION] Fingerprint: {fingerprint[:20]}...")
            
            # Формируем заголовки
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "x-device-fingerprint": fingerprint,
                "x-requested-with": "XMLHttpRequest",
                "referer": search_url,
                "cookie": cookie_header,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            
            # Создаем объект сессии
            session_data = {
                "username": username,
                "fingerprint": fingerprint,
                "cookies": cookies_dict,
                "cookie_header": cookie_header,
                "headers": headers,
                "context": context,
                "browser": browser,
                "page": page,
                "created_at": int(time.time()),
                "last_used": int(time.time()),
                "search_url": search_url
            }
            
            print(f"[SESSION] ✅ Сессия для {username} создана")
            return session_data
                
        except Exception as e:
            print(f"[SESSION] ❌ Ошибка создания сессии: {e}")
            traceback.print_exc()
            if browser:
                try:
                    browser.close()
                except:
                    pass
            return None
    
    def make_request(self, session_data: Dict, endpoint: str, params: dict = None):
        """Делаем API запрос"""
        try:
            url = urljoin(BASE_URL, endpoint)
            if params:
                query_string = urlencode(params, doseq=True)
                url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
            
            headers = session_data["headers"].copy()
            headers["referer"] = session_data.get("search_url", urljoin(BASE_URL, "/dashboard/search"))
            
            response = session_data["context"].request.get(url, headers=headers, timeout=30000)
            
            session_data["last_used"] = int(time.time())
            
            result = {
                "status": response.status,
                "text": response.text(),
                "success": response.status == 200
            }
            
            if response.status == 200:
                try:
                    result["json"] = response.json()
                except:
                    result["json"] = None
            else:
                result["error"] = response.text()[:500]
            
            return result
            
        except Exception as e:
            print(f"[REQUEST] ❌ Ошибка запроса: {e}")
            return {"error": str(e), "success": False}

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(30)

# ================== 5. ПУЛ СЕССИЙ ==================
def init_token_pool():
    global pw_sessions, pw_cycle

    print("\n" + "=" * 60)
    print("🔄 ИНИЦИАЛИЗАЦИЯ ПУЛА СЕССИЙ")
    print("=" * 60)
    
    new_sessions = []
    for acc in accounts:
        print(f"[POOL] Создаем сессию для {acc['username']}...")
        
        session_data = pw_manager.create_session(acc["username"], acc["password"])
        
        if session_data:
            new_sessions.append(session_data)
            print(f"[POOL] ✅ Сессия создана")
        else:
            print(f"[POOL] ❌ Не удалось создать сессию")

    with PW_SESSIONS_LOCK:
        pw_sessions = new_sessions
        pw_cycle = itertools.cycle(pw_sessions) if pw_sessions else None

    if pw_sessions:
        print(f"\n[POOL] ✅ Пул инициализирован!")
        print(f"[POOL] Активных сессий: {len(pw_sessions)}")
    else:
        print("\n[POOL] ⚠️ ПУСТОЙ ПУЛ СЕССИЙ!")
    
    print("=" * 60)
    return len(pw_sessions) > 0

def get_next_session() -> Optional[Dict]:
    global pw_sessions, pw_cycle

    if not pw_sessions:
        if not init_token_pool():
            return None

    with PW_SESSIONS_LOCK:
        if pw_cycle is None:
            pw_cycle = itertools.cycle(pw_sessions)
        try:
            s = next(pw_cycle)
            return s
        except StopIteration:
            pw_cycle = itertools.cycle(pw_sessions)
            s = next(pw_cycle)
            return s

def refresh_session(username: str) -> Optional[Dict]:
    """Обновляем сессию"""
    global pw_sessions, pw_cycle
    
    try:
        print(f"[REFRESH] 🔄 Обновление сессии для {username}...")
        
        acc = next((a for a in accounts if a["username"] == username), None)
        if not acc:
            return None
        
        with PW_SESSIONS_LOCK:
            old_session = next((s for s in pw_sessions if s.get("username") == username), None)
            if old_session and old_session.get("browser"):
                try:
                    old_session["browser"].close()
                except:
                    pass
        
        new_session = pw_manager.create_session(acc["username"], acc["password"])
        
        if new_session:
            with PW_SESSIONS_LOCK:
                pw_sessions = [s for s in pw_sessions if s.get("username") != username]
                pw_sessions.append(new_session)
                pw_cycle = itertools.cycle(pw_sessions)
            
            print(f"[REFRESH] ✅ Сессия обновлена")
            return new_session
        else:
            print(f"[REFRESH] ❌ Не удалось обновить сессию")
            return None
            
    except Exception as e:
        print(f"[REFRESH ERROR] {e}")
        return None

# ================== 6. CRM GET ==================
def crm_get(endpoint: str, params: dict = None):
    """Основная функция для API запросов"""
    session = get_next_session()
    if not session:
        return ResponseLike(500, "❌ Нет доступных сессий")
    
    username = session.get("username", "unknown")
    
    # Делаем запрос
    result = pw_manager.make_request(session, endpoint, params)
    
    if result.get("success"):
        return ResponseLike(
            status_code=result["status"],
            text=result["text"],
            json_data=result.get("json")
        )
    else:
        # Если ошибка аутентификации, пробуем обновить сессию
        if result.get("status") in [401, 403]:
            print(f"[CRM] ❌ Ошибка аутентификации, обновляем сессию...")
            new_session = refresh_session(username)
            
            if new_session:
                result = pw_manager.make_request(new_session, endpoint, params)
                if result.get("success"):
                    return ResponseLike(
                        status_code=result["status"],
                        text=result["text"],
                        json_data=result.get("json")
                    )
        
        return ResponseLike(
            status_code=result.get("status", 500),
            text=result.get("error", result.get("text", "Unknown error")),
            json_data=None
        )

# ================== 7. ОЧЕРЕДЬ ==================
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

# ================== 8. ПОИСКОВЫЕ ФУНКЦИИ ==================
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
        return f"❌ Ошибка {resp.status_code}"
    
    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    
    results = []
    for i, p in enumerate(data[:5], 1):
        result = f"{i}. 🧾 <b>ИИН: {p.get('iin','')}</b>"
        if p.get('snf'):
            result += f"\n   👤 {p.get('snf','')}"
        if p.get('phone_number'):
            result += f"\n   📱 {p.get('phone_number','')}"
        if p.get('birthday'):
            result += f"\n   📅 {p.get('birthday','')}"
        results.append(result)
    
    return "\n\n".join(results)

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    
    r = enqueue_crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
    
    data = resp.json()
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    results = []
    for i, p in enumerate(data[:5], 1):
        result = f"{i}. 📱 <b>Телефон: {p.get('phone_number','')}</b>"
        if p.get('snf'):
            result += f"\n   👤 {p.get('snf','')}"
        if p.get('iin'):
            result += f"\n   🧾 ИИН: {p.get('iin','')}"
        results.append(result)
    
    return "\n\n".join(results)

def search_by_fio(text: str):
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "true", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "true", "limit": 10}
    
    r = enqueue_crm_get("/api/v3/search/fio", params=q)
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
    
    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."
    
    results = []
    for i, p in enumerate(data[:10], 1):
        result = f"{i}. 👤 <b>{p.get('snf','')}</b>"
        if p.get('iin'):
            result += f"\n   🧾 ИИН: {p.get('iin','')}"
        if p.get('birthday'):
            result += f"\n   📅 Дата рождения: {p.get('birthday','')}"
        if p.get('phone_number'):
            result += f"\n   📱 Телефон: {p.get('phone_number','')}"
        results.append(result)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 9. FLASK APP ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600

def load_allowed_users():
    """Загружаем список разрешенных пользователей"""
    global ALLOWED_USER_IDS
    try:
        print(f"[AUTH] Загружаем разрешенных пользователей из: {ALLOWED_USERS_URL}")
        response = requests.get(ALLOWED_USERS_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            ALLOWED_USER_IDS = [int(i) for i in data.get("allowed_users", [])]
            print(f"[AUTH] ✅ Загружено {len(ALLOWED_USER_IDS)} разрешенных пользователей")
        else:
            print(f"[AUTH] ⚠️ Не удалось загрузить, статус: {response.status_code}")
            ALLOWED_USER_IDS = [0]
    except Exception as e:
        print(f"[AUTH] ❌ Ошибка загрузки: {e}")
        ALLOWED_USER_IDS = [0]

@app.route('/api/session/start', methods=['POST'])
def start_session():
    # Сначала загружаем актуальный список
    load_allowed_users()
    
    data = request.json
    user_id = data.get('telegram_user_id')
    
    if not user_id:
        return jsonify({"error": "Нет Telegram ID"}), 400
    
    try:
        user_id_int = int(user_id)
        if user_id_int not in ALLOWED_USER_IDS:
            print(f"[SESSION] ❌ Отказано в доступе для ID: {user_id_int}")
            return jsonify({"error": "Нет доступа"}), 403
        
        now = time.time()
        existing = active_sessions.get(user_id_int)
        
        if existing and (now - existing["created"]) < SESSION_TTL:
            return jsonify({"error": "Сессия уже активна."}), 403
        
        if existing and (now - existing["created"]) >= SESSION_TTL:
            del active_sessions[user_id_int]
        
        session_token = f"{user_id_int}-{int(now)}-{random.randint(1000,9999)}"
        active_sessions[user_id_int] = {"token": session_token, "created": now}
        
        print(f"[SESSION] 🔑 Активирована сессия для {user_id_int}")
        return jsonify({"session_token": session_token})
        
    except ValueError:
        return jsonify({"error": "Неверный Telegram ID"}), 400
    except Exception as e:
        print(f"[SESSION] ❌ Ошибка: {e}")
        return jsonify({"error": "Внутренняя ошибка"}), 500

@app.before_request
def validate_session():
    if request.path == "/api/search" and request.method == "POST":
        data = request.json or {}
        uid = data.get("telegram_user_id")
        token = data.get("session_token")
        
        if not uid or not token:
            return jsonify({"error": "Не указаны учетные данные"}), 403
        
        try:
            uid_int = int(uid)
            session = active_sessions.get(uid_int)
            if not session:
                return jsonify({"error": "Сессия не найдена."}), 403
            if session["token"] != token:
                return jsonify({"error": "Сессия недействительна."}), 403
            if time.time() - session["created"] > SESSION_TTL:
                del active_sessions[uid_int]
                return jsonify({"error": "Сессия истекла."}), 403
        except ValueError:
            return jsonify({"error": "Неверный Telegram ID"}), 400

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    
    if not user_id:
        return jsonify({"error": "Ошибка авторизации."}), 403
    
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    print(f"[SEARCH] Пользователь {user_id} ищет: {query[:50]}...")
    
    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith(("+", "8", "7")):
        reply = search_by_phone(query)
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
    
    load_allowed_users()
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
                "fingerprint": s.get("fingerprint", "")[:20] + "...",
                "cookies_count": len(s.get("cookies", {})),
                "created_at": s.get("created_at"),
                "age_seconds": int(time.time()) - s.get("created_at", 0)
            })
    
    return jsonify({
        "active_sessions_count": len(pw_sessions),
        "sessions": sessions_info,
        "queue_size": crm_queue.qsize(),
        "active_flask_sessions": len(active_sessions)
    })

@app.route('/api/debug/test-search', methods=['POST'])
def debug_test_search():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    query = data.get('query', '931229400494')
    
    print(f"[DEBUG] Тестовый поиск: {query}")
    
    if query.isdigit() and len(query) == 12:
        result = search_by_iin(query)
    elif query.startswith(("+", "8", "7")):
        result = search_by_phone(query)
    else:
        result = search_by_fio(query)
    
    return jsonify({
        "query": query,
        "result": result
    })

@app.route('/api/debug/init-sessions', methods=['POST'])
def debug_init_sessions():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    try:
        success = init_token_pool()
        with PW_SESSIONS_LOCK:
            session_count = len(pw_sessions)
        
        return jsonify({
            "success": success,
            "sessions": session_count
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    with PW_SESSIONS_LOCK:
        session_count = len(pw_sessions)
    
    return jsonify({
        "status": "ok" if session_count > 0 else "error",
        "sessions": session_count,
        "queue": crm_queue.qsize(),
        "active_flask_sessions": len(active_sessions),
        "allowed_users": len(ALLOWED_USER_IDS)
    })

# ================== 10. ЗАПУСК СЕРВЕРА ==================
print("\n" + "=" * 60)
print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
print("=" * 60)

# Загружаем разрешенных пользователей
load_allowed_users()

# Инициализируем пул сессий
time.sleep(2)
init_success = init_token_pool()

if not init_success:
    print("\n⚠️ ВНИМАНИЕ: Не удалось создать сессии!")
else:
    print("\n✅ СЕРВЕР ГОТОВ К РАБОТЕ!")

def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
        
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

if __name__ == "__main__":
    print(f"\n🌐 Сервер запущен!")
    print(f"📋 Проверка: curl https://api.reft.site/api/health")
    print("\n✅ Готов к работе с Telegram мини-приложением!")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
