# -*- coding: utf-8 -*-
import os
import time
import json
import random
import traceback
import hashlib
from threading import Thread, Lock
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode, urljoin

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

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
    {"username": "klon9", "password": "7755SSaa"},
]

# ================== 3. SINGLE SESSION ==================
class PenaSession:
    """Одна сессия для всех запросов"""
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cookies = {}
        self.headers = {}
        self.fingerprint = None
        self.is_initialized = False
        self.lock = Lock()
        
    def initialize(self):
        """Инициализация сессии"""
        with self.lock:
            if self.is_initialized:
                return True
                
            print("🔄 Инициализация Playwright сессии...")
            
            try:
                # Запускаем Playwright
                self.playwright = sync_playwright().start()
                
                # Запускаем браузер в легком режиме
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
                        "--disable-extensions",
                        "--window-size=1280,720"
                    ]
                )
                
                # Создаем контекст
                self.context = self.browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                    locale="ru-RU",
                    timezone_id="Europe/Moscow",
                    ignore_https_errors=True,
                )
                
                # Создаем страницу
                self.page = self.context.new_page()
                
                # Anti-detection
                self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                """)
                
                # Логинимся
                print("🔐 Логинимся в pena.rest...")
                self.page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                
                # Заполняем логин/пароль
                self.page.fill(LOGIN_SELECTOR, accounts[0]["username"])
                time.sleep(0.5)
                self.page.fill(PASSWORD_SELECTOR, accounts[0]["password"])
                time.sleep(0.5)
                
                # Нажимаем кнопку
                self.page.click(SIGN_IN_BUTTON_SELECTOR)
                time.sleep(3)
                
                # Переходим на dashboard
                self.page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=20000)
                time.sleep(2)
                
                # Получаем куки
                cookies_list = self.context.cookies()
                self.cookies = {c['name']: c['value'] for c in cookies_list}
                
                # Генерируем fingerprint
                self.fingerprint = hashlib.sha256(f"{accounts[0]['username']}{int(time.time())}".encode()).hexdigest()
                
                # Создаем заголовки
                self._create_headers()
                
                self.is_initialized = True
                print("✅ Сессия инициализирована")
                return True
                
            except Exception as e:
                print(f"❌ Ошибка инициализации: {e}")
                traceback.print_exc()
                return False
    
    def _create_headers(self):
        """Создание заголовков"""
        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "ru-RU,ru;q=0.9",
            "content-type": "application/json",
            "referer": f"{BASE_URL}/dashboard/search",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "x-device-fingerprint": self.fingerprint,
            "cookie": cookie_header,
            "x-requested-with": "XMLHttpRequest"
        }
    
    def make_request(self, endpoint: str, params: dict = None):
        """Выполнение запроса"""
        with self.lock:
            try:
                # Формируем URL
                url = urljoin(BASE_URL, endpoint)
                if params:
                    query_string = urlencode(params, doseq=True)
                    url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
                
                print(f"📡 Запрос: {url[:80]}...")
                
                # Отправляем запрос
                response = self.context.request.get(
                    url, 
                    headers=self.headers, 
                    timeout=20000
                )
                
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
                return {"error": str(e), "success": False}
    
    def close(self):
        """Закрытие сессии"""
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            print("✅ Сессия закрыта")
        except:
            pass

# Глобальная сессия
pena_session = PenaSession()

# ================== 4. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    """Поиск по ИИН"""
    print(f"🔍 Поиск по ИИН: {iin}")
    
    result = pena_session.make_request("/api/v3/search/iin", params={"iin": iin})
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return "⚠️ Ничего не найдено по ИИН."
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ сервера."
    
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    
    results = []
    for i, p in enumerate(data[:5], 1):
        result_text = f"{i}. 🧾 <b>ИИН: {p.get('iin','')}</b>"
        if p.get('snf'):
            result_text += f"\n   👤 {p.get('snf','')}"
        if p.get('phone_number'):
            result_text += f"\n   📱 {p.get('phone_number','')}"
        if p.get('birthday'):
            result_text += f"\n   📅 {p.get('birthday','')}"
        results.append(result_text)
    
    return "\n\n".join(results)

def search_by_phone(phone: str):
    """Поиск по телефону"""
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    
    print(f"🔍 Поиск по телефону: {phone} -> {clean}")
    
    result = pena_session.make_request("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ сервера."
    
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    results = []
    for i, p in enumerate(data[:5], 1):
        result_text = f"{i}. 📱 <b>Телефон: {p.get('phone_number','')}</b>"
        if p.get('snf'):
            result_text += f"\n   👤 {p.get('snf','')}"
        if p.get('iin'):
            result_text += f"\n   🧾 ИИН: {p.get('iin','')}"
        results.append(result_text)
    
    return "\n\n".join(results)

def search_by_fio(text: str):
    """Поиск по ФИО"""
    print(f"🔍 Поиск по ФИО: {text}")
    
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        params = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "true", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        params.update({"smart_mode": "true", "limit": 10})
    
    result = pena_session.make_request("/api/v3/search/fio", params=params)
    
    if not result["success"]:
        return f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
    
    if result["status"] == 404:
        return "⚠️ Ничего не найдено."
    
    if result["status"] != 200:
        return f"❌ Ошибка сервера: {result['status']}"
    
    try:
        data = result.get("json", [])
    except:
        return "❌ Не удалось обработать ответ сервера."
    
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."
    
    results = []
    for i, p in enumerate(data[:10], 1):
        result_text = f"{i}. 👤 <b>{p.get('snf','')}</b>"
        if p.get('iin'):
            result_text += f"\n   🧾 ИИН: {p.get('iin','')}"
        if p.get('birthday'):
            result_text += f"\n   📅 Дата рождения: {p.get('birthday','')}"
        if p.get('phone_number'):
            result_text += f"\n   📱 Телефон: {p.get('phone_number','')}"
        results.append(result_text)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 5. FLASK APP ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600

def load_allowed_users():
    """Загружаем список разрешенных пользователей"""
    global ALLOWED_USER_IDS
    try:
        response = requests.get(ALLOWED_USERS_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            ALLOWED_USER_IDS = [int(i) for i in data.get("allowed_users", [])]
            print(f"✅ Загружено {len(ALLOWED_USER_IDS)} разрешенных пользователей")
        else:
            ALLOWED_USER_IDS = [0]
    except:
        ALLOWED_USER_IDS = [0]

@app.route('/api/session/start', methods=['POST'])
def start_session():
    """Начало сессии"""
    load_allowed_users()
    
    data = request.json
    user_id = data.get('telegram_user_id')
    
    if not user_id:
        return jsonify({"error": "Нет Telegram ID"}), 400
    
    try:
        user_id_int = int(user_id)
        if user_id_int not in ALLOWED_USER_IDS:
            return jsonify({"error": "Нет доступа"}), 403
        
        now = time.time()
        
        # Создаем сессию
        session_token = f"{user_id_int}-{int(now)}-{random.randint(1000,9999)}"
        active_sessions[user_id_int] = {"token": session_token, "created": now}
        
        return jsonify({"session_token": session_token})
        
    except ValueError:
        return jsonify({"error": "Неверный Telegram ID"}), 400
    except Exception as e:
        return jsonify({"error": "Внутренняя ошибка"}), 500

@app.route('/api/search', methods=['POST'])
def api_search():
    """Основной поисковый эндпоинт"""
    # ВРЕМЕННО ОТКЛЮЧАЕМ ПРОВЕРКУ АВТОРИЗАЦИИ ДЛЯ ТЕСТОВ
    data = request.json or {}
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    print(f"\n{'='*50}")
    print(f"🔍 Поисковый запрос: {query}")
    print(f"{'='*50}")
    
    try:
        if query.isdigit() and len(query) == 12:
            reply = search_by_iin(query)
        elif query.startswith(("+", "8", "7")):
            reply = search_by_phone(query)
        else:
            reply = search_by_fio(query)
        
        print(f"✅ Ответ готов ({len(reply)} символов)")
        print(f"{'='*50}")
        
        return jsonify({"result": reply})
        
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    return jsonify({
        "status": "ok" if pena_session.is_initialized else "error",
        "session_initialized": pena_session.is_initialized,
        "active_flask_sessions": len(active_sessions),
        "allowed_users": len(ALLOWED_USER_IDS)
    })

@app.route('/api/debug/init', methods=['POST'])
def debug_init():
    """Принудительная инициализация"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    success = pena_session.initialize()
    return jsonify({"success": success})

