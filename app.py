# -*- coding: utf-8 -*-
import time
import json
import random
import itertools
import traceback
from threading import Thread, Lock
from typing import Dict, List, Optional
from queue import Queue
from urllib.parse import urlencode

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Page

# ================= НАСТРОЙКИ =================
BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_SELECTOR = 'button[type="submit"]'

ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = []

SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

# ================= АККАУНТЫ =================
accounts = [
    {"username": "from1", "password": "2255NNbb"},
    {"username": "from2", "password": "2244NNrr"},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
]

# ================= PLAYWRIGHT =================
_pw = None
_browser = None
PW_LOCK = Lock()

class PwSession:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.context = None
        self.page: Optional[Page] = None

pw_pool: List[PwSession] = []
pw_cycle = None

def pw_start():
    global _pw, _browser
    if _pw is None:
        _pw = sync_playwright().start()
    if _browser is None:
        _browser = _pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

def pw_login(acc) -> Optional[PwSession]:
    try:
        pw_start()
        s = PwSession(acc["username"], acc["password"])
        s.context = _browser.new_context(user_agent=random.choice(USER_AGENTS))
        s.page = s.context.new_page()

        s.page.goto(LOGIN_PAGE, timeout=60000)
        s.page.fill(LOGIN_SELECTOR, acc["username"])
        time.sleep(0.3)
        s.page.fill(PASSWORD_SELECTOR, acc["password"])
        time.sleep(0.3)
        s.page.click(SIGN_IN_SELECTOR)
        s.page.wait_for_timeout(1500)

        s.page.goto(f"{BASE_URL}/search", timeout=60000)
        print(f"[PLW] ✅ {acc['username']} logged in")
        return s
    except Exception as e:
        print(f"[PLW ERROR] {acc['username']}: {e}")
        traceback.print_exc()
        return None

def init_pw_pool():
    global pw_pool, pw_cycle
    with PW_LOCK:
        if pw_pool:
            return
        print("[PW] init pool")
        for acc in accounts:
            s = pw_login(acc)
            if s:
                pw_pool.append(s)
        pw_cycle = itertools.cycle(pw_pool)
        print(f"[PW] sessions ready: {len(pw_pool)}")

def get_pw() -> Optional[PwSession]:
    if not pw_pool:
        init_pw_pool()
    return next(pw_cycle) if pw_pool else None

def js_fetch(page: Page, url: str):
    script = """
    async (url) => {
        try {
            const r = await fetch(url, {credentials:'include'});
            return {status:r.status, text:await r.text()};
        } catch(e) {
            return {status:0, text:String(e)};
        }
    }
    """
    return page.evaluate(script, url)

def crm_get(endpoint, params=None):
    s = get_pw()
    if not s:
        return {"status":0,"text":"no session"}

    url = API_BASE + endpoint
    if params:
        url += "?" + urlencode(params)

    r = js_fetch(s.page, url)

    if r["status"] in (401,403) or "fingerprint" in r["text"].lower():
        print(f"[AUTH] relogin {s.username}")
        try:
            s.context.close()
        except:
            pass
        pw_pool.remove(s)
        ns = pw_login({"username": s.username, "password": s.password})
        if ns:
            pw_pool.append(ns)
            return js_fetch(ns.page, url)

    return r

# ================= QUEUE =================
crm_queue = Queue()
RESULT_TIMEOUT = 40

def worker():
    while True:
        func, args, box = crm_queue.get()
        try:
            box["result"] = func(*args)
        except Exception as e:
            box["error"] = str(e)
        crm_queue.task_done()

Thread(target=worker, daemon=True).start()

def enqueue(endpoint, params=None):
    box = {}
    crm_queue.put((crm_get, (endpoint, params), box))
    start = time.time()
    while True:
        if "result" in box:
            return box["result"]
        if "error" in box:
            return {"status":0,"text":box["error"]}
        if time.time() - start > RESULT_TIMEOUT:
            return {"status":0,"text":"timeout"}
        time.sleep(0.1)

# ================= ПОИСК =================
def parse_json(txt):
    try:
        return json.loads(txt)
    except:
        return None

def search_iin(iin):
    r = enqueue("/api/v2/person-search/by-iin", {"iin": iin})
    if r["status"] != 200:
        return f"❌ CRM {r['status']}"
    p = parse_json(r["text"]) or {}
    return (
        f"👤 {p.get('snf','')}\n"
        f"ИИН: {p.get('iin','')}\n"
        f"Телефон: {p.get('phone_number','')}\n"
        f"Адрес: {p.get('address','')}"
    )

def search_phone(phone):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = enqueue("/api/v2/person-search/by-phone", {"phone": clean})
    if r["status"] != 200:
        return f"❌ CRM {r['status']}"
    d = parse_json(r["text"])
    if not d:
        return "⚠️ Ничего не найдено"
    p = d[0] if isinstance(d,list) else d
    return f"{p.get('snf','')} | {p.get('iin','')}"

def search_fio(q):
    parts = q.split()
    params = {"limit":10,"smart_mode":"false"}
    if len(parts)>0: params["surname"]=parts[0]
    if len(parts)>1: params["name"]=parts[1]
    if len(parts)>2: params["father_name"]=parts[2]
    r = enqueue("/api/v2/person-search/smart", params)
    if r["status"] != 200:
        return f"❌ CRM {r['status']}"
    data = parse_json(r["text"]) or []
    if isinstance(data, dict): data=[data]
    return "\n".join([f"{i+1}. {p.get('snf','')} {p.get('iin','')}" for i,p in enumerate(data[:10])])

# ================= FLASK =================
app = Flask(__name__)
CORS(app)

active_sessions = {}
SESSION_TTL = 3600

@app.route("/api/session/start", methods=["POST"])
def start_session():
    uid = request.json.get("telegram_user_id")
    if int(uid) not in ALLOWED_USER_IDS:
        return jsonify({"error":"no access"}),403
    token = f"{uid}-{int(time.time())}"
    active_sessions[uid] = {"token":token,"time":time.time()}
    return jsonify({"session_token":token})

@app.route("/api/search", methods=["POST"])
def api_search():
    d = request.json
    uid = d.get("telegram_user_id")
    if uid not in active_sessions:
        return jsonify({"error":"no session"}),403

    q = d.get("query","").strip()
    if q.isdigit() and len(q)==12:
        return jsonify({"result": search_iin(q)})
    if q.startswith(("+","7","8")):
        return jsonify({"result": search_phone(q)})
    return jsonify({"result": search_fio(q)})

@app.route("/api/queue-size")
def queue_size():
    return jsonify({"queue_size": crm_queue.qsize()})

@app.route("/api/refresh-users", methods=["POST"])
def refresh_users():
    if request.headers.get("Authorization") != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error":"forbidden"}),403
    fetch_allowed()
    return jsonify({"ok":True})

# ================= INIT =================
def fetch_allowed():
    global ALLOWED_USER_IDS
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        ALLOWED_USER_IDS = r.json().get("allowed_users",[])
        print(f"[AUTH] allowed users: {len(ALLOWED_USER_IDS)}")
    except Exception as e:
        print("[AUTH ERROR]", e)

fetch_allowed()
Thread(target=init_pw_pool, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
