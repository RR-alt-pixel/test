# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List
from queue import Queue

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
API_BASE = BASE_URL
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

TOKENS_FILE = "tokens.json"
TOKENS_LOCK = Lock()

# ================== 2. ПУЛ ТОКЕНОВ ==================
token_pool: List[Dict] = []
token_cycle = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

def load_tokens_from_file() -> List[Dict]:
    """Загрузка токенов из файла"""
    global token_pool, token_cycle
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    token_pool = data
                    token_cycle = itertools.cycle(token_pool)
                    print(f"[TOKENS] ✅ Загружено {len(token_pool)} токенов из файла.")
                    return token_pool
                else:
                    print("[TOKENS] ⚠️ Файл пустой или некорректный.")
        else:
            print(f"[TOKENS] ⚠️ Файл {TOKENS_FILE} не найден.")
    except Exception as e:
        print(f"[TOKENS ERROR] Ошибка загрузки: {e}")
        traceback.print_exc()
    
    token_pool = []
    token_cycle = None
    return []

def save_tokens_to_file():
    """Сохранение токенов в файл"""
    global token_pool
    try:
        with TOKENS_LOCK:
            tmp = TOKENS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(token_pool, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)
            print(f"[TOKENS] 💾 Сохранено {len(token_pool)} токенов.")
    except Exception as e:
        print(f"[TOKENS ERROR] Ошибка сохранения: {e}")
        traceback.print_exc()

# ================== 3. TOKEN GETTER ==================
def get_next_token() -> Optional[Dict]:
    """Получить следующий токен из пула"""
    global token_pool, token_cycle
    
    if not token_pool:
        print("[POOL] ❌ Пул токенов пуст! Ожидаем загрузки с VPS.")
        return None
        
    if token_cycle is None:
        token_cycle = itertools.cycle(token_pool)
    
    try:
        token = next(token_cycle)
        print(f"[POOL] 🔁 Используется токен: {token.get('username', 'unknown')}")
        return token
    except StopIteration:
        print("[POOL] ⚠️ StopIteration - перезапуск цикла")
        token_cycle = itertools.cycle(token_pool)
        token = next(token_cycle)
        return token

# ================== 4. CRM GET ==================
def crm_get(endpoint: str, params: dict = None):
    """Выполнить GET запрос к CRM"""
    token = get_next_token()
    if not token:
        return "❌ Нет доступных токенов CRM."
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": token.get("user_agent", random.choice(USER_AGENTS)),
        "Cookie": token.get("cookie_header", "")
    }

    if "/by-address" in endpoint:
        headers["Referer"] = f"{BASE_URL}/person-search"
    else:
        headers["Referer"] = f"{BASE_URL}/search"

    url = endpoint if endpoint.startswith("http") else API_BASE + endpoint
    
    try:
        print(f"[CRM] 🌐 GET {url} | Токен: {token.get('username')}")
        r = requests.get(url, headers=headers, params=params, timeout=20)
        
        # Проверка авторизации
        if r.status_code in (401, 403):
            print(f"[CRM] ⚠️ Токен {token.get('username')} истёк (HTTP {r.status_code})")
            # Просто пропускаем этот токен, VPS обновит позже
            return f"❌ Токен истёк. Попробуйте через несколько минут."
        
        print(f"[CRM] ✅ Ответ: {r.status_code}")
        return r
        
    except Exception as e:
        print(f"[CRM ERROR] {e}")
        traceback.print_exc()
        return f"❌ Ошибка запроса: {e}"

# ================== 5. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    """Обработчик очереди запросов"""
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(1.7, 2.5))  # Задержка между запросами
        except Exception as e:
            print(f"[WORKER ERROR] {e}")
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
    """Добавить запрос в очередь"""
    result_box = {}
    crm_queue.put((crm_get, (endpoint,), {"params": params}, result_box))
    
    t0 = time.time()
    while "result" not in result_box and "error" not in result_box:
        if time.time() - t0 > RESULT_TIMEOUT:
            return {"status": "timeout"}
        time.sleep(0.1)
    
    if "error" in result_box:
        return {"status": "error", "error": result_box["error"]}
    
    return {"status": "ok", "result": result_box["result"]}

# ================== 6. ALLOWED USERS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    """Загрузить список разрешённых пользователей"""
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ids = [int(i) for i in data.get("allowed_users", [])]
            if ids:
                ALLOWED_USER_IDS = ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH] ✅ Загружено {len(ALLOWED_USER_IDS)} разрешённых пользователей.")
    except Exception as e:
        print(f"[AUTH ERROR] {e}")

def periodic_fetch():
    """Периодическое обновление списка пользователей"""
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 7. ПОИСК ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    p = resp.json()
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = enqueue_crm_get("/api/v2/person-search/by-phone", params={"phone": clean})
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0] if isinstance(data, list) else data
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_fio(text: str):
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}
    r = enqueue_crm_get("/api/v2/person-search/smart", params=q)
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data:
        return "⚠️ Ничего не найдено."
    if isinstance(data, dict):
        data = [data]
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

def search_by_address(address: str):
    params = {"address": address, "exact_match": "false", "limit": 50}
    r = enqueue_crm_get("/api/v2/person-search/by-address", params=params)
    if r["status"] != "ok":
        return "⌛ В очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
    data = resp.json()
    if isinstance(data, dict):
        data = [data]
    results = []
    for i, p in enumerate(data[:10], start=1):
        results.append(f"{i}. {p.get('snf','')} — {p.get('address','')}")
    return "\n".join(results)

