# -*- coding: utf-8 -*-
import os
import time
import json
import random
import traceback
import hashlib
import threading
import queue
from threading import Thread, Lock, Event
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlencode, urljoin
from datetime import datetime

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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

# ================== 3. PLAYWRIGHT В ОДНОМ ПОТОКЕ ==================
class PlaywrightWorker:
    """Рабочий поток для ВСЕХ Playwright операций"""
    def __init__(self):
        self.task_queue = queue.Queue()
        self.result_queues = {}  # task_id -> queue.Queue для результата
        self.task_counter = 0
        self.task_lock = Lock()
        self.worker_thread = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.fingerprint = None
        self.cookies = {}
        self.headers = {}
        self.is_running = False
        self.init_event = Event()
        
    def start(self):
        """Запустить рабочий поток"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        
        self.worker_thread = Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        self.is_running = True
        print("[PLAYWRIGHT WORKER] ✅ Рабочий поток запущен")
        
    def _worker_loop(self):
        """Главный цикл рабочего потока - ВСЕ Playwright операции здесь!"""
        print("[PLAYWRIGHT WORKER] 🚀 Запуск Playwright в рабочем потоке...")
        
        try:
            # 1. Инициализация Playwright
            self.playwright = sync_playwright().start()
            print("[PLAYWRIGHT WORKER] ✅ Playwright запущен")
            
            # 2. Запуск браузера
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080"
                ]
            )
            print("[PLAYWRIGHT WORKER] ✅ Браузер запущен")
            
            # 3. Создание контекста
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            print("[PLAYWRIGHT WORKER] ✅ Контекст создан")
            
            # 4. Создание страницы
            self.page = self.context.new_page()
            
            # 5. Добавляем anti-detection скрипты
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            # 6. Логин в систему
            print("[PLAYWRIGHT WORKER] 🔐 Выполняем логин...")
            self._login()
            
            print("[PLAYWRIGHT WORKER] ✅ Инициализация завершена!")
            self.init_event.set()
            
            # 7. Основной цикл обработки задач
            while self.is_running:
                try:
                    task = self.task_queue.get(timeout=1)
                    task_id, task_type, task_data, result_queue = task
                    
                    try:
                        result = self._process_task(task_type, task_data)
                        result_queue.put((task_id, {"success": True, "data": result}))
                    except Exception as e:
                        result_queue.put((task_id, {
                            "success": False, 
                            "error": str(e),
                            "traceback": traceback.format_exc()
                        }))
                    
                    self.task_queue.task_done()
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"[PLAYWRIGHT WORKER] ❌ Ошибка в цикле: {e}")
                    
        except Exception as e:
            print(f"[PLAYWRIGHT WORKER] ❌ Критическая ошибка: {e}")
            traceback.print_exc()
            self.init_event.set()  # Все равно сигнализируем о завершении
            
    def _login(self):
        """Логин в pena.rest"""
        try:
            # Переходим на страницу логина
            self.page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            
            # Заполняем логин
            self.page.fill(LOGIN_SELECTOR, accounts[0]["username"])
            time.sleep(0.5)
            
            # Заполняем пароль
            self.page.fill(PASSWORD_SELECTOR, accounts[0]["password"])
            time.sleep(0.5)
            
            # Нажимаем кнопку
            self.page.click(SIGN_IN_BUTTON_SELECTOR)
            time.sleep(3)
            
            # Переходим на dashboard
            self.page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=30000)
            time.sleep(2)
            
            # Получаем cookies
            cookies_list = self.context.cookies()
            self.cookies = {c['name']: c['value'] for c in cookies_list}
            
            # Генерируем fingerprint
            self.fingerprint = self._generate_fingerprint()
            
            # Создаем заголовки
            self._create_headers()
            
            print(f"[PLAYWRIGHT WORKER] ✅ Логин успешен")
            print(f"[PLAYWRIGHT WORKER] 📦 Cookies: {len(self.cookies)}")
            print(f"[PLAYWRIGHT WORKER] 📍 Fingerprint: {self.fingerprint[:30]}...")
            
        except Exception as e:
            print(f"[PLAYWRIGHT WORKER] ❌ Ошибка логина: {e}")
            raise
    
    def _generate_fingerprint(self):
        """Генерация fingerprint"""
        try:
            browser_data = self.page.evaluate("""
                () => ({
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    languages: navigator.languages.join(','),
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory,
                    screen: `${screen.width}x${screen.height}`,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    timestamp: Date.now()
                })
            """)
            
            data_str = json.dumps(browser_data, sort_keys=True) + accounts[0]["username"]
            return hashlib.sha256(data_str.encode()).hexdigest()
        except:
            return hashlib.sha256(f"{int(time.time())}{random.randint(1000, 9999)}".encode()).hexdigest()
    
    def _create_headers(self):
        """Создание заголовков для запросов"""
        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        
        self.headers = {
            "accept": "application/json",
            "accept-language": "ru-RU,ru;q=0.9",
            "content-type": "application/json",
            "referer": f"{BASE_URL}/dashboard/search",
            "sec-ch-ua": '"Chromium";v="145", "Not:A-Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "x-device-fingerprint": self.fingerprint,
            "cookie": cookie_header,
            "x-requested-with": "XMLHttpRequest"
        }
    
    def _process_task(self, task_type: str, task_data: Any):
        """Обработка задачи"""
        if task_type == "api_request":
            return self._make_api_request(task_data)
        elif task_type == "test_connection":
            return self._test_connection()
        elif task_type == "get_info":
            return self._get_worker_info()
        else:
            raise ValueError(f"Неизвестный тип задачи: {task_type}")
    
    def _make_api_request(self, task_data: Dict):
        """Выполнение API запроса"""
        endpoint = task_data["endpoint"]
        params = task_data.get("params", {})
        
        # Формируем URL
        url = urljoin(BASE_URL, endpoint)
        if params:
            query_string = urlencode(params, doseq=True)
            url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
        
        print(f"[PLAYWRIGHT WORKER] 📡 Запрос к: {url}")
        
        # Делаем запрос через контекст (все в одном потоке!)
        response = self.context.request.get(url, headers=self.headers, timeout=30000)
        
        result = {
            "status": response.status,
            "url": url,
            "text": response.text(),
            "headers": dict(response.headers)
        }
        
        if response.status == 200:
            try:
                result["json"] = response.json()
            except:
                result["json"] = None
        else:
            result["error"] = response.text()[:500]
            
        return result
    
    def _test_connection(self):
        """Тестовый запрос"""
        test_url = urljoin(BASE_URL, "/api/v3/search/iin?iin=931229400494")
        response = self.context.request.get(test_url, headers=self.headers, timeout=10000)
        return {"status": response.status, "test_passed": response.status == 200}
    
    def _get_worker_info(self):
        """Информация о рабочем потоке"""
        return {
            "thread": threading.current_thread().name,
            "thread_id": threading.get_ident(),
            "cookies_count": len(self.cookies),
            "fingerprint": self.fingerprint[:30] + "..." if self.fingerprint else None,
            "is_running": self.is_running
        }
    
    def submit_task(self, task_type: str, task_data: Dict, timeout: int = 30):
        """Отправить задачу в рабочий поток"""
        with self.task_lock:
            task_id = self.task_counter
            self.task_counter += 1
            
        result_queue = queue.Queue()
        self.result_queues[task_id] = result_queue
        
        # Отправляем задачу
        self.task_queue.put((task_id, task_type, task_data, result_queue))
        
        # Ждем результат
        try:
            result_id, result = result_queue.get(timeout=timeout)
            
            if result_id != task_id:
                raise RuntimeError(f"Несоответствие ID задачи: {result_id} != {task_id}")
            
            return result
            
        except queue.Empty:
            raise TimeoutError(f"Таймаут ожидания задачи {task_id}")
        finally:
            # Очищаем очередь результата
            with self.task_lock:
                if task_id in self.result_queues:
                    del self.result_queues[task_id]
    
    def stop(self):
        """Остановить рабочий поток"""
        self.is_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        
        if self.playwright:
            try:
                self.playwright.stop()
            except:
                pass

# Глобальный экземпляр рабочего потока
pw_worker = PlaywrightWorker()

# ================== 4. FLASK API ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

def crm_get(endpoint: str, params: dict = None):
    """API запрос через Playwright worker"""
    try:
        result = pw_worker.submit_task("api_request", {
            "endpoint": endpoint,
            "params": params
        }, timeout=30)
        
        if result["success"]:
            data = result["data"]
            return ResponseLike(
                status_code=data["status"],
                text=data["text"],
                json_data=data.get("json")
            )
        else:
            print(f"[CRM GET] ❌ Ошибка: {result.get('error')}")
            return ResponseLike(500, result.get("error", "Unknown error"))
            
    except Exception as e:
        print(f"[CRM GET] ❌ Исключение: {e}")
        return ResponseLike(500, str(e))

class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

# ================== 5. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    print(f"[SEARCH IIN] 🔍 Поиск по ИИН: {iin}")
    
    resp = crm_get("/api/v3/search/iin", params={"iin": iin})
    
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
    
    print(f"[SEARCH PHONE] 🔍 Поиск по телефону: {phone} (чистый: {clean})")
    
    resp = crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
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
    print(f"[SEARCH FIO] 🔍 Поиск по ФИО: {text}")
    
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
    
    resp = crm_get("/api/v3/search/fio", params=q)
    
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

# ================== 6. FLASK РОУТИНГ ==================
@app.before_request
def before_request():
    # Отключаем проверку сессий для тестов
    pass

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    print(f"\n" + "=" * 60)
    print(f"[SEARCH] 🔍 Запрос: {query}")
    print(f"[SEARCH] Поток: {threading.current_thread().name}")
    print("=" * 60)
    
    try:
        if query.isdigit() and len(query) == 12:
            reply = search_by_iin(query)
        elif query.startswith(("+", "8", "7")):
            reply = search_by_phone(query)
        else:
            reply = search_by_fio(query)
        
        print(f"[SEARCH] ✅ Ответ готов, длина: {len(reply)} символов")
        print("=" * 60)
        
        return jsonify({"result": reply})
        
    except Exception as e:
        print(f"[SEARCH] ❌ Ошибка: {e}")
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Тестируем соединение через worker
        result = pw_worker.submit_task("test_connection", {}, timeout=10)
        test_passed = result.get("success", False) and result.get("data", {}).get("test_passed", False)
        
        info = pw_worker.submit_task("get_info", {}, timeout=5)
        
        return jsonify({
            "status": "ok" if test_passed else "error",
            "worker_running": pw_worker.is_running,
            "worker_initialized": pw_worker.init_event.is_set(),
            "test_passed": test_passed,
            "worker_info": info.get("data") if info.get("success") else None,
            "queue_size": pw_worker.task_queue.qsize(),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "worker_running": pw_worker.is_running,
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/debug/worker', methods=['GET'])
def debug_worker():
    """Информация о рабочем потоке"""
    try:
        info = pw_worker.submit_task("get_info", {}, timeout=5)
        return jsonify({
            "success": True,
            "worker_info": info
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ================== 7. ЗАПУСК ==================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
    print("=" * 60)
    print("Архитектура: ВСЕ Playwright операции в одном потоке")
    print("Решена проблема: 'cannot switch to a different thread'")
    print("=" * 60)
    
    # Запускаем Playwright worker
    pw_worker.start()
    
    # Ждем инициализации
    print("\n[MAIN] ⏳ Ожидаем инициализации Playwright worker...")
    initialized = pw_worker.init_event.wait(timeout=30)
    
    if initialized:
        print("[MAIN] ✅ Playwright worker инициализирован!")
        
        # Тестируем соединение
        try:
            test_result = pw_worker.submit_task("test_connection", {}, timeout=10)
            if test_result.get("success"):
                print("[MAIN] ✅ Тестовый запрос успешен!")
            else:
                print(f"[MAIN] ⚠️ Тестовый запрос не прошел: {test_result.get('error')}")
        except Exception as e:
            print(f"[MAIN] ⚠️ Ошибка тестового запроса: {e}")
    else:
        print("[MAIN] ⚠️ Таймаут инициализации Playwright worker!")
    
    print("\n🌐 Flask сервер запускается на порту 5000...")
    print("📋 Проверка: http://localhost:5000/api/health")
    print("🔍 Поиск: POST http://localhost:5000/api/search")
    print("=" * 60)
    
    # Запускаем Flask
    app.run(host='0.0.0.0', port=5000, threaded=True, use_reloader=False)
