# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify 
from flask_cors import CORS 
from threading import Thread 
from playwright.sync_api import sync_playwright # СИНХРОННЫЙ PLAYWRIGHT ДЛЯ FLASK/GUNICORN 
from typing import Optional, Dict
import re

# ================== 1. НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================

# 🛑 1. ЗАМЕНИТЕ: Токен вашего рабочего бота
BOT_TOKEN = "8240195944:AAEQFd2met5meCU1uwu5PvPejJoiKu94cms" 

# 🟢 2. URL НА ВАШ ВНЕШНИЙ JSON-ФАЙЛ СО СПИСКОМ ID
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json" 
ALLOWED_USER_IDS = [0] 

BASE_URL = "https://crm431241.ru" # Упрощенный BASE_URL для удобства
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44" 

# ================== 2. НАСТРОЙКИ PLAYWRIGHT ==================
LOGIN_URL_PLW = f"{BASE_URL}/auth/login" 
DASHBOARD_URL = f"{BASE_URL}/dashboard" 
LOGIN_SELECTOR = '#username' 
PASSWORD_SELECTOR = '#password' 
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]' # Исправлен селектор кнопки

# ================== 3. АККАУНТЫ И ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==================
# Используем blue1, который вы подтвердили, что работает
accounts = [
    {"username": "blue1", "password": "852dfghm"}, 
]

# Глобальные переменные для пула
token_pool = []
token_cycle = None

# ================== 4. МОДЕЛЬ ТОКЕНА (Словарь) ==================
# Оставляем формат словаря для совместимости с вашим кодом

# ================== 5. ЛОГИКА CRM И ТОКЕНЫ (Playwright) ==================

# ================== ЛОГИКА CRM И ТОКЕНЫ (Playwright) ==================

def login_crm(username, password, p) -> Optional[Dict]:
    """
    Выполняет вход через Playwright, полагаясь на переменную окружения 
    PLAYWRIGHT_BROWSERS_PATH для автоматического поиска браузера.
    """
    browser = None
    
    try:
        print(f"[PLW] Попытка запуска браузера. Ожидаем автоматического поиска...")
        
        # 🔴 КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Добавление флагов для экономии памяти/скорости
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-setuid-sandbox',
                '--disable-gpu',           # Отключение GPU (важно для безголовых)
                '--disable-dev-shm-usage', # Уменьшение использования /dev/shm
                '--single-process',        # Запуск в одном процессе
                '--no-zygote'              # Дополнительный флаг безопасности
            ],
            timeout=30000 # Макс. 30 секунд на запуск
        )
        
        # 🔴 ИЗМЕНЕНИЕ: Сокращен общий таймаут страницы
        page = browser.new_page()
        page.set_default_timeout(30000) 

        print(f"[PLW] Переход на страницу входа: {LOGIN_URL_PLW}")
        # Сокращен wait_until до load
        page.goto(LOGIN_URL_PLW, wait_until='load', timeout=15000) 
        
        # Ввод данных
        page.type(LOGIN_SELECTOR, username, delay=50) 
        time.sleep(1.0) 
        page.type(PASSWORD_SELECTOR, password, delay=50)
        time.sleep(2.0) # Немного сокращено

        # Отправка формы
        page.click(SIGN_IN_BUTTON_SELECTOR)
        time.sleep(4) # Немного сокращено

        # Принудительный переход
        page.goto(DASHBOARD_URL, wait_until='load', timeout=10000)
        time.sleep(2) # Немного сокращено

        if "dashboard" in page.url:
            print(f"[LOGIN PLW] {username} ✅ Вход успешен. URL: {page.url}")
            
            cookies = page.context.cookies()
            cookies_for_requests = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
            user_agent = page.evaluate('navigator.userAgent')

            # Логика извлечения CSRF-токена
            csrf_token_sec = next((c['value'] for c in cookies if c['name'] == '__Secure-csrf_token'), None)
            if csrf_token_sec:
                csrf_value = csrf_token_sec.split('.')[0] 
            else:
                print(f"[WARN] {username}: CSRF-токен '__Secure-csrf_token' не найден. Используем заглушку.")
                csrf_value = "MISSING_CSRF_PLACEHOLDER"
                
            return {
                "username": username, "csrf": csrf_value, "time": int(time.time()),
                "user_agent": user_agent, "cookie_header": cookies_for_requests 
            }
        
        print(f"[LOGIN PLW FAIL] {username}: Не удалось войти. URL: {page.url}")
        return None

    except Exception as e:
        print(f"[LOGIN PLW ERR] {username}: {type(e).__name__}: {e}")
        return None
    finally:
        if browser:
            browser.close()
            
