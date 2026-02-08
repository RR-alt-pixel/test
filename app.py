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
from urllib.parse import urlencode

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

TOKENS_FILE = "tokens.json"   # оставляем, но ниже сохраняем только сериализуемые метаданные
TOKENS_LOCK = Lock()

# ================== 2. АККАУНТЫ ==================
accounts = [
  {"username": "klon9", "password": "7755SSaa"},
]

# ================== 3. ПУЛ PLAYWRIGHT СЕССИЙ ==================
pw_sessions: List[Dict] = []          # живые браузерные сессии (browser/context/page)
pw_cycle = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Playwright должен жить постоянно (иначе fingerprint/сессия умрут)
_PW = None
_PW_LOCK = Lock()

class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data

def _ensure_playwright_started():
    global _PW
    with _PW_LOCK:
        if _PW is None:
            _PW = sync_playwright().start()
            print("[PW] ✅ Playwright started")

# ================== 3.1 TOKENS FILE (оставляем) ==================
def load_tokens_from_file() -> List[Dict]:
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    print(f"[TOKENS] 🔁 Загружено {len(data)} записей (метаданные).")
                    return data
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
        traceback.print_exc()
    return []

def save_tokens_to_file():
    try:
        with TOKENS_LOCK:
            tmp = TOKENS_FILE + ".tmp"
            meta = []
            for s in pw_sessions:
                meta.append({
                    "username": s.get("username"),
                    "user_agent": s.get("user_agent"),
                    "csrf_token": s.get("csrf_token"),
                    "cookie_header": s.get("cookie_header"),
                    "time": s.get("time"),
                })
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)
            print(f"[TOKENS] 💾 Сохранено {len(meta)} записей (метаданные).")
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
        traceback.print_exc()

# ================== 4. PLAYWRIGHT LOGIN (ЖИВАЯ СЕССИЯ) ==================
def login_crm_playwright(username: str, password: str, show_browser: bool = False) -> Optional[Dict]:
    _ensure_playwright_started()
    browser = None
    try:
        print(f"[PLW] 🔵 Вход под {username}...")
        browser = _PW.chromium.launch(
            headless=not show_browser,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            timeout=60000
        )
        ua = random.choice(USER_AGENTS)
        context = browser.new_context(user_agent=ua)
        page: Page = context.new_page()

        page.goto(LOGIN_PAGE, wait_until="load", timeout=30000)
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.4)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.4)
        page.click(SIGN_IN_BUTTON_SELECTOR)
        page.wait_for_timeout(2000)

        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        csrf = next((c["value"] for c in cookies if c["name"] == "csrf_token"), "")
        user_agent = page.evaluate("() => navigator.userAgent")

        if cookie_header:
            sess = {
                "username": username,
                "password": password,      # чтобы refresh работал без поиска в accounts
                "browser": browser,
                "context": context,
                "page": page,
                "cookie_header": cookie_header,
                "csrf_token": csrf,
                "user_agent": user_agent or ua,
                "time": int(time.time())
            }
            print(f"[PLW] ✅ {username} авторизован.")
            return sess

        # если куки не получили — закрываем
        try:
            browser.close()
        except Exception:
            pass
        return None

    except Exception as e:
        print(f"[PLW ERROR] {username}: {e}")
        traceback.print_exc()
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        return None

# ================== 5. ПУЛ СЕССИЙ ИНИЦИАЛИЗАЦИЯ ==================
def init_token_pool_playwright(show_browser: bool = False):
    global pw_sessions, pw_cycle
    _ensure_playwright_started()

    # файл читаем, но реальная защита теперь держится на живых pages,
    # поэтому всегда поднимаем pw_sessions (иначе fingerprint не будет).
    load_tokens_from_file()

    print("[POOL] 🔄 Логин через Playwright (живые сессии)...")
    pw_sessions = []
    for acc in accounts:
        tok = login_crm_playwright(acc["username"], acc["password"], show_browser=show_browser)
        if tok:
            pw_sessions.append(tok)

    if pw_sessions:
        pw_cycle = itertools.cycle(pw_sessions)
        save_tokens_to_file()
        print(f"[POOL] ✅ Загружено {len(pw_sessions)} сессий.")
        print(f"[PW] sessions ready: {len(pw_sessions)}")
    else:
        pw_cycle = None
        print("[POOL] ❌ Пустой пул сессий.")

# ================== 6. SESSION GETTER ==================
def get_next_session() -> Optional[Dict]:
    global pw_sessions, pw_cycle
    if not pw_sessions:
        init_token_pool_playwright()
        if not pw_sessions:
            return None
    if pw_cycle is None:
        pw_cycle = itertools.cycle(pw_sessions)
    try:
        s = next(pw_cycle)
        print(f"[POOL] 🔁 Используется сессия {s['username']}")
        return s
    except StopIteration:
        pw_cycle = itertools.cycle(pw_sessions)
        s = next(pw_cycle)
        print(f"[POOL] ♻️ Перезапуск цикла, выбран {s['username']}")
        return s