@app.route('/api/debug/test', methods=['GET'])
def debug_test():
    """Тестовый запрос"""
    iin = request.args.get('iin', '931229400494')
    result = pena_session.make_request("/api/v3/search/iin", params={"iin": iin})
    return jsonify(result)

# ================== 6. ЗАПУСК ==================
print("\n" + "=" * 60)
print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
print("=" * 60)
print("Архитектура: Одна сессия, без очередей")
print("Решена проблема: cannot switch to a different thread")
print("⚠️ ЗАЩИТА ОТКЛЮЧЕНА ДЛЯ ТЕСТОВ")
print("=" * 60)

# Загружаем разрешенных пользователей
load_allowed_users()

# Инициализируем сессию
print("\n🔄 Инициализация сессии...")
init_success = pena_session.initialize()

if init_success:
    print("✅ СЕРВЕР ГОТОВ К РАБОТЕ!")
else:
    print("❌ Не удалось инициализировать сессию")

print(f"\n🌐 Сервер запускается...")
print("🔍 Поиск: POST /api/search")
print("📋 Проверка: GET /api/health")
print("=" * 60)

if __name__ == "__main__":
    # Запускаем Flask
    app.run(
        host='0.0.0.0', 
        port=5000, 
        threaded=True, 
        use_reloader=False,
        debug=False
    )
