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
        self.sessions = {}
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
                self.ready.set()
    
    def create_session(self, username: str, password: str) -> Optional[Dict]:
        """Создаем новую сессию с извлечением fingerprint"""
        if not self._pw:
            return None
        
        print(f"[SESSION] Создаем сессию для {username}")
        
        browser = None
        try:
            # Запускаем браузер с теми же настройками что и в тестовом скрипте
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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            
            page = context.new_page()
            
            # Маскируем Playwright
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)
            
            # Переменная для хранения fingerprint
            fingerprint = None
            
            # Функция для перехвата fingerprint
            def capture_fingerprint(request):
                nonlocal fingerprint
                if 'x-device-fingerprint' in request.headers:
                    fp = request.headers['x-device-fingerprint']
                    if fp and len(fp) == 64:
                        fingerprint = fp
                        print(f"[SESSION] Найден fingerprint: {fp[:30]}...")
            
            page.on("request", capture_fingerprint)
            
            # 1. Логинимся
            print(f"[SESSION] Логин {username}...")
            page.goto(LOGIN_PAGE, wait_until="networkidle")
            time.sleep(1)
            
            page.fill(LOGIN_SELECTOR, username)
            page.fill(PASSWORD_SELECTOR, password)
            page.click(SIGN_IN_BUTTON_SELECTOR)
            
            # Ждем dashboard
            try:
                page.wait_for_url("**/dashboard**", timeout=10000)
                print(f"[SESSION] ✅ Успешный вход для {username}")
            except:
                current_url = page.url
                print(f"[SESSION] Текущий URL: {current_url}")
                if "dashboard" not in current_url:
                    raise Exception("Не удалось войти в dashboard")
            
            time.sleep(2)
            
            # 2. Переходим на страницу поиска
            search_url = urljoin(BASE_URL, "/dashboard/search")
            page.goto(search_url, wait_until="networkidle")
            time.sleep(3)
            
            # 3. Получаем куки
            cookies = context.cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies}
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # 4. Если fingerprint не нашелся в запросах, пробуем получить из JS
            if not fingerprint:
                print("[SESSION] Ищем fingerprint в JavaScript...")
                try:
                    js_result = page.evaluate("""
                        () => {
                            // Ищем в window
                            const windowKeys = Object.keys(window);
                            for (const key of windowKeys) {
                                try {
                                    const value = window[key];
                                    if (typeof value === 'string' && value.length === 64 && /^[a-f0-9]{64}$/.test(value)) {
                                        return value;
                                    }
                                } catch(e) {}
                            }
                            return null;
                        }
                    """)
                    
                    if js_result:
                        fingerprint = js_result
                        print(f"[SESSION] Найден fingerprint в JS: {fingerprint[:30]}...")
                except:
                    pass
            
            # 5. Если все еще нет, генерируем
            if not fingerprint:
                print("[SESSION] Генерируем fingerprint...")
                browser_data = page.evaluate("""
                    () => {
                        return {
                            userAgent: navigator.userAgent,
                            platform: navigator.platform,
                            languages: navigator.languages.join(','),
                            hardwareConcurrency: navigator.hardwareConcurrency,
                            timestamp: Date.now()
                        };
                    }
                """)
                
                data_str = json.dumps(browser_data, sort_keys=True) + username
                fingerprint = hashlib.sha256(data_str.encode()).hexdigest()
                print(f"[SESSION] Сгенерирован fingerprint: {fingerprint[:30]}...")
            
            # 6. Формируем заголовки как в рабочем тесте
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "x-device-fingerprint": fingerprint,
                "x-requested-with": "XMLHttpRequest",
                "referer": search_url,
                "cookie": cookie_header,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                "sec-ch-ua": '"Chromium";v="145", "Not:A-Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
            
            # 7. Создаем объект сессии
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
            }
            
            # 8. Тестируем сессию
            print("[SESSION] Тестируем сессию...")
            test_response = context.request.get(
                urljoin(BASE_URL, "/api/v3/search/fio?limit=1&surname=TEST"),
                headers=headers
            )
            
            print(f"[SESSION] Тестовый запрос: статус {test_response.status}")
            
            if test_response.status == 200:
                print(f"[SESSION] ✅ Сессия для {username} создана успешно")
                return session_data
            else:
                print(f"[SESSION] ❌ Сессия нерабочая: {test_response.status}")
                browser.close()
                return None
                
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
        """Делаем API запрос с использованием сессии"""
        try:
            url = urljoin(BASE_URL, endpoint)
            if params:
                query_string = urlencode(params, doseq=True)
                url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
            
            # Обновляем заголовки (особенно referer)
            headers = session_data["headers"].copy()
            headers["referer"] = urljoin(BASE_URL, "/dashboard/search")
            
            # Делаем запрос
            response = session_data["context"].request.get(url, headers=headers, timeout=30000)
            
            # Обновляем время использования
            session_data["last_used"] = int(time.time())
            
            return {
                "status": response.status,
                "text": response.text(),
                "json": response.json() if response.status == 200 else None,
                "success": response.status == 200
            }
            
        except Exception as e:
            print(f"[REQUEST] ❌ Ошибка запроса: {e}")
            return {"error": str(e), "success": False}

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(30)

