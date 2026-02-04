# -*- coding: utf-8 -*-
import os
import time
import json
import random
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

# VPS PLAYWRIGHT SERVER
VPS_URL = "http://85.198.88.213:5001"

# ================== 2. CRM GET ЧЕРЕЗ VPS ==================
def crm_get(endpoint: str, params: dict = None):
    """Выполнить GET запрос через VPS Playwright"""
    try:
        print(f"[CRM] 🌐 Запрос через VPS: {endpoint}")
        
        r = requests.post(
            f"{VPS_URL}/api/crm-request",
            headers={
                "Authorization": f"Bearer {SECRET_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "endpoint": endpoint,
                "params": params or {}
            },
            timeout=30
        )
        
        if r.status_code == 200:
            data = r.json()
            
            # Создаём фейковый response объект для совместимости
            class FakeResponse:
                def __init__(self, data, status_code):
                    self._data = data
                    self.status_code = status_code
                    self.text = json.dumps(data)
                
                def json(self):
                    return self._data
            
            return FakeResponse(data.get('result'), 200)
        elif r.status_code == 503:
            print(f"[CRM] ⚠️ VPS перезапускается")
            return "⌛ Сервис перезапускается. Попробуйте через 30 секунд."
        else:
            print(f"[CRM] ❌ VPS error: {r.status_code}")
            return f"❌ Ошибка VPS: {r.status_code}"
            
    except requests.exceptions.Timeout:
        print(f"[CRM] ⏱️ Timeout")
        return "⏱️ Превышено время ожидания. Попробуйте снова."
    except requests.exceptions.ConnectionError:
        print(f"[CRM] ❌ Нет соединения с VPS")
        return "❌ Нет соединения с сервером. Попробуйте позже."
    except Exception as e:
        print(f"[CRM ERROR] {e}")
        traceback.print_exc()
        return f"❌ Ошибка: {e}"

# ================== 3. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    """Обработчик очереди запросов"""
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(1.5, 2.0))
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

# ================== 4. ALLOWED USERS ==================
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

# ================== 5. ПОИСК ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
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
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
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
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code == 404:
        return "⚠️ Ничего не найдено."
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}"
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

# ================== 6. FLASK + СЕССИИ ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600

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

    if existing and (now - existing["created"]) < SESSION_TTL:
        print(f"[SESSION] ❌ Попытка перезапуска сессии {user_id}")
        return jsonify({"error": "Сессия уже активна. Повторите позже."}), 403

    if existing and (now - existing["created"]) >= SESSION_TTL:
        del active_sessions[user_id]
        print(f"[SESSION] ⏰ Истекшая сессия {user_id} удалена")

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
            return jsonify({"error": "Сессия недействительна."}), 403

        if time.time() - session["created"] > SESSION_TTL:
            del active_sessions[uid]
            print(f"[SESSION] ⏰ Истёк срок сессии {uid}")
            return jsonify({"error": "Сессия истекла."}), 403

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

@app.route('/api/vps-status', methods=['GET'])
def vps_status():
    """Проверить статус VPS"""
    try:
        r = requests.get(f"{VPS_URL}/health", timeout=5)
        return jsonify(r.json())
    except:
        return jsonify({"error": "VPS недоступен"}), 503

# ================== 7. ЗАПУСК ==================
print("=" * 60)
print("🚀 Запуск Render API Gateway")
print("=" * 60)

fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()

def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
            print(f"[SESSION] 🧹 Удалена сессия {uid}")
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

print(f"VPS URL: {VPS_URL}")
print("=" * 60)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
