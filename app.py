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
import logging

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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('pena_api.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

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
        self.login_attempts = 0
        self.max_login_attempts = 3
        
    def start(self):
        """Запустить рабочий поток"""
        if self.worker_thread and self.worker_thread.is_alive():
            return
        
        self.worker_thread = Thread(target=self._worker_loop, daemon=True, name="PlaywrightWorker")
        self.worker_thread.start()
        self.is_running = True
        logger.info("✅ Рабочий поток запущен")
        
    def _worker_loop(self):
        """Главный цикл рабочего потока - ВСЕ Playwright операции здесь!"""
        logger.info("🚀 Запуск Playwright в рабочем потоке...")
        
        try:
            # 1. Инициализация Playwright
            logger.info("Инициализация Playwright...")
            self.playwright = sync_playwright().start()
            logger.info("✅ Playwright запущен")
            
            # 2. Запуск браузера
            logger.info("Запуск браузера...")
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials"
                ]
            )
            logger.info("✅ Браузер запущен")
            
            # 3. Создание контекста
            logger.info("Создание контекста...")
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
            )
            logger.info("✅ Контекст создан")
            
            # 4. Создание страницы
            self.page = self.context.new_page()
            
            # 5. Добавляем anti-detection скрипты
            self.page.add_init_script("""
                // Удаляем webdriver
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                // Переопределяем plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [{
                        0: {type: "application/x-google-chrome-pdf"},
                        1: {type: "application/pdf"},
                        length: 2,
                        item: function(index) { return this[index] || null; },
                        namedItem: function() { return null; },
                        refresh: function() {}
                    }]
                });
                
                // Переопределяем languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['ru-RU', 'ru', 'en-US', 'en']
                });
                
                // Добавляем chrome объект
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
                
                // Переопределяем WebGL
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                    return getParameter(parameter);
                };
                
                // Переопределяем permissions
                const originalQuery = navigator.permissions.query;
                navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            
            # 6. Логин в систему
            logger.info("🔐 Выполняем логин...")
            self._login()
            
            logger.info("✅ Инициализация завершена!")
            self.init_event.set()
            
            # 7. Основной цикл обработки задач
            while self.is_running:
                try:
                    task = self.task_queue.get(timeout=1)
                    task_id, task_type, task_data, result_queue = task
                    
                    logger.info(f"📥 Получена задача {task_id}: {task_type}")
                    
                    try:
                        result = self._process_task(task_type, task_data)
                        logger.info(f"✅ Задача {task_id} выполнена успешно")
                        result_queue.put((task_id, {"success": True, "data": result}))
                    except Exception as e:
                        logger.error(f"❌ Ошибка в задаче {task_id}: {str(e)}")
                        result_queue.put((task_id, {
                            "success": False, 
                            "error": str(e),
                            "traceback": traceback.format_exc()
                        }))
                    
                    self.task_queue.task_done()
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле обработки задач: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в рабочем потоке: {e}")
            traceback.print_exc()
            self.init_event.set()
            
    def _login(self):
        """Логин в pena.rest"""
        for attempt in range(self.max_login_attempts):
            try:
                logger.info(f"Попытка логина #{attempt + 1}")
                
                # Очищаем куки перед логином
                self.context.clear_cookies()
                
                # Переходим на страницу логина
                logger.info(f"Переход на {LOGIN_PAGE}")
                self.page.goto(LOGIN_PAGE, wait_until="networkidle", timeout=60000)
                time.sleep(2)
                
                # Проверяем, не появилась ли капча
                page_content = self.page.content()
                if "captcha" in page_content.lower() or "капча" in page_content.lower():
                    logger.warning("⚠️ Обнаружена капча!")
                    time.sleep(5)
                    continue
                
                # Заполняем логин
                logger.info(f"Ввод логина: {accounts[0]['username']}")
                self.page.fill(LOGIN_SELECTOR, accounts[0]["username"])
                time.sleep(random.uniform(0.5, 1.5))
                
                # Заполняем пароль
                logger.info("Ввод пароля")
                self.page.fill(PASSWORD_SELECTOR, accounts[0]["password"])
                time.sleep(random.uniform(0.5, 1.5))
                
                # Нажимаем кнопку
                logger.info("Нажатие кнопки входа")
                self.page.click(SIGN_IN_BUTTON_SELECTOR)
                time.sleep(3)
                
                # Ждем редиректа
                current_url = self.page.url
                logger.info(f"Текущий URL: {current_url}")
                
                # Проверяем успешность логина
                if "dashboard" in current_url or "search" in current_url:
                    logger.info("✅ Логин успешен")
                    
                    # Даем время для загрузки всех ресурсов
                    time.sleep(2)
                    
                    # Переходим на страницу поиска
                    search_url = f"{BASE_URL}/dashboard/search"
                    logger.info(f"Переход на {search_url}")
                    self.page.goto(search_url, wait_until="networkidle", timeout=30000)
                    time.sleep(2)
                    
                    # Получаем cookies
                    cookies_list = self.context.cookies()
                    self.cookies = {c['name']: c['value'] for c in cookies_list}
                    
                    # Генерируем fingerprint
                    self.fingerprint = self._generate_fingerprint()
                    
                    # Создаем заголовки
                    self._create_headers()
                    
                    logger.info(f"✅ Логин завершен успешно")
                    logger.info(f"📦 Получено cookies: {len(self.cookies)}")
                    logger.info(f"🔑 Fingerprint: {self.fingerprint[:30]}..." if self.fingerprint else "Нет fingerprint")
                    
                    # Проверяем важные куки
                    important_cookies = ['cf_clearance', 'aegis_session', 'access_token', 'session']
                    for cookie_name in important_cookies:
                        if cookie_name in self.cookies:
                            value = self.cookies[cookie_name]
                            logger.info(f"🍪 {cookie_name}: {value[:50]}...")
                        else:
                            logger.warning(f"🍪 {cookie_name}: НЕТ")
                    
                    return True
                else:
                    logger.warning(f"⚠️ Не удалось войти, URL: {current_url}")
                    
                    # Делаем скриншот для отладки
                    try:
                        screenshot_path = f"login_failure_attempt_{attempt}.png"
                        self.page.screenshot(path=screenshot_path)
                        logger.info(f"📸 Скриншот сохранен: {screenshot_path}")
                    except:
                        pass
                    
                    time.sleep(3)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при логине (попытка {attempt + 1}): {e}")
                traceback.print_exc()
                time.sleep(5)
        
        raise Exception(f"Не удалось войти после {self.max_login_attempts} попыток")
    
    def _generate_fingerprint(self):
        """Генерация fingerprint"""
        try:
            logger.info("Генерация fingerprint...")
            
            # Пробуем получить из localStorage
            fingerprint = self.page.evaluate("""
                () => {
                    try {
                        // Ищем fingerprint в различных местах
                        const keys = Object.keys(window);
                        for (const key of keys) {
                            const value = window[key];
                            if (typeof value === 'string' && value.length === 64 && /^[a-f0-9]{64}$/i.test(value)) {
                                return value;
                            }
                        }
                        
                        // Ищем в localStorage
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            const value = localStorage.getItem(key);
                            if (value && value.length === 64 && /^[a-f0-9]{64}$/i.test(value)) {
                                return value;
                            }
                        }
                        
                        return null;
                    } catch(e) {
                        return null;
                    }
                }
            """)
            
            if fingerprint:
                logger.info(f"✅ Найден fingerprint в браузере: {fingerprint[:30]}...")
                return fingerprint
            
            # Генерируем свой fingerprint
            logger.info("Генерация нового fingerprint...")
            browser_data = self.page.evaluate("""
                () => ({
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    languages: navigator.languages.join(','),
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory || 4,
                    screen: `${screen.width}x${screen.height}`,
                    colorDepth: screen.colorDepth,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                    sessionStorage: sessionStorage.length,
                    localStorage: localStorage.length,
                    timestamp: Date.now(),
                    random: Math.random().toString(36).substring(2, 15)
                })
            """)
            
            data_str = json.dumps(browser_data, sort_keys=True) + accounts[0]["username"] + str(int(time.time()))
            fingerprint = hashlib.sha256(data_str.encode()).hexdigest()
            
            logger.info(f"📝 Сгенерирован fingerprint: {fingerprint[:30]}...")
            return fingerprint
            
        except Exception as e:
            logger.error(f"❌ Ошибка генерации fingerprint: {e}")
            # Фоллбэк
            fingerprint = hashlib.sha256(f"{int(time.time())}{random.randint(1000, 9999)}{accounts[0]['username']}".encode()).hexdigest()
            logger.info(f"📝 Фоллбэк fingerprint: {fingerprint[:30]}...")
            return fingerprint
    
    def _create_headers(self):
        """Создание заголовков для запросов"""
        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "priority": "u=1, i",
            "referer": f"{BASE_URL}/dashboard/search",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "x-device-fingerprint": self.fingerprint or "",
            "cookie": cookie_header,
            "x-requested-with": "XMLHttpRequest",
            "origin": BASE_URL
        }
        
        logger.info(f"📋 Созданы заголовки, cookies: {len(self.cookies)}")
    
    def _process_task(self, task_type: str, task_data: Any):
        """Обработка задачи"""
        if task_type == "api_request":
            return self._make_api_request(task_data)
        elif task_type == "test_connection":
            return self._test_connection()
        elif task_type == "get_info":
            return self._get_worker_info()
        elif task_type == "re_login":
            return self._re_login()
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
        
        logger.info(f"📡 Запрос к: {url}")
        logger.info(f"📋 Параметры: {params}")
        logger.info(f"🔑 Fingerprint: {self.fingerprint[:20] if self.fingerprint else 'НЕТ'}")
        
        # Показываем важные куки
        important_cookies = ['cf_clearance', 'aegis_session', 'access_token', 'session', 'XSRF-TOKEN']
        logger.info("🍪 Проверка cookies:")
        for cookie_name in important_cookies:
            if cookie_name in self.cookies:
                value = self.cookies[cookie_name]
                logger.info(f"  ✅ {cookie_name}: {value[:30]}...")
            else:
                logger.info(f"  ❌ {cookie_name}: НЕТ")
        
        # Делаем запрос
        logger.info(f"⏳ Отправляем запрос...")
        start_time = time.time()
        
        try:
            response = self.context.request.get(
                url, 
                headers=self.headers, 
                timeout=30000
            )
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Ответ получен за {elapsed:.2f} сек")
            logger.info(f"📊 Статус: {response.status}")
            
            response_text = response.text()
            logger.info(f"📏 Длина ответа: {len(response_text)} символов")
            
            # Логируем первые 500 символов ответа
            if response_text:
                logger.info(f"📄 Начало ответа: {response_text[:500]}")
            else:
                logger.info(f"📄 Ответ пустой")
            
            # Логируем важные заголовки ответа
            response_headers = dict(response.headers)
            logger.info("📋 Заголовки ответа:")
            for key, value in response_headers.items():
                key_lower = key.lower()
                if any(x in key_lower for x in ['content-type', 'content-length', 'set-cookie', 'x-', 'cf-']):
                    logger.info(f"  {key}: {value}")
            
            result = {
                "status": response.status,
                "url": url,
                "text": response_text,
                "headers": response_headers,
                "elapsed": elapsed
            }
            
            if response.status == 200:
                try:
                    json_data = response.json()
                    result["json"] = json_data
                    logger.info(f"✅ JSON успешно распарсен")
                    
                    if isinstance(json_data, list):
                        logger.info(f"📊 Найдено записей: {len(json_data)}")
                        if json_data and len(json_data) > 0:
                            # Показываем первую запись для примера
                            first_item = json_data[0]
                            logger.info(f"📝 Пример записи: {json.dumps(first_item, ensure_ascii=False)[:200]}...")
                    elif isinstance(json_data, dict):
                        logger.info(f"📊 Ключи: {list(json_data.keys())}")
                        if 'error' in json_data:
                            logger.warning(f"⚠️ Ответ содержит ошибку: {json_data.get('error')}")
                except Exception as json_error:
                    result["json"] = None
                    logger.warning(f"⚠️ Не удалось распарсить JSON: {json_error}")
                    logger.info(f"📄 Ответ как текст: {response_text[:500]}")
            elif response.status in [401, 403, 419]:
                logger.error(f"❌ Ошибка авторизации: {response.status}")
                result["auth_error"] = True
                result["error"] = f"Auth error {response.status}: {response_text[:200]}"
            else:
                result["error"] = response_text[:500]
                logger.error(f"❌ Ошибка сервера: {response.status}")
                logger.error(f"📄 Текст ошибки: {response_text[:500]}")
                
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Исключение при запросе: {e}")
            logger.error(f"⏱ Время до ошибки: {elapsed:.2f} сек")
            traceback.print_exc()
            raise
    
    def _test_connection(self):
        """Тестовый запрос"""
        logger.info("🔍 Тестовый запрос соединения")
        
        # Тест 1: Проверка доступности сайта
        try:
            self.page.goto(f"{BASE_URL}/dashboard", wait_until="networkidle", timeout=10000)
            logger.info("✅ Сайт доступен")
        except Exception as e:
            logger.error(f"❌ Сайт недоступен: {e}")
            return {"status": "error", "site_available": False}
        
        # Тест 2: API запрос
        test_url = urljoin(BASE_URL, "/api/v3/search/iin?iin=931229400494")
        logger.info(f"🔍 Тестовый API запрос: {test_url}")
        
        try:
            response = self.context.request.get(test_url, headers=self.headers, timeout=15000)
            logger.info(f"📊 Тестовый статус: {response.status}")
            
            return {
                "status": "ok" if response.status == 200 else "error",
                "test_passed": response.status == 200,
                "response_status": response.status,
                "response_length": len(response.text())
            }
        except Exception as e:
            logger.error(f"❌ Ошибка тестового запроса: {e}")
            return {"status": "error", "test_passed": False, "error": str(e)}
    
    def _get_worker_info(self):
        """Информация о рабочем потоке"""
        return {
            "thread": threading.current_thread().name,
            "thread_id": threading.get_ident(),
            "cookies_count": len(self.cookies),
            "important_cookies": {
                name: (self.cookies.get(name, "")[:30] + "..." if name in self.cookies else "НЕТ")
                for name in ['cf_clearance', 'aegis_session', 'access_token', 'session']
            },
            "fingerprint": self.fingerprint[:30] + "..." if self.fingerprint else None,
            "is_running": self.is_running,
            "queue_size": self.task_queue.qsize()
        }
    
    def _re_login(self):
        """Перелогин"""
        logger.info("🔄 Выполнение перелогина...")
        self._login()
        return {"success": True, "message": "Перелогин выполнен"}
    
    def submit_task(self, task_type: str, task_data: Dict, timeout: int = 30):
        """Отправить задачу в рабочий поток"""
        with self.task_lock:
            task_id = self.task_counter
            self.task_counter += 1
            
        result_queue = queue.Queue()
        self.result_queues[task_id] = result_queue
        
        # Отправляем задачу
        self.task_queue.put((task_id, task_type, task_data, result_queue))
        logger.info(f"📤 Отправлена задача {task_id}: {task_type}")
        
        # Ждем результат
        try:
            result_id, result = result_queue.get(timeout=timeout)
            
            if result_id != task_id:
                logger.error(f"Несоответствие ID задачи: {result_id} != {task_id}")
                raise RuntimeError(f"Несоответствие ID задачи: {result_id} != {task_id}")
            
            logger.info(f"📥 Получен результат задачи {task_id}")
            return result
            
        except queue.Empty:
            logger.error(f"Таймаут ожидания задачи {task_id}")
            raise TimeoutError(f"Таймаут ожидания задачи {task_id}")
        finally:
            # Очищаем очередь результата
            with self.task_lock:
                if task_id in self.result_queues:
                    del self.result_queues[task_id]
    
    def stop(self):
        """Остановить рабочий поток"""
        logger.info("🛑 Остановка рабочего потока...")
        self.is_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        
        if self.browser:
            try:
                self.browser.close()
                logger.info("✅ Браузер закрыт")
            except:
                logger.warning("⚠️ Не удалось закрыть браузер")
        
        if self.playwright:
            try:
                self.playwright.stop()
                logger.info("✅ Playwright остановлен")
            except:
                logger.warning("⚠️ Не удалось остановить Playwright")

# Глобальный экземпляр рабочего потока
pw_worker = PlaywrightWorker()

# ================== 4. FLASK API ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

def crm_get(endpoint: str, params: dict = None):
    """API запрос через Playwright worker"""
    logger.info(f"📨 CRM GET: {endpoint}, params: {params}")
    
    try:
        result = pw_worker.submit_task("api_request", {
            "endpoint": endpoint,
            "params": params
        }, timeout=30)
        
        if result["success"]:
            data = result["data"]
            
            # Проверяем ошибку авторизации
            if data.get("auth_error"):
                logger.warning("⚠️ Обнаружена ошибка авторизации, пробуем перелогин...")
                # Пробуем перелогин
                try:
                    relogin_result = pw_worker.submit_task("re_login", {}, timeout=30)
                    if relogin_result.get("success"):
                        logger.info("✅ Перелогин успешен, повторяем запрос...")
                        # Повторяем запрос
                        result = pw_worker.submit_task("api_request", {
                            "endpoint": endpoint,
                            "params": params
                        }, timeout=30)
                        if result["success"]:
                            data = result["data"]
                        else:
                            return ResponseLike(500, result.get("error", "Auth error after relogin"))
                    else:
                        return ResponseLike(401, "Требуется повторная авторизация")
                except Exception as relogin_error:
                    logger.error(f"❌ Ошибка при перелогине: {relogin_error}")
                    return ResponseLike(401, "Ошибка авторизации")
            
            return ResponseLike(
                status_code=data["status"],
                text=data["text"],
                json_data=data.get("json")
            )
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"❌ Ошибка в CRM GET: {error_msg}")
            return ResponseLike(500, error_msg)
            
    except TimeoutError as e:
        logger.error(f"⏰ Таймаут в CRM GET: {e}")
        return ResponseLike(504, "Таймаут запроса")
    except Exception as e:
        logger.error(f"❌ Исключение в CRM GET: {e}")
        traceback.print_exc()
        return ResponseLike(500, str(e))

# ================== 5. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    logger.info(f"🔍 Поиск по ИИН: {iin}")
    
    resp = crm_get("/api/v3/search/iin", params={"iin": iin})
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text[:100] if hasattr(resp, 'text') else ''}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ: {resp.text[:200]}"
    
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
        if p.get('source'):
            result += f"\n   📍 Источник: {p.get('source')}"
        results.append(result)
    
    return "\n\n".join(results)

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    
    logger.info(f"🔍 Поиск по телефону: {phone} (чистый: {clean})")
    
    resp = crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text[:100] if hasattr(resp, 'text') else ''}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ: {resp.text[:200]}"
    
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    
    results = []
    for i, p in enumerate(data[:5], 1):
        result = f"{i}. 📱 <b>Телефон: {p.get('phone_number','')}</b>"
        if p.get('snf'):
            result += f"\n   👤 {p.get('snf','')}"
        if p.get('iin'):
            result += f"\n   🧾 ИИН: {p.get('iin','')}"
        if p.get('source'):
            result += f"\n   📍 Источник: {p.get('source')}"
        results.append(result)
    
    return "\n\n".join(results)

def search_by_fio(text: str):
    logger.info(f"🔍 Поиск по ФИО: {text}")
    
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
        return f"❌ Ошибка {resp.status_code}: {resp.text[:100] if hasattr(resp, 'text') else ''}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ: {resp.text[:200]}"
    
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
        if p.get('source'):
            result += f"\n   📍 Источник: {p.get('source')}"
        results.append(result)
    
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 6. FLASK РОУТИНГ ==================
@app.before_request
def log_request_info():
    """Логирование входящих запросов"""
    logger.info(f"📥 Входящий запрос: {request.method} {request.path}")
    if request.method in ['POST', 'PUT'] and request.is_json:
        logger.info(f"📄 Тело запроса: {request.json}")

@app.after_request
def log_response_info(response):
    """Логирование исходящих ответов"""
    logger.info(f"📤 Исходящий ответ: {response.status}")
    return response

@app.route('/api/search', methods=['POST'])
def api_search():
    """Основной поисковый эндпоинт"""
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Поисковый запрос: {query}")
    logger.info(f"📊 Поток Flask: {threading.current_thread().name}")
    logger.info(f"{'='*60}")
    
    try:
        if query.isdigit() and len(query) == 12:
            reply = search_by_iin(query)
        elif query.startswith(("+", "8", "7")):
            reply = search_by_phone(query)
        else:
            reply = search_by_fio(query)
        
        logger.info(f"✅ Ответ готов, длина: {len(reply)} символов")
        logger.info(f"{'='*60}")
        
        return jsonify({"result": reply})
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {e}")
        traceback.print_exc()
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    try:
        # Тестируем соединение через worker
        result = pw_worker.submit_task("test_connection", {}, timeout=10)
        
        info = {}
        try:
            info_result = pw_worker.submit_task("get_info", {}, timeout=5)
            if info_result.get("success"):
                info = info_result.get("data", {})
        except:
            pass
        
        test_passed = result.get("success", False) and result.get("data", {}).get("test_passed", False)
        
        return jsonify({
            "status": "ok" if test_passed else "error",
            "worker_running": pw_worker.is_running,
            "worker_initialized": pw_worker.init_event.is_set(),
            "test_passed": test_passed,
            "worker_info": info,
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

@app.route('/api/debug/test-request', methods=['GET'])
def debug_test_request():
    """Тестовый запрос"""
    iin = request.args.get('iin', '931229400494')
    endpoint = request.args.get('endpoint', '/api/v3/search/iin')
    
    try:
        result = pw_worker.submit_task("api_request", {
            "endpoint": endpoint,
            "params": {"iin": iin}
        }, timeout=30)
        
        return jsonify({
            "success": result.get("success", False),
            "data": result.get("data"),
            "error": result.get("error")
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/debug/re-login', methods=['POST'])
def debug_re_login():
    """Принудительный перелогин"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    try:
        result = pw_worker.submit_task("re_login", {}, timeout=30)
        return jsonify(result)
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
    print("Логирование: включено (pena_api.log)")
    print("=" * 60)
    
    # Запускаем Playwright worker
    pw_worker.start()
    
    # Ждем инициализации
    print("\n[MAIN] ⏳ Ожидаем инициализации Playwright worker...")
    initialized = pw_worker.init_event.wait(timeout=45)
    
    if initialized:
        print("[MAIN] ✅ Playwright worker инициализирован!")
        
        # Тестируем соединение
        try:
            test_result = pw_worker.submit_task("test_connection", {}, timeout=15)
            if test_result.get("success"):
                data = test_result.get("data", {})
                if data.get("test_passed"):
                    print("[MAIN] ✅ Тестовый запрос успешен!")
                    print(f"[MAIN] 📊 Статус: {data.get('response_status')}")
                    print(f"[MAIN] 📏 Длина ответа: {data.get('response_length')}")
                else:
                    print(f"[MAIN] ⚠️ Тестовый запрос не прошел: {data}")
            else:
                print(f"[MAIN] ⚠️ Ошибка тестового запроса: {test_result.get('error')}")
        except Exception as e:
            print(f"[MAIN] ⚠️ Ошибка тестового запроса: {e}")
    else:
        print("[MAIN] ⚠️ Таймаут инициализации Playwright worker!")
    
    print("\n🌐 Flask сервер запускается на порту 5000...")
    print("📋 Проверка здоровья: GET http://localhost:5000/api/health")
    print("🔍 Поиск: POST http://localhost:5000/api/search")
    print("🐛 Отладка: GET http://localhost:5000/api/debug/test-request?iin=931229400494")
    print("📁 Логи: pena_api.log")
    print("=" * 60)
    
    # Запускаем Flask
    app.run(
        host='0.0.0.0', 
        port=5000, 
        threaded=True, 
        use_reloader=False,
        debug=False
    )