# ================== 5. ПУЛ СЕССИЙ (ОБНОВЛЕННЫЙ) ==================
def init_token_pool():
    global pw_sessions, pw_cycle

    print("[POOL] 🔄 Инициализация пула сессий...")
    
    new_sessions = []
    for acc in accounts:
        print(f"[POOL] Создаем сессию для {acc['username']}...")
        
        session_data = pw_manager.create_session(acc["username"], acc["password"])
        
        if session_data:
            new_sessions.append(session_data)
            print(f"[POOL] ✅ Сессия для {acc['username']} создана")
        else:
            print(f"[POOL] ❌ Не удалось создать сессию для {acc['username']}")

    with PW_SESSIONS_LOCK:
        pw_sessions = new_sessions
        pw_cycle = itertools.cycle(pw_sessions) if pw_sessions else None

    if pw_sessions:
        print(f"[POOL] ✅ Пул инициализирован, сессий: {len(pw_sessions)}")
        for s in pw_sessions:
            fp = s.get("fingerprint", "")[:20]
            cookies_count = len(s.get("cookies", {}))
            print(f"[POOL]   - {s['username']}: FP={fp}..., Cookies={cookies_count}")
    else:
        print("[POOL] ❌ Пустой пул сессий.")

def get_next_session() -> Optional[Dict]:
    global pw_sessions, pw_cycle

    if not pw_sessions:
        init_token_pool()
        with PW_SESSIONS_LOCK:
            if not pw_sessions:
                return None

    with PW_SESSIONS_LOCK:
        if pw_cycle is None:
            pw_cycle = itertools.cycle(pw_sessions)
        try:
            s = next(pw_cycle)
            fp = s.get("fingerprint", "")[:20]
            print(f"[POOL] 🔁 Используется сессия {s['username']} (FP: {fp}...)")
            return s
        except StopIteration:
            pw_cycle = itertools.cycle(pw_sessions)
            s = next(pw_cycle)
            return s

def refresh_session(username: str) -> Optional[Dict]:
    """Обновляем сессию для пользователя"""
    global pw_sessions, pw_cycle
    
    try:
        print(f"[REFRESH] 🔄 Обновление сессии для {username}...")
        
        acc = next((a for a in accounts if a["username"] == username), None)
        if not acc:
            print(f"[REFRESH] ❌ Аккаунт не найден")
            return None
        
        # Закрываем старую сессию
        with PW_SESSIONS_LOCK:
            old_session = next((s for s in pw_sessions if s.get("username") == username), None)
            if old_session and old_session.get("browser"):
                try:
                    old_session["browser"].close()
                except:
                    pass
        
        # Создаем новую
        new_session = pw_manager.create_session(acc["username"], acc["password"])
        
        if new_session:
            with PW_SESSIONS_LOCK:
                # Удаляем старую, добавляем новую
                pw_sessions = [s for s in pw_sessions if s.get("username") != username]
                pw_sessions.append(new_session)
                pw_cycle = itertools.cycle(pw_sessions)
            
            print(f"[REFRESH] ✅ Сессия для {username} обновлена")
            return new_session
        else:
            print(f"[REFRESH] ❌ Не удалось обновить сессию")
            return None
            
    except Exception as e:
        print(f"[REFRESH ERROR] {e}")
        return None

# ================== 6. CRM GET (ОБНОВЛЕННЫЙ) ==================
def crm_get(endpoint: str, params: dict = None):
    """Основная функция для API запросов"""
    session = get_next_session()
    if not session:
        return ResponseLike(500, "❌ Нет доступных сессий")
    
    username = session.get("username", "unknown")
    fingerprint = session.get("fingerprint", "")[:20]
    
    print(f"[CRM] {username} -> {endpoint}")
    print(f"[CRM] Fingerprint: {fingerprint}...")
    
    # Делаем запрос через менеджер
    result = pw_manager.make_request(session, endpoint, params)
    
    if result.get("success"):
        return ResponseLike(
            status_code=result["status"],
            text=result["text"],
            json_data=result["json"]
        )
    else:
        # Если ошибка аутентификации, пробуем обновить сессию
        if result.get("status") in [401, 403]:
            print(f"[CRM] ❌ Ошибка аутентификации, обновляем сессию...")
            new_session = refresh_session(username)
            
            if new_session:
                # Пробуем снова с новой сессией
                result = pw_manager.make_request(new_session, endpoint, params)
                if result.get("success"):
                    return ResponseLike(
                        status_code=result["status"],
                        text=result["text"],
                        json_data=result["json"]
                    )
        
        # Возвращаем ошибку
        return ResponseLike(
            status_code=result.get("status", 500),
            text=result.get("text", result.get("error", "Unknown error")),
            json_data=None
        )

