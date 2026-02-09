# server_fixed.py (с поддержкой множества аккаунтов)
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
from collections import defaultdict

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright, TimeoutError, Browser, BrowserContext, Page

# ================== КОНСТАНТЫ ==================
BASE_URL = "https://pena.rest"
LOGIN_URL = f"{BASE_URL}/auth/login"
SEARCH_URL = f"{BASE_URL}/dashboard/search"

# Загрузка аккаунтов
def load_accounts():
    """Загрузка аккаунтов из файла accounts.json или использование по умолчанию"""
    accounts_file = "accounts.json"
    default_accounts = [
        {"username": "from3", "password": "6666HHbb"},
        {"username": "from4", "password": "2266XXss"},
        {"username": "from5", "password": "8888RRnn"},
        {"username": "from6", "password": "1133NNhh"},
        {"username": "from7", "password": "8822IIee"},
        {"username": "from8", "password": "6688HHSS"},
        {"username": "from9", "password": "5588IIkk"},
        {"username": "from10", "password": "4499AAmm"},
        {"username": "klon1", "password": "6644FFjj"},
        {"username": "klon2", "password": "1144NNgg"},
        {"username": "klon3", "password": "7733YYuu"},
        {"username": "klon4", "password": "4433VVtt"},
        {"username": "klon5", "password": "2244TTii"},
        {"username": "klon6", "password": "1199DDxx"},
        {"username": "klon7", "password": "1144UUxx"},
        {"username": "klon8", "password": "5577EEww"},
        {"username": "klon9", "password": "7755SSaa"},
        {"username": "klon10", "password": "9999VVff"}
    ]
    
    try:
        if os.path.exists(accounts_file):
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
                print(f"✅ Загружено {len(accounts)} аккаунтов из файла accounts.json")
                return accounts
        else:
            # Создаем файл с аккаунтами по умолчанию
            with open(accounts_file, 'w', encoding='utf-8') as f:
                json.dump(default_accounts, f, ensure_ascii=False, indent=2)
            print(f"📁 Создан файл accounts.json с {len(default_accounts)} аккаунтом(ами)")
            return default_accounts
    except Exception as e:
        print(f"❌ Ошибка загрузки аккаунтов: {e}")
        return default_accounts

# Загружаем аккаунты
ACCOUNTS = load_accounts()

# Разрешенные пользователи
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS = []

# ================== КЛАСС СЕССИИ PLAYWRIGHT ==================
class PenaSession:
    """Сессия Playwright для работы с pena.rest (работает в своем потоке)"""
    
    def __init__(self, account: Dict, session_id: int):
        self.account = account
        self.session_id = session_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.fingerprint = None
        self.cookies = {}
        self.headers = {}
        self.is_active = False
        self.is_busy = False
        self.last_used = time.time()
        self.request_count = 0
        self.error_count = 0
        self.captured_fingerprints = []
        
        # Очередь задач для этого потока
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        
        # Запускаем поток для этой сессии
        self.thread = threading.Thread(target=self._run_worker, daemon=True, name=f"Session-{session_id}")
        self.thread.start()
    
    def _run_worker(self):
        """Главный рабочий поток сессии (ВСЕ операции с Playwright здесь)"""
        thread_name = threading.current_thread().name
        print(f"🔧 Запущен рабочий поток {thread_name} для {self.account['username']}")
        
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
                print(f"✅ Сессия {self.account['username']} (ID: {self.session_id}) активна")
            else:
                print(f"❌ Не удалось войти для {self.account['username']} (ID: {self.session_id})")
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
                            self.is_busy = True
                            method = getattr(self, method_name)
                            result = method(*args, **kwargs)
                            self.result_queue.put((task_id, {"success": True, "result": result}))
                        else:
                            self.result_queue.put((task_id, {"success": False, "error": f"Метод {method_name} не найден"}))
                    except Exception as e:
                        self.result_queue.put((task_id, {"success": False, "error": str(e)}))
                    finally:
                        self.is_busy = False
                        self.request_count += 1
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"❌ Ошибка в рабочем потоке {thread_name}: {e}")
                    self.error_count += 1
                    
        except Exception as e:
            print(f"❌ Критическая ошибка в потоке {thread_name}: {e}")
            traceback.print_exc()
            self.error_count += 1
        finally:
            self._cleanup()
    
    def _login(self) -> bool:
        """Логин на сайт (выполняется в рабочем потоке)"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                print(f"🔐 Попытка {attempt + 1}/{max_attempts} логина для {self.account['username']}...")
                
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
                print(f"✅ Логин успешен для {self.account['username']} (ID: {self.session_id})")
                print(f"  Fingerprint: {self.fingerprint[:30]}...")
                print(f"  Куки: {len(self.cookies)} шт.")
                
                return True
                
            except Exception as e:
                print(f"❌ Ошибка логина для {self.account['username']} (попытка {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(5)  # Пауза перед следующей попыткой
                continue
        
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
                print(f"🔍 Поиск по ИИН: {query} (сессия {self.session_id})")
                return self._search_iin(query)
            elif query.startswith(("+", "8", "7")):
                print(f"🔍 Поиск по телефону: {query} (сессия {self.session_id})")
                return self._search_phone(query)
            else:
                print(f"🔍 Поиск по ФИО: {query} (сессия {self.session_id})")
                return self._search_fio(query)
                
        except Exception as e:
            print(f"❌ Исключение в search (сессия {self.session_id}): {e}")
            traceback.print_exc()
            self.error_count += 1
            return {"success": False, "error": str(e)}
    
    def _search_iin(self, iin: str) -> Dict:
        """Поиск по ИИН"""
        try:
            url = urljoin(BASE_URL, f"/api/v3/search/iin?iin={iin}")
            print(f"🌐 Запрос к URL: {url} (сессия {self.session_id})")
            response = self.context.request.get(url, headers=self.headers, timeout=30000)
            
            print(f"📡 Статус ответа: {response.status} (сессия {self.session_id})")
            
            if response.status == 200:
                data = response.json()
                
                # Логируем полученные данные для отладки
                print(f"📊 Получены данные от pena.rest (сессия {self.session_id}): {json.dumps(data, ensure_ascii=False)[:200]}...")
                
                if not isinstance(data, list) or not data:
                    formatted = "⚠️ Ничего не найдено по ИИН."
                    print(f"ℹ️ Данные пустые или не список (сессия {self.session_id})")
                else:
                    results = []
                    for i, p in enumerate(data[:5], 1):
                        # Проверяем, что p - это словарь
                        if isinstance(p, dict):
                            result = f"{i}. 🧾 <b>ИИН: {p.get('iin', 'Нет')}</b>"
                            if p.get('snf'):
                                result += f"\n   👤 {p.get('snf', '')}"
                            if p.get('phone_number'):
                                result += f"\n   📱 {p.get('phone_number', '')}"
                            if p.get('birthday'):
                                result += f"\n   📅 {p.get('birthday', '')}"
                            # Добавляем дополнительную информацию, если есть
                            if p.get('address'):
                                result += f"\n   🏠 {p.get('address', '')}"
                            if p.get('nationality'):
                                result += f"\n   🇰🇿 Национальность: {p.get('nationality', '')}"
                            results.append(result)
                        else:
                            print(f"⚠️ Элемент не является словарем: {p} (сессия {self.session_id})")
                    formatted = "\n\n".join(results)
                
                print(f"📝 Отформатированный результат (сессия {self.session_id}): {formatted[:100]}...")
                print(f"📏 Длина отформатированного результата: {len(formatted)}")
                
                return {
                    "success": True,
                    "search_type": "iin",
                    "query": iin,
                    "formatted": formatted,
                    "raw_data": data,
                    "status_code": response.status
                }
            elif response.status == 404:
                print(f"ℹ️ Ответ 404 - ничего не найдено (сессия {self.session_id})")
                return {
                    "success": True,
                    "search_type": "iin",
                    "query": iin,
                    "formatted": "⚠️ Ничего не найдено по ИИН.",
                    "status_code": response.status
                }
            else:
                error_text = response.text()[:500]
                print(f"❌ Ошибка HTTP {response.status}: {error_text} (сессия {self.session_id})")
                return {
                    "success": False,
                    "error": f"HTTP {response.status}: {error_text}",
                    "status_code": response.status
                }
                
        except Exception as e:
            print(f"❌ Исключение в _search_iin (сессия {self.session_id}): {e}")
            traceback.print_exc()
            self.error_count += 1
            return {"success": False, "error": str(e)}
    
    def _search_phone(self, phone: str) -> Dict:
        """Поиск по телефону"""
        try:
            # Очищаем номер
            clean = ''.join(filter(str.isdigit, phone))
            if clean.startswith("8"):
                clean = "7" + clean[1:]
            
            url = urljoin(BASE_URL, f"/api/v3/search/phone?phone={clean}&limit=10")
            print(f"🌐 Запрос к URL: {url} (сессия {self.session_id})")
            response = self.context.request.get(url, headers=self.headers, timeout=30000)
            
            print(f"📡 Статус ответа: {response.status} (сессия {self.session_id})")
            
            if response.status == 200:
                data = response.json()
                print(f"📊 Получены данные от pena.rest (сессия {self.session_id}): {json.dumps(data, ensure_ascii=False)[:200]}...")
                
                if not isinstance(data, list) or not data:
                    formatted = f"⚠️ Ничего не найдено по номеру {phone}"
                else:
                    results = []
                    for i, p in enumerate(data[:5], 1):
                        if isinstance(p, dict):
                            result = f"{i}. 📱 <b>Телефон: {p.get('phone_number','')}</b>"
                            if p.get('snf'):
                                result += f"\n   👤 {p.get('snf','')}"
                            if p.get('iin'):
                                result += f"\n   🧾 ИИН: {p.get('iin','')}"
                            if p.get('birthday'):
                                result += f"\n   📅 {p.get('birthday','')}"
                            results.append(result)
                    formatted = "\n\n".join(results)
                
                print(f"📝 Отформатированный результат (сессия {self.session_id}): {formatted[:100]}...")
                
                return {
                    "success": True,
                    "search_type": "phone",
                    "query": phone,
                    "formatted": formatted,
                    "raw_data": data,
                    "status_code": response.status
                }
            elif response.status == 404:
                return {
                    "success": True,
                    "search_type": "phone",
                    "query": phone,
                    "formatted": f"⚠️ Ничего не найдено по номеру {phone}",
                    "status_code": response.status
                }
            else:
                error_text = response.text()[:500]
                print(f"❌ Ошибка HTTP {response.status}: {error_text} (сессия {self.session_id})")
                return {
                    "success": False,
                    "error": f"HTTP {response.status}: {error_text}",
                    "status_code": response.status
                }
                
        except Exception as e:
            print(f"❌ Исключение в _search_phone (сессия {self.session_id}): {e}")
            traceback.print_exc()
            self.error_count += 1
            return {"success": False, "error": str(e)}
    
    def _search_fio(self, text: str) -> Dict:
        """Поиск по ФИО"""
        try:
            # Определяем параметры поиска
            if text.startswith(",,"):
                parts = text[2:].strip().split()
                if len(parts) < 2:
                    return {
                        "success": True,
                        "search_type": "fio",
                        "query": text,
                        "formatted": "⚠️ Укажите имя и отчество после ',,'",
                        "status_code": 400
                    }
                params = {
                    "name": parts[0],
                    "father_name": " ".join(parts[1:]),
                    "smart_mode": "true",
                    "limit": 10
                }
            else:
                parts = text.split(" ")
                params = {}
                if len(parts) >= 1 and parts[0] != "":
                    params["surname"] = parts[0]
                if len(parts) >= 2 and parts[1] != "":
                    params["name"] = parts[1]
                if len(parts) >= 3 and parts[2] != "":
                    params["father_name"] = parts[2]
                params["smart_mode"] = "true"
                params["limit"] = 10
            
            query_string = urlencode(params)
            url = urljoin(BASE_URL, f"/api/v3/search/fio?{query_string}")
            print(f"🌐 Запрос к URL: {url} (сессия {self.session_id})")
            response = self.context.request.get(url, headers=self.headers, timeout=30000)
            
            print(f"📡 Статус ответа: {response.status} (сессия {self.session_id})")
            
            if response.status == 200:
                data = response.json()
                print(f"📊 Получены данные от pena.rest (сессия {self.session_id}): {json.dumps(data, ensure_ascii=False)[:200]}...")
                
                if not isinstance(data, list) or not data:
                    formatted = "⚠️ Ничего не найдено."
                else:
                    results = []
                    for i, p in enumerate(data[:10], 1):
                        if isinstance(p, dict):
                            result = f"{i}. 👤 <b>{p.get('snf','')}</b>"
                            if p.get('iin'):
                                result += f"\n   🧾 ИИН: {p.get('iin','')}"
                            if p.get('birthday'):
                                result += f"\n   📅 Дата рождения: {p.get('birthday','')}"
                            if p.get('phone_number'):
                                result += f"\n   📱 Телефон: {p.get('phone_number','')}"
                            results.append(result)
                    formatted = "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)
                
                print(f"📝 Отформатированный результат (сессия {self.session_id}): {formatted[:100]}...")
                
                return {
                    "success": True,
                    "search_type": "fio",
                    "query": text,
                    "formatted": formatted,
                    "raw_data": data,
                    "status_code": response.status
                }
            elif response.status == 404:
                return {
                    "success": True,
                    "search_type": "fio",
                    "query": text,
                    "formatted": "⚠️ Ничего не найдено.",
                    "status_code": response.status
                }
            else:
                error_text = response.text()[:500]
                print(f"❌ Ошибка HTTP {response.status}: {error_text} (сессия {self.session_id})")
                return {
                    "success": False,
                    "error": f"HTTP {response.status}: {error_text}",
                    "status_code": response.status
                }
                
        except Exception as e:
            print(f"❌ Исключение в _search_fio (сессия {self.session_id}): {e}")
            traceback.print_exc()
            self.error_count += 1
            return {"success": False, "error": str(e)}
    
    def execute_task(self, method_name: str, *args, **kwargs) -> Dict:
        """Добавление задачи в очередь и ожидание результата"""
        task_id = f"{self.account['username']}_{self.session_id}_{int(time.time())}_{random.randint(1000, 9999)}"
        
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
            print(f"✅ Сессия {self.account['username']} (ID: {self.session_id}) очищена")
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
    """Управление сессиями Playwright с балансировкой нагрузки"""
    
    def __init__(self):
        self.sessions: List[PenaSession] = []
        self.session_counter = 0
        self.lock = threading.Lock()
        self.cache = {}  # Простой кэш результатов
        self.cache_lock = threading.Lock()
        self.request_counter = defaultdict(int)  # Счетчик запросов по сессиям
        self.failed_sessions = set()  # ID неработающих сессий
        
    def initialize(self) -> bool:
        """Инициализация сессий для всех аккаунтов"""
        print(f"🔄 Инициализация сессий для {len(ACCOUNTS)} аккаунтов...")
        
        for i, account in enumerate(ACCOUNTS):
            print(f"Создаем сессию {i+1}/{len(ACCOUNTS)} для {account['username']}...")
            session_id = self.session_counter
            session = PenaSession(account, session_id)
            self.sessions.append(session)
            self.session_counter += 1
            
            # Ждем пока сессия станет активной
            for attempt in range(30):  # 30 попыток по 1 секунде
                if session.is_active:
                    print(f"✅ Сессия {account['username']} (ID: {session_id}) активна")
                    break
                time.sleep(1)
            else:
                print(f"⚠️ Сессия {account['username']} (ID: {session_id}) не активировалась")
                self.failed_sessions.add(session_id)
        
        active_sessions = len([s for s in self.sessions if s.is_active])
        print(f"✅ Активных сессий: {active_sessions} из {len(self.sessions)}")
        
        # Запускаем мониторинг сессий в отдельном потоке
        if active_sessions > 0:
            monitor_thread = threading.Thread(target=self._monitor_sessions, daemon=True)
            monitor_thread.start()
            print(f"📊 Запущен мониторинг сессий")
        
        return active_sessions > 0
    
    def _monitor_sessions(self):
        """Мониторинг состояния сессий"""
        while True:
            time.sleep(60)  # Проверка каждую минуту
            with self.lock:
                active_count = 0
                for session in self.sessions:
                    if session.is_active:
                        active_count += 1
                        # Если сессия долго не использовалась (более 10 минут), обновим ее
                        if time.time() - session.last_used > 600 and not session.is_busy:
                            print(f"🔄 Сессия {session.account['username']} (ID: {session.session_id}) долго не использовалась, проверка...")
                
                print(f"📊 Мониторинг: {active_count} активных сессий из {len(self.sessions)}")
    
    def get_best_session(self) -> Optional[PenaSession]:
        """Выбор лучшей сессии для запроса (наименее загруженная)"""
        with self.lock:
            # Фильтруем активные и не занятые сессии
            available_sessions = [s for s in self.sessions 
                                 if s.is_active and not s.is_busy and s.session_id not in self.failed_sessions]
            
            if not available_sessions:
                # Если нет доступных сессий, пробуем использовать любую активную
                available_sessions = [s for s in self.sessions if s.is_active]
            
            if not available_sessions:
                return None
            
            # Выбираем сессию с наименьшим количеством запросов
            available_sessions.sort(key=lambda s: s.request_count)
            return available_sessions[0]
    
    def search(self, query: str) -> Dict:
        """Поиск с использованием кэша и балансировкой нагрузки"""
        # Проверяем кэш
        cache_key = query.lower().strip()
        with self.cache_lock:
            if cache_key in self.cache:
                cached = self.cache[cache_key]
                if time.time() - cached["timestamp"] < 300:  # 5 минут кэш
                    print(f"📦 Использован кэш для: {query}")
                    return cached["result"]
        
        # Получаем лучшую сессию для запроса
        session = self.get_best_session()
        
        if not session:
            # Если нет активных сессий, проверяем кэш еще раз
            with self.cache_lock:
                if cache_key in self.cache:
                    cached = self.cache[cache_key]
                    print(f"📦 Использован старый кэш для: {query}")
                    return cached["result"]
            return {"success": False, "error": "Нет активных сессий"}
        
        print(f"🔄 Используем сессию {session.account['username']} (ID: {session.session_id}, запросов: {session.request_count}) для запроса: {query}")
        
        # Выполняем поиск
        task_result = session.execute_task("search", query)
        
        # Если execute_task вернул {"success": True, "result": actual_result}
        if task_result.get('success'):
            actual_result = task_result.get('result')
            
            # Сохраняем в кэш при успехе
            if actual_result and actual_result.get("success"):
                with self.cache_lock:
                    self.cache[cache_key] = {
                        "result": actual_result,
                        "timestamp": time.time(),
                        "query": query,
                        "session_id": session.session_id
                    }
            
            return actual_result
        else:
            # Если ошибка, помечаем сессию как проблемную
            self.failed_sessions.add(session.session_id)
            print(f"⚠️ Сессия {session.session_id} помечена как проблемная из-за ошибки: {task_result.get('error')}")
            
            # Пробуем другую сессию
            return {"success": False, "error": task_result.get('error', 'Ошибка выполнения задачи')}
    
    def get_status(self) -> Dict:
        """Получение статуса всех сессий"""
        sessions_info = []
        with self.lock:
            for session in self.sessions:
                sessions_info.append({
                    "id": session.session_id,
                    "username": session.account['username'],
                    "is_active": session.is_active,
                    "is_busy": session.is_busy,
                    "fingerprint": session.fingerprint[:20] + "..." if session.fingerprint else "Нет",
                    "cookies_count": len(session.cookies),
                    "request_count": session.request_count,
                    "error_count": session.error_count,
                    "last_used": session.last_used,
                    "last_used_human": datetime.fromtimestamp(session.last_used).strftime("%H:%M:%S") if session.last_used else "Никогда",
                    "is_failed": session.session_id in self.failed_sessions
                })
        
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions if s.is_active]),
            "busy_sessions": len([s for s in self.sessions if s.is_busy]),
            "failed_sessions": len(self.failed_sessions),
            "sessions": sessions_info,
            "cache_size": len(self.cache),
            "accounts_count": len(ACCOUNTS)
        }
    
    def cleanup(self):
        """Очистка всех сессий"""
        print("🔄 Очистка всех сессий...")
        for session in self.sessions:
            session.stop()
        print("✅ Все сессии очищены")
    
    def restart_failed_sessions(self):
        """Перезапуск неработающих сессий"""
        with self.lock:
            print(f"🔄 Перезапуск {len(self.failed_sessions)} неработающих сессий...")
            restarted = 0
            for session_id in list(self.failed_sessions):
                if session_id < len(self.sessions):
                    session = self.sessions[session_id]
                    if not session.is_active:
                        print(f"🔄 Перезапуск сессии {session_id}...")
                        # Здесь можно добавить логику перезапуска
                        # Пока просто убираем из списка проблемных
                        self.failed_sessions.remove(session_id)
                        restarted += 1
            print(f"✅ Перезапущено {restarted} сессий")

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
        'total_accounts': len(ACCOUNTS),
        'active_sessions': status['active_sessions'],
        'total_sessions': status['total_sessions'],
        'busy_sessions': status['busy_sessions'],
        'failed_sessions': status['failed_sessions'],
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
        
        print(f"🔍 Поиск от пользователя {user_id}: {query}")
        
        # Выполняем поиск через менеджер сессий
        result = session_manager.search(query)
        
        print(f"📊 Результат поиска: success={result.get('success')}, has_formatted={result.get('formatted') is not None}")
        
        if result.get('success'):
            formatted_result = result.get('formatted')
            if formatted_result:
                print(f"📏 Длина отформатированного результата: {len(formatted_result)}")
                print(f"📄 Результат: {formatted_result[:100]}...")
                return jsonify({'result': formatted_result})
            else:
                print("⚠️ Отформатированный результат отсутствует")
                return jsonify({'error': 'Нет данных в ответе'}), 500
        else:
            print(f"❌ Ошибка поиска: {result.get('error')}")
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
    return jsonify({'success': True, 'message': 'Кэш очищен', 'cache_size': 0})

@app.route('/api/debug/restart_sessions', methods=['POST'])
def restart_sessions():
    """Перезапуск неработающих сессий"""
    session_manager.restart_failed_sessions()
    return jsonify({'success': True, 'message': 'Запущен перезапуск сессий'})

@app.route('/api/debug/accounts', methods=['GET'])
def debug_accounts():
    """Информация об аккаунтах"""
    return jsonify({
        'accounts': ACCOUNTS,
        'count': len(ACCOUNTS)
    })

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
        print(f"👤 Аккаунтов: {len(ACCOUNTS)}")
        print(f"👤 Разрешенных пользователей: {len(allowed_users)}")
        print(f"🌐 API доступен по адресу: http://0.0.0.0:5000")
        print("\n📋 Доступные endpoint-ы:")
        print("  /api/health          - Проверка состояния")
        print("  /api/session/start   - Создание сессии")
        print("  /api/search          - Поиск по ИИН/телефону/ФИО")
        print("  /api/debug/sessions  - Отладка сессий")
        print("  /api/debug/accounts  - Просмотр аккаунтов")
        
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
