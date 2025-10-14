# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify 
from flask_cors import CORS 
from threading import Thread 

# ================== НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================

# 🛑 1. ЗАМЕНИТЕ: Токен вашего рабочего бота
BOT_TOKEN = "7966914480:AAEeWXbLeIYjAMLKARCWzSJOKo9c_Cfyvhs" 

# 🟢 URL НА ВАШ ВНЕШНИЙ JSON-ФАЙЛ СО СПИСКОМ ID
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json" 
# ВРЕМЕННЫЙ СПИСОК: Используется, если не удалось загрузить файл
ALLOWED_USER_IDS = [0] 

# 🟢 НОВОЕ: URL для загрузки рабочих токенов
TOKENS_FILE_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/tokens.json"

BASE_URL = "https://crm431241.ru/api/v2/person-search/"
# LOGIN_URL = "https://crm431241.ru/api/auth/login" # УДАЛЕНО: Не используется
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44" 

# ================== АККАУНТЫ (РУЧНОЙ ПУЛ) ==================
# 🛑 УДАЛЕН статический список логинов/паролей. Теперь пул загружается из tokens.json
token_pool = []
token_cycle = None

# ================== ЛОГИКА CRM И ТОКЕНЫ ==================

# 🛑 УДАЛЕНА ФУНКЦИЯ login_crm, поскольку автоматическая авторизация не работает.

def init_token_pool():
    global token_pool, token_cycle
    print("🔐 Загрузка ручных токенов из tokens.json...")
    
    try:
        r = requests.get(TOKENS_FILE_URL, timeout=10)
        
        if r.status_code == 200:
            raw_tokens = r.json()
            new_pool = []
            
            for t in raw_tokens:
                # Считываем все 3 необходимых поля: access, csrf, session_id
                new_pool.append({
                    "username": t.get("username", "unknown"),
                    "access": t.get("access", ""),
                    "csrf": t.get("csrf", ""),
                    "session_id": t.get("session_id", ""), # 🟢 Считываем session_id
                    "time": int(time.time())
                })
            
            token_pool = new_pool
            
            if not token_pool:
                 print("❌ Нет токенов в ручном пуле! Проверьте tokens.json.")
            else:
                token_cycle = itertools.cycle(token_pool)
                print(f"[POOL] УСПЕХ! Загружено {len(token_pool)} ручных токенов ✅")
            
        else:
            print(f"[POOL FAIL] Ошибка загрузки токенов с GitHub. Статус: {r.status_code}")
            
    except Exception as e:
        print(f"[POOL ERR] Критическая ошибка при загрузке токенов: {e}")


def crm_get(endpoint, params=None):
    global token_cycle, token_pool
    if not token_cycle or not token_pool:
        init_token_pool()

    if not token_pool:
        # Теперь init_token_pool возвращает None при ошибке, проверяем пул снова
        return "❌ Ошибка: Нет доступных токенов CRM."

    # Максимальное количество попыток (размер пула)
    max_attempts = len(token_pool) 
    
    for attempt in range(max_attempts):
        token = next(token_cycle)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            # 🟢 В заголовки Cookie добавлены access, csrf и session_id
            "Cookie": (
                f"__Secure-access_token={token['access']}; "
                f"__Secure-csrf_token={token['csrf']};"
                f"__Secure-session_id={token['session_id']};"
            ),
            "X-CSRF-Token": token["csrf"]
        }

        try:
            r = requests.get(endpoint, headers=headers, params=params, timeout=15)
        except Exception as e:
            print(f"[CONN ERR] {token['username']}: {e}. Пробуем следующий токен.")
            continue 

        if r.status_code in (401, 403):
            # 🛑 РУЧНОЙ РЕЖИМ: Перелогин невозможен. Просто переходим к следующему токену.
            print(f"[AUTH FAIL] {token['username']} токен устарел/заблокирован. Требуется ручное обновление tokens.json. Переход к следующему токену.")
            continue 

        # Если код 200, или другая ошибка, которую нужно вернуть пользователю.
        return r
    
    # Если прошли через все токены и не получили 200, возвращаем ошибку.
    return "❌ Ошибка: Все токены в пуле неактивны. Обновите tokens.json."


# ================== ЛОГИКА ДИНАМИЧЕСКОЙ ЗАГРУЗКИ ID ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600 # Обновлять список раз в час (3600 секунд)

def fetch_allowed_users():
    # ... (Оставляем эту функцию без изменений)
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
    # ... (Оставляем эту функцию без изменений)
    """Запускает функцию загрузки ID в фоновом режиме."""
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL) 


# ================== ФУНКЦИИ ПОИСКА ==================
# ... (Оставляем функции search_by_iin, search_by_phone, search_by_fio без изменений)
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
# ... (Оставляем эту функцию без изменений)
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
        # Возвращаем 400 и сообщение об ошибке, если оно начинается с ❌ или ⚠️
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400
        
    return jsonify({"result": reply})


@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
# ... (Оставляем эту функцию без изменений)
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

print("🔐 Загрузка ручных токенов...")
init_token_pool() # 🟢 Теперь просто загружаем токены из tokens.json
print("🚀 API-сервер готов к приему запросов.")

# ================== ЗАПУСК (ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО ТЕСТИРОВАНИЯ) ==================
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
