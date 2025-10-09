# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify 
from flask_cors import CORS # 🟢 Импорт CORS из правильной библиотеки

# ================== НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================

# 🛑 1. ЗАМЕНИТЕ: Токен вашего рабочего бота
BOT_TOKEN = "7966914480:AAEeWXbLeIYjAMLKARCWzSJOKo9c_Cfyvhs" 

# 🛑 2. ЗАМЕНИТЕ: Список Telegram ID, которым разрешен доступ (целые числа!)
ALLOWED_USER_IDS = [
    969375371,
    778902346,
    5692415820,
    1051165772,
    1374645414,
    915023405,
    1159572989,
    6129246993,
    1494004945,
    5062899800,
    640600272,
    799169593,
    7177191221,
    773396054,
    5392431479,
    6019188001,
    6662359247,
    5384889579,
    790423584,
    1012749952,
    1405984544,
    5073747017,
    1040856818,
    802788440,
    7730012562,
    623627933,
    860652787,
    6225806713,
    2058683693,
    1968043148,
    6770261556,
    784180619,
    6928322497,
    7566232987,
    1254976460,
    1783416541,
    788502048,
    1484066710,
    752916915,
    1618757650,
    941927787,
    5564825444,
    5332940894,
    7784186014,
    956132738,
    1275124417,
    7751229349,
    1116448164,
    5783639759,
    5616228063,
    717172120,
    961667944,
    1104542943,
    879187758,
    8089488846,
    721855963,
    1023563267,
    5663889994,
    5992221182,
    1281366644,
    5563361241,
    530349287,
    7601771676,
    7901648220,
    6827356505,
    7690872970,
    348855434,
    508642392,
    2059557140,
    7626970568,
    1287418109,
    6437882820,
    1039340191,
    456063920,
    1631130991,
    1142989148,
    5526538305,
    1437036406,
    6504211516,
    907155592,
    849719603,
    2024736576,
    1311633918,
    6317696807,
    852843228,
    1518371259,
    8045255757,
    8269985775,
    5340526392,
    5760697026,
    7280521419,
    909136658,
    7160152249,
    1059890949,
    1051466704,
    6857567062,
    800054895,
    6187763017,
    852017170,
    7423097832,
    870812749,
    1103862186,
    8280428412,
    8402824170,
    7684479404,
    7609891732,
    7931611261,
    7731848116,
    8344948242,
    8151093154,
    468773255,
    8134736524,
    8357644245,
    7844018705,
    507216990,
    1860804604,
    8210066171,
    7360585112,
    7523001155,
    854447862,
    8068251450,
    5669547390,
    5725683353,
    7327085952,
]

BASE_URL = "https://crm431241.ru/api/v2/person-search/"
LOGIN_URL = "https://crm431241.ru/api/auth/login"
SECRET_TOKEN = "YOUR_SUPER_SECRET_TOKEN_12345" 

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

token_pool = []
token_cycle = None

# ================== ЛОГИКА CRM И ТОКЕНЫ ==================

def login_crm(username, password):
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
    global token_cycle, token_pool
    if not token_cycle:
        init_token_pool()

    if not token_pool:
        return "❌ Ошибка: Нет доступных токенов CRM."

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
                return crm_get(endpoint, params)
            else:
                print(f"[AUTH FAIL] {token['username']} не смог обновиться.")
    return r

# ================== ФУНКЦИИ ПОИСКА ==================

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

# 🟢 ИНИЦИАЛИЗАЦИЯ CORS: Разрешаем ВСЕ запросы со ВСЕХ источников
CORS(app, resources={r"/*": {"origins": "*"}}) 

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    
    # 🚨 БЛОК ПРОВЕРКИ АВТОРИЗАЦИИ ПО ID 🚨
    user_id = data.get('telegram_user_id')
    
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации: ID пользователя не найден."}), 403

    try:
        # Проверяем, есть ли ID в списке разрешенных
        if int(user_id) not in ALLOWED_USER_IDS:
            print(f"❌ Доступ запрещен для ID: {user_id}")
            return jsonify({"error": "У вас нет доступа к этому приложению."}), 403
    except ValueError:
        return jsonify({"error": "Неверный формат ID пользователя."}), 403
    # ---------------------------------------------
    
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
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400
        
    return jsonify({"result": reply})

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    print("🔐 Авторизация всех аккаунтов...")
    init_token_pool()
    print("🚀 API-сервер запущен на http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000)
