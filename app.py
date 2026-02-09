# -*- coding: utf-8 -*-
import os
import time
import json
import random
import hashlib
import threading
from typing import List, Dict, Any
from urllib.parse import urlencode, urljoin

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

# ================== 1. НАСТРОЙКИ ==================
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

ACCOUNT = {"username": "klon9", "password": "7755SSaa"}

# ================== 2. GLOBAL PLAYWRIGHT ==================
class GlobalPlaywright:
    """Один Playwright на весь процесс с сохранением fingerprint"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance.device_fingerprint = None
        return cls._instance
    
    def _generate_stable_fingerprint(self):
        """Генерируем стабильный fingerprint на основе аккаунта"""
        # Используем аккаунт + константу для генерации всегда одинакового fingerprint
        seed = f"{ACCOUNT['username']}-{ACCOUNT['password']}-stable-seed-v1"
        return hashlib.sha256(seed.encode()).hexdigest()
    
    def _set_fingerprint_in_browser(self):
        """Устанавливаем fingerprint в браузере"""
        if not self.device_fingerprint:
            self.device_fingerprint = self._generate_stable_fingerprint()
        
        # Устанавливаем fingerprint в localStorage и sessionStorage
        self.page.evaluate(f"""
            () => {{
                try {{
                    localStorage.setItem('deviceFingerprint', '{self.device_fingerprint}');
                    sessionStorage.setItem('deviceFingerprint', '{self.device_fingerprint}');
                    window.deviceFingerprint = '{self.device_fingerprint}';
                }} catch(e) {{
                    console.error('Failed to set fingerprint:', e);
                }}
            }}
        """)
        
        print(f"🔑 Device Fingerprint установлен: {self.device_fingerprint[:30]}...")
    
    def initialize(self):
        """Инициализация в основном потоке при старте"""
        with self._lock:
            if self._initialized:
                return True
                
            print("🔄 Инициализация Playwright...")
            try:
                # Генерируем стабильный fingerprint ДО создания браузера
                self.device_fingerprint = self._generate_stable_fingerprint()
                print(f"🔑 Сгенерирован стабильный fingerprint: {self.device_fingerprint[:30]}...")
                
                self.playwright = sync_playwright().start()
                
                self.browser = self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",
                        "--no-zygote",
                        "--no-first-run",
                    ]
                )
                
                self.context = self.browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="ru-RU",
                    timezone_id="Europe/Moscow",
                    ignore_https_errors=True,
                )
                
                self.page = self.context.new_page()
                
                self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = {runtime: {}};
                """)
                
                # Логинимся
                return self._do_login()
                
            except Exception as e:
                print(f"❌ Ошибка инициализации: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    def _do_login(self):
        """Выполняем логин с установкой fingerprint"""
        try:
            print(f"🔐 Логинимся под {ACCOUNT['username']}...")
            
            # Переходим на страницу логина
            self.page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            
            # КРИТИЧНО: Устанавливаем fingerprint ДО заполнения формы
            self._set_fingerprint_in_browser()
            time.sleep(0.5)
            
            # Заполняем форму
            self.page.fill(LOGIN_SELECTOR, ACCOUNT['username'])
            time.sleep(0.5)
            self.page.fill(PASSWORD_SELECTOR, ACCOUNT['password'])
            time.sleep(0.5)
            
            # Нажимаем кнопку входа
            self.page.click(SIGN_IN_BUTTON_SELECTOR)
            time.sleep(4)
            
            # Проверяем успешность
            current_url = self.page.url
            print(f"📍 Текущий URL после логина: {current_url}")
            
            if "dashboard" not in current_url and "search" not in current_url:
                print("⚠️ Не на dashboard, пытаемся перейти...")
                self.page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=10000)
                time.sleep(2)
                
                # Снова устанавливаем fingerprint после редиректа
                self._set_fingerprint_in_browser()
            
            current_url = self.page.url
            
            if "dashboard" in current_url or "search" in current_url:
                self._initialized = True
                print("✅ Playwright инициализирован и залогинен")
                
                # Проверяем что fingerprint сохранён
                saved_fp = self.page.evaluate("""
                    () => {
                        return localStorage.getItem('deviceFingerprint') || 
                               sessionStorage.getItem('deviceFingerprint') ||
                               window.deviceFingerprint || 
                               'NOT_FOUND';
                    }
                """)
                print(f"🔍 Fingerprint в браузере: {saved_fp[:30] if saved_fp != 'NOT_FOUND' else saved_fp}...")
                
                return True
            else:
                print("❌ Не удалось войти")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка логина: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def make_request(self, endpoint: str, params: dict = None):
        """ВСЕ запросы синхронно с блокировкой"""
        with self._lock:
            try:
                if not self._initialized:
                    return {"error": "Not initialized", "success": False}
                
                # Формируем URL
                url = urljoin(BASE_URL, endpoint)
                if params:
                    query_string = urlencode(params, doseq=True)
                    url = f"{url}?{query_string}"
                
                print(f"📡 Запрос: {url[:80]}...")
                
                # Получаем актуальные куки
                cookies = self.context.cookies()
                cookies_dict = {c['name']: c['value'] for c in cookies}
                
                # КРИТИЧНО: Добавляем x-device-fingerprint заголовок
                headers = {
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json",
                    "referer": f"{BASE_URL}/dashboard/search",
                    "cookie": "; ".join([f"{k}={v}" for k, v in cookies_dict.items()]),
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                    "x-device-fingerprint": self.device_fingerprint,  # Используем сохранённый fingerprint
                    "x-requested-with": "XMLHttpRequest",
                }
                
                # Делаем запрос
                response = self.context.request.get(url, headers=headers, timeout=15000)
                
                print(f"📊 Ответ: {response.status}")
                
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
                    result["error"] = response.text()[:200]
                
                return result
                
            except Exception as e:
                print(f"❌ Ошибка запроса: {e}")
                import traceback
                traceback.print_exc()
                return {"error": str(e), "success": False}
    
    def reauth(self):
        """Переавторизация с СОХРАНЕНИЕМ fingerprint"""
        with self._lock:
            try:
                print("🔄 Переавторизация (с сохранением fingerprint)...")
                
                # ВАЖНО: НЕ меняем fingerprint!
                old_fp = self.device_fingerprint
                print(f"🔑 Используем тот же fingerprint: {old_fp[:30]}...")
                
                # Выполняем логин
                success = self._do_login()
                
                if success:
                    print("✅ Переавторизация завершена")
                else:
                    print("❌ Переавторизация не удалась")
                
                return success
                
            except Exception as e:
                print(f"❌ Ошибка переавторизации: {e}")
                return False

