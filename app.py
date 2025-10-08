# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify

# ================== НАСТРОЙКИ (Ваши настройки) ==================
# BOT_TOKEN, USERS_FILE и прочие настройки, связанные с Telegram-ботом, 
# больше не используются в этом файле.
BASE_URL = "https://crm431241.ru/api/v2/person-search/"
LOGIN_URL = "https://crm431241.ru/api/auth/login"

# ================== АККАУНТЫ ==================
accounts = [
    {"username": "Brown1", "password": "48XQ48XQ"},
    {"username": "Brown2", "password": "16QU16QU"},
    {"username": "Brown3", "password": "39KU39KU"},
    {"username": "Brown4", "password": "77HW77HW"},
    {"username": "Brown5", "password": "38SK38SK"},
    {"username": "Brown6", "password": "17HV17HV"},
    {"username": "Brown7", "password": "37ML37ML"},
    {"username": "Brown8", "password": "32UV32UV"},
    {"username": "Brown9", "password": "55SG55SG"},
    {"username": "Brown10", "password": "77RE77RE"},
]

# Пул токенов: [{"username": ..., "access": ..., "csrf": ..., "time": ...}]
token_pool = []
token_cycle = None

# ================== CRM & ТОКЕНЫ (Ваша логика, адаптированная) ==================

def login_crm(username, password):
    # Логика логина остаётся без изменений
    try:
        r = requests.post(LOGIN_URL, json={
            "username": username,
            "password": password,
            "device_fingerprint": "web-client",
            "device_info": None,
            "remember_me": False
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            print(f"[LOGIN] {username} ✅")
            return {
                "username": username,
                "access": data["access_token"],
                "csrf": data["csrf_token"],
                "time": int(time.time())
            }
        else:
            print(f"[LOGIN FAIL] {username}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[LOGIN ERR] {username}: {e}")
    return None

def init_token_pool():
    global token_pool, token_cycle
    token_pool.clear()
    for acc in accounts:
        tok = login_crm(acc["username"], acc["password"])
        if tok:
            token_pool.append(tok)
    if not token_pool:
        print("❌ Нет активных токенов! Проверить логины/пароли.")
    else:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] Успешно загружено {len(token_pool)} токенов ✅")

def crm_get(endpoint, params=None):
    # Логика запроса и обновления токенов без изменений
    global token_cycle, token_pool
    if not token_cycle:
        init_token_pool()

    token = next(token_cycle)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cookie": (
            f"__Secure-access_token={token['access']}; "
            f"__Secure-csrf_token={token['csrf']};"
        ),
        "X-CSRF-Token": token["csrf"]
    }

    try:
        r = requests.get(endpoint, headers=headers, params=params, timeout=15)
    except Exception as e:
        return f"❌ Ошибка соединения: {e}"

    if r.status_code in (401, 403):
        # Логика перелогина
        print(f"[AUTH] {token['username']} → токен устарел, перелогин...")
        acc_info = next((acc for acc in accounts if acc["username"] == token["username"]), None)
        if acc_info:
            new_t = login_crm(acc_info["username"], acc_info["password"])
            if new_t:
                idx = next((i for i, t in enumerate(token_pool) if t["username"] == token["username"]), None)
                if idx is not None:
                    token_pool[idx] = new_t
                token_cycle = itertools.cycle(token_pool)
                print(f"[AUTH] {token['username']} обновлён ✅")
                # Повторяем запрос
                return crm_get(endpoint, params)
            else:
                print(f"[AUTH FAIL] {token['username']} не смог обновиться.")
    return r

# ================== ЛОГИКА ПОИСКА (Без изменений) ==================

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

@app.route('/api/search', methods=['POST'])
def api_search():
    # Mini App пришлёт данные в JSON-формате
    data = request.json
    query = data.get('query', '').strip()
    
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    # Определение типа запроса и вызов соответствующей функции
    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith("+") or query.startswith("8") or query.startswith("7"):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    # Mini App ожидает JSON-ответ
    if reply.startswith('❌') or reply.startswith('⚠️'):
         # Если ошибка, вернём её явно
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400
    
    return jsonify({"result": reply})

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    print("🔐 Авторизация всех аккаунтов...")
    init_token_pool()
    print("🚀 API-сервер запущен на http://0.0.0.0:5000")
    # ВАЖНО: При развертывании используйте Gunicorn или другой WSGI-сервер и HTTPS!
    app.run(host='0.0.0.0', port=5000)
