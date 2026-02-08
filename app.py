# -*- coding: utf-8 -*-
import os
import time
import json
import random
import traceback
import hashlib
import threading
import queue
import signal
import sys
import gc
import resource
from threading import Thread, Lock, Event
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode, urljoin
from datetime import datetime
import logging

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

# ================== 3. PLAYWRIGHT В ОДНОМ ПОТОКЕ (ИСПРАВЛЕННЫЙ) ==================
class PlaywrightWorker:
    """Рабочий поток для ВСЕХ Playwright операций - оптимизирован для малой памяти"""
    def __init__(self):
        self.task_queue = queue.Queue(maxsize=100)
        self.result_queues = {}
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
        """Главный цикл рабочего потока - оптимизирован для малой памяти"""
        # Увеличиваем лимит файловых дескрипторов
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (65536, 65536))
            logger.info("✅ Лимит файловых дескрипторов увеличен до 65536")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось увеличить лимит файловых дескрипторов: {e}")
        
        logger.info("🚀 Запуск Playwright в рабочем потоке...")
        
        try:
            # 1. Инициализация Playwright
            logger.info("Инициализация Playwright...")
            self.playwright = sync_playwright().start()
            logger.info("✅ Playwright запущен")
            
            # 2. Запуск браузера в УЛЬТРА-ЛЕГКОМ режиме
            logger.info("Запуск браузера в легком режиме...")
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=[
                    # Безопасность
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    
                    # Оптимизация памяти
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",          # ВАЖНО: только один процесс
                    "--no-zygote",              # ВАЖНО: без зиготы
                    "--no-first-run",
                    
                    # Отключение ненужного
                    "--disable-extensions",
                    "--disable-plugins",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-component-update",
                    "--disable-sync",
                    "--disable-translate",
                    
                    # Отключение фич для экономии памяти
                    "--disable-features=AudioServiceOutOfProcess,TranslateUI",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-ipc-flooding-protection",
                    
                    # Дополнительная оптимизация
                    "--disable-background-timer-throttling",
                    "--disable-client-side-phishing-detection",
                    "--disable-hang-monitor",
                    "--disable-popup-blocking",
                    "--disable-prompt-on-repost",
                    "--disable-domain-reliability",
                    "--disable-speech-api",
                    
                    # Разрешение
                    "--window-size=1280,720",
                    "--use-gl=egl"
                ],
                # Дополнительные настройки
                chromium_sandbox=False,
                handle_sigint=False,
                handle_sigterm=False,
                handle_sighup=False,
                timeout=60000
            )
            logger.info("✅ Браузер запущен в легком режиме")
            
            # 3. Создание контекста с минимальными настройками
            logger.info("Создание контекста...")
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                ignore_https_errors=True,
                # Минимальные настройки
                java_script_enabled=True,
                bypass_csp=False,
                has_touch=False,
                is_mobile=False,
                device_scale_factor=1,
                # Убираем лишнее
                storage_state=None,
                permissions=[]
            )
            logger.info("✅ Контекст создан")
            
            # 4. Создание страницы
            self.page = self.context.new_page()
            
            # 5. Минимальные anti-detection скрипты
            self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { 
                    get: () => [{ 
                        0: {type: "application/pdf"}, 
                        length: 1,
                        item: function() { return null; }
                    }] 
                });
            """)
            
            # 6. Логин в систему
            logger.info("🔐 Выполняем логин...")
            login_success = self._login()
            
            if not login_success:
                logger.error("❌ Не удалось выполнить логин")
                self.init_event.set()
                return
            
            logger.info("✅ Инициализация завершена!")
            self.init_event.set()
            
            # 7. Основной цикл обработки задач
            while self.is_running:
                try:
                    task = self.task_queue.get(timeout=0.5)
                    task_id, task_type, task_data, result_queue = task
                    
                    logger.debug(f"📥 Получена задача {task_id}: {task_type}")
                    
                    try:
                        # Принудительная сборка мусора перед задачей
                        gc.collect()
                        
                        result = self._process_task(task_type, task_data)
                        
                        # Принудительная сборка мусора после задачи
                        gc.collect()
                        
                        logger.debug(f"✅ Задача {task_id} выполнена")
                        result_queue.put((task_id, {"success": True, "data": result}))
                    except Exception as e:
                        logger.error(f"❌ Ошибка в задаче {task_id}: {str(e)[:200]}")
                        result_queue.put((task_id, {
                            "success": False, 
                            "error": str(e),
                            "traceback": traceback.format_exc()
                        }))
                    
                    self.task_queue.task_done()
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле обработки: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в рабочем потоке: {e}")
            traceback.print_exc()
            self.init_event.set()
            
    def _login(self):
        """Логин в pena.rest"""
        for attempt in range(self.max_login_attempts):
            try:
                logger.info(f"🔐 Попытка логина #{attempt + 1}")
                
                # Очищаем куки
                self.context.clear_cookies()
                time.sleep(1)
                
                # Переходим на страницу логина
                logger.info(f"🌐 Переход на {LOGIN_PAGE}")
                self.page.goto(LOGIN_PAGE, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                
                # Проверяем капчу
                page_content = self.page.content()
                if any(word in page_content.lower() for word in ["captcha", "капча", "robot", "робот"]):
                    logger.warning("⚠️ Обнаружена капча! Ждем 10 секунд...")
                    time.sleep(10)
                    continue
                
                # Заполняем логин
                logger.info(f"👤 Ввод логина: {accounts[0]['username']}")
                self.page.fill(LOGIN_SELECTOR, accounts[0]["username"])
                time.sleep(random.uniform(0.3, 0.7))
                
                # Заполняем пароль
                logger.info("🔑 Ввод пароля")
                self.page.fill(PASSWORD_SELECTOR, accounts[0]["password"])
                time.sleep(random.uniform(0.3, 0.7))
                
                # Нажимаем кнопку
                logger.info("🖱️ Нажатие кнопки входа")
                self.page.click(SIGN_IN_BUTTON_SELECTOR)
                time.sleep(3)
                
                # Проверяем успешность
                current_url = self.page.url
                logger.info(f"📍 Текущий URL: {current_url}")
                
                if any(keyword in current_url for keyword in ["dashboard", "search", "main"]):
                    logger.info("✅ Логин успешен")
                    
                    # Краткая пауза
                    time.sleep(1)
                    
                    # Получаем cookies
                    cookies_list = self.context.cookies()
                    self.cookies = {c['name']: c['value'] for c in cookies_list}
                    
                    # Генерируем fingerprint
                    self.fingerprint = self._generate_fingerprint()
                    
                    # Создаем заголовки
                    self._create_headers()
                    
                    logger.info(f"📊 Cookies: {len(self.cookies)} шт")
                    
                    # Логируем важные куки
                    important_cookies = ['cf_clearance', 'aegis_session', 'access_token']
                    for cookie_name in important_cookies:
                        if cookie_name in self.cookies:
                            value = self.cookies[cookie_name]
                            logger.info(f"🍪 {cookie_name}: {value[:20]}...")
                    
                    return True
                else:
                    logger.warning(f"⚠️ Логин неудачен, URL: {current_url[:50]}...")
                    time.sleep(2)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при логине (попытка {attempt + 1}): {e}")
                time.sleep(2)
        
        logger.error("❌ Все попытки логина провалились")
        return False
    
    def _generate_fingerprint(self):
        """Генерация fingerprint"""
        try:
            # Простая генерация чтобы не нагружать память
            data = {
                "username": accounts[0]["username"],
                "timestamp": int(time.time()),
                "random": random.randint(1000, 9999),
                "user_agent": "Chrome/120.0.0.0"
            }
            data_str = json.dumps(data, sort_keys=True)
            return hashlib.sha256(data_str.encode()).hexdigest()
        except:
            return hashlib.sha256(f"{int(time.time())}{random.randint(1000, 9999)}".encode()).hexdigest()
    
    def _create_headers(self):
        """Создание заголовков для запросов"""
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
            "x-device-fingerprint": self.fingerprint or "",
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
        
        logger.info(f"📡 Запрос: {url[:80]}...")
        
        start_time = time.time()
        
        try:
            response = self.context.request.get(
                url, 
                headers=self.headers, 
                timeout=20000  # Уменьшенный таймаут
            )
            
            elapsed = time.time() - start_time
            logger.info(f"📊 Ответ: {response.status} за {elapsed:.1f}сек")
            
            response_text = response.text()
            
            result = {
                "status": response.status,
                "url": url,
                "text": response_text,
                "elapsed": elapsed
            }
            
            if response.status == 200:
                try:
                    json_data = response.json()
                    result["json"] = json_data
                    if isinstance(json_data, list):
                        logger.info(f"📝 Найдено записей: {len(json_data)}")
                except:
                    result["json"] = None
            else:
                result["error"] = response_text[:200]
                logger.warning(f"⚠️ Ошибка {response.status}")
            
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Исключение при запросе за {elapsed:.1f}сек: {str(e)[:100]}")
            
            # Если EPIPE ошибка - перезапускаем
            if "EPIPE" in str(e) or "Broken pipe" in str(e):
                logger.critical("💥 EPIPE/Broken pipe - требуется перезапуск браузера")
                raise RuntimeError("EPIPE_ERROR")
            
            raise
    
    def _test_connection(self):
        """Тестовый запрос"""
        try:
            test_url = urljoin(BASE_URL, "/api/v3/search/iin?iin=931229400494")
            response = self.context.request.get(test_url, headers=self.headers, timeout=10000)
            return {
                "test_passed": response.status == 200,
                "status": response.status,
                "elapsed": 0
            }
        except Exception as e:
            return {"test_passed": False, "error": str(e)}
    
    def _get_worker_info(self):
        """Информация о рабочем потоке"""
        return {
            "thread": threading.current_thread().name,
            "cookies_count": len(self.cookies),
            "fingerprint": self.fingerprint[:20] + "..." if self.fingerprint else None,
            "is_running": self.is_running,
            "queue_size": self.task_queue.qsize(),
            "memory_usage": self._get_memory_usage()
        }
    
    def _get_memory_usage(self):
        """Получить использование памяти"""
        try:
            import psutil
            process = psutil.Process()
            return {
                "rss_mb": process.memory_info().rss / 1024 / 1024,
                "vms_mb": process.memory_info().vms / 1024 / 1024,
                "percent": process.memory_percent()
            }
        except:
            return {"error": "psutil not available"}
    
    def _re_login(self):
        """Перелогин"""
        logger.info("🔄 Перелогин...")
        success = self._login()
        return {"success": success}
    
    def submit_task(self, task_type: str, task_data: Dict, timeout: int = 25):
        """Отправить задачу в рабочий поток"""
        with self.task_lock:
            task_id = self.task_counter
            self.task_counter += 1
            
        result_queue = queue.Queue()
        self.result_queues[task_id] = result_queue
        
        # Проверяем не перегружена ли очередь
        if self.task_queue.qsize() > 50:
            logger.warning(f"⚠️ Очередь перегружена: {self.task_queue.qsize()} задач")
        
        # Отправляем задачу
        self.task_queue.put((task_id, task_type, task_data, result_queue))
        
        # Ждем результат
        try:
            result_id, result = result_queue.get(timeout=timeout)
            
            if result_id != task_id:
                raise RuntimeError(f"Несоответствие ID задачи")
            
            return result
            
        except queue.Empty:
            logger.error(f"⏰ Таймаут задачи {task_id}")
            raise TimeoutError(f"Таймаут ожидания задачи {task_id}")
        finally:
            with self.task_lock:
                if task_id in self.result_queues:
                    del self.result_queues[task_id]
    
    def stop(self):
        """Корректная остановка рабочего потока"""
        logger.info("🛑 Корректная остановка PlaywrightWorker...")
        self.is_running = False
        
        # Очищаем очередь
        while not self.task_queue.empty():
            try:
                self.task_queue.get_nowait()
                self.task_queue.task_done()
            except queue.Empty:
                break
        
        # Ждем завершения потока
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
        
        # Закрываем браузер
        if self.browser:
            try:
                self.browser.close()
                logger.info("✅ Браузер закрыт")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка закрытия браузера: {e}")
        
        # Останавливаем Playwright
        if self.playwright:
            try:
                self.playwright.stop()
                logger.info("✅ Playwright остановлен")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка остановки Playwright: {e}")
        
        # Принудительная сборка мусора
        gc.collect()
        
        logger.info("✅ PlaywrightWorker остановлен")

# Глобальный экземпляр рабочего потока
pw_worker = PlaywrightWorker()

# ================== 4. ОБРАБОТЧИКИ СИГНАЛОВ ==================
def graceful_shutdown(signum, frame):
    """Корректное завершение работы"""
    logger.info(f"📴 Получен сигнал {signum}, завершаем работу...")
    
    # Останавливаем Playwright worker
    if 'pw_worker' in globals():
        pw_worker.stop()
    
    # Даем время на завершение
    time.sleep(1)
    
    logger.info("✅ Корректное завершение выполнено")
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

# ================== 5. FLASK API ==================
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

def crm_get(endpoint: str, params: dict = None, max_retries: int = 2):
    """API запрос через Playwright worker с повторными попытками"""
    for retry in range(max_retries + 1):
        try:
            result = pw_worker.submit_task("api_request", {
                "endpoint": endpoint,
                "params": params
            }, timeout=25)
            
            if result["success"]:
                data = result["data"]
                
                # Проверяем ошибку авторизации
                if data.get("status") in [401, 403, 419]:
                    logger.warning(f"⚠️ Ошибка авторизации {data['status']}")
                    if retry < max_retries:
                        logger.info("🔄 Пробуем перелогин...")
                        try:
                            relogin_result = pw_worker.submit_task("re_login", {}, timeout=20)
                            if relogin_result.get("success"):
                                continue  # Повторяем запрос
                        except:
                            pass
                
                return ResponseLike(
                    status_code=data["status"],
                    text=data["text"],
                    json_data=data.get("json")
                )
            else:
                error_msg = result.get('error', 'Unknown error')
                
                # Если EPIPE ошибка - перезапускаем worker
                if "EPIPE_ERROR" in error_msg and retry < max_retries:
                    logger.critical("💥 EPIPE ошибка, перезапускаем worker...")
                    pw_worker.stop()
                    time.sleep(3)
                    pw_worker.start()
                    pw_worker.init_event.wait(30)
                    continue
                
                logger.error(f"❌ Ошибка в CRM GET: {error_msg}")
                return ResponseLike(500, error_msg)
                
        except TimeoutError as e:
            logger.error(f"⏰ Таймаут в CRM GET (попытка {retry + 1}): {e}")
            if retry < max_retries:
                time.sleep(1)
                continue
            return ResponseLike(504, "Таймаут запроса")
        except Exception as e:
            logger.error(f"❌ Исключение в CRM GET (попытка {retry + 1}): {e}")
            if retry < max_retries:
                time.sleep(1)
                continue
            return ResponseLike(500, str(e))
    
    return ResponseLike(500, "Все попытки запроса провалились")

# ================== 6. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin: str):
    logger.info(f"🔍 Поиск по ИИН: {iin}")
    
    resp = crm_get("/api/v3/search/iin", params={"iin": iin})
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ"
    
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
    
    logger.info(f"🔍 Поиск по телефону: {phone} (чистый: {clean})")
    
    resp = crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 10})
    
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ"
    
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
        return f"❌ Ошибка {resp.status_code}"
    
    try:
        data = resp.json()
    except:
        return f"❌ Не удалось распарсить ответ"
    
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

# ================== 7. FLASK РОУТИНГ ==================
@app.route('/api/search', methods=['POST'])
def api_search():
    """Основной поисковый эндпоинт"""
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400
    
    logger.info(f"\n{'='*50}")
    logger.info(f"🔍 Поиск: {query}")
    logger.info(f"{'='*50}")
    
    try:
        if query.isdigit() and len(query) == 12:
            reply = search_by_iin(query)
        elif query.startswith(("+", "8", "7")):
            reply = search_by_phone(query)
        else:
            reply = search_by_fio(query)
        
        logger.info(f"✅ Ответ готов ({len(reply)} символов)")
        logger.info(f"{'='*50}")
        
        return jsonify({"result": reply})
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {e}")
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервиса"""
    try:
        # Быстрый тест
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
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/debug/test', methods=['GET'])
def debug_test():
    """Тестовый запрос"""
    iin = request.args.get('iin', '931229400494')
    
    try:
        result = pw_worker.submit_task("api_request", {
            "endpoint": "/api/v3/search/iin",
            "params": {"iin": iin}
        }, timeout=20)
        
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

