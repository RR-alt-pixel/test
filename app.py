# -*- coding: utf-8 -*-
import os
import time
import json
import random
import threading
import traceback
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Any
from queue import Queue
from urllib.parse import urlencode, urljoin

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

# ================== КОНСТАНТЫ ==================
BASE_URL = "https://pena.rest"
LOGIN_URL = f"{BASE_URL}/auth/login"
SEARCH_URL = f"{BASE_URL}/dashboard/search"

# Аккаунты
ACCOUNTS = [
    {"username": "klon9", "password": "7755SSaa"}
]

# Разрешенные пользователи
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS = []

# ================== СЕССИЯ PLAYWRIGHT ==================
class PenaSession:
    """Сессия для работы с pena.rest в одном потоке"""
    
    def __init__(self, account: Dict):
        self.account = account
        self.browser = None
        self.context = None
        self.page = None
        self.cookies = {}
        self.fingerprint = None
        self.headers = {}
        self.is_active = False
        self.last_used = 0
        
    def login(self):
        """Логин на сайт"""
        print(f"🔐 Логин {self.account['username']}...")
        
        try:
            # Запускаем браузер
            playwright = sync_playwright().start()
            
            self.browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
                slow_mo=100
            )
            
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            
            # Маскировка Playwright
            self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            self.page = self.context.new_page()
            
            # Логин
            self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            
            # Заполняем форму
            self.page.fill('input[placeholder="Логин"]', self.account['username'])
            time.sleep(0.5)
            self.page.fill('input[placeholder="Пароль"]', self.account['password'])
            time.sleep(0.5)
            
            # Нажимаем кнопку
            self.page.click('button[type="submit"]')
            time.sleep(3)
            
            # Проверяем успешность
            current_url = self.page.url
            if "dashboard" not in current_url:
                print(f"⚠️ Dashboard не найден, пробуем перейти...")
                self.page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=10000)
                time.sleep(2)
            
            # Переходим на страницу поиска
            self.page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            time.sleep(3)
            
            # Получаем куки
            cookies_list = self.context.cookies()
            self.cookies = {c['name']: c['value'] for c in cookies_list}
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
            
            # Генерируем fingerprint
            self.fingerprint = self._generate_fingerprint()
            
            # Формируем заголовки
            self.headers = {
                "accept": "application/json",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "ru-RU,ru;q=0.9",
                "content-type": "application/json",
                "priority": "u=1, i",
                "referer": SEARCH_URL,
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
            
            self.is_active = True
            self.last_used = time.time()
            
            print(f"✅ Сессия создана для {self.account['username']}")
            print(f"📋 Fingerprint: {self.fingerprint[:30]}...")
            print(f"🍪 Куки: {len(self.cookies)} шт.")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания сессии: {e}")
            traceback.print_exc()
            self.close()
            return False
    
    def _generate_fingerprint(self) -> str:
        """Генерация fingerprint"""
        try:
            browser_data = self.page.evaluate("""
                () => {
                    return {
                        userAgent: navigator.userAgent,
                        platform: navigator.platform,
                        languages: navigator.languages.join(','),
                        hardwareConcurrency: navigator.hardwareConcurrency,
                        deviceMemory: navigator.deviceMemory,
                        screen: `${screen.width}x${screen.height}`,
                        colorDepth: screen.colorDepth,
                        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                        sessionStorage: sessionStorage.length,
                        localStorage: localStorage.length,
                        timestamp: Date.now(),
                        random: Math.random().toString(36).substring(2)
                    };
                }
            """)
            
            data_str = json.dumps(browser_data, sort_keys=True) + self.account['username'] + str(time.time())
            return hashlib.sha256(data_str.encode()).hexdigest()
        except:
            data_str = f"{self.account['username']}{int(time.time())}{random.randint(1000, 9999)}"
            return hashlib.sha256(data_str.encode()).hexdigest()
    
    def search(self, search_type: str, query: str) -> Dict:
        """Выполнение поискового запроса"""
        self.last_used = time.time()
        
        try:
            # Формируем URL и параметры
            if search_type == "iin":
                url = urljoin(BASE_URL, f"/api/v3/search/iin?iin={query}")
            elif search_type == "phone":
                clean = ''.join(filter(str.isdigit, query))
                if clean.startswith("8"):
                    clean = "7" + clean[1:]
                url = urljoin(BASE_URL, f"/api/v3/search/phone?phone={clean}&limit=10")
            elif search_type == "fio":
                parts = query.split(" ", 2)
                params = {}
                if len(parts) >= 1:
                    params["surname"] = parts[0]
                if len(parts) >= 2:
                    params["name"] = parts[1]
                if len(parts) >= 3:
                    params["father_name"] = parts[2]
                params["smart_mode"] = "true"
                params["limit"] = 10
                query_string = urlencode(params)
                url = urljoin(BASE_URL, f"/api/v3/search/fio?{query_string}")
            else:
                return {"success": False, "error": f"Неизвестный тип поиска: {search_type}"}
            
            # Выполняем запрос
            response = self.context.request.get(url, headers=self.headers, timeout=30000)
            
            if response.status == 200:
                data = response.json()
                return {"success": True, "data": data}
            else:
                error_text = response.text()[:500]
                print(f"❌ Ошибка запроса: HTTP {response.status}")
                return {"success": False, "error": f"HTTP {response.status}: {error_text}"}
                
        except Exception as e:
            print(f"❌ Исключение при запросе: {e}")
            return {"success": False, "error": str(e)}
    
    def close(self):
        """Закрытие сессии"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            self.is_active = False
            print(f"✅ Сессия закрыта")
        except:
            pass

# ================== МЕНЕДЖЕР СЕССИЙ ==================
class SessionManager:
    """Управление сессиями - ВСЕ В ОДНОМ ПОТОКЕ"""
    
    def __init__(self):
        self.sessions: List[PenaSession] = []
        self.current_index = 0
        self.lock = threading.Lock()
        self.request_queue = Queue()
        self.worker_thread = None
        
    def initialize(self):
        """Инициализация сессий"""
        print("🔄 Инициализация сессий...")
        
        for account in ACCOUNTS:
            session = PenaSession(account)
            if session.login():
                self.sessions.append(session)
        
        if self.sessions:
            print(f"✅ Создано сессий: {len(self.sessions)}")
            # Запускаем воркер для обработки запросов
            self.worker_thread = threading.Thread(target=self._process_requests, daemon=True)
            self.worker_thread.start()
            return True
        else:
            print("❌ Не удалось создать ни одной сессии")
            return False
    
    def _process_requests(self):
        """Обработка запросов из очереди (в одном потоке)"""
        print("🔧 Запущен воркер обработки запросов")
        
        while True:
            try:
                # Получаем запрос из очереди
                request_data = self.request_queue.get(timeout=1)
                
                # Обрабатываем запрос
                self._handle_request(request_data)
                
            except Exception as e:
                continue
    
    def _handle_request(self, request_data: Dict):
        """Обработка одного запроса"""
        try:
            # Выбираем сессию (round-robin)
            with self.lock:
                if not self.sessions:
                    request_data['result'] = "❌ Нет активных сессий"
                    request_data['event'].set()
                    return
                
                session = self.sessions[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.sessions)
            
            # Выполняем поиск
            result = session.search(request_data['search_type'], request_data['query'])
            
            if result['success']:
                # Форматируем результат
                formatted = self._format_result(result['data'], request_data['search_type'])
                request_data['result'] = formatted
            else:
                request_data['result'] = f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}"
            
        except Exception as e:
            request_data['result'] = f"❌ Исключение: {str(e)}"
        
        finally:
            # Сигнализируем о завершении
            request_data['event'].set()
    
    def _format_result(self, data: Any, search_type: str) -> str:
        """Форматирование результата поиска"""
        if not isinstance(data, list) or not data:
            return "⚠️ Ничего не найдено."
        
        results = []
        for i, item in enumerate(data[:5], 1):
            if search_type == "iin":
                result = f"{i}. 🧾 <b>ИИН: {item.get('iin', 'Нет')}</b>"
                if item.get('snf'):
                    result += f"\n   👤 {item.get('snf')}"
                if item.get('phone_number'):
                    result += f"\n   📱 {item.get('phone_number')}"
                if item.get('birthday'):
                    result += f"\n   📅 {item.get('birthday')}"
            
            elif search_type == "phone":
                result = f"{i}. 📱 <b>Телефон: {item.get('phone_number', 'Нет')}</b>"
                if item.get('snf'):
                    result += f"\n   👤 {item.get('snf')}"
                if item.get('iin'):
                    result += f"\n   🧾 ИИН: {item.get('iin')}"
            
            elif search_type == "fio":
                result = f"{i}. 👤 <b>{item.get('snf', 'Нет ФИО')}</b>"
                if item.get('iin'):
                    result += f"\n   🧾 ИИН: {item.get('iin')}"
                if item.get('birthday'):
                    result += f"\n   📅 {item.get('birthday')}"
                if item.get('phone_number'):
                    result += f"\n   📱 Телефон: {item.get('phone_number')}"
            
            results.append(result)
        
        return "\n\n".join(results)
    
    def add_search_request(self, search_type: str, query: str) -> str:
        """Добавление запроса в очередь и ожидание результата"""
        event = threading.Event()
        request_data = {
            'search_type': search_type,
            'query': query,
            'event': event,
            'result': None
        }
        
        # Добавляем в очередь
        self.request_queue.put(request_data)
        
        # Ждем результат (таймаут 30 секунд)
        if event.wait(timeout=30):
            return request_data['result']
        else:
            return "⌛ Таймаут ожидания результата"

# ================== FLASK СЕРВЕР ==================
app = Flask(__name__)
CORS(app)

# Глобальные объекты
session_manager = SessionManager()
user_sessions = {}  # user_id -> session_token
allowed_users = []

def load_allowed_users():
    """Загрузка разрешенных пользователей"""
    global allowed_users
    try:
        print(f"🔐 Загрузка разрешенных пользователей...")
        response = requests.get(ALLOWED_USERS_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            allowed_users = [int(uid) for uid in data.get("allowed_users", [])]
            print(f"✅ Загружено {len(allowed_users)} пользователей")
        else:
            print(f"⚠️ Не удалось загрузить пользователей")
            allowed_users = []
    except Exception as e:
        print(f"❌ Ошибка загрузки пользователей: {e}")
        allowed_users = []

@app.before_request
def before_request():
    """Обработка CORS"""
    if request.method == 'OPTIONS':
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response

@app.route('/api/health', methods=['GET'])
def health():
    """Проверка здоровья сервера"""
    return jsonify({
        'status': 'ok',
        'sessions': len(session_manager.sessions),
        'queue_size': session_manager.request_queue.qsize(),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/session/start', methods=['POST'])
def start_session():
    """Создание сессии пользователя"""
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type должен быть application/json'}), 415
        
        data = request.get_json()
        user_id = data.get('telegram_user_id')
        
        if not user_id:
            return jsonify({'error': 'Не указан Telegram ID'}), 400
        
        # Загружаем актуальный список пользователей
        load_allowed_users()
        
        user_id_int = int(user_id)
        
        # Проверяем доступ (если есть разрешенные пользователи)
        if allowed_users and user_id_int not in allowed_users:
            print(f"❌ Пользователь {user_id_int} не имеет доступа")
            return jsonify({'error': 'Нет доступа'}), 403
        
        # Создаем сессию
        session_token = f"{user_id_int}_{int(time.time())}_{random.randint(1000, 9999)}"
        user_sessions[user_id_int] = {
            'token': session_token,
            'created': time.time()
        }
        
        print(f"🔑 Создана сессия для пользователя {user_id_int}")
        return jsonify({'session_token': session_token})
        
    except Exception as e:
        print(f"❌ Ошибка создания сессии: {e}")
        return jsonify({'error': 'Внутренняя ошибка'}), 500

@app.route('/api/search', methods=['POST'])
def search():
    """Поиск по ИИН, телефону или ФИО"""
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type должен быть application/json'}), 415
        
        data = request.get_json()
        user_id = data.get('telegram_user_id')
        session_token = data.get('session_token')
        query = data.get('query', '').strip()
        
        if not user_id or not session_token:
            return jsonify({'error': 'Не указаны учетные данные'}), 403
        
        if not query:
            return jsonify({'error': 'Пустой запрос'}), 400
        
        # Проверяем сессию
        user_id_int = int(user_id)
        session = user_sessions.get(user_id_int)
        
        if not session or session['token'] != session_token:
            return jsonify({'error': 'Недействительная сессия'}), 403
        
        # Проверяем, не истекла ли сессия (1 час)
        if time.time() - session['created'] > 3600:
            del user_sessions[user_id_int]
            return jsonify({'error': 'Сессия истекла'}), 403
        
        print(f"🔍 Поиск от пользователя {user_id}: {query[:50]}...")
        
        # Определяем тип поиска
        if query.isdigit() and len(query) == 12:
            search_type = "iin"
        elif query.startswith(("+", "8", "7")):
            search_type = "phone"
        else:
            search_type = "fio"
        
        # Отправляем запрос в очередь
        result = session_manager.add_search_request(search_type, query)
        
        return jsonify({'result': result})
        
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Внутренняя ошибка'}), 500

# ================== ЗАПУСК ==================
if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
    print("=" * 60)
    
    # Загружаем разрешенных пользователей
    load_allowed_users()
    
    # Инициализируем сессии
    if session_manager.initialize():
        print(f"\n✅ СЕРВЕР ГОТОВ К РАБОТЕ!")
        print(f"📊 Активных сессий: {len(session_manager.sessions)}")
        print(f"👤 Разрешенных пользователей: {len(allowed_users)}")
        print(f"🌐 API доступен по адресу: http://0.0.0.0:5000")
        
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    else:
        print("❌ Не удалось инициализировать сессии")