def init_token_pool():
    """Инициализирует глобальный пул токенов, авторизуясь через Playwright."""
    global token_pool, token_cycle
    token_pool.clear()
    
    print("🔐 Авторизация всех аккаунтов (запустит Playwright)...")
    
    with sync_playwright() as p:
        for acc in accounts:
            tok = login_crm(acc["username"], acc["password"], p)
            if tok:
                token_pool.append(tok)
                print(f"[POOL] Аккаунт {tok['username']} успешно авторизован.")
            else:
                print(f"[POOL] Аккаунт {acc['username']} не смог авторизоваться.")
        
    if not token_pool:
        print("❌ Пул токенов пуст! Проверьте аккаунты и Playwright.")
        token_cycle = None
    else:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] Успешно загружено {len(token_pool)} токенов (через Playwright) ✅")

def get_next_token() -> Optional[Dict]:
    """Возвращает следующий токен из пула, или None."""
    global token_cycle, token_pool
    
    if not token_cycle:
        print("[AUTH] Пул токенов пуст. Попытка инициализации...")
        init_token_pool()
        if not token_cycle:
            return None
            
    try:
        return next(token_cycle)
    except StopIteration:
        # Этого не должно случиться с itertools.cycle, но для безопасности
        return None

def crm_get(endpoint, params=None):
    """
    Выполняет API-запрос, используя токен из пула, с обработкой 401/403 и 
    автоматической повторной авторизацией.
    """
    for _ in range(2): # 2 попытки: текущий токен и новый после релогина
        token = get_next_token()
        if not token:
            return "❌ Ошибка: Нет доступных токенов CRM."

        # Используем данные, захваченные Playwright
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token["user_agent"], 
            "Cookie": token["cookie_header"], # Полная рабочая строка куки
        }
        
        # Добавляем CSRF только если это не заглушка
        if token["csrf"] != "MISSING_CSRF_PLACEHOLDER":
             headers["X-CSRF-Token"] = token["csrf"]

        url = f"{BASE_URL}{endpoint}" # Добавляем BASE_URL к эндпоинту
        
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"

        if r.status_code in (401, 403):
            print(f"[AUTH] {token['username']} → токен устарел, попытка перелогина...")
            
            acc_info = next((acc for acc in accounts if acc["username"] == token["username"]), None)
            if acc_info:
                # ПЕРЕЛОГИН ЧЕРЕЗ PLAYWRIGHT
                with sync_playwright() as p:
                    new_t = login_crm(acc_info["username"], acc_info["password"], p)
                
                if new_t:
                    # Обновляем токен в пуле
                    idx = next((i for i, t in enumerate(token_pool) if t["username"] == token["username"]), None)
                    if idx is not None:
                        token_pool[idx] = new_t
                    token_cycle = itertools.cycle(token_pool) # Пересоздаем цикл
                    print(f"[AUTH] {token['username']} обновлён ✅")
                    continue # Повторяем внешний цикл (с новым токеном)
                else:
                    print(f"[AUTH FAIL] {token['username']} не смог обновиться.")
        
        # Если не 401/403 или после релогина не сработал continue
        return r
    
    return "❌ Ошибка: Не удалось получить данные после повторной авторизации." # Если 2 попытки провалились

# ================== 6. ЛОГИКА ДИНАМИЧЕСКОЙ ЗАГРУЗКИ ID (без изменений) ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    print("[AUTH-LOG] Начало попытки загрузки ID.")
    try:
        response = requests.get(ALLOWED_USERS_URL, timeout=10) 
        print(f"[AUTH-LOG] Статус код от GitHub: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            new_list = [int(i) for i in data.get("allowed_users", [])]
            
            if new_list:
                ALLOWED_USER_IDS = new_list
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH-LOG] УСПЕХ! Загружено {len(ALLOWED_USER_IDS)} разрешенных ID.")
            else:
                print("[AUTH-LOG ERROR] Список ID пуст в источнике.")
        else:
            print(f"[AUTH-LOG ERROR] Не удалось загрузить список ID. Статус: {response.status_code}")
            
    except Exception as e:
        print(f"[AUTH-LOG CRITICAL ERROR] Исключение при загрузке: {e}")

