# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List, Any
from queue import Queue
from urllib.parse import urlencode

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page

# ================== 1. НАСТРОЙКИ ==================
# BOT_TOKEN тут не используется (это API-сервер), оставил как у тебя.
BOT_TOKEN = "PASTE_YOUR_TOKEN_HERE"

ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL

SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

TOKENS_FILE = "tokens.json"
TOKENS_LOCK = Lock()

# ================== 2. АККАУНТЫ ==================
# ВАЖНО: вставь сюда свои реальные логины/пароли
accounts = [
    {"username": "from1", "password": "2255NNbb"},
    {"username": "from2", "password": "2244NNrr"},
]

# ================== 3. ПУЛ ТОКЕНОВ (оставил, но requests больше не используется) ==================
token_pool: List[Dict] = []
token_cycle = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

def load_tokens_from_file() -> List[Dict]:
    global token_pool, token_cycle
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    token_pool = data
                    token_cycle = itertools.cycle(token_pool) if token_pool else None
                    print(f"[TOKENS] 🔁 Загружено {len(token_pool)} токенов.")
                    return token_pool
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
        traceback.print_exc()
    token_pool = []
    token_cycle = None
    return []

def save_tokens_to_file():
    global token_pool
    try:
        with TOKENS_LOCK:
            tmp = TOKENS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(token_pool, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)
            print(f"[TOKENS] 💾 Сохранено {len(token_pool)} токенов.")
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
        traceback.print_exc()

# ================== 4. PLAYWRIGHT LOGIN (оставил, но основной трафик теперь тоже через Playwright) ==================
def login_crm_playwright(username: str, password: str, p, show_browser: bool = False) -> Optional[Dict]:
    browser = None
    try:
        print(f"[PLW] 🔵 Вход под {username}...")
        browser = p.chromium.launch(
            headless=not show_browser,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            timeout=60000
        )
        context = browser.new_context(user_agent=random.choice(USER_AGENTS))
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
        user_agent = page.evaluate("() => navigator.userAgent")

        if cookie_header:
            token = {
                "username": username,
                "cookie_header": cookie_header,
                "user_agent": user_agent,
                "time": int(time.time())
            }
            print(f"[PLW] ✅ {username} авторизован.")
            return token
        return None
    except Exception as e:
        print(f"[PLW ERROR] {username}: {e}")
        return None
    finally:
        if browser:
            browser.close()

# ================== 5. PLAYWRIGHT ПУЛ (главное изменение: CRM-запросы тоже через браузер) ==================
PLAYWRIGHT_LOCK = Lock()

_pw = None
_browser = None

class PwSession:
    def __init__(self, username: str, password: str, user_agent: str):
        self.username = username
        self.password = password
        self.user_agent = user_agent
        self.context = None
        self.page: Optional[Page] = None
        self.last_login = 0

pw_pool: List[PwSession] = []
pw_cycle = None

def _pw_start():
    global _pw, _browser
    if _pw is None:
        _pw = sync_playwright().start()
    if _browser is None:
        _browser = _pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            timeout=60000
        )

def _pw_stop():
    global _pw, _browser
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _browser = None
    _pw = None

def _pw_make_session(acc: Dict[str, str]) -> PwSession:
    _pw_start()
    ua = random.choice(USER_AGENTS)
    s = PwSession(acc["username"], acc["password"], ua)
    s.context = _browser.new_context(user_agent=ua)
    s.page = s.context.new_page()
    return s

def _pw_login_session(s: PwSession) -> bool:
    try:
        assert s.page is not None
        s.page.goto(LOGIN_PAGE, wait_until="load", timeout=45000)
        s.page.fill(LOGIN_SELECTOR, s.username)
        time.sleep(0.25)
        s.page.fill(PASSWORD_SELECTOR, s.password)
        time.sleep(0.25)
        s.page.click(SIGN_IN_BUTTON_SELECTOR)
        s.page.wait_for_timeout(1500)

        # важно: после логина остаёмся в домене, чтобы fetch работал в том же origin
        s.page.goto(f"{BASE_URL}/search", wait_until="load", timeout=45000)
        s.last_login = int(time.time())
        print(f"[PLW] ✅ {s.username} logged in (persistent).")
        return True
    except Exception as e:
        print(f"[PLW LOGIN ERROR] {s.username}: {e}")
        traceback.print_exc()
        return False

def init_pw_pool():
    global pw_pool, pw_cycle
    with PLAYWRIGHT_LOCK:
        if pw_pool:
            pw_cycle = itertools.cycle(pw_pool)
            print(f"[PW POOL] 🟢 Уже инициализировано {len(pw_pool)} сессий.")
            return

        print("[PW POOL] 🔄 Инициализация Playwright-сессий...")
        pw_pool = []
        try:
            for acc in accounts:
                s = _pw_make_session(acc)
                ok = _pw_login_session(s)
                if ok:
                    pw_pool.append(s)
                else:
                    try:
                        if s.context:
                            s.context.close()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[PW POOL ERROR] {e}")
            traceback.print_exc()

        pw_cycle = itertools.cycle(pw_pool) if pw_pool else None
        print(f"[PW POOL] ✅ Готово. Сессий: {len(pw_pool)}")

def get_next_pw_session() -> Optional[PwSession]:
    global pw_cycle
    if not pw_pool:
        init_pw_pool()
    if not pw_pool:
        return None
    if pw_cycle is None:
        pw_cycle = itertools.cycle(pw_pool)
    return next(pw_cycle)