# Глобальный экземпляр
pw = GlobalPlaywright()

# ================== 3. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    print(f"🔍 Поиск по ИИН: {iin}")
    result = pw.make_request("/api/v3/search/iin", params={"iin": iin})
    
    if result.get("status") == 401:
        print("⚠️ 401 - переавторизация...")
        pw.reauth()
        time.sleep(1)
        result = pw.make_request("/api/v3/search/iin", params={"iin": iin})
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return "⚠️ Ничего не найдено по ИИН."
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ."
    
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    
    results = []
    for i, item in enumerate(data[:5], 1):
        result_text = f"{i}. 🧾 <b>ИИН: {item.get('iin','')}</b>"
        if item.get('snf'):
            result_text += f"\n   👤 {item.get('snf','')}"
        if item.get('phone_number'):
            result_text += f"\n   📱 {item.get('phone_number','')}"
        if item.get('birthday'):
            result_text += f"\n   📅 {item.get('birthday','')}"
        results.append(result_text)
    
    return "\n\n".join(results)

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    
    print(f"🔍 Поиск по телефону: {clean}")
    result = pw.make_request("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
    if result.get("status") == 401:
        pw.reauth()
        time.sleep(1)
        result = pw.make_request("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ."
    
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    results = []
    for i, item in enumerate(data[:5], 1):
        result_text = f"{i}. 📱 <b>{item.get('phone_number','')}</b>"
        if item.get('snf'):
            result_text += f"\n   👤 {item.get('snf','')}"
        if item.get('iin'):
            result_text += f"\n   🧾 {item.get('iin','')}"
        results.append(result_text)
    
    return "\n\n".join(results)

def search_by_fio(text: str):
    print(f"🔍 Поиск по ФИО: {text}")
    
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        params = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "true", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0]:
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1]:
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2]:
            params["father_name"] = parts[2]
        params.update({"smart_mode": "true", "limit": 10})
    
    result = pw.make_request("/api/v3/search/fio", params=params)
    
    if result.get("status") == 401:
        pw.reauth()
        time.sleep(1)
        result = pw.make_request("/api/v3/search/fio", params=params)
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return "⚠️ Ничего не найдено."
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ."
    
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."
    
    results = []
    for i, item in enumerate(data[:10], 1):
        result_text = f"{i}. 👤 <b>{item.get('snf','')}</b>"
        if item.get('iin'):
            result_text += f"\n   🧾 {item.get('iin','')}"
        if item.get('birthday'):
            result_text += f"\n   📅 {item.get('birthday','')}"
        if item.get('phone_number'):
            result_text += f"\n   📱 {item.get('phone_number','')}"
        results.append(result_text)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