def periodic_fetch():
    while True:
        fetch_allowed_users()
        time.sleep(FETCH_INTERVAL) 

# ================== 7. ФУНКЦИИ ПОИСКА (с коррекцией BASE_URL) ==================

def search_by_iin(iin):
    ENDPOINT = "/api/v2/person-search/by-iin" # Исправлено: только эндпоинт
    r = crm_get(ENDPOINT, params={"iin": iin})
    if isinstance(r, str): return r
    
    if r.status_code == 404: 
        return "⚠️ Ничего не найдено по ИИН."
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
    
    p = r.json()
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"🌍 Национальность: {p.get('nationality','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_phone(phone):
    ENDPOINT = "/api/v2/person-search/by-phone" # Исправлено: только эндпоинт
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"): clean = "7" + clean[1:]
    r = crm_get(ENDPOINT, params={"phone": clean})
    if isinstance(r, str): return r
    if r.status_code == 404: return f"⚠️ Ничего не найдено по номеру {phone}"
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
    
    data = r.json()
    if not data: return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0] if isinstance(data, list) else data
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"🌍 Национальность: {p.get('nationality','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_fio(text):
    ENDPOINT = "/api/v2/person-search/smart" # Исправлено: только эндпоинт
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2: return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "": params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "": params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "": params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}

    r = crm_get(ENDPOINT, params=q)
    if isinstance(r, str): return r
    if r.status_code == 404: return "⚠️ Ничего не найдено."
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
    
    data = r.json()
    if not data: return "⚠️ Ничего не найдено."
    if isinstance(data, dict): data = [data]
    
    results = []
    for i, p in enumerate(data[:10], start=1):
        results.append(
            f"{i}. 👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 Дата рождения: {p.get('birthday','')}\n"
            f"🚻 Пол: {p.get('sex','')}\n"
            f"🌍 Национальность: {p.get('nationality','')}"
        )
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 8. API ENDPOINT (Flask) ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}) 

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации: ID пользователя не найден."}), 403

    try:
        if int(user_id) not in ALLOWED_USER_IDS:
            print(f"❌ Доступ запрещен для ID: {user_id}")
            return jsonify({"error": "У вас нет доступа к этому приложению."}), 403
    except ValueError:
        return jsonify({"error": "Неверный формат ID пользователя."}), 403
    
    if not token_pool:
        return jsonify({"error": "Сервис не готов. Нет активных токенов CRM."}), 400
        
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith("+") or query.startswith("8") or query.startswith("7"):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    if reply.startswith('❌') or reply.startswith('⚠️'):
        # При ошибке возвращаем 400, чтобы фронтенд мог обработать
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400
        
    return jsonify({"result": reply})


@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Неверный секретный токен. Доступ запрещен."}), 403

    print("[AUTH-LOG] Принудительное обновление списка ID запущено вручную.")
    fetch_allowed_users()
    
    return jsonify({
        "status": "success", 
        "message": "Список разрешенных пользователей обновлен немедленно.",
        "loaded_count": len(ALLOWED_USER_IDS)
    }), 200

# ================== 9. ЗАПУСК ИНИЦИАЛИЗАЦИИ ==================

print("--- 🔴 DEBUG: НАЧАЛО ЗАПУСКА API 🔴 ---")
# 1. Инициализация разрешенных ID (нужно для первых проверок)
print("🔐 Первая загрузка списка ID...")
fetch_allowed_users() 
# 2. Запуск фонового обновления списка ID
print("🔄 Запуск фонового обновления списка ID...")
Thread(target=periodic_fetch, daemon=True).start() 
# 3. Инициализация токенов (запустит Playwright)
print("🔐 Авторизация всех аккаунтов (запустит Playwright)...")
Thread(target=init_token_pool, daemon=True).start() 

print("🚀 API-сервер готов к приему запросов.")

# ================== ЗАПУСК (ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО ТЕСТИРОВАНИЯ) ==================
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