# ================== 7. ОЧЕРЕДЬ И FLASK (ОСТАВЛЯЕМ БЕЗ ИЗМЕНЕНИЙ) ==================
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
        error_text = resp.text
        if "fingerprint" in error_text.lower() or "authentication" in error_text.lower():
            return f"❌ Ошибка аутентификации. Попробуйте позже."
        return f"❌ Ошибка {resp.status_code}: {error_text[:100]}"
    
    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    
    # Форматируем результат
    results = []
    for i, p in enumerate(data[:5], 1):
        result = f"{i}. 🧾 <b>ИИН: {p.get('iin','')}</b>"
        if p.get('snf'):
            result += f"\n   👤 {p.get('snf','')}"
        if p.get('phone_number'):
            result += f"\n   📱 {p.get('phone_number','')}"
        if p.get('birthday'):
            result += f"\n   📅 {p.get('birthday','')}"
        if p.get('address'):
            result += f"\n   🏠 {p.get('address','')[:50]}..."
        results.append(result)
    
    return "\n\n".join(results) if results else "⚠️ Данные найдены, но пустые."

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
    
    # Форматируем результат
    results = []
    for i, p in enumerate(data[:5], 1):
        result = f"{i}. 📱 <b>Телефон: {p.get('phone_number','')}</b>"
        if p.get('snf'):
            result += f"\n   👤 {p.get('snf','')}"
        if p.get('iin'):
            result += f"\n   🧾 ИИН: {p.get('iin','')}"
        if p.get('birthday'):
            result += f"\n   📅 {p.get('birthday','')}"
        results.append(result)
    
    return "\n\n".join(results)

def search_by_fio(text: str):
    # Обработка ФИО (как в предыдущей версии)
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
    
    # Форматируем результат
    results = []
    for i, p in enumerate(data[:10], 1):
        result = f"{i}. 👤 <b>{p.get('snf','')}</b>"
        if p.get('iin'):
            result += f"\n   🧾 ИИН: {p.get('iin','')}"
        if p.get('birthday'):
            result += f"\n   📅 Дата рождения: {p.get('birthday','')}"
        if p.get('phone_number'):
            result += f"\n   📱 Телефон: {p.get('phone_number','')}"
        if p.get('nationality'):
            result += f"\n   🌍 Национальность: {p.get('nationality','')}"
        results.append(result)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 9. FLASK APP (МИНИМАЛЬНЫЕ ИЗМЕНЕНИЯ) ==================
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
    
    # Определяем тип запроса
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
    
    # Загружаем разрешенных пользователей
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ALLOWED_USER_IDS.clear()
            ALLOWED_USER_IDS.extend([int(i) for i in data.get("allowed_users", [])])
            print(f"[AUTH] ✅ Обновлены разрешенные пользователи: {len(ALLOWED_USER_IDS)}")
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
    
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
                "has_cf_clearance": "cf_clearance" in s.get("cookies", {}),
                "created_at": s.get("created_at"),
                "last_used": s.get("last_used"),
                "age_seconds": int(time.time()) - s.get("created_at", 0)
            })
    
    return jsonify({
        "active_sessions_count": len(pw_sessions),
        "sessions": sessions_info,
        "queue_size": crm_queue.qsize()
    })

@app.route('/api/debug/test-search', methods=['POST'])
def debug_test_search():
    """Тестовый поиск для отладки"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    query = data.get('query', '931229400494')
    search_type = data.get('type', 'iin')
    
    if search_type == 'iin':
        result = search_by_iin(query)
    elif search_type == 'phone':
        result = search_by_phone(query)
    else:
        result = search_by_fio(query)
    
    return jsonify({
        "query": query,
        "type": search_type,
        "result": result
    })

# ================== 10. ЗАПУСК ==================
print("🚀 Запуск обновленного API сервера...")
print("=" * 60)
print("Исправления:")
print("1. Правильное извлечение fingerprint")
print("2. Сохранение всех кук (включая cf_clearance)")
print("3. Использование правильных заголовков запроса")
print("=" * 60)

# Инициализируем пул сессий
time.sleep(2)
init_token_pool()

def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
            print(f"[SESSION] 🧹 Удалена сессия {uid}")
        
        # Также проверяем Playwright сессии
        with PW_SESSIONS_LOCK:
            for session in pw_sessions:
                # Если сессия старая, обновляем ее
                if now - session.get("created_at", 0) > 3600:  # 1 час
                    print(f"[POOL] 🔄 Сессия {session.get('username')} устарела, обновляем...")
                    refresh_session(session.get("username"))
        
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

if __name__ == "__main__":
    print(f"\n🌐 Сервер запущен на http://0.0.0.0:5000")
    print(f"📊 Для отладки: curl -H 'Authorization: Bearer {SECRET_TOKEN}' http://localhost:5000/api/debug/sessions")
    print(f"🔧 Тестовый поиск: curl -X POST -H 'Authorization: Bearer {SECRET_TOKEN}' -H 'Content-Type: application/json' -d '{{\"query\":\"931229400494\",\"type\":\"iin\"}}' http://localhost:5000/api/debug/test-search")
    print("\n✅ Готов к работе!")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