# ================== 8. FLASK + СЕССИИ ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600  # 1 час

@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.json
    user_id = data.get('telegram_user_id')
    if not user_id:
        return jsonify({"error": "Нет Telegram ID"}), 400
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа"}), 403

    now = time.time()
    existing = active_sessions.get(user_id)

    # Проверка активной сессии
    if existing and (now - existing["created"]) < SESSION_TTL:
        print(f"[SESSION] ❌ Попытка перезапуска сессии {user_id}, отклонено.")
        return jsonify({"error": "Сессия уже активна. Повторите позже."}), 403

    # Удаление истёкшей сессии
    if existing and (now - existing["created"]) >= SESSION_TTL:
        del active_sessions[user_id]
        print(f"[SESSION] ⏰ Истекшая сессия {user_id} удалена")

    # Создание новой сессии
    session_token = f"{user_id}-{int(now)}-{random.randint(1000,9999)}"
    active_sessions[user_id] = {
        "token": session_token,
        "created": now
    }

    print(f"[SESSION] 🔑 Активирована сессия для {user_id}")
    return jsonify({"session_token": session_token})

@app.before_request
def validate_session():
    if request.path == "/api/search" and request.method == "POST":
        data = request.json or {}
        uid = data.get("telegram_user_id")
        token = data.get("session_token")

        session = active_sessions.get(uid)
        if not session:
            return jsonify({"error": "Сессия не найдена. Авторизуйтесь заново."}), 403

        if session["token"] != token:
            print(f"[SESSION] ⚠️ Несовпадение токена: uid={uid}")
            return jsonify({"error": "Сессия недействительна. Вход возможен только с одного устройства."}), 403

        if time.time() - session["created"] > SESSION_TTL:
            del active_sessions[uid]
            print(f"[SESSION] ⏰ Истёк срок действия сессии {uid}")
            return jsonify({"error": "Сессия истекла. Авторизуйтесь заново."}), 403

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации."}), 403
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа."}), 403

    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith(("+", "8", "7")):
        reply = search_by_phone(query)
    elif any(x in query.upper() for x in ["УЛ.", "ПР.", "ДОМ", "РЕСПУБЛИКА"]):
        reply = search_by_address(query)
    else:
        reply = search_by_fio(query)
    
    return jsonify({"result": reply})

@app.route('/api/queue-size', methods=['GET'])
def queue_size():
    return jsonify({"queue_size": crm_queue.qsize()})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    fetch_allowed_users()
    return jsonify({"ok": True, "count": len(ALLOWED_USER_IDS)})

# ====== ЭНДПОИНТ: ПРИЁМ ТОКЕНОВ С VPS ======
@app.route('/api/admin/upload-tokens', methods=['POST'])
def upload_tokens():
    """Принять токены с VPS и сохранить"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        print("[UPLOAD] ❌ Неверный токен авторизации")
        return jsonify({"error": "Forbidden"}), 403

    data = request.json

    if not isinstance(data, list) or not data:
        print("[UPLOAD] ❌ Некорректные данные")
        return jsonify({"error": "Expected non-empty list of tokens"}), 400

    # Валидация токенов
    for t in data:
        if not isinstance(t, dict):
            return jsonify({"error": "Each token must be an object"}), 400
        if not t.get("username") or not t.get("cookie_header") or not t.get("user_agent"):
            print(f"[UPLOAD] ❌ Некорректный токен: {t}")
            return jsonify({"error": "Token missing fields: username/cookie_header/user_agent"}), 400

    try:
        # Сохранение в файл
        tmp = TOKENS_FILE + ".tmp"
        with TOKENS_LOCK:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)

        # Обновление глобального пула
        global token_pool, token_cycle
        token_pool = data
        token_cycle = itertools.cycle(token_pool) if token_pool else None

        print(f"[UPLOAD] ✅ Получено и загружено {len(token_pool)} токенов")
        return jsonify({"ok": True, "count": len(token_pool)})
        
    except Exception as e:
        print(f"[UPLOAD ERROR] {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ====== ЭНДПОИНТ: ПРОВЕРКА СТАТУСА ТОКЕНОВ ======
@app.route('/api/admin/tokens-status', methods=['GET'])
def tokens_status():
    """Проверить наличие токенов"""
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    
    return jsonify({
        "tokens_count": len(token_pool),
        "tokens": [{"username": t.get("username"), "has_cookie": bool(t.get("cookie_header"))} for t in token_pool]
    })

# ================== 9. ЗАПУСК ==================
print("=" * 60)
print("🚀 Запуск Render API сервера")
print("=" * 60)

# Загрузка разрешённых пользователей
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()

# ЗАГРУЗКА ТОКЕНОВ ПРИ СТАРТЕ
print("[INIT] Загрузка токенов из файла...")
load_tokens_from_file()

if not token_pool:
    print("[INIT] ⚠️ Токены не найдены. Ожидаем загрузки с VPS.")
else:
    print(f"[INIT] ✅ Готов к работе с {len(token_pool)} токенами")

# Очистка истёкших сессий
def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
            print(f"[SESSION] 🧹 Удалена просроченная сессия {uid}")
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

print("=" * 60)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
