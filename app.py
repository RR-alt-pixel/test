# -*- coding: utf-8 -*-
import os
import time
import json
import random
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

# ================== 2. GLOBAL PLAYWRIGHT (один на все) ==================
class GlobalPlaywright:
    """Один Playwright на весь процесс"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def initialize(self):
        """Инициализация в основном потоке при старте"""
        with self._lock:
            if self._initialized:
                return True
                
            print("🔄 Инициализация Playwright...")
            try:
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
                        "--window-size=1280,720"
                    ]
                )
                
                self.context = self.browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                    locale="ru-RU",
                    timezone_id="Europe/Moscow",
                    ignore_https_errors=True,
                )
                
                self.page = self.context.new_page()
                
                self.page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = {runtime: {}};
                """)
                
                # Логинимся
                print("🔐 Логинимся...")
                self.page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                
                self.page.fill(LOGIN_SELECTOR, "klon9")
                time.sleep(0.5)
                self.page.fill(PASSWORD_SELECTOR, "7755SSaa")
                time.sleep(0.5)
                self.page.click(SIGN_IN_BUTTON_SELECTOR)
                time.sleep(3)
                
                # Проверяем успешность
                if "dashboard" not in self.page.url:
                    print("⚠️ Переход на dashboard...")
                    self.page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=10000)
                    time.sleep(2)
                
                self._initialized = True
                print("✅ Playwright инициализирован")
                return True
                
            except Exception as e:
                print(f"❌ Ошибка инициализации: {e}")
                import traceback
                traceback.print_exc()
                return False
    
    def make_request(self, endpoint: str, params: dict = None):
        """ВСЕ запросы в основном потоке - синхронно"""
        with self._lock:  # Блокировка чтобы не было параллельных запросов
            try:
                if not self._initialized:
                    print("⚠️ Playwright не инициализирован")
                    return {"error": "Not initialized", "success": False}
                
                # Формируем URL
                url = urljoin(BASE_URL, endpoint)
                if params:
                    query_string = urlencode(params, doseq=True)
                    url = f"{url}?{query_string}"
                
                print(f"📡 Синхронный запрос: {url[:80]}...")
                
                # Получаем актуальные куки перед запросом
                cookies = self.context.cookies()
                cookies_dict = {c['name']: c['value'] for c in cookies}
                
                # Формируем заголовки
                headers = {
                    "accept": "application/json, text/plain, */*",
                    "content-type": "application/json",
                    "referer": f"{BASE_URL}/dashboard/search",
                    "cookie": "; ".join([f"{k}={v}" for k, v in cookies_dict.items()]),
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "x-requested-with": "XMLHttpRequest",
                    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
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
                return {"error": str(e), "success": False}

# Глобальный экземпляр
pw = GlobalPlaywright()

# ================== 3. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    """Поиск по ИИН"""
    print(f"🔍 Поиск по ИИН: {iin}")
    
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
        return "❌ Не удалось обработать ответ сервера."
    
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
        if item.get('source'):
            result_text += f"\n   📍 {item.get('source')}"
        results.append(result_text)
    
    return "\n\n".join(results)

def search_by_phone(phone: str):
    """Поиск по телефону"""
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    
    print(f"🔍 Поиск по телефону: {phone} -> {clean}")
    
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
        return "❌ Не удалось обработать ответ сервера."
    
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    results = []
    for i, item in enumerate(data[:5], 1):
        result_text = f"{i}. 📱 <b>Телефон: {item.get('phone_number','')}</b>"
        if item.get('snf'):
            result_text += f"\n   👤 {item.get('snf','')}"
        if item.get('iin'):
            result_text += f"\n   🧾 ИИН: {item.get('iin','')}"
        if item.get('source'):
            result_text += f"\n   📍 {item.get('source')}"
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
        return "❌ Не удалось обработать ответ сервера."
    
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."
    
    results = []
    for i, item in enumerate(data[:10], 1):
        result_text = f"{i}. 👤 <b>{item.get('snf','')}</b>"
        if item.get('iin'):
            result_text += f"\n   🧾 ИИН: {item.get('iin','')}"
        if item.get('birthday'):
            result_text += f"\n   📅 Дата рождения: {item.get('birthday','')}"
        if item.get('phone_number'):
            result_text += f"\n   📱 Телефон: {item.get('phone_number','')}"
        if item.get('source'):
            result_text += f"\n   📍 {item.get('source')}"
        results.append(result_text)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 4. FLASK APP ==================
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
    # ВРЕМЕННО ОТКЛЮЧАЕМ ПРОВЕРКУ
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
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    test_result = pw.make_request("/api/v3/search/iin", params={"iin": "931229400494"})
    
    return jsonify({
        "status": "ok" if test_result["success"] else "error",
        "test_passed": test_result["success"],
        "playwright_initialized": pw._initialized,
        "active_sessions": len(active_sessions)
    })

@app.route('/api/debug/test', methods=['GET'])
def debug_test():
    """Тестовый запрос"""
    iin = request.args.get('iin', '931229400494')
    result = pw.make_request("/api/v3/search/iin", params={"iin": iin})
    return jsonify(result)

# ================== 5. ЗАПУСК ==================
print("\n" + "=" * 60)
print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
print("=" * 60)
print("Архитектура: Один Playwright, все запросы синхронно")
print("Решено: Нет ошибки 'cannot switch to a different thread'")
print("Запросы: Синхронные, с блокировкой")
print("=" * 60)

# Инициализируем Playwright в основном потоке
print("\n🔄 Инициализация Playwright...")
init_success = pw.initialize()

if init_success:
    print("✅ СЕРВЕР ГОТОВ К РАБОТЕ!")
else:
    print("❌ Не удалось инициализировать Playwright")

# Загружаем разрешенных пользователей
load_allowed_users()

print(f"\n🌐 Сервер запускается...")
print("🔍 Поиск: POST /api/search")
print("📋 Проверка: GET /api/health")
print("=" * 60)

if __name__ == "__main__":
    # Запускаем Flask в одном потоке!
    from werkzeug.serving import run_simple
    run_simple(
        '0.0.0.0', 
        5000, 
        app, 
        threaded=False,  # ВАЖНО: НЕ threaded!
        processes=1,
        use_reloader=False
    )