# ================== 8. ЗАПУСК ==================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК PENA.REST API СЕРВЕРА (ОПТИМИЗИРОВАННЫЙ)")
    print("=" * 60)
    print("Архитектура: Один поток Playwright, оптимизированная память")
    print("Исправлено: EPIPE ошибки, перегрузка памяти")
    print("Логи: pena_api.log")
    print("=" * 60)
    
    # Запускаем Playwright worker
    pw_worker.start()
    
    # Ждем инициализации
    print("\n⏳ Ожидаем инициализации Playwright...")
    initialized = pw_worker.init_event.wait(timeout=40)
    
    if initialized:
        print("✅ Playwright инициализирован")
        
        # Тестовый запрос
        try:
            test_result = pw_worker.submit_task("test_connection", {}, timeout=15)
            if test_result.get("success") and test_result.get("data", {}).get("test_passed"):
                print("✅ Тестовый запрос успешен")
            else:
                print(f"⚠️ Тестовый запрос не прошел: {test_result}")
        except Exception as e:
            print(f"⚠️ Ошибка тестового запроса: {e}")
    else:
        print("❌ Таймаут инициализации Playwright!")
    
    print("\n🌐 Flask сервер запускается...")
    print("📡 Health check: GET /api/health")
    print("🔍 Поиск: POST /api/search")
    print("=" * 60)
    
    # Запускаем Flask
    from werkzeug.serving import run_simple
    run_simple(
        '0.0.0.0', 
        5000, 
        app, 
        threaded=True, 
        use_reloader=False,
        processes=1
    )