# ================== 7. REFRESH СЕССИИ ==================
def refresh_token_for_username(username: str) -> Optional[Dict]:
    global pw_sessions, pw_cycle
    try:
        # находим старую сессию
        old = None
        for s in pw_sessions:
            if s.get("username") == username:
                old = s
                break

        if not old:
            # если не нашли — ищем в accounts
            acc = next(a for a in accounts if a["username"] == username)
            new_sess = login_crm_playwright(acc["username"], acc["password"])
        else:
            new_sess = login_crm_playwright(old["username"], old["password"])

        if new_sess:
            # закрываем старую
            if old:
                try:
                    old["browser"].close()
                except Exception:
                    pass

            # заменяем/добавляем
            for i, s in enumerate(pw_sessions):
                if s.get("username") == username:
                    pw_sessions[i] = new_sess
                    break
            else:
                pw_sessions.append(new_sess)

            pw_cycle = itertools.cycle(pw_sessions)
            save_tokens_to_file()
            print(f"[AUTH] 🔁 {username} session refreshed.")
            return new_sess

    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        traceback.print_exc()
    return None

# ================== 7.1 FETCH ВНУТРИ PLAYWRIGHT PAGE ==================
def _build_url(endpoint: str, params: dict = None) -> str:
    # endpoint может быть "/api/..." или "https://..."
    if endpoint.startswith("http"):
        url = endpoint
    else:
        url = API_BASE + endpoint

    if params:
        qs = urlencode(params, doseq=True)
        if "?" in url:
            url = url + "&" + qs
        else:
            url = url + "?" + qs
    return url

def crm_get(endpoint: str, params: dict = None):
    sess = get_next_session()
    if not sess:
        return "❌ Нет сессий Playwright."

    page: Page = sess["page"]
    url = _build_url(endpoint, params=params)

    # fetch делаем внутри браузера, чтобы прошёл device fingerprint
    js = """
    async (url) => {
      try {
        const r = await fetch(url, { method: "GET", credentials: "include" });
        const txt = await r.text();
        let jsn = null;
        try { jsn = JSON.parse(txt); } catch (e) {}
        return { ok: r.ok, status: r.status, text: txt, json: jsn };
      } catch (e) {
        return { ok: false, status: 0, text: String(e), json: null, error: String(e) };
      }
    }
    """

    try:
        out = page.evaluate(js, url)

        status = int(out.get("status", 0) or 0)
        txt = out.get("text", "") or ""
        jsn = out.get("json", None)

        # если 401/403 — пробуем refresh и повтор 1 раз
        if status in (401, 403):
            uname = sess["username"]
            print(f"[AUTH] {uname} → 401/403 → обновляем сессию")
            new_sess = refresh_token_for_username(uname)
            if new_sess:
                page2: Page = new_sess["page"]
                out = page2.evaluate(js, url)
                status = int(out.get("status", 0) or 0)
                txt = out.get("text", "") or ""
                jsn = out.get("json", None)

        return ResponseLike(status_code=status, text=txt, json_data=jsn)

    except Exception as e:
        return f"❌ Ошибка CRM(fetch): {e}"

# ================== 8. ОЧЕРЕДЬ CRM ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(1.7, 2.0))
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
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

# ================== 9. ALLOWED USERS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ids = [int(i) for i in data.get("allowed_users", [])]
            if ids:
                ALLOWED_USER_IDS = ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH] ✅ {len(ALLOWED_USER_IDS)} пользователей разрешено.")
    except Exception as e:
        print(f"[AUTH ERROR] {e}")

def periodic_fetch():
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 10. ПОИСК ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v3/search/iin", params={"iin": iin})
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

    data = resp.json()
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено по ИИН."
    p = data[0]

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

    r = enqueue_crm_get("/api/v3/search/phone", params={"phone": clean, "limit": 100})
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
    if not isinstance(data, list) or not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0]

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
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "true", "limit": 100}
        # в таком режиме фамилия не используется (как у тебя было в v2 логике)
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "true", "limit": 100}

    r = enqueue_crm_get("/api/v3/search/fio", params=q)
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
    if not isinstance(data, list) or not data:
        return "⚠️ Ничего не найдено."

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
    return "⚠️ Поиск по адресу на pena.rest (v3) не настроен. Скинь запрос из Network — добавлю."

# ================== 11. FLASK + СЕССИИ ==================
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

    if existing and (now - existing["created"]) < SESSION_TTL:
        print(f"[SESSION] ❌ Попытка перезапуска сессии {user_id}, отклонено.")
        return jsonify({"error": "Сессия уже активна. Повторите позже."}), 403

    if existing and (now - existing["created"]) >= SESSION_TTL:
        del active_sessions[user_id]
        print(f"[SESSION] ⏰ Истекшая сессия {user_id} удалена")

    session_token = f"{user_id}-{int(now)}-{random.randint(1000,9999)}"
    active_sessions[user_id] = {
        "token": session_token,
        "created": now
    }

    print(f"[SESSION] 🔑 Активирована новая сессия для {user_id}")
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
            print(f"[SESSION] ⏰ Истек срок действия сессии {uid}")
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

# ================== 12. ЗАПУСК ==================
print("🚀 Запуск API с очередью запросов...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()
Thread(target=init_token_pool_playwright, daemon=True).start()

def cleanup_sessions():
    while True:
        now = time.time()
        expired = [uid for uid, s in active_sessions.items() if now - s["created"] > SESSION_TTL]
        for uid in expired:
            del active_sessions[uid]
            print(f"[SESSION] 🧹 Удалена просроченная сессия {uid}")
        time.sleep(300)

Thread(target=cleanup_sessions, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
