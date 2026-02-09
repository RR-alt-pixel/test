# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import random
import signal
import threading
import traceback
import hashlib
import itertools
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from queue import Queue, Empty
from urllib.parse import urlencode, urljoin, quote
from threading import Thread, Lock, Event, Timer
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError

import requests
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

# ================== КОНСТАНТЫ И НАСТРОЙКИ ==================
BASE_URL = "https://pena.rest"
LOGIN_URL = f"{BASE_URL}/auth/login"
SEARCH_URL = f"{BASE_URL}/dashboard/search"

# Токены и безопасность
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4")
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "Refresh-Server-Key-2025-Oct-VK44")
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"

# Селекторы для авторизации
LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SUBMIT_SELECTOR = 'button[type="submit"]'

# Настройки пула сессий
MAX_SESSIONS_PER_ACCOUNT = 2
SESSION_TTL = 3600  # 1 час
REQUEST_TIMEOUT = 30
QUEUE_TIMEOUT = 60

# ================== ДАТАКЛАССЫ ==================
@dataclass
class Account:
    username: str
    password: str
    active_sessions: int = 0
    max_sessions: int = MAX_SESSIONS_PER_ACCOUNT
    is_blocked: bool = False
    block_until: float = 0

@dataclass
class SessionData:
    id: str
    account: Account
    fingerprint: str
    cookies: Dict[str, str]
    headers: Dict[str, str]
    created_at: float
    last_used: float
    is_active: bool = True
    context: Optional[BrowserContext] = None
    browser: Optional[Browser] = None
    page: Optional[Page] = None
    
    @property
    def age(self) -> float:
        return time.time() - self.created_at
    
    @property
    def idle_time(self) -> float:
        return time.time() - self.last_used

@dataclass
class SearchRequest:
    id: str
    user_id: int
    query: str
    search_type: str  # iin, phone, fio
    created_at: float
    status: str = "pending"  # pending, processing, completed, failed
    result: Optional[Any] = None
    error: Optional[str] = None

@dataclass
class UserSession:
    user_id: int
    token: str
    created_at: float
    last_activity: float
    
    def is_valid(self) -> bool:
        return (time.time() - self.created_at) < SESSION_TTL

