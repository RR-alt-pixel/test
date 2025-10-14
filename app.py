# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify 
from flask_cors import CORS 
from threading import Thread 
from playwright.sync_api import sync_playwright # 🟢 Playwright для автологина

# ================== НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================

# 🛑 1. ЗАМЕНИТЕ: Токен вашего рабочего бота
BOT_TOKEN = "7966914480:AAEeWXbLeIYjAMLKARCWzSJOKo9c_Cfyvhs" 

# 🟢 2. URL НА ВАШ ВНЕШНИЙ JSON-ФАЙЛ СО СПИСКОМ ID
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json" 
# ВРЕМЕННЫЙ СПИСОК: Используется, если не удалось загрузить файл
ALLOWED_USER_IDS = [0] 

BASE_URL = "https://crm431241.ru/api/v2/person-search/"
LOGIN_URL = "https://crm431241.ru/api/auth/login"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44" 

# 🟢 URL НА ВАШ ВНЕШНИЙ JSON-ФАЙЛ С ЛОГИНАМИ/ПАРОЛЯМИ
# ⚠️ ЗАМЕНИТЕ ЭТОТ URL НА ССЫЛКУ К ВАШЕМУ login_accounts.json НА GITHUB
LOGIN_ACCOUNTS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/login_accounts.json"

# ================== АККАУНТЫ И ТОКЕНЫ ==================
# accounts теперь будет хранить логины/пароли, загруженные из JSON
accounts_info = [] 
token_pool = []
token_cycle = None

# ================== ЛОГИКА CRM И ТОКЕНЫ ==================

def get_session_cookies(username, password):
    """Использует Playwright для выполнения JS, получения device_fp и рабочих куки."""
    print(f"[PLW] Попытка авторизации {username} через Playwright...")
    try:
        with sync_playwright() as p:
            # Запускаем безголовый Chromium, установленный через Dockerfile
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # 1. Переходим на страницу логина
            page.goto(LOGIN_URL, timeout=30000) 
            
            # 2. Вводим данные
            # Предполагаем, что селекторы 'input[name="username"]' и 'input[name="password"]' верны.
            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            
            # 3. Нажимаем кнопку Войти и ждем успешного ответа от API
            with page.wait_for_response(
                lambda response: "api/auth/login" in response.url and response.status == 200, 
                timeout=45000 # Долгий таймаут из-за медленного запуска браузера на Render
            ) as response:
                 page.click('button[type="submit"]')

            # 4. Получаем куки после успешного входа
            cookies = context.cookies()
            
            access_token = next((c['value'] for c in cookies if c['name'] == '__Secure-access_token'), None)
            csrf_token = next((c['value'] for c in cookies if c['name'] == '__Secure-csrf_token'), None)
            session_id = next((c['value'] for c in cookies if c['name'] == '__Secure-session_id'), None)
            
            browser.close()
            
            if access_token and csrf_token and session_id:
                print(f"[PLW] {username} УСПЕХ! Токены получены.")
                return {
                    "username": username,
                    "access": access_token,
                    "csrf": csrf_token,
                    "session_id": session_id,
                    "time": int(time.time())
                }
            
            print(f"[PLW FAIL] {username}: Куки не найдены после входа.")
            return None
            
    except Exception as e:
        print(f"[PLW CRITICAL ERR] {username}: Автологин не удался: {e}")
        return None

def init_token_pool():
    global token_pool, token_cycle, accounts_info
    
    # 1. Загрузка логинов/паролей
    try:
        r = requests.get(LOGIN_ACCOUNTS_URL, timeout=10)
        if r.status_code == 200:
            accounts_info = r.json()
            print(f"[ACCOUNTS] Загружено {len(accounts_info)} пар логин/пароль.")
        else:
             print(f"[ACCOUNTS FAIL] Ошибка загрузки логинов. Статус: {r.status_code}")
             return
    except Exception as e:
        print(f"[ACCOUNTS ERR] Критическая ошибка при загрузке логинов: {e}")
        return
    
    # 2. Авторизация через Playwright
    token_pool.clear()
    for acc in accounts_info:
        # ⚠️ ВАЖНО: При первом запуске может быть очень долго (до минуты)
        tok = get_session_cookies(acc["username"], acc["password"]) 
        if tok:
            token_pool.append(tok)
            
    if not token_pool:
        print("❌ Нет активных токенов! Авторизация Playwright не удалась.")
    else:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] Успешно загружено {len(token_pool)} токенов ✅")

