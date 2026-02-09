# server_fixed.py
import os
import time
import json
import hashlib
import traceback
import threading
import random
import queue
import sys
from datetime import datetime
from urllib.parse import urljoin, quote, urlencode
from typing import Optional, Dict, List, Any, Tuple

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright, TimeoutError, Browser, BrowserContext, Page

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

# ================== КЛАСС СЕССИИ PLAYWRIGHT ==================
class PenaSession:
    """Сессия Playwright для работы с pena.rest (работает в своем потоке)"""
    
    def __init__(self, account: Dict):
        self.account = account
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.fingerprint = None
        self.cookies = {}
        self.headers = {}
        self.is_active = False
        self.last_used = time.time()
        self.captured_fingerprints = []
        
        # Очередь задач для этого потока
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        
        # Запускаем поток для этой сессии
        self.thread = threading.Thread(target=self._run_worker, daemon=True)
        self.thread.start()
    
    def _run_worker(self):
        """Главный рабочий поток сессии (ВСЕ операции с Playwright здесь)"""
        print(f"🔧 Запущен рабочий поток для {self.account['username']}")
        
        try:
            # Инициализируем Playwright в этом потоке
            self.playwright = sync_playwright().start()
            
            # Запускаем браузер
            self.browser = self.playwright.chromium.launch(
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
                timeout=60000
            )
            
            # Создаем контекст
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
            
            # Логинимся
            if self._login():
                self.is_active = True
                print(f"✅ Сессия {self.account['username']} активна")
            else:
                print(f"❌ Не удалось войти для {self.account['username']}")
                return
            
            # Основной цикл обработки задач
            while not self.stop_event.is_set():
                try:
                    # Получаем задачу из очереди
                    task_id, method_name, args, kwargs = self.task_queue.get(timeout=1)
                    
                    if method_name == "stop":
                        break
                    
                    # Выполняем метод
                    try:
                        if hasattr(self, method_name):
                            method = getattr(self, method_name)
                            result = method(*args, **kwargs)
                            self.result_queue.put((task_id, {"success": True, "result": result}))
                        else:
                            self.result_queue.put((task_id, {"success": False, "error": f"Метод {method_name} не найден"}))
                    except Exception as e:
                        self.result_queue.put((task_id, {"success": False, "error": str(e)}))
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"❌ Ошибка в рабочем потоке: {e}")
                    
        except Exception as e:
            print(f"❌ Критическая ошибка в потоке {self.account['username']}: {e}")
            traceback.print_exc()
        finally:
            self._cleanup()
    
    def _login(self) -> bool:
        """Логин на сайт (выполняется в рабочем потоке)"""
        try:
            print(f"🔐 Логин {self.account['username']}...")
            
            # Настраиваем перехватчик запросов для сбора fingerprint
            def extract_fingerprint(request):
                # Ищем в заголовках
                if 'x-device-fingerprint' in request.headers:
                    fp = request.headers['x-device-fingerprint']
                    if fp and len(fp) == 64 and fp not in self.captured_fingerprints:
                        self.captured_fingerprints.append(fp)
                        print(f"[{self.account['username']}] Найден fingerprint: {fp[:30]}...")
                        self.fingerprint = fp
                
                # Ищем в теле запроса
                if request.post_data:
                    try:
                        data = json.loads(request.post_data)
                        if 'device_fingerprint' in data and data['device_fingerprint']:
                            fp = data['device_fingerprint']
                            if fp and len(fp) == 64 and fp not in self.captured_fingerprints:
                                self.captured_fingerprints.append(fp)
                                print(f"[{self.account['username']}] Найден fingerprint в теле: {fp[:30]}...")
                                self.fingerprint = fp
                    except:
                        pass
            
            self.page.on("request", extract_fingerprint)
            
            # Переходим на страницу логина
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
            print(f"🌐 Переходим на страницу поиска...")
            self.page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            time.sleep(3)
            
            # Если fingerprint не извлечен, генерируем
            if not self.fingerprint and self.captured_fingerprints:
                self.fingerprint = self.captured_fingerprints[0]
            elif not self.fingerprint:
                print(f"⚠️ Fingerprint не извлечен, генерируем...")
                self.fingerprint = self._generate_fingerprint()
            
            # Получаем куки
            cookies_list = self.context.cookies()
            self.cookies = {c['name']: c['value'] for c in cookies_list}
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
            
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
            
            self.last_used = time.time()
            print(f"✅ Логин успешен для {self.account['username']}")
            print(f"  Fingerprint: {self.fingerprint[:30]}...")
            print(f"  Куки: {len(self.cookies)} шт.")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка логина для {self.account['username']}: {e}")
            traceback.print_exc()
            return False
    
    def _generate_fingerprint(self) -> str:
        """Генерация fingerprint (резервный метод)"""
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
    
    def search(self, query: str) -> Dict:
        """Поиск по запросу (выполняется в рабочем потоке)"""
        self.last_used = time.time()
        
        try:
            # Определяем тип поиска
            if query.isdigit() and len(query) == 12:
                search_type = "iin"
            elif query.startswith(("+", "8", "7")):
                search_type = "phone"
            else:
                search_type = "fio"
            
            # Формируем URL
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
            
            # Выполняем запрос
            response = self.context.request.get(url, headers=self.headers, timeout=30000)
            
            if response.status == 200:
                data = response.json()
                
                # Форматируем результат
                formatted = self._format_result(data, search_type)
                
                return {
                    "success": True,
                    "search_type": search_type,
                    "query": query,
                    "formatted": formatted,
                    "raw_data": data,
                    "status_code": response.status
                }
            else:
                error_text = response.text()[:500]
                return {
                    "success": False,
                    "error": f"HTTP {response.status}: {error_text}",
                    "status_code": response.status
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
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
    
    def execute_task(self, method_name: str, *args, **kwargs) -> Dict:
        """Добавление задачи в очередь и ожидание результата"""
        task_id = f"{self.account['username']}_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # Добавляем задачу в очередь
        self.task_queue.put((task_id, method_name, args, kwargs))
        
        # Ждем результат
        start_time = time.time()
        while time.time() - start_time < 30:  # Таймаут 30 секунд
            try:
                # Проверяем очередь результатов
                result_id, result = self.result_queue.get(timeout=0.1)
                if result_id == task_id:
                    return result
                else:
                    # Не наш результат, кладем обратно
                    self.result_queue.put((result_id, result))
            except queue.Empty:
                continue
        
        return {"success": False, "error": "Таймаут ожидания результата"}
    
    def _cleanup(self):
        """Очистка ресурсов"""
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            self.is_active = False
            print(f"✅ Сессия {self.account['username']} очищена")
        except:
            pass
    
    def stop(self):
        """Остановка рабочего потока"""
        self.stop_event.set()
        self.task_queue.put(("dummy", "stop", [], {}))
        if self.thread.is_alive():
            self.thread.join(timeout=5)

# ================== МЕНЕДЖЕР СЕССИЙ ==================
class SessionManager:
    """Управление сессиями Playwright"""
    
    def __init__(self):
        self.sessions: List[PenaSession] = []
        self.current_index = 0
        self.lock = threading.Lock()
        self.cache = {}  # Простой кэш результатов
        self.cache_lock = threading.Lock()
        
    def initialize(self) -> bool:
        """Инициализация сессий"""
        print("🔄 Инициализация сессий...")
        
        for account in ACCOUNTS:
            print(f"Создаем сессию для {account['username']}...")
            session = PenaSession(account)
            self.sessions.append(session)
            
            # Ждем пока сессия станет активной
            for _ in range(30):  # 30 попыток по 1 секунде
                if session.is_active:
                    print(f"✅ Сессия {account['username']} активна")
                    break
                time.sleep(1)
            else:
                print(f"⚠️ Сессия {account['username']} не активировалась")
        
        active_sessions = len([s for s in self.sessions if s.is_active])
        print(f"✅ Активных сессий: {active_sessions} из {len(self.sessions)}")
        
        return active_sessions > 0
    
    def search(self, query: str) -> Dict:
        """Поиск с использованием кэша и round-robin"""
        # Проверяем кэш
        cache_key = query.lower().strip()
        with self.cache_lock:
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                if time.time() - cached["timestamp"] < 300:  # 5 минут кэш
                    print(f"📦 Использован кэш для: {query}")
                    return cached["result"]
        
        with self.lock:
            if not self.sessions:
                return {"success": False, "error": "Нет активных сессий"}
            
            # Выбираем сессию round-robin
            for _ in range(len(self.sessions)):
                session = self.sessions[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.sessions)
                
                if session.is_active:
                    print(f"🔄 Используем сессию {session.account['username']} для запроса: {query}")
                    
                    # Выполняем поиск
                    result = session.execute_task("search", query)
                    
                    # Сохраняем в кэш при успехе
                    if result.get("success"):
                        with self.cache_lock:
                            self.cache[cache_key] = {
                                "result": result,
                                "timestamp": time.time(),
                                "query": query
                            }
                    
                    return result
        
        return {"success": False, "error": "Нет доступных сессий"}
    
    def get_status(self) -> Dict:
        """Получение статуса всех сессий"""
        sessions_info = []
        for session in self.sessions:
            sessions_info.append({
                "username": session.account['username'],
                "is_active": session.is_active,
                "fingerprint": session.fingerprint[:20] + "..." if session.fingerprint else "Нет",
                "cookies_count": len(session.cookies),
                "last_used": session.last_used
            })
        
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions if s.is_active]),
            "sessions": sessions_info,
            "cache_size": len(self.cache)
        }
    
    def cleanup(self):
        """Очистка всех сессий"""
        print("🔄 Очистка всех сессий...")
        for session in self.sessions:
            session.stop()
        print("✅ Все сессии очищены")

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
    status = session_manager.get_status()
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'sessions': status['active_sessions'],
        'total_sessions': status['total_sessions'],
        'cache_size': status['cache_size'],
        'queue_size': 0
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
        
        # Выполняем поиск через менеджер сессий
        result = session_manager.search(query)
        
        if result.get('success'):
            return jsonify({'result': result.get('formatted')})
        else:
            return jsonify({'error': result.get('error', 'Неизвестная ошибка')}), 500
        
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Внутренняя ошибка'}), 500

@app.route('/api/debug/sessions', methods=['GET'])
def debug_sessions():
    """Отладочная информация о сессиях"""
    status = session_manager.get_status()
    return jsonify(status)

@app.route('/api/debug/clear_cache', methods=['POST'])
def clear_cache():
    """Очистка кэша"""
    with session_manager.cache_lock:
        session_manager.cache.clear()
    return jsonify({'success': True, 'message': 'Кэш очищен'})

# ================== ЗАПУСК ==================
def cleanup_on_exit():
    """Очистка при выходе"""
    print("\n🛑 Очистка ресурсов при выходе...")
    session_manager.cleanup()
    sys.exit(0)

if __name__ == '__main__':
    import signal
    signal.signal(signal.SIGINT, lambda s, f: cleanup_on_exit())
    signal.signal(signal.SIGTERM, lambda s, f: cleanup_on_exit())
    
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА")
    print("=" * 60)
    
    # Загружаем разрешенных пользователей
    load_allowed_users()
    
    # Инициализируем сессии
    if session_manager.initialize():
        print(f"\n✅ СЕРВЕР ГОТОВ К РАБОТЕ!")
        print(f"📊 Активных сессий: {len([s for s in session_manager.sessions if s.is_active])}")
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
        cleanup_on_exit()