# ================== МЕНЕДЖЕР СЕССИЙ ==================
class SessionManager:
    def __init__(self):
        self.playwright = None
        self.sessions: Dict[str, SessionData] = {}
        self.accounts: List[Account] = []
        self.session_cycle = None
        self.lock = Lock()
        self.init_event = Event()
        self.fingerprint_cache: Dict[str, str] = {}
        
        # Статистика
        self.stats = {
            "total_created": 0,
            "total_destroyed": 0,
            "total_requests": 0,
            "failed_requests": 0,
            "queue_size": 0,
        }
    
    def initialize(self) -> bool:
        """Инициализация Playwright и загрузка аккаунтов"""
        print("🔄 Инициализация SessionManager...")
        
        try:
            # Запускаем Playwright
            self.playwright = sync_playwright().start()
            
            # Загружаем аккаунты
            self._load_accounts()
            
            # Создаем начальные сессии
            self._create_initial_sessions()
            
            self.init_event.set()
            print("✅ SessionManager инициализирован")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка инициализации SessionManager: {e}")
            traceback.print_exc()
            return False
    
    def _load_accounts(self):
        """Загрузка аккаунтов"""
        try:
            # Попробуем загрузить из переменных окружения
            accounts_env = os.environ.get("PENA_ACCOUNTS", "")
            if accounts_env:
                accounts_data = json.loads(accounts_env)
                self.accounts = [Account(**acc) for acc in accounts_data]
            else:
                # Или из файла
                try:
                    with open("accounts.json", "r", encoding="utf-8") as f:
                        accounts_data = json.load(f)
                        self.accounts = [Account(**acc) for acc in accounts_data]
                except:
                    # По умолчанию
                    self.accounts = [
                        Account(username="klon9", password="7755SSaa"),
                    ]
        except Exception as e:
            print(f"⚠️ Ошибка загрузки аккаунтов: {e}")
            self.accounts = [
                Account(username="klon9", password="7755SSaa"),
            ]
        
        print(f"📋 Загружено аккаунтов: {len(self.accounts)}")
        for acc in self.accounts:
            print(f"  - {acc.username}")
    
    def _create_initial_sessions(self):
        """Создание начальных сессий для каждого аккаунта"""
        print("🔄 Создание начальных сессий...")
        
        for account in self.accounts:
            if account.is_blocked and time.time() < account.block_until:
                print(f"⚠️ Аккаунт {account.username} заблокирован до {datetime.fromtimestamp(account.block_until)}")
                continue
            
            print(f"🔄 Создаем сессию для {account.username}...")
            session = self._create_session(account)
            if session:
                print(f"✅ Создана сессия для {account.username}")
            else:
                print(f"❌ Не удалось создать сессию для {account.username}")
        
        self._update_cycle()
    
    def _create_session(self, account: Account) -> Optional[SessionData]:
        """Создание новой сессии"""
        print(f"🔄 Создание сессии для {account.username}...")
        
        browser = None
        context = None
        page = None
        
        try:
            # Запускаем браузер
            browser = self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--window-size=1920,1080",
                ],
                timeout=60000
            )
            
            # Создаем контекст
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            
            # Маскировка Playwright
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            page = context.new_page()
            
            # Логин
            print(f"🔐 Логин {account.username}...")
            page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
            time.sleep(3)
            
            # Проверяем, не попали ли мы уже на dashboard (например, если уже авторизованы)
            current_url = page.url
            if "dashboard" in current_url:
                print(f"✅ Уже на dashboard: {current_url}")
            else:
                # Заполняем форму
                page.fill(LOGIN_SELECTOR, account.username)
                time.sleep(1)
                page.fill(PASSWORD_SELECTOR, account.password)
                time.sleep(1)
                
                # Нажимаем кнопку
                page.click(SUBMIT_SELECTOR)
                time.sleep(5)
                
                # Проверяем успешность логина
                current_url = page.url
                if "dashboard" not in current_url:
                    print(f"⚠️ Dashboard не найден, текущий URL: {current_url}")
                    # Пробуем перейти на dashboard
                    try:
                        page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=10000)
                        time.sleep(3)
                    except Exception as e:
                        print(f"⚠️ Не удалось перейти на dashboard: {e}")
            
            # Переходим на страницу поиска
            print("🌐 Переходим на страницу поиска...")
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            time.sleep(3)
            
            # Генерируем fingerprint
            fingerprint = self._generate_fingerprint(page, account.username)
            
            # Получаем куки
            cookies_list = context.cookies()
            cookies_dict = {c['name']: c['value'] for c in cookies_list}
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
            
            # Проверяем важные куки
            important_cookies = ['cf_clearance', 'aegis_session', 'access_token']
            for cookie_name in important_cookies:
                if cookie_name in cookies_dict:
                    print(f"  ✅ {cookie_name}: {cookies_dict[cookie_name][:20]}...")
                else:
                    print(f"  ⚠️ {cookie_name}: НЕТ")
            
            # Формируем заголовки
            headers = {
                "accept": "application/json",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
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
                "x-device-fingerprint": fingerprint,
                "cookie": cookie_header,
                "x-requested-with": "XMLHttpRequest",
                "origin": BASE_URL
            }
            
            # Создаем объект сессии
            session_id = f"{account.username}_{int(time.time())}_{random.randint(1000, 9999)}"
            session_data = SessionData(
                id=session_id,
                account=account,
                fingerprint=fingerprint,
                cookies=cookies_dict,
                headers=headers,
                created_at=time.time(),
                last_used=time.time(),
                context=context,
                browser=browser,
                page=page
            )
            
            with self.lock:
                self.sessions[session_id] = session_data
                account.active_sessions += 1
                self.stats["total_created"] += 1
            
            print(f"✅ Сессия создана: {session_id[:20]}...")
            return session_data
            
        except Exception as e:
            print(f"❌ Ошибка создания сессии: {e}")
            traceback.print_exc()
            
            # Закрываем ресурсы в случае ошибки
            if page:
                try:
                    page.close()
                except:
                    pass
            if context:
                try:
                    context.close()
                except:
                    pass
            if browser:
                try:
                    browser.close()
                except:
                    pass
            
            # Блокируем аккаунт на 5 минут при ошибке
            account.is_blocked = True
            account.block_until = time.time() + 300
            
            return None
    
    def _generate_fingerprint(self, page: Page, username: str) -> str:
        """Генерация fingerprint на основе данных браузера"""
        try:
            browser_data = page.evaluate("""
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
            
            data_str = json.dumps(browser_data, sort_keys=True) + username + str(time.time())
            return hashlib.sha256(data_str.encode()).hexdigest()
        except:
            # Резервная генерация
            data_str = f"{username}{int(time.time())}{random.randint(1000, 9999)}"
            return hashlib.sha256(data_str.encode()).hexdigest()
    
    def get_session(self) -> Optional[SessionData]:
        """Получение доступной сессии (round-robin)"""
        with self.lock:
            if not self.sessions:
                return None
            
            # Обновляем цикл если нужно
            if not self.session_cycle:
                self._update_cycle()
            
            # Ищем активную сессию
            for _ in range(len(self.sessions)):
                session = next(self.session_cycle)
                if session.is_active and not session.account.is_blocked:
                    session.last_used = time.time()
                    return session
            
            return None
    
    def _update_cycle(self):
        """Обновление round-robin цикла"""
        active_sessions = [s for s in self.sessions.values() if s.is_active]
        self.session_cycle = itertools.cycle(active_sessions) if active_sessions else None
    
    def make_request(self, session: SessionData, endpoint: str, params: Dict = None) -> Dict:
        """Выполнение запроса через сессию"""
        self.stats["total_requests"] += 1
        
        try:
            # Формируем URL
            url = urljoin(BASE_URL, endpoint)
            if params:
                query_string = urlencode(params, doseq=True)
                url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
            
            # Обновляем заголовки
            headers = session.headers.copy()
            headers["referer"] = SEARCH_URL
            
            # Выполняем запрос
            response = session.context.request.get(
                url, 
                headers=headers, 
                timeout=REQUEST_TIMEOUT * 1000  # миллисекунды
            )
            
            session.last_used = time.time()
            
            # Обработка ответа
            if response.status == 200:
                try:
                    data = response.json()
                    return {
                        "success": True,
                        "status": response.status,
                        "data": data,
                        "text": response.text()[:500] if response.text() else ""
                    }
                except:
                    return {
                        "success": False,
                        "status": response.status,
                        "error": "Invalid JSON response",
                        "text": response.text()[:500] if response.text() else ""
                    }
            else:
                error_text = response.text()[:500] if response.text() else ""
                
                # Если ошибка аутентификации, помечаем сессию неактивной
                if response.status in [401, 403, 419]:
                    print(f"⚠️ Сессия {session.id[:20]}... недействительна (статус {response.status})")
                    session.is_active = False
                
                return {
                    "success": False,
                    "status": response.status,
                    "error": f"HTTP {response.status}",
                    "text": error_text
                }
                
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            self.stats["failed_requests"] += 1
            return {
                "success": False,
                "error": str(e),
                "status": 0
            }
    
    def refresh_session(self, session_id: str) -> bool:
        """Обновление сессии"""
        with self.lock:
            if session_id not in self.sessions:
                return False
            
            old_session = self.sessions[session_id]
            account = old_session.account
            
            # Закрываем старую сессию
            self._close_session(old_session)
            
            # Создаем новую
            new_session = self._create_session(account)
            
            if new_session:
                # Удаляем старую и добавляем новую
                del self.sessions[session_id]
                self.sessions[new_session.id] = new_session
                self._update_cycle()
                return True
        
        return False
    
    def _close_session(self, session: SessionData):
        """Закрытие сессии и освобождение ресурсов"""
        try:
            if session.page:
                session.page.close()
            if session.context:
                session.context.close()
            if session.browser:
                session.browser.close()
            
            session.account.active_sessions -= 1
            session.is_active = False
            
            self.stats["total_destroyed"] += 1
            print(f"✅ Сессия {session.id[:20]}... закрыта")
        except Exception as e:
            print(f"⚠️ Ошибка закрытия сессии: {e}")
    
    def cleanup(self):
        """Очистка устаревших сессий"""
        with self.lock:
            now = time.time()
            to_remove = []
            
            for session_id, session in self.sessions.items():
                # Закрываем сессии старше 2 часов или неактивные более 30 минут
                if session.age > 7200 or session.idle_time > 1800:
                    to_remove.append(session_id)
            
            for session_id in to_remove:
                self._close_session(self.sessions[session_id])
                del self.sessions[session_id]
            
            # Разблокируем аккаунты
            for account in self.accounts:
                if account.is_blocked and now > account.block_until:
                    account.is_blocked = False
                    print(f"✅ Аккаунт {account.username} разблокирован")
            
            self._update_cycle()
            
            if to_remove:
                print(f"🧹 Очищено сессий: {len(to_remove)}")
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        with self.lock:
            active_sessions = len([s for s in self.sessions.values() if s.is_active])
            if active_sessions > 0:
                avg_age = sum(s.age for s in self.sessions.values() if s.is_active) / active_sessions
            else:
                avg_age = 0
            
            return {
                "active_sessions": active_sessions,
                "total_sessions": len(self.sessions),
                "active_accounts": len([a for a in self.accounts if not a.is_blocked]),
                "avg_session_age": round(avg_age, 1),
                "requests": self.stats.copy(),
                "queue_size": self.stats["queue_size"]
            }

# ================== МЕНЕДЖЕР ПОИСКА ==================
class SearchManager:
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.request_queue = Queue()
        self.results_cache: Dict[str, Dict] = {}
        self.cache_lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.stats = {
            "total_searches": 0,
            "successful": 0,
            "failed": 0,
            "cached": 0,
        }
        
        # Запускаем воркеры
        for i in range(3):
            Thread(target=self._search_worker, daemon=True, name=f"SearchWorker-{i}").start()
        
        # Запускаем очистку кэша
        Thread(target=self._cache_cleaner, daemon=True).start()
    
    def _search_worker(self):
        """Воркер для обработки поисковых запросов"""
        while True:
            try:
                request_data = self.request_queue.get(timeout=1)
                if request_data:
                    self._process_search_request(request_data)
            except Empty:
                continue
            except Exception as e:
                print(f"❌ Ошибка в воркере поиска: {e}")
    
    def _process_search_request(self, request_data: Dict):
        """Обработка поискового запроса"""
        request_id = request_data["id"]
        query = request_data["query"]
        search_type = request_data["search_type"]
        
        # Проверяем кэш
        cache_key = f"{search_type}:{query}"
        with self.cache_lock:
            if cache_key in self.results_cache:
                cached = self.results_cache[cache_key]
                if time.time() - cached["timestamp"] < 300:  # 5 минут кэш
                    self.stats["cached"] += 1
                    request_data["result"] = cached["result"]
                    request_data["status"] = "completed"
                    return
        
        self.stats["total_searches"] += 1
        
        # Получаем сессию
        session = self.session_manager.get_session()
        if not session:
            request_data["error"] = "Нет доступных сессий"
            request_data["status"] = "failed"
            self.stats["failed"] += 1
            return
        
        try:
            # Формируем параметры запроса
            params = self._build_search_params(search_type, query)
            endpoint = self._get_search_endpoint(search_type)
            
            # Выполняем запрос
            result = self.session_manager.make_request(session, endpoint, params)
            
            if result["success"]:
                # Форматируем результат
                formatted = self._format_search_result(result["data"], search_type)
                
                # Сохраняем в кэш
                with self.cache_lock:
                    self.results_cache[cache_key] = {
                        "result": formatted,
                        "timestamp": time.time(),
                        "query": query,
                        "type": search_type
                    }
                
                request_data["result"] = formatted
                request_data["status"] = "completed"
                self.stats["successful"] += 1
                
                print(f"✅ Поиск успешен: {search_type}:{query}")
            else:
                # Если ошибка аутентификации, пробуем обновить сессию
                if result.get("status") in [401, 403, 419]:
                    print(f"🔄 Обновление сессии из-за ошибки {result.get('status')}")
                    if self.session_manager.refresh_session(session.id):
                        # Повторяем запрос с новой сессией
                        session = self.session_manager.get_session()
                        if session:
                            result = self.session_manager.make_request(session, endpoint, params)
                            if result["success"]:
                                formatted = self._format_search_result(result["data"], search_type)
                                request_data["result"] = formatted
                                request_data["status"] = "completed"
                                self.stats["successful"] += 1
                                return
                
                request_data["error"] = result.get("error", "Unknown error")
                request_data["status"] = "failed"
                self.stats["failed"] += 1
                print(f"❌ Поиск не удался: {search_type}:{query} - {result.get('error')}")
                
        except Exception as e:
            request_data["error"] = str(e)
            request_data["status"] = "failed"
            self.stats["failed"] += 1
            print(f"❌ Исключение при поиске: {e}")
            traceback.print_exc()
    
    def _build_search_params(self, search_type: str, query: str) -> Dict:
        """Построение параметров поиска"""
        if search_type == "iin":
            return {"iin": query}
        elif search_type == "phone":
            # Очищаем номер телефона
            clean = ''.join(filter(str.isdigit, query))
            if clean.startswith("8"):
                clean = "7" + clean[1:]
            return {"phone": clean, "limit": 10}
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
            return params
        return {}
    
    def _get_search_endpoint(self, search_type: str) -> str:
        """Получение эндпоинта для типа поиска"""
        endpoints = {
            "iin": "/api/v3/search/iin",
            "phone": "/api/v3/search/phone",
            "fio": "/api/v3/search/fio"
        }
        return endpoints.get(search_type, "/api/v3/search/iin")
    
    def _format_search_result(self, data: Any, search_type: str) -> str:
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
    
    def _cache_cleaner(self):
        """Очистка устаревшего кэша"""
        while True:
            time.sleep(300)  # Каждые 5 минут
            with self.cache_lock:
                now = time.time()
                to_remove = []
                for key, value in self.results_cache.items():
                    if now - value["timestamp"] > 1800:  # 30 минут
                        to_remove.append(key)
                
                for key in to_remove:
                    del self.results_cache[key]
                
                if to_remove:
                    print(f"🧹 Очищено из кэша: {len(to_remove)} записей")
    
    def search(self, user_id: int, query: str) -> Future:
        """Добавление запроса в очередь поиска"""
        # Определяем тип поиска
        if query.isdigit() and len(query) == 12:
            search_type = "iin"
        elif query.startswith(("+", "8", "7")):
            search_type = "phone"
        else:
            search_type = "fio"
        
        # Создаем запрос
        request_id = f"{user_id}_{int(time.time())}_{random.randint(1000, 9999)}"
        request_data = {
            "id": request_id,
            "user_id": user_id,
            "query": query,
            "search_type": search_type,
            "created_at": time.time(),
            "status": "pending",
            "result": None,
            "error": None
        }
        
        # Добавляем в очередь
        self.session_manager.stats["queue_size"] = self.request_queue.qsize()
        self.request_queue.put(request_data)
        
        # Возвращаем Future для отслеживания
        future = Future()
        
        def check_status():
            start_time = time.time()
            while time.time() - start_time < QUEUE_TIMEOUT:
                if request_data["status"] in ["completed", "failed"]:
                    if request_data["status"] == "completed":
                        future.set_result(request_data["result"])
                    else:
                        future.set_exception(Exception(request_data["error"]))
                    break
                time.sleep(0.1)
            else:
                future.set_exception(TimeoutError("Таймаут ожидания результата"))
        
        Thread(target=check_status, daemon=True).start()
        return future
    
    def get_stats(self) -> Dict:
        """Получение статистики поиска"""
        return {
            **self.stats,
            "queue_size": self.request_queue.qsize(),
            "cache_size": len(self.results_cache)
        }

# ================== МЕНЕДЖЕР АВТОРИЗАЦИИ ==================
class AuthManager:
    def __init__(self):
        self.allowed_users: List[int] = []
        self.user_sessions: Dict[int, UserSession] = {}
        self.lock = Lock()
        self.last_update = 0
        
        # Загружаем пользователей при запуске
        self.load_allowed_users()
    
    def load_allowed_users(self):
        """Загрузка разрешенных пользователей"""
        try:
            print(f"🔐 Загрузка разрешенных пользователей из {ALLOWED_USERS_URL}")
            response = requests.get(ALLOWED_USERS_URL, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.allowed_users = [int(uid) for uid in data.get("allowed_users", [])]
                self.last_update = time.time()
                print(f"✅ Загружено {len(self.allowed_users)} разрешенных пользователей")
                print(f"📋 ID пользователей: {self.allowed_users}")
            else:
                print(f"⚠️ Не удалось загрузить пользователей, статус: {response.status_code}")
                # По умолчанию разрешим всем (для тестирования)
                self.allowed_users = [0]  # Разрешаем ID 0 для тестов
        except Exception as e:
            print(f"❌ Ошибка загрузки пользователей: {e}")
            # По умолчанию разрешим всем (для тестирования)
            self.allowed_users = [0]  # Разрешаем ID 0 для тестов
    
    def is_user_allowed(self, user_id: int) -> bool:
        """Проверка разрешен ли пользователь"""
        with self.lock:
            # Обновляем список раз в 5 минут
            if time.time() - self.last_update > 300:
                self.load_allowed_users()
            
            # Разрешаем всем, если список пустой (для тестирования)
            if not self.allowed_users:
                return True
            
            return user_id in self.allowed_users
    
    def create_session(self, user_id: int) -> Optional[str]:
        """Создание сессии для пользователя"""
        if not self.is_user_allowed(user_id):
            print(f"❌ Пользователь {user_id} не имеет доступа. Разрешенные ID: {self.allowed_users}")
            return None
        
        with self.lock:
            # Проверяем существующую сессию
            existing = self.user_sessions.get(user_id)
            if existing and existing.is_valid():
                existing.last_activity = time.time()
                return existing.token
            
            # Создаем новую сессию
            token = f"{user_id}_{int(time.time())}_{random.randint(1000, 9999)}"
            self.user_sessions[user_id] = UserSession(
                user_id=user_id,
                token=token,
                created_at=time.time(),
                last_activity=time.time()
            )
            
            print(f"🔑 Создана сессия для пользователя {user_id}")
            return token
    
    def validate_session(self, user_id: int, token: str) -> bool:
        """Валидация сессии пользователя"""
        with self.lock:
            session = self.user_sessions.get(user_id)
            if not session:
                print(f"❌ Сессия не найдена для пользователя {user_id}")
                return False
            
            if session.token != token:
                print(f"❌ Неверный токен для пользователя {user_id}")
                return False
            
            if not session.is_valid():
                print(f"❌ Сессия истекла для пользователя {user_id}")
                del self.user_sessions[user_id]
                return False
            
            session.last_activity = time.time()
            return True
    
    def cleanup_sessions(self):
        """Очистка устаревших сессий"""
        with self.lock:
            now = time.time()
            to_remove = []
            
            for user_id, session in self.user_sessions.items():
                if not session.is_valid():
                    to_remove.append(user_id)
            
            for user_id in to_remove:
                del self.user_sessions[user_id]
            
            if to_remove:
                print(f"🧹 Очищено пользовательских сессий: {len(to_remove)}")
    
    def get_stats(self) -> Dict:
        """Получение статистики авторизации"""
        with self.lock:
            return {
                "allowed_users": len(self.allowed_users),
                "active_sessions": len(self.user_sessions),
                "last_update": self.last_update
            }

# ================== ГЛОБАЛЬНЫЕ МЕНЕДЖЕРЫ ==================
session_manager = SessionManager()
search_manager = SearchManager(session_manager)
auth_manager = AuthManager()

# ================== FLASK ПРИЛОЖЕНИЕ ==================
app = Flask(__name__)
# Настройки CORS для работы с фронтендом
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "expose_headers": ["Content-Type", "Authorization"]
    }
})

@app.before_request
def handle_options():
    """Обработка OPTIONS запросов для CORS"""
    if request.method == 'OPTIONS':
        response = Response()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        return response

@app.before_request
def before_request():
    """Проверка авторизации для защищенных эндпоинтов"""
    # Пропускаем OPTIONS и публичные эндпоинты
    if request.method == 'OPTIONS':
        return None
    
    public_endpoints = ['/api/health', '/api/session/start']
    if request.path in public_endpoints:
        return None
    
    # Проверяем Content-Type для POST запросов
    if request.method == 'POST':
        if not request.is_json:
            return jsonify({"error": "Content-Type должен быть application/json"}), 415
    
    # Проверяем авторизацию
    data = request.json or {}
    user_id = data.get("telegram_user_id")
    token = data.get("session_token")
    
    if not user_id or not token:
        return jsonify({"error": "Не указаны учетные данные"}), 403
    
    try:
        user_id_int = int(user_id)
        if not auth_manager.validate_session(user_id_int, token):
            return jsonify({"error": "Недействительная сессия"}), 403
    except ValueError:
        return jsonify({"error": "Неверный Telegram ID"}), 400
    except Exception as e:
        print(f"❌ Ошибка проверки сессии: {e}")
        return jsonify({"error": "Внутренняя ошибка"}), 500
    
    return None

@app.route("/api/health", methods=["GET"])
def health():
    """Проверка здоровья сервера"""
    stats = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "session": session_manager.get_stats(),
        "search": search_manager.get_stats(),
        "auth": auth_manager.get_stats()
    }
    
    # Проверяем наличие активных сессий
    if stats["session"]["active_sessions"] == 0:
        stats["status"] = "warning"
        stats["message"] = "Нет активных сессий"
    
    return jsonify(stats)

@app.route("/api/session/start", methods=["POST"])
def start_session():
    """Начало сессии пользователя"""
    try:
        # Проверяем Content-Type
        if not request.is_json:
            return jsonify({"error": "Content-Type должен быть application/json"}), 415
        
        data = request.get_json()
        user_id = data.get("telegram_user_id")
        
        if not user_id:
            return jsonify({"error": "Не указан Telegram ID"}), 400
        
        try:
            user_id_int = int(user_id)
            token = auth_manager.create_session(user_id_int)
            
            if not token:
                return jsonify({"error": "Пользователь не имеет доступа"}), 403
            
            return jsonify({
                "session_token": token,
                "expires_in": SESSION_TTL
            })
        except ValueError:
            return jsonify({"error": "Неверный Telegram ID"}), 400
        
    except Exception as e:
        print(f"❌ Ошибка создания сессии: {e}")
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка"}), 500

@app.route("/api/search", methods=["POST"])
def search():
    """Поиск по ИИН, телефону или ФИО"""
    try:
        # Проверяем Content-Type
        if not request.is_json:
            return jsonify({"error": "Content-Type должен быть application/json"}), 415
        
        data = request.get_json()
        user_id = data.get("telegram_user_id")
        query = data.get("query", "").strip()
        
        if not query:
            return jsonify({"error": "Пустой запрос"}), 400
        
        print(f"🔍 Поиск от пользователя {user_id}: {query[:50]}...")
        
        # Запускаем поиск
        future = search_manager.search(int(user_id), query)
        
        # Ждем результат с таймаутом
        try:
            result = future.result(timeout=QUEUE_TIMEOUT)
            return jsonify({"result": result})
        except TimeoutError:
            return jsonify({"error": "Таймаут ожидания результата"}), 408
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка"}), 500

@app.route("/api/debug/sessions", methods=["GET"])
def debug_sessions():
    """Отладочная информация о сессиях"""
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    sessions_info = []
    for session in session_manager.sessions.values():
        sessions_info.append({
            "id": session.id[:30],
            "username": session.account.username,
            "fingerprint": session.fingerprint[:20] + "...",
            "cookies_count": len(session.cookies),
            "age": round(session.age, 1),
            "idle": round(session.idle_time, 1),
            "is_active": session.is_active,
            "account_blocked": session.account.is_blocked,
            "has_cf_clearance": "cf_clearance" in session.cookies,
            "has_aegis_session": "aegis_session" in session.cookies
        })
    
    return jsonify({
        "sessions": sessions_info,
        "stats": session_manager.get_stats()
    })

@app.route("/api/debug/refresh-session/<session_id>", methods=["POST"])
def debug_refresh_session(session_id):
    """Принудительное обновление сессии"""
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    success = session_manager.refresh_session(session_id)
    return jsonify({"success": success})

@app.route("/api/debug/create-session", methods=["POST"])
def debug_create_session():
    """Создание новой сессии"""
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    
    if not username or not password:
        # Используем первый доступный аккаунт
        account = session_manager.accounts[0] if session_manager.accounts else None
    else:
        account = Account(username=username, password=password)
    
    if not account:
        return jsonify({"error": "Нет доступных аккаунтов"}), 400
    
    session = session_manager._create_session(account)
    if session:
        return jsonify({
            "success": True,
            "session_id": session.id,
            "fingerprint": session.fingerprint[:30] + "...",
            "cookies_count": len(session.cookies)
        })
    else:
        return jsonify({"success": False, "error": "Не удалось создать сессию"})

@app.route("/api/debug/test-search", methods=["POST"])
def debug_test_search():
    """Тестовый поиск"""
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.json or {}
    query = data.get("query", "931229400494")
    
    try:
        future = search_manager.search(0, query)
        result = future.result(timeout=30)
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/refresh-users", methods=["POST"])
def admin_refresh_users():
    """Обновление списка пользователей"""
    auth_header = request.headers.get("Authorization")
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    auth_manager.load_allowed_users()
    return jsonify({
        "success": True,
        "allowed_users": len(auth_manager.allowed_users),
        "user_ids": auth_manager.allowed_users
    })

# ================== ФУНКЦИИ ОБСЛУЖИВАНИЯ ==================
def maintenance_worker():
    """Фоновая задача для обслуживания"""
    while True:
        try:
            # Очистка сессий
            session_manager.cleanup()
            
            # Очистка пользовательских сессий
            auth_manager.cleanup_sessions()
            
            # Обновление статистики очереди
            session_manager.stats["queue_size"] = search_manager.request_queue.qsize()
            
            time.sleep(60)  # Каждую минуту
            
        except Exception as e:
            print(f"❌ Ошибка в maintenance_worker: {e}")
            time.sleep(60)

def shutdown_handler(signum, frame):
    """Обработчик graceful shutdown"""
    print("\n🛑 Получен сигнал завершения...")
    
    # Закрываем все сессии
    for session in session_manager.sessions.values():
        session_manager._close_session(session)
    
    # Закрываем Playwright
    if session_manager.playwright:
        session_manager.playwright.stop()
    
    print("✅ Ресурсы освобождены")
    sys.exit(0)

# ================== ЗАПУСК СЕРВЕРА ==================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА (ИСПРАВЛЕННАЯ ВЕРСИЯ)")
    print("=" * 60)
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Инициализация менеджеров
    print("🔄 Инициализация менеджеров...")
    
    if not session_manager.initialize():
        print("❌ Не удалось инициализировать SessionManager")
        sys.exit(1)
    
    # Запускаем обслуживание
    Thread(target=maintenance_worker, daemon=True).start()
    
    print("\n✅ СЕРВЕР ГОТОВ К РАБОТЕ!")
    print(f"📊 Активных сессий: {len([s for s in session_manager.sessions.values() if s.is_active])}")
    print(f"👤 Разрешенных пользователей: {len(auth_manager.allowed_users)}")
    print(f"📋 ID разрешенных пользователей: {auth_manager.allowed_users}")
    print(f"🌐 API доступен по адресу: http://0.0.0.0:5000")
    print("\n📝 Для тестирования используйте:")
    print("  1. curl -X POST http://localhost:5000/api/session/start -H 'Content-Type: application/json' -d '{\"telegram_user_id\":0}'")
    print("  2. Используйте полученный session_token в запросах поиска")
    print("=" * 60)
    
    # Запуск Flask
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False
    )