def crm_get(endpoint, params=None):
    global token_cycle, token_pool, accounts_info
    
    if not token_pool or not token_cycle:
        init_token_pool()
        if not token_pool:
            return "❌ Ошибка: Нет доступных токенов CRM. Автологин Playwright не удался."

    max_attempts = len(token_pool) + 1 # Даем +1 попытку на перелогин

    for attempt in range(max_attempts):
        token = next(token_cycle)
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": (
                f"__Secure-access_token={token['access']}; "
                f"__Secure-csrf_token={token['csrf']}; "
                f"__Secure-session_id={token['session_id']};" # 🟢 Добавлен session_id
            ),
            "X-CSRF-Token": token["csrf"]
        }

        try:
            r = requests.get(endpoint, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"

        if r.status_code in (401, 403):
            print(f"[AUTH] {token['username']} → токен устарел, инициируем Playwright перелогин...")
            
            # Находим логин/пароль для этого аккаунта
            acc_info = next((acc for acc in accounts_info if acc["username"] == token["username"]), None)
            
            if acc_info:
                # 🟢 Перелогин через Playwright
                new_t = get_session_cookies(acc_info["username"], acc_info["password"])
                
                if new_t:
                    # Успех: Обновляем токен в пуле
                    idx = next((i for i, t in enumerate(token_pool) if t["username"] == token["username"]), None)
                    if idx is not None:
                        token_pool[idx] = new_t
                    
                    token_cycle = itertools.cycle(token_pool)
                    print(f"[AUTH] {token['username']} обновлён через Playwright ✅. Повторяем запрос.")
                    
                    # Повторяем исходный запрос с новым токеном
                    return crm_get(endpoint, params)
                else:
                    print(f"[AUTH FAIL] {token['username']} не смог обновиться через Playwright.")
            
            # Если перелогин не удался, переходим к следующему токену
            continue 

        # Если статус 200 (или любая другая ошибка, кроме 401/403)
        return r
    
    # Если все попытки перелогина и перебора исчерпаны
    print("❌ Критический сбой: Все токены неактивны и не смогли обновиться!")
    return "❌ Критическая ошибка: Невозможно получить доступ к CRM. Попробуйте позже."


# ================== ЛОГИКА ДИНАМИЧЕСКОЙ ЗАГРУЗКИ ID ==================
# ... (Оставляем fetch_allowed_users и periodic_fetch БЕЗ ИЗМЕНЕНИЙ) ...
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600 # Обновлять список раз в час (3600 секунд)

def fetch_allowed_users():
    """Загружает список разрешенных ID из внешнего источника."""
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    print("[AUTH-LOG] Начало попытки загрузки ID.")
    try:
        print(f"[AUTH-LOG] Загрузка списка ID с {ALLOWED_USERS_URL}...")
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
                print("[AUTH-LOG ERROR] Список ID пуст в источнике, оставляем старый список.")
        else:
            print(f"[AUTH-LOG ERROR] Не удалось загрузить список ID. Статус: {response.status_code}")
            
    except Exception as e:
        print(f"[AUTH-LOG CRITICAL ERROR] Исключение при загрузке: {e}")

def periodic_fetch():
    """Запускает функцию загрузки ID в фоновом режиме."""
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL) 


# ================== ФУНКЦИИ ПОИСКА ==================
# ... (Оставляем search_by_iin, search_by_phone, search_by_fio БЕЗ ИЗМЕНЕНИЙ) ...
def search_by_iin(iin):
    r = crm_get(BASE_URL + "by-iin", params={"iin": iin})
    if isinstance(r, str): return r
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
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"): clean = "7" + clean[1:]
    r = crm_get(BASE_URL + "by-phone", params={"phone": clean})
    if isinstance(r, str): return r
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

    r = crm_get(BASE_URL + "smart", params=q)
    if isinstance(r, str): return r
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


# ================== API ENDPOINT (Flask) ==================
app = Flask(__name__)

# ИНИЦИАЛИЗАЦИЯ CORS: Разрешаем ВСЕ запросы со ВСЕХ источников
CORS(app, resources={r"/*": {"origins": "*"}}) 

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    
    # 🚨 БЛОК ПРОВЕРКИ АВТОРИЗАЦИИ ПО ID 🚨
    user_id = data.get('telegram_user_id')
    
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации: ID пользователя не найден."}), 403

    try:
        if int(user_id) not in ALLOWED_USER_IDS:
            print(f"❌ Доступ запрещен для ID: {user_id}")
            return jsonify({"error": "У вас нет доступа к этому приложению."}), 403
    except ValueError:
        return jsonify({"error": "Неверный формат ID пользователя."}), 403
    # ---------------------------------------------
    
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
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400
        
    return jsonify({"result": reply})


@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    """Точка для немедленного принудительного обновления списка разрешенных ID."""
    
    # 🚨 Проверка на секретный токен
    auth_header = request.headers.get('Authorization')
    
    # Проверка: Заголовок должен быть "Bearer YOUR_SECRET_TOKEN"
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Неверный секретный токен. Доступ запрещен."}), 403

    # Вызываем функцию немедленно, не дожидаясь таймера
    print("[AUTH-LOG] Принудительное обновление списка ID запущено вручную.")
    fetch_allowed_users()
    
    return jsonify({
        "status": "success", 
        "message": "Список разрешенных пользователей обновлен немедленно.",
        "loaded_count": len(ALLOWED_USER_IDS)
    }), 200


# ================== ПРИНУДИТЕЛЬНЫЙ ЗАПУСК ИНИЦИАЛИЗАЦИИ GUNICORN ==================

# Этот код будет выполнен, когда Gunicorn загрузит приложение.
print("--- 🔴 DEBUG: НАЧАЛО ЗАПУСКА API 🔴 ---")

print("🔐 Первая загрузка списка ID...")
fetch_allowed_users() 

print("🔄 Запуск фонового обновления списка ID...")
Thread(target=periodic_fetch, daemon=True).start() 

print("🔐 Авторизация всех аккаунтов через Playwright (займет время)...")
init_token_pool() 
print("🚀 API-сервер готов к приему запросов.")

# ================== ЗАПУСК (ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО ТЕСТИРОВАНИЯ) ==================
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