def search_by_address(address: str):
    return "⚠️ Поиск по адресу временно недоступен."

# ================== 4. FLASK APP ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600

def load_allowed_users():
    global ALLOWED_USER_IDS
    try:
        response = requests.get(ALLOWED_USERS_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            ALLOWED_USER_IDS = [int(i) for i in data.get("allowed_users", [])]
            print(f"✅ Загружено {len(ALLOWED_USER_IDS)} пользователей")
    except Exception as e:
        ALLOWED_USER_IDS = [0]

@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.json
    user_id = data.get('telegram_user_id')
    
    if not user_id:
        return jsonify({"error": "Нет Telegram ID"}), 400
    
    try:
        user_id_int = int(user_id)
        if user_id_int not in ALLOWED_USER_IDS:
            return jsonify({"error": "Нет доступа"}), 403
        
        now = time.time()
        existing = active_sessions.get(user_id_int)
        
        if existing and (now - existing["created"]) < SESSION_TTL:
            return jsonify({"error": "Сессия уже активна."}), 403
        
        session_token = f"{user_id_int}-{int(now)}-{random.randint(1000,9999)}"
        active_sessions[user_id_int] = {"token": session_token, "created": now}
        
        print(f"🔑 Сессия для {user_id_int}")
        return jsonify({"session_token": session_token})
        
    except Exception as e:
        return jsonify({"error": "Ошибка"}), 500

@app.before_request
def validate_session():
    if request.path == "/api/search" and request.method == "POST":
        data = request.json or {}
        uid = data.get("telegram_user_id")
        token = data.get("session_token")
        
        if not uid or not token:
            return jsonify({"error": "Нет данных сессии"}), 403
        
        try:
            uid_int = int(uid)
        except:
            return jsonify({"error": "Неверный ID"}), 403
        
        session = active_sessions.get(uid_int)
        if not session:
            return jsonify({"error": "Сессия не найдена."}), 403
        
        if session["token"] != token:
            return jsonify({"error": "Сессия недействительна."}), 403
        
        if time.time() - session["created"] > SESSION_TTL:
            del active_sessions[uid_int]
            return jsonify({"error": "Сессия истекла."}), 403

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json or {}
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    print(f"\n{'='*50}")
    print(f"🔍 Поиск: {query}")
    print(f"{'='*50}")
    
    try:
        if query.isdigit() and len(query) == 12:
            reply = search_by_iin(query)
        elif query.startswith(("+", "8", "7")):
            reply = search_by_phone(query)
        elif any(x in query.upper() for x in ["УЛ.", "ПР.", "ДОМ"]):
            reply = search_by_address(query)
        else:
            reply = search_by_fio(query)
        
        print(f"✅ Готово")
        return jsonify({"result": reply})
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return jsonify({"error": "Ошибка сервера"}), 500

@app.route('/api/queue-size', methods=['GET'])
def queue_size():
    return jsonify({"queue_size": 0})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    load_allowed_users()
    return jsonify({"ok": True, "count": len(ALLOWED_USER_IDS)})

@app.route('/api/health', methods=['GET'])
def health_check():
    test = pw.make_request("/api/v3/search/iin", params={"iin": "931229400494"})
    return jsonify({
        "status": "ok" if test["success"] else "error",
        "playwright_ok": pw._initialized,
        "fingerprint": pw.device_fingerprint[:30] + "..." if pw.device_fingerprint else "None"
    })

# ================== 5. ЗАПУСК ==================
print("\n" + "=" * 60)
print("🚀 ЗАПУСК СЕРВЕРА")
print("=" * 60)

init_success = pw.initialize()

if init_success:
    print("✅ ГОТОВ!")
    print(f"🔑 Fingerprint: {pw.device_fingerprint[:30]}...")
else:
    print("❌ Ошибка инициализации")

load_allowed_users()

def keep_alive():
    while True:
        time.sleep(600)
        print("💓 Keep-alive...")
        test = pw.make_request("/api/v3/search/iin", params={"iin": "931229400494"})
        if not test["success"]:
            pw.reauth()

threading.Thread(target=keep_alive, daemon=True).start()

print("=" * 60)

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    run_simple('0.0.0.0', 5000, app, threaded=False, processes=1, use_reloader=False)