def relogin_pw_session(username: str) -> Optional[PwSession]:
    global pw_pool, pw_cycle
    with PLAYWRIGHT_LOCK:
        try:
            idx = None
            for i, s in enumerate(pw_pool):
                if s.username == username:
                    idx = i
                    break

            # закрываем старый
            if idx is not None:
                old = pw_pool[idx]
                try:
                    if old.context:
                        old.context.close()
                except Exception:
                    pass
                del pw_pool[idx]

            # создаём новый
            acc = next(a for a in accounts if a["username"] == username)
            s = _pw_make_session(acc)
            ok = _pw_login_session(s)
            if ok:
                pw_pool.append(s)
                pw_cycle = itertools.cycle(pw_pool)
                print(f"[PW POOL] 🔁 {username} relogin ok.")
                return s
            else:
                try:
                    if s.context:
                        s.context.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[PW RELOGIN ERROR] {username}: {e}")
            traceback.print_exc()

        pw_cycle = itertools.cycle(pw_pool) if pw_pool else None
        return None

def _js_fetch(page: Page, url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    # Выполняем fetch внутри браузера: это и есть обход "Device fingerprint required".
    script = """
    async ({ url, headers }) => {
      try {
        const r = await fetch(url, { method: "GET", headers, credentials: "include" });
        const text = await r.text();
        return { ok: true, status: r.status, text };
      } catch (e) {
        return { ok: false, status: 0, text: String(e) };
      }
    }
    """
    return page.evaluate(script, {"url": url, "headers": headers})

def crm_get_playwright(endpoint: str, params: dict = None) -> Dict[str, Any]:
    s = get_next_pw_session()
    if not s or not s.page:
        return {"ok": False, "status": 0, "text": "❌ Нет Playwright-сессий."}

    # URL
    url = endpoint if endpoint.startswith("http") else (API_BASE + endpoint)
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params, doseq=True)

    # Referer (как у тебя было)
    if "/by-address" in endpoint:
        referer = f"{BASE_URL}/person-search"
    else:
        referer = f"{BASE_URL}/search"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    }

    # пробуем 1 раз
    r1 = _js_fetch(s.page, url, headers)

    # если 401/403 или fingerprint — перелогин и второй заход
    need_reauth = False
    if not r1.get("ok"):
        need_reauth = True
    else:
        st = int(r1.get("status") or 0)
        txt = (r1.get("text") or "")
        if st in (401, 403):
            need_reauth = True
        if "Device fingerprint" in txt or "device fingerprint" in txt:
            need_reauth = True

    if need_reauth:
        print(f"[AUTH] {s.username} → reauth (status={r1.get('status')})")
        new_s = relogin_pw_session(s.username)
        if not new_s or not new_s.page:
            return {"ok": False, "status": 0, "text": "❌ Reauth failed."}
        r2 = _js_fetch(new_s.page, url, headers)
        return r2

    return r1

# ================== 8. ОЧЕРЕДЬ CRM (оставил твою логику) ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    while True:
        try:
            func, args, kwargs, result_box = crm_queue.get()
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(random.uniform(0.9, 1.2))
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
    result_box = {}
    crm_queue.put((crm_get_playwright, (endpoint,), {"params": params}, result_box))
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

# ================== 10. ПОИСК (адаптировал под новый формат ответа) ==================
def _parse_json_text(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None

def search_by_iin(iin: str):
    q = {"iin": iin}
    r = enqueue_crm_get("/api/v2/person-search/by-iin", params=q)
    if r["status"] != "ok":
        return "⌛ Ваш запрос в очереди."
    resp = r["result"]  # dict {ok,status,text}
    if not resp.get("ok"):
        return f"❌ Ошибка CRM: {resp.get('text')}"
    status = int(resp.get("status") or 0)
    text = resp.get("text") or ""

    if status == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if status != 200:
        return f"❌ Ошибка {status}: {text}"

    p = _parse_json_text(text) or {}
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
    if not resp.get("ok"):
        return f"❌ Ошибка CRM: {resp.get('text')}"
    status = int(resp.get("status") or 0)
    text = resp.get("text") or ""

    if status == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if status != 200:
        return f"❌ Ошибка {status}: {text}"

    data = _parse_json_text(text)
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
    if not resp.get("ok"):
        return f"❌ Ошибка CRM: {resp.get('text')}"
    status = int(resp.get("status") or 0)
    body = resp.get("text") or ""

    if status == 404:
        return "⚠️ Ничего не найдено."
    if status != 200:
        return f"❌ Ошибка {status}: {body}"

    data = _parse_json_text(body)
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
    if not resp.get("ok"):
        return f"❌ Ошибка CRM: {resp.get('text')}"
    status = int(resp.get("status") or 0)
    body = resp.get("text") or ""
    if status != 200:
        return f"❌ Ошибка {status}: {body}"

    data = _parse_json_text(body)
    if isinstance(data, dict):
        data = [data]
    results = []
    for i, p in enumerate((data or [])[:10], start=1):
        results.append(f"{i}. {p.get('snf','')} — {p.get('address','')}")
    return "\n".join(results) if results else "⚠️ Ничего не найдено."

# ================== 11. FLASK + СЕССИИ ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

active_sessions: Dict[int, Dict[str, float]] = {}
SESSION_TTL = 3600  # 1 час

@app.route('/api/session/start', methods=['POST'])
def start_session():
    data = request.json or {}
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
    active_sessions[user_id] = {"token": session_token, "created": now}

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
    data = request.json or {}
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации."}), 403
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа."}), 403

    query = (data.get('query') or '').strip()
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
Thread(target=init_pw_pool, daemon=True).start()

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
