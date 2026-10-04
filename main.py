# -*- coding: utf-8 -*-
"""
⚡ TikTok Spark v21.0
Registration + Guide Images + Auto-Farming + Orders
"""
import os, sys, json, time, uuid, random, string, sqlite3, hashlib, hmac
import threading, asyncio, logging, traceback
from datetime import datetime, timedelta
from functools import wraps

import requests
from flask import (Flask, request, session, redirect, url_for, flash,
                   get_flashed_messages, jsonify, send_file)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters, ContextTypes)

# ═══════════════════════════════════════════════════════════
#                    ⚙️ الإعدادات
# ═══════════════════════════════════════════════════════════
BOT_TOKEN        = "8793761912:AAGmy2ciz7_PKIQ42sLKByJ_kf-1_0_p6n8"
ADMIN_CHAT_ID    = 8305189242
SECRET_KEY       = "tikspark-v210-CHANGE-ME"
DB_PATH          = "spark.db"
WEB_PORT         = 5000

VIP_CONTACT      = "@kJkJKa"
VIP_CONTACT_LINK = "https://t.me/kJkJKa"
APP_DOWNLOAD_LINK = "https://play.google.com/store/apps/details?id=com.dev.vidspark"

# ═══════════ صور الشرح (من السورس الأصلي) ═══════════
GUIDE_IMAGES = {
    "step1": "https://j.top4top.io/p_3908ephlc0.jpg",
    "step2": "https://g.top4top.io/p_3908gsmex0.jpg",
    "step3": "https://b.top4top.io/p_3908cpfmg3.jpg",
}

FREE_HOURS       = 24
COOLDOWN_HOURS   = 5
VIEWS_MAX_USES   = 2

FREE_LIMITS = {"followers": (1, 20), "likes": (1, 20),
               "comments": (1, 20), "views": (1, 500)}
VIP_LIMITS  = {"followers": (20, 100000), "likes": (20, 100000),
               "comments": (20, 100000), "views": (100, 1000000)}

FREE_BLAST_MAX_ACTIVE = 1
FREE_BLAST_MIN_HOURS  = 5
VIP_BLAST_MAX_ACTIVE  = 99
VIP_BLAST_MIN_HOURS   = 1

SERVICE_PRICES = {"followers": 5, "likes": 4, "views": 1, "comments": 5}
SVC_NAMES = {"followers":"متابعين","likes":"لايكات","views":"مشاهدات","comments":"تعليقات"}
SVC_EMO   = {"followers":"👥","likes":"❤️","views":"👁️","comments":"💬"}
SVC_TGT   = {"followers":"اسم المستخدم","likes":"رابط الفيديو",
             "views":"رابط الفيديو","comments":"رابط الفيديو"}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("spark")

# ═══════════════════════════════════════════════════════════
#                    💾 DB
# ═══════════════════════════════════════════════════════════
DB_LOCK = threading.RLock()

def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    c.row_factory = sqlite3.Row
    return c

def db(query, params=(), fetch=False):
    with DB_LOCK:
        c = _conn()
        try:
            cur = c.execute(query, params)
            c.commit()
            if fetch: return [dict(r) for r in cur.fetchall()]
            return cur.lastrowid
        except Exception as e:
            log.error(f"DB: {e}"); raise
        finally: c.close()

def db_one(q, p=()):
    r = db(q, p, True); return r[0] if r else None

def _hash(s): return hashlib.sha256(s.encode()).hexdigest()

SCHEMAS = {
    "users": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "username": "TEXT UNIQUE",
        "password": "TEXT",
        "status": "TEXT DEFAULT 'free'",
        "free_expires": "TEXT",
        "vip_expires": "TEXT",
        "vip_plan": "TEXT",
        "last_use": "TEXT",
        "views_used": "INTEGER DEFAULT 0",
        "total_uses": "INTEGER DEFAULT 0",
        "tiktok_username": "TEXT",
        "auto_farm": "INTEGER DEFAULT 0",
        "created_at": "TEXT",
        "last_seen": "TEXT",
    },
    "pool": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "username": "TEXT",
        "password": "TEXT",
        "owner_id": "INTEGER DEFAULT 0",
        "owner_type": "TEXT DEFAULT 'admin'",
        "token": "TEXT", "csrf": "TEXT",
        "points": "INTEGER DEFAULT 0",
        "status": "TEXT DEFAULT 'active'",
        "last_login": "TEXT", "created_at": "TEXT",
    },
    "plans": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "name": "TEXT", "duration_days": "INTEGER", "price": "TEXT",
    },
    "orders": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "user_id": "INTEGER",
        "service": "TEXT", "target": "TEXT", "amount": "INTEGER",
        "status": "TEXT DEFAULT 'pending'",
        "api_order_id": "TEXT", "pool_account_id": "INTEGER",
        "source": "TEXT DEFAULT 'service'",
        "created_at": "TEXT",
    },
    "blasts": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "task_id": "TEXT UNIQUE", "user_id": "INTEGER",
        "service": "TEXT", "target": "TEXT", "amount": "INTEGER", "hours": "INTEGER",
        "status": "TEXT DEFAULT 'active'",
        "run_count": "INTEGER DEFAULT 0", "next_run": "TEXT", "created_at": "TEXT",
    },
    "messages": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "user_id": "INTEGER", "code": "TEXT",
        "from_admin": "INTEGER DEFAULT 0",
        "text": "TEXT", "is_read": "INTEGER DEFAULT 0", "created_at": "TEXT",
    },
    "tickets": {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "user_id": "INTEGER", "code": "TEXT", "message": "TEXT",
        "status": "TEXT DEFAULT 'open'", "created_at": "TEXT",
    },
}

def _existing_cols(c, table):
    try: return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    except: return set()

def _ensure_schema():
    c = _conn()
    try:
        for table, schema in SCHEMAS.items():
            needed = set(schema.keys())
            existing = _existing_cols(c, table)
            if not existing:
                cols_sql = ", ".join(f"{col} {dfn}" for col, dfn in schema.items())
                c.execute(f"CREATE TABLE {table} ({cols_sql})")
                log.info(f"✅ Created '{table}'")
                continue
            missing = needed - existing
            if missing:
                log.warning(f"⚠️ '{table}' missing: {missing}")
                try:
                    for col in missing:
                        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {schema[col]}")
                    log.info(f"✅ Added columns to '{table}'")
                except Exception as e:
                    log.error(f"ALTER failed: {e}")
        c.commit()
    finally:
        c.close()

def init_db():
    with DB_LOCK:
        _ensure_schema()
        log.info("💾 DB ready")

# ═══════════════ USERS (تسجيل المستخدمين) ═══════════════
def user_create(u, p):
    try:
        uid = db("INSERT INTO users(username,password,status,created_at) VALUES(?,?,?,?)",
                 (u, _hash(p), "free", datetime.now().isoformat()))
        # تجربة مجانية 24 ساعة تلقائية
        exp = (datetime.now() + timedelta(hours=FREE_HOURS)).isoformat()
        db("UPDATE users SET free_expires=? WHERE id=?", (exp, uid))
        return uid
    except sqlite3.IntegrityError: return None
def user_auth(u, p):
    return db_one("SELECT * FROM users WHERE username=? AND password=?", (u, _hash(p)))
def user_get(uid):
    try: return db_one("SELECT * FROM users WHERE id=?", (uid,))
    except: return None
def user_by_name(u):
    try: return db_one("SELECT * FROM users WHERE username=?", (u,))
    except: return None
def user_all():
    try: return db("SELECT * FROM users ORDER BY id DESC", fetch=True)
    except: return []
def user_upd(uid, **f):
    if not f: return
    k = ", ".join(f"{x}=?" for x in f)
    try: db(f"UPDATE users SET {k} WHERE id=?", list(f.values())+[uid])
    except: pass
def user_del(uid):
    try: db("DELETE FROM users WHERE id=?", (uid,))
    except: pass

def user_status(u):
    if not u: return "unknown"
    if u.get("status") == "banned": return "banned"
    now = datetime.now()
    for key, st in (("vip_expires","vip"), ("free_expires","free")):
        val = u.get(key)
        if val:
            try:
                if datetime.fromisoformat(val) > now: return st
            except: pass
    return "expired"

def user_activate_free(uid):
    exp = (datetime.now() + timedelta(hours=FREE_HOURS)).isoformat()
    user_upd(uid, status="free", free_expires=exp, vip_expires=None, vip_plan=None,
             last_use=None, views_used=0, total_uses=0)

def user_activate_vip(uid, days, plan):
    exp = (datetime.now() + timedelta(days=days)).isoformat()
    user_upd(uid, status="vip", vip_expires=exp, vip_plan=plan, last_use=None)

def user_ban(uid, b=True):
    user_upd(uid, status="banned" if b else "free")

def cooldown_left(u):
    if user_status(u) != "free": return 0
    if not u or not u.get("last_use"): return 0
    try:
        last = datetime.fromisoformat(u["last_use"])
        diff = (last + timedelta(hours=COOLDOWN_HOURS) - datetime.now()).total_seconds()
        return max(0, int(diff))
    except: return 0

def can_use_free_views(u):
    return (u.get("views_used") or 0) < VIEWS_MAX_USES

# ═══════════════ POOL ═══════════════
def pool_add(u, p, owner_id=0, owner_type="admin"):
    return db("INSERT INTO pool(username,password,owner_id,owner_type,created_at) VALUES(?,?,?,?,?)",
              (u, p, owner_id, owner_type, datetime.now().isoformat()))
def pool_all():
    try: return db("SELECT * FROM pool ORDER BY id ASC", fetch=True)
    except: return []
def pool_by_owner(owner_id):
    try: return db("SELECT * FROM pool WHERE owner_id=?", (owner_id,), fetch=True)
    except: return []
def pool_get(aid):
    try: return db_one("SELECT * FROM pool WHERE id=?", (aid,))
    except: return None
def pool_del(aid):
    try: db("DELETE FROM pool WHERE id=?", (aid,))
    except: pass
def pool_upd(aid, **f):
    if not f: return
    k = ", ".join(f"{x}=?" for x in f)
    try: db(f"UPDATE pool SET {k} WHERE id=?", list(f.values())+[aid])
    except: pass

# ═══════════════ PLANS ═══════════════
def plan_add(n, d, p): db("INSERT INTO plans(name,duration_days,price) VALUES(?,?,?)", (n, d, p))
def plan_all():
    try: return db("SELECT * FROM plans ORDER BY id DESC", fetch=True)
    except: return []
def plan_del(pid):
    try: db("DELETE FROM plans WHERE id=?", (pid,))
    except: pass

# ═══════════════ ORDERS ═══════════════
def order_add(uid, svc, target, amount, api_id=None, pool_id=None, status="pending", source="service"):
    return db("INSERT INTO orders(user_id,service,target,amount,api_order_id,pool_account_id,status,source,created_at) "
              "VALUES(?,?,?,?,?,?,?,?,?)",
              (uid, svc, target, amount, api_id, pool_id, status, source, datetime.now().isoformat()))
def order_all(uid=None, limit=100):
    try:
        if uid:
            return db("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit), fetch=True)
        return db("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,), fetch=True)
    except: return []

# ═══════════════ BLASTS ═══════════════
def blast_add(tid, uid, svc, target, amount, hours):
    db("INSERT INTO blasts(task_id,user_id,service,target,amount,hours,created_at) VALUES(?,?,?,?,?,?,?)",
       (tid, uid, svc, target, amount, hours, datetime.now().isoformat()))
def blast_all(uid=None, status=None):
    try:
        q, p, c = "SELECT * FROM blasts", [], []
        if uid: c.append("user_id=?"); p.append(uid)
        if status: c.append("status=?"); p.append(status)
        if c: q += " WHERE " + " AND ".join(c)
        q += " ORDER BY id DESC"
        return db(q, p, fetch=True)
    except: return []
def blast_get(tid):
    try: return db_one("SELECT * FROM blasts WHERE task_id=?", (tid,))
    except: return None
def blast_stop(tid):
    try: db("UPDATE blasts SET status='stopped' WHERE task_id=?", (tid,))
    except: pass
def blast_del(tid):
    try: db("DELETE FROM blasts WHERE task_id=?", (tid,))
    except: pass
def blast_inc(tid, nxt=None):
    try: db("UPDATE blasts SET run_count=run_count+1, next_run=? WHERE task_id=?", (nxt, tid))
    except: pass

# ═══════════════ MESSAGES / TICKETS ═══════════════
def msg_add(uid, code, text, from_admin=False):
    db("INSERT INTO messages(user_id,code,text,from_admin,created_at) VALUES(?,?,?,?,?)",
       (uid, code, text, 1 if from_admin else 0, datetime.now().isoformat()))
def msg_all_for(uid, limit=50):
    try: return db("SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit), fetch=True)
    except: return []
def msg_unread(uid):
    try:
        r = db_one("SELECT COUNT(*) as c FROM messages WHERE user_id=? AND from_admin=1 AND is_read=0", (uid,))
        return r["c"] if r else 0
    except: return 0
def msg_mark_read(uid):
    try: db("UPDATE messages SET is_read=1 WHERE user_id=? AND from_admin=1", (uid,))
    except: pass
def ticket_add(uid, code, msg):
    return db("INSERT INTO tickets(user_id,code,message,created_at) VALUES(?,?,?,?)",
              (uid, code, msg, datetime.now().isoformat()))
def ticket_all(limit=50):
    try: return db("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,), fetch=True)
    except: return []

# ═══════════════════════════════════════════════════════════
#                    🎯 TikTok API
# ═══════════════════════════════════════════════════════════
DEVINFO = ('{"d":"61393235613366373261636533656632",'
           '"n":"494e46494e495820496e66696e6978204c697465203330",'
           '"o":"16","t":"d","v":"2.2.9","s":"0,0"}')
_kb = [0x35,0x30,0x1c,0x2f,0x2c,0x2c,0x28,0x31,0x35,0x30,0x1c,0x2f,0x2c,0x2c,0x28,0x31]
SK = bytes(b ^ 0x43 for b in _kb)
OPS = {
    "LoginAccount": "3522613813036d73817b2715e67743f8d23d7a85ad08b7e12aa3b29a24a17c43",
    "AttestDevice": "bfaf5a72aeb9a337811da6a6d13e0b73680a18ffde0c59a23701e55b98ac2515",
    "GetOrders":    "330a1eb97775a2f520b2e848601c40f8211d171c778c18840b37260ce94fb725",
    "ActionOrder":  "5177239275a5e78347f7d925501b1a774b76a086f67c33b0033c740dd676f62b",
    "CreateOrder":  "ad7a6397c3970b1e7601f69d24989bff330e256ee5e39321a8d1ad3fe3879b48",
}
API = "https://api.tikspark.xyz/graphql"
AV = ("https://p16-common-sign.tiktokcdn.com/musically-maliva-obj/"
      "1594805258216454~tplv-tiktokx-cropcenter:720:720.webp")

def _sig(ts, n, p):
    return hmac.new(SK, f"{ts}-{n}-{p}".encode(), hashlib.sha256).hexdigest()

def api_req(payload, op, token=None, csrf=None, auth=True):
    ps = json.dumps(payload, separators=(',',':'))
    ts = str(int(time.time()*1000)); n = str(uuid.uuid4())[:16]
    h = {"X-APOLLO-OPERATION-NAME": op,
         "Accept": "multipart/mixed; deferSpec=20220824, application/json",
         "x-language": "ar", "x-app-name": "com.dev.vidspark",
         "x-device-info": DEVINFO, "x-app-sig": _sig(ts,n,ps),
         "x-app-ts": ts, "x-app-nonce": n,
         "Content-Type": "application/json",
         "User-Agent": "okhttp/4.12.0", "Accept-Encoding": "gzip"}
    if op in OPS: h["X-APOLLO-OPERATION-ID"] = OPS[op]
    if auth:
        if token: h["token"] = token
        if csrf: h["x-csrf-token"] = csrf
    try:
        r = requests.post(API, headers=h, data=ps, timeout=15)
        return r, r.json()
    except Exception as e:
        return None, {"error": str(e)}

def tt_login(u, p):
    pl = {"operationName": "LoginAccount",
          "variables": {"data": {"id": "", "uniqueId": u, "nickname": "",
            "avatarMedium": AV, "followerCount": 0, "followingCount": 0,
            "videoCount": 0, "privateAccount": False, "diggCount": 0,
            "authMethod": "local", "password": p}},
          "query": "mutation LoginAccount($data: TiktokInfo) { loginTiktok(data: $data) "
                   "{ accessToken user { _id nickname score username banned } } }"}
    o, r = api_req(pl, "LoginAccount", auth=False)
    if o and "errors" not in r:
        try:
            return (r['data']['loginTiktok']['accessToken'],
                    o.headers.get("x-csrf-token"),
                    r['data']['loginTiktok']['user'])
        except: pass
    return None, None, None

def tt_attest(t, c):
    pl = {"operationName": "AttestDevice",
          "variables": {"integrityToken": "CpsCARCnMGtvLkiuhYFGDW3rUoE73im9X9NmXA1cHOZZOzgRp5FtsmIrZBoNek0K7XIoZiR9XKg1bpApXNem9MbcR4UiIxz1n4Wgv_LA4hSSAbHzpaAfXcnLyKgwnOXGRUieQ4OOpMTMDRxD6O7kd3jjAfcbcHFt3bdgyw7CJYpxz4oq3lIti658lCdnt1NvJzUwfYSp6eWKcvKV5lScaq-nkplRn7hz38A8kLhYNx6w-7rne41hWCR6BQISVfBewaqeh7RL-9iEDrzK-ECbdEwBnpO_LfAqCJKn1bf5VkVxuPAz5qPvB8cNE7ZBMAyMnDHdjNDwpnZMA2EXsgRsyT6Fm_l3MNugWDdWbRgww6sAw6KrRzeBDETsXTh1ZBpqAWerZWp6AIjaDa-b0NFbOS69HsGnfpE7hljmu3OTsd4tM6nM50qiSc4QGuD4aM-joJFJYKIsWf_grquB66tYnYa2mCWcPl1hIEApHMXbCLiO7nwX-8LXEwCDvVNT4f8mjgtI1__D_C_f4g",
                        "requestHash": "gPyB7FF-XeZc2kwi2L-KZXs2t21Z8oPErvHD9gn572PyR"},
          "query": "mutation AttestDevice($integrityToken: String!, $requestHash: String!) "
                   "{ attestDevice(integrityToken: $integrityToken, requestHash: $requestHash) "
                   "{ ok verified } }"}
    _, r = api_req(pl, "AttestDevice", t, c)
    return r and "errors" not in r

def tt_orders(t, c):
    p = {"operationName": "GetOrders", "variables": {},
         "query": "query GetOrders { getOrders { _id status } }"}
    _, r = api_req(p, "GetOrders", t, c)
    return r.get("data",{}).get("getOrders",[]) if r and "errors" not in r else []

def tt_action(t, c, oid):
    rn = random.randint(3000, 4500)
    p = {"operationName": "ActionOrder",
         "variables": {"orderId": oid, "validationData": {
             "attempts": 1, "initialNumber": float(rn),
             "timeSpent": float(random.randint(4000, 7000)),
             "actualCount": rn+1, "source": "CLIENT_CRONET"}},
         "query": "mutation ActionOrder($orderId: ID!, $validationData: ValidationDataInput!) "
                  "{ actionOrder(orderId: $orderId, validationData: $validationData) { score } }"}
    _, r = api_req(p, "ActionOrder", t, c)
    return r

def tt_create(t, c, svc, amount, target):
    v = {"type": svc, "amount": amount, "avatar": AV, "initialCount": 0}
    if svc == "followers": v["tiktokerUsername"] = target
    else:
        v["videoLink"] = target
        v["initialCount"] = random.randint(100, 500000)
    p = {"operationName": "CreateOrder", "variables": v,
         "query": "mutation CreateOrder($type: Action!, $amount: Int!, "
                  "$tiktokerUsername: String, $videoLink: String, $avatar: String, "
                  "$initialCount: Int) { createOrder(orderInput: { type: $type amount: $amount "
                  "tiktokerUsername: $tiktokerUsername videoLink: $videoLink avatar: $avatar "
                  "initialCount: $initialCount } ) { _id status } }"}
    _, r = api_req(p, "CreateOrder", t, c)
    return r

# ═══════════════════════════════════════════════════════════
#                    🏦 Pool Manager
# ═══════════════════════════════════════════════════════════
POOL_CLIENTS = {}
FARM_THREADS = {}
FARM_STOP = {}
POOL_LOCK = threading.RLock()

def cost_of(svc, amt): return SERVICE_PRICES.get(svc, 1) * amt

def pool_login(aid):
    try:
        acc = pool_get(aid)
        if not acc: return None
        token, csrf, ud = tt_login(acc["username"], acc["password"])
        if not token or not tt_attest(token, csrf):
            pool_upd(aid, status="dead"); return None
        pts = int(ud.get("score", 0) or 0)
        with POOL_LOCK:
            POOL_CLIENTS[aid] = {"token": token, "csrf": csrf,
                                 "points": pts, "username": acc["username"]}
        pool_upd(aid, token=token, csrf=csrf, points=pts,
                 status="active", last_login=datetime.now().isoformat())
        return POOL_CLIENTS[aid]
    except Exception as e:
        log.error(f"pool_login: {e}"); return None

def pool_refresh_all():
    n = 0
    for a in pool_all():
        try:
            if pool_login(a["id"]): n += 1
        except: pass
    log.info(f"🔄 pool refreshed: {n}/{len(pool_all())}")
    return n

def pool_deduct(aid, amt):
    with POOL_LOCK:
        if aid in POOL_CLIENTS:
            POOL_CLIENTS[aid]["points"] = max(0, POOL_CLIENTS[aid]["points"] - amt)
            pool_upd(aid, points=POOL_CLIENTS[aid]["points"])
        else:
            a = pool_get(aid)
            if a: pool_upd(aid, points=max(0, (a["points"] or 0) - amt))

def pool_add_points(aid, amt):
    with POOL_LOCK:
        if aid in POOL_CLIENTS:
            POOL_CLIENTS[aid]["points"] += amt
            pool_upd(aid, points=POOL_CLIENTS[aid]["points"])
        else:
            a = pool_get(aid)
            if a: pool_upd(aid, points=(a["points"] or 0) + amt)

def pool_get_client_for(need):
    for aid, c in sorted(POOL_CLIENTS.items(), key=lambda x: -x[1]["points"]):
        if c["points"] >= need: return aid, c
    for a in pool_all():
        if a["status"] != "active" or a["id"] in POOL_CLIENTS: continue
        c = pool_login(a["id"])
        if c and c["points"] >= need: return a["id"], c
    return None, None

def pool_has_any():
    try: return len(pool_all()) > 0
    except: return False

def execute_order(svc, amount, target):
    try:
        need = cost_of(svc, amount)
        aid, c = pool_get_client_for(need)
        if not aid: return None, None, "⚠️ الخدمة مشغولة — حاول لاحقاً"
        r = tt_create(c["token"], c["csrf"], svc, amount, target)
        if not r or "errors" in r:
            err = "فشل"
            if r and "errors" in r:
                try: err = r["errors"][0]["message"]
                except: pass
            return None, None, err
        oid = r.get("data", {}).get("createOrder", {}).get("_id", "unknown")
        pool_deduct(aid, need)
        return oid, aid, None
    except Exception as e:
        return None, None, f"خطأ: {e}"

def farm_loop(aid):
    try:
        c = POOL_CLIENTS.get(aid) or pool_login(aid)
        if not c:
            FARM_THREADS.pop(aid, None); FARM_STOP.pop(aid, None); return
        FARM_STOP[aid] = False
        while not FARM_STOP.get(aid):
            try:
                orders = tt_orders(c["token"], c["csrf"])
                pending = [o["_id"] for o in orders if o.get("status") == "pending"]
                if not pending: time.sleep(3); continue
                for oid in pending:
                    if FARM_STOP.get(aid): break
                    r = tt_action(c["token"], c["csrf"], oid)
                    if r and "errors" not in r:
                        try:
                            g = int(r.get("data",{}).get("actionOrder",{}).get("score",0) or 0)
                            if g > 0: pool_add_points(aid, g)
                        except: pass
                    time.sleep(0.15)
            except: time.sleep(3)
    finally:
        FARM_THREADS.pop(aid, None); FARM_STOP.pop(aid, None)

def farm_start(aid):
    if aid in FARM_THREADS and FARM_THREADS[aid].is_alive(): return False
    t = threading.Thread(target=farm_loop, args=(aid,), daemon=True)
    FARM_THREADS[aid] = t; t.start(); return True

def farm_stop(aid): FARM_STOP[aid] = True
def farm_running(aid): return aid in FARM_THREADS and FARM_THREADS[aid].is_alive()
def farm_start_all():
    n = 0
    for a in pool_all():
        if not farm_running(a["id"]): farm_start(a["id"]); n += 1
    return n
def farm_stop_all():
    for aid in list(FARM_THREADS.keys()): farm_stop(aid)
    return len(FARM_THREADS)

def blast_loop(task_id):
    try:
        while True:
            t = blast_get(task_id)
            if not t or t["status"] != "active": return
            hours = t["hours"]
            for _ in range(hours * 360):
                time.sleep(10)
                t = blast_get(task_id)
                if not t or t["status"] != "active": return
            t = blast_get(task_id)
            if not t or t["status"] != "active": return
            svc, target = t["service"], t["target"]
            amount = t["amount"]
            oid, pool_id, err = execute_order(svc, amount, target)
            if oid:
                order_add(t["user_id"], svc, target, amount, oid, pool_id, "pending", source="blast")
            blast_inc(task_id, (datetime.now() + timedelta(hours=hours)).isoformat())
    except: pass

def blast_start(task_id):
    threading.Thread(target=blast_loop, args=(task_id,), daemon=True).start()

def blast_run_first_now(uid, svc, target, amount):
    oid, pool_id, err = execute_order(svc, amount, target)
    if oid:
        order_add(uid, svc, target, amount, oid, pool_id, "pending", source="blast")
        return True, None
    return False, err

def notify_admin(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                      timeout=10)
    except: pass

# ═══════════════════════════════════════════════════════════
#                    🌐 Flask
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#05060d;--ink:#f1f5f9;--mut:#94a3b8;
  --line:rgba(255,255,255,.08);--glass:rgba(255,255,255,.04);
  --pri:#7c3aed;--pri2:#a855f7;--pink:#ec4899;--cyan:#06b6d4;
  --green:#10b981;--red:#ef4444;--gold:#fbbf24;
}
html,body{width:100%;overflow-x:hidden}
body{
  font-family:-apple-system,"SF Pro Display","Segoe UI",Tahoma,sans-serif;
  background:
    radial-gradient(ellipse 70% 50% at 10% -10%, rgba(168,85,247,.4) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 90% 10%, rgba(236,72,153,.3) 0%, transparent 60%),
    radial-gradient(ellipse 80% 60% at 50% 110%, rgba(6,182,212,.25) 0%, transparent 60%),
    #05060d;
  color:var(--ink);min-height:100vh;direction:rtl;line-height:1.6;padding-bottom:40px;
  -webkit-font-smoothing:antialiased;
}
body::before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:
    linear-gradient(rgba(168,85,247,.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(168,85,247,.03) 1px, transparent 1px);
  background-size:40px 40px;
  mask-image:radial-gradient(ellipse at center, black 40%, transparent 85%);
  -webkit-mask-image:radial-gradient(ellipse at center, black 40%, transparent 85%);
}
.container{max-width:1080px;margin:0 auto;padding:24px 18px;position:relative;z-index:1}
a{color:#67e8f9;text-decoration:none;transition:.15s}
a:hover{color:#a5f3fc}
.navbar{
  position:sticky;top:0;z-index:100;
  display:flex;justify-content:space-between;align-items:center;
  padding:14px 22px;background:rgba(5,6,13,.72);
  backdrop-filter:blur(24px) saturate(180%);
  -webkit-backdrop-filter:blur(24px) saturate(180%);
  border-bottom:1px solid var(--line);flex-wrap:wrap;gap:10px;
}
.logo{display:flex;align-items:center;gap:10px;font-weight:900;font-size:18px}
.logo .mark{
  width:36px;height:36px;border-radius:12px;
  background:conic-gradient(from 210deg, #a855f7, #ec4899, #06b6d4, #a855f7);
  display:grid;place-items:center;font-size:20px;
  box-shadow:0 8px 30px rgba(168,85,247,.5);
  animation:spin 8s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}
.logo .word{
  background:linear-gradient(90deg,#f1f5f9,#a855f7,#67e8f9);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.nav{display:flex;gap:4px;flex-wrap:wrap;align-items:center}
.nav a{padding:9px 16px;border-radius:11px;font-size:14px;font-weight:600;color:#cbd5e1;position:relative}
.nav a:hover{background:var(--glass);color:#fff}
.nav a .dot{
  position:absolute;top:5px;left:5px;min-width:18px;height:18px;border-radius:9px;
  background:var(--red);color:#fff;font-size:10px;padding:0 5px;
  display:grid;place-items:center;font-weight:800;
}
.hero{text-align:center;padding:32px 20px 24px}
.hero h1{
  font-size:clamp(30px,6vw,56px);font-weight:900;line-height:1.05;letter-spacing:-1px;
  background:linear-gradient(120deg,#f1f5f9 0%,#a855f7 40%,#ec4899 70%,#67e8f9 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  background-size:200% 200%;animation:slide 6s ease-in-out infinite;
}
@keyframes slide{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
.hero .sub{margin-top:16px;color:#b5aee0;font-size:15px;max-width:520px;margin-inline:auto}
.hero .pills{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:22px}
.chip{
  display:inline-flex;align-items:center;gap:6px;padding:8px 14px;
  border-radius:999px;font-size:12px;font-weight:700;
  background:var(--glass);border:1px solid var(--line);color:#cbd5e1;
}
.chip.on{background:rgba(16,185,129,.12);border-color:rgba(16,185,129,.35);color:#6ee7b7}
.card{
  background:linear-gradient(180deg,rgba(20,16,45,.7),rgba(10,8,28,.7));
  border:1px solid var(--line);border-radius:22px;padding:22px;margin-bottom:16px;
  backdrop-filter:blur(20px);
  box-shadow:0 8px 40px rgba(0,0,0,.35);position:relative;overflow:hidden;
}
.card.glow::before{
  content:"";position:absolute;top:0;left:15%;right:15%;height:1px;
  background:linear-gradient(90deg,transparent,#a855f7,#67e8f9,transparent);
}
.card h2{font-size:19px;font-weight:800;color:#fff;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.card h3{font-size:15px;font-weight:700;color:#e0e7ff;margin-bottom:8px}
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:13px 22px;border-radius:14px;border:none;
  font-weight:800;font-size:14.5px;font-family:inherit;cursor:pointer;
  color:#fff;text-decoration:none;transition:all .18s cubic-bezier(.4,0,.2,1);
}
.btn:hover{transform:translateY(-2px)}
.btn:active{transform:translateY(0) scale(.98)}
.btn:disabled,.btn.dis{opacity:.4;cursor:not-allowed;pointer-events:none}
.btn-primary{background:linear-gradient(135deg,#7c3aed,#a855f7);box-shadow:0 10px 30px rgba(168,85,247,.4)}
.btn-pink{background:linear-gradient(135deg,#db2777,#ec4899);box-shadow:0 10px 30px rgba(236,72,153,.4)}
.btn-cyan{background:linear-gradient(135deg,#0891b2,#06b6d4);box-shadow:0 10px 30px rgba(6,182,212,.4)}
.btn-gold{background:linear-gradient(135deg,#d97706,#fbbf24);color:#1a1000;box-shadow:0 10px 30px rgba(251,191,36,.4)}
.btn-green{background:linear-gradient(135deg,#059669,#10b981);box-shadow:0 10px 30px rgba(16,185,129,.4)}
.btn-ghost{background:var(--glass);border:1px solid var(--line);color:#e5e7eb}
.btn-ghost:hover{background:rgba(168,85,247,.12);border-color:rgba(168,85,247,.4)}
.btn-block{display:flex;width:100%}
.btn-sm{padding:8px 14px;font-size:12.5px;border-radius:10px}
.btn-lg{padding:17px 32px;font-size:16px;border-radius:16px}
label{display:block;margin:14px 0 7px;font-weight:700;color:#c9c4ff;font-size:12.5px;letter-spacing:.4px;text-transform:uppercase}
input,select,textarea{
  width:100%;padding:13px 16px;border-radius:14px;
  border:1px solid var(--line);background:rgba(5,6,13,.7);
  color:#fff;font-size:15px;font-family:inherit;transition:.15s;
}
input:focus,select:focus,textarea:focus{
  outline:none;border-color:var(--pri2);background:rgba(5,6,13,.95);
  box-shadow:0 0 0 4px rgba(168,85,247,.15);
}
textarea{resize:vertical;min-height:100px}
.svc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.svc{
  position:relative;cursor:pointer;text-decoration:none;color:inherit;
  padding:20px;border-radius:20px;
  background:linear-gradient(155deg,rgba(30,24,64,.9),rgba(12,8,32,.95));
  border:1px solid var(--line);transition:.25s;overflow:hidden;
  display:flex;flex-direction:column;gap:6px;
}
.svc::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 20% 0%, var(--glow,rgba(168,85,247,.3)) 0%, transparent 55%);opacity:.7}
.svc:hover{transform:translateY(-5px);border-color:var(--pri2);box-shadow:0 20px 50px rgba(168,85,247,.35)}
.svc .emo{font-size:38px;position:relative;z-index:1;line-height:1}
.svc .name{font-size:16px;font-weight:800;color:#fff;position:relative;z-index:1}
.svc .lim{font-size:11.5px;color:#94a3b8;font-family:ui-monospace,monospace;position:relative;z-index:1}
.svc .arrow{margin-top:8px;position:relative;z-index:1;font-size:11px;font-weight:800;padding:5px 10px;border-radius:8px;background:rgba(168,85,247,.2);color:#c4b5fd;align-self:flex-start}
.svc.f{--glow:rgba(168,85,247,.5)}
.svc.l{--glow:rgba(236,72,153,.5)}
.svc.v{--glow:rgba(251,191,36,.5)}
.svc.c{--glow:rgba(6,182,212,.5)}
.alert{padding:13px 16px;border-radius:14px;margin:10px 0;font-weight:700;font-size:13.5px;display:flex;gap:10px;align-items:flex-start;line-height:1.55}
.alert-success{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);color:#6ee7b7}
.alert-danger{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#fca5a5}
.alert-info{background:rgba(6,182,212,.1);border:1px solid rgba(6,182,212,.3);color:#a5f3fc}
.alert-warn{background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.3);color:#fcd34d}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{padding:12px;text-align:right;border-bottom:1px solid var(--line)}
th{color:#94a3b8;font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.6px}
tr:hover td{background:rgba(255,255,255,.02)}
code{background:rgba(255,255,255,.06);padding:2px 8px;border-radius:6px;font-family:ui-monospace,monospace;font-size:12.5px;color:#a5f3fc}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:800}
.badge-pending{background:rgba(251,191,36,.15);color:#fcd34d;border:1px solid rgba(251,191,36,.3)}
.badge-processing{background:rgba(6,182,212,.15);color:#a5f3fc;border:1px solid rgba(6,182,212,.3)}
.badge-completed{background:rgba(16,185,129,.15);color:#6ee7b7;border:1px solid rgba(16,185,129,.3)}
.badge-failed{background:rgba(239,68,68,.15);color:#fca5a5;border:1px solid rgba(239,68,68,.3)}
.badge-blast{background:rgba(168,85,247,.2);color:#c4b5fd;border:1px solid rgba(168,85,247,.4)}
.grid{display:grid;gap:12px}
.g2{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.g4{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
.stat{text-align:center;padding:16px 10px;border-radius:16px;background:linear-gradient(180deg,rgba(168,85,247,.08),rgba(168,85,247,.02));border:1px solid var(--line)}
.stat .num{font-size:24px;font-weight:900;color:#fff;line-height:1.1}
.stat .num.g{background:linear-gradient(135deg,#a855f7,#67e8f9);-webkit-background-clip:text;background-clip:text;color:transparent}
.stat .lbl{font-size:11.5px;color:#94a3b8;margin-top:6px;font-weight:700}
.notice{padding:16px 20px;border-radius:18px;margin-bottom:16px;background:linear-gradient(135deg,rgba(16,185,129,.12),rgba(6,182,212,.06));border:1px solid rgba(16,185,129,.35);display:flex;align-items:center;gap:14px}
.notice.gold{background:linear-gradient(135deg,rgba(251,191,36,.12),rgba(217,119,6,.06));border-color:rgba(251,191,36,.35)}
.notice.red{background:linear-gradient(135deg,rgba(239,68,68,.12),rgba(190,24,93,.06));border-color:rgba(239,68,68,.35)}
.notice .ico{font-size:32px;width:56px;height:56px;display:grid;place-items:center;border-radius:16px;background:rgba(255,255,255,.05);flex-shrink:0}
.notice .body{flex:1;min-width:0}
.notice .body h3{margin-bottom:4px;font-size:15px;color:#fff;font-weight:800}
.notice .body p{font-size:12.5px;color:#cbd5e1}
.feat{list-style:none;padding:0;margin:14px 0}
.feat li{padding:10px 0;font-size:13.5px;display:flex;align-items:center;gap:10px;border-bottom:1px dashed var(--line)}
.feat li:last-child{border-bottom:0}
.feat li::before{content:"✓";color:#10b981;font-weight:900;font-size:14px;width:20px;height:20px;border-radius:6px;background:rgba(16,185,129,.12);display:grid;place-items:center;flex-shrink:0}
.msg-item{padding:14px 16px;border-radius:16px;margin-bottom:10px;font-size:13.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
.msg-admin{background:linear-gradient(135deg,rgba(168,85,247,.14),rgba(236,72,153,.06));border:1px solid rgba(168,85,247,.3);border-right:4px solid #a855f7}
.msg-admin::before{content:"👑 من المطور";display:block;font-size:10.5px;color:#c4b5fd;font-weight:800;margin-bottom:8px;letter-spacing:.6px;text-transform:uppercase}
.msg-user{background:rgba(6,182,212,.05);border:1px solid rgba(6,182,212,.2);border-right:4px solid #06b6d4}
.msg-user::before{content:"👤 منك";display:block;font-size:10.5px;color:#a5f3fc;font-weight:800;margin-bottom:8px;letter-spacing:.6px;text-transform:uppercase}
.msg-time{font-size:10.5px;color:#64748b;margin-top:8px;display:block;font-family:ui-monospace,monospace}
.footer{text-align:center;padding:36px 20px 24px;color:#64748b;font-size:12.5px}
.footer a{color:#a855f7;font-weight:700}
.fab{
  position:fixed;bottom:22px;left:22px;z-index:150;
  width:56px;height:56px;border-radius:50%;
  background:linear-gradient(135deg,#7c3aed,#ec4899);
  display:grid;place-items:center;cursor:pointer;
  box-shadow:0 12px 40px rgba(168,85,247,.55);font-size:24px;
  border:2px solid rgba(255,255,255,.1);transition:.25s;
}
.fab:hover{transform:scale(1.08) rotate(-8deg)}
/* Guide images */
.guide-step{margin-bottom:24px;text-align:center}
.guide-step img{
  max-width:100%;border-radius:18px;
  border:2px solid var(--line);
  box-shadow:0 20px 60px rgba(0,0,0,.5);
}
.guide-step .cap{
  margin-top:14px;padding:14px 20px;border-radius:14px;
  background:linear-gradient(135deg,rgba(168,85,247,.15),rgba(6,182,212,.08));
  border:1px solid rgba(168,85,247,.35);
  font-weight:800;color:#fff;
}
.success-page{
  max-width:600px;margin:40px auto;text-align:center;
  padding:40px 26px;border-radius:24px;
  background:linear-gradient(155deg,rgba(16,185,129,.14),rgba(6,182,212,.06));
  border:2px solid rgba(16,185,129,.45);
  box-shadow:0 24px 70px rgba(16,185,129,.25);
  animation:successPop .5s cubic-bezier(.4,0,.2,1);
}
@keyframes successPop{0%{transform:scale(.8);opacity:0}50%{transform:scale(1.05)}100%{transform:scale(1);opacity:1}}
.success-page .big-emo{font-size:88px;line-height:1;margin-bottom:20px;animation:bounce 1.2s ease-in-out infinite}
@keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-14px)}}
.success-page h1{font-size:30px;font-weight:900;margin-bottom:14px;background:linear-gradient(120deg,#6ee7b7,#a5f3fc);-webkit-background-clip:text;background-clip:text;color:transparent}
.success-page p{font-size:15px;color:#cbd5e1;line-height:1.75;margin-bottom:8px}
.success-page .details{margin:26px 0;padding:18px;border-radius:16px;background:rgba(5,6,13,.5);border:1px solid var(--line);text-align:right}
.success-page .details .row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px dashed var(--line);font-size:13.5px}
.success-page .details .row:last-child{border-bottom:0}
.success-page .details .row .lbl{color:#94a3b8}
.success-page .details .row .val{color:#fff;font-weight:700}
@media(max-width:600px){
  .navbar{padding:12px 14px}
  .nav a{padding:7px 11px;font-size:12.5px}
  .container{padding:16px 12px}
  .card{padding:18px;border-radius:18px}
  .hero{padding:24px 12px 18px}
  .fab{width:50px;height:50px;font-size:22px;bottom:16px;left:16px}
  .success-page{margin:20px auto;padding:30px 18px}
  .success-page .big-emo{font-size:64px}
  .success-page h1{font-size:22px}
}
"""

def render(body, title="TikTok Spark", u=None):
    try: msgs = get_flashed_messages(with_categories=True)
    except: msgs = []
    msg_html = "".join(f'<div class="alert alert-{c}">{m}</div>' for c, m in msgs)
    nav_html = ""
    if u:
        try: unread = msg_unread(u["id"])
        except: unread = 0
        dot = f'<span class="dot">{unread}</span>' if unread > 0 else ''
        nav_html = (
            f'<a href="/">🏠 الرئيسية</a>'
            f'<a href="/services">🛍️ الخدمات</a>'
            f'<a href="/blast">🚀 الرشق</a>'
            f'<a href="/orders">📋 طلباتي</a>'
            f'<a href="/my-account">👤 حسابي</a>'
            f'<a href="/messages">{dot}📨</a>'
        )
    else:
        nav_html = (
            '<a href="/">🏠 الرئيسية</a>'
            '<a href="/guide">📖 الشرح</a>'
            '<a href="/login">🔐 دخول</a>'
            '<a href="/register" class="btn-primary" style="color:#fff">📝 سجل</a>'
        )

    return f'''<!DOCTYPE html><html lang="ar" dir="rtl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05060d">
<title>{title} · TikTok Spark</title>
<style>{CSS}</style>
</head><body>
<div class="navbar">
  <div class="logo"><span class="mark">⚡</span><span class="word">TikTok&nbsp;Spark</span></div>
  <nav class="nav">{nav_html}</nav>
</div>
<div class="container">
{msg_html}
{body}
</div>
<div class="footer">
  TikTok Spark v21.0 · 2026 · <a href="{VIP_CONTACT_LINK}" target="_blank">{VIP_CONTACT}</a>
</div>
<div class="fab" onclick="location.href='/help'" title="الدعم">💬</div>
</body></html>'''

def current_user():
    uid = session.get("uid")
    return user_get(uid) if uid else None

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("uid"):
            flash("🔐 سجل دخول أولاً", "warn")
            return redirect(url_for("login"))
        return f(*a, **kw)
    return w

def user_limits(u):
    st = user_status(u)
    return VIP_LIMITS if st == "vip" else FREE_LIMITS if st == "free" else {}

def can_use(u):
    return u and user_status(u) in ("free", "vip")

@app.errorhandler(Exception)
def handle_error(e):
    log.error(f"❌ {e}\n{traceback.format_exc()}")
    try:
        return render(f'''
        <div class="card glow" style="border-color:rgba(239,68,68,.4)">
          <h2>⚠️ حدث خطأ مؤقت</h2>
          <p style="color:#cbd5e1;margin-bottom:14px">حاول تحديث الصفحة</p>
          <a href="/" class="btn btn-primary btn-block">🔙 الرئيسية</a>
        </div>''', "خطأ")
    except:
        return f"<pre>Error: {e}</pre>", 500

# ═══════════════ 🌐 الصفحات العامة ═══════════════
@app.route("/")
def index():
    u = current_user()
    # إن لم يكن مسجل دخول → عرض صفحة ترحيب
    if not u:
        body = f'''
        <div class="hero">
          <h1>TikTok Spark</h1>
          <p class="sub">منصة خدمات TikTok الاحترافية — أنشئ حسابك مجاناً وابدأ فوراً</p>
          <div class="pills">
            <span class="chip on">⚡ فوري</span>
            <span class="chip on">🔒 آمن</span>
            <span class="chip on">♾️ رشق تلقائي</span>
            <span class="chip on">🎁 تجربة مجانية</span>
          </div>
          <div style="margin-top:32px" class="grid g2">
            <a href="/register" class="btn btn-primary btn-lg btn-block">📝 إنشاء حساب جديد</a>
            <a href="/login" class="btn btn-ghost btn-lg btn-block">🔐 تسجيل الدخول</a>
          </div>
        </div>
        <div class="card glow">
          <h2>✨ لماذا TikTok Spark؟</h2>
          <div class="grid g3" style="margin-top:14px">
            <div class="stat"><div class="num g">24/7</div><div class="lbl">🕐 خدمة دائمة</div></div>
            <div class="stat"><div class="num g">⚡</div><div class="lbl">تنفيذ فوري</div></div>
            <div class="stat"><div class="num g">🔒</div><div class="lbl">أمان كامل</div></div>
          </div>
        </div>
        <div class="card">
          <h2>🚀 كيف تبدأ؟</h2>
          <div class="grid g3" style="margin-top:14px">
            <div class="stat"><div class="num">1</div><div class="lbl">📝 سجّل حسابك</div></div>
            <div class="stat"><div class="num">2</div><div class="lbl">📖 اتبع الشرح</div></div>
            <div class="stat"><div class="num">3</div><div class="lbl">👤 أضف حساب TikTok</div></div>
            <div class="stat"><div class="num">4</div><div class="lbl">🌱 شغّل التجميع</div></div>
            <div class="stat"><div class="num">5</div><div class="lbl">🛍️ اطلب خدمة</div></div>
            <div class="stat"><div class="num">6</div><div class="lbl">🚀 فعّل الرشق</div></div>
          </div>
        </div>
        <div class="card">
          <h2>📖 شرح إنشاء حساب TikTok</h2>
          <p style="color:#cbd5e1;margin-bottom:14px">اتبع الصور خطوة بخطوة لإنشاء حساب TikTok جديد</p>
          <a href="/guide" class="btn btn-cyan btn-block">👁️ مشاهدة الشرح</a>
        </div>'''
        return render(body, "الرئيسية", None)

    st = user_status(u)
    if st == "banned":
        return render('<div class="card"><h2>🚫 محظور</h2></div>', "محظور", u)

    # المستخدم مسجل دخول
    has_pool = len(pool_by_owner(u["id"])) > 0 or pool_has_any()
    pool_warning = ""
    if not pool_has_any():
        pool_warning = '<div class="alert alert-warn">⚠️ الخدمة قيد التهيئة — تواصل مع المطور</div>'

    # شريط الحالة
    if st == "free":
        cd = cooldown_left(u)
        if cd > 0:
            h, m = cd // 3600, (cd % 3600) // 60
            cd_html = f'<div class="alert alert-warn">⏰ الاستخدام التالي بعد: <b>{h}س {m}د</b></div>'
        else:
            cd_html = '<div class="alert alert-success">✅ يمكنك الاستخدام الآن</div>'
        vl = VIEWS_MAX_USES - (u.get("views_used") or 0)
        status_html = f'''
        <div class="notice">
          <div class="ico">🎁</div>
          <div class="body">
            <h3>مرحباً {u["username"]} — تجربتك المجانية نشطة</h3>
            <p>تنتهي: <b>{u["free_expires"][:16]}</b></p>
          </div>
        </div>
        <div class="card glow">
          <h2>🎁 الحدود المجانية</h2>
          <div class="grid g4" style="margin-top:12px">
            <div class="stat"><div class="num">20</div><div class="lbl">👥 متابعين</div></div>
            <div class="stat"><div class="num">20</div><div class="lbl">❤️ لايكات</div></div>
            <div class="stat"><div class="num">20</div><div class="lbl">💬 تعليقات</div></div>
            <div class="stat"><div class="num">500</div><div class="lbl">👁️ مشاهدات</div></div>
          </div>
          <p style="font-size:12.5px;color:#94a3b8;margin-top:14px">👁️ المشاهدات المتبقية: <b>{vl}/{VIEWS_MAX_USES}</b></p>
          {cd_html}
          <a href="{VIP_CONTACT_LINK}" class="btn btn-gold btn-block" style="margin-top:14px" target="_blank">👑 ترقية VIP</a>
        </div>'''
    elif st == "expired":
        status_html = f'''
        <div class="notice red"><div class="ico">⌛</div>
        <div class="body"><h3>انتهت تجربتك</h3><p>جدّد أو اشترِ VIP</p></div></div>
        <div class="card glow">
          <a href="{VIP_CONTACT_LINK}" class="btn btn-pink btn-block" target="_blank">👑 شراء VIP — {VIP_CONTACT}</a>
        </div>'''
    else:
        status_html = f'''
        <div class="notice gold"><div class="ico">👑</div>
        <div class="body"><h3>عضوية VIP نشطة</h3>
        <p>الباقة: <b>{u.get("vip_plan","VIP")}</b> · تنتهي: <b>{u["vip_expires"][:16]}</b></p></div></div>
        <div class="card glow">
          <h2>👑 ميزات VIP</h2>
          <div class="grid g4" style="margin-top:12px">
            <div class="stat"><div class="num g">100K</div><div class="lbl">👥 متابعين</div></div>
            <div class="stat"><div class="num g">100K</div><div class="lbl">❤️ لايكات</div></div>
            <div class="stat"><div class="num g">100K</div><div class="lbl">💬 تعليقات</div></div>
            <div class="stat"><div class="num g">1M</div><div class="lbl">👁️ مشاهدات</div></div>
          </div>
        </div>'''

    cd_ok = (st != "free") or (cooldown_left(u) == 0)
    use_dis = '' if (can_use(u) and cd_ok and pool_has_any()) else 'style="opacity:.5;pointer-events:none"'

    # عرض حالة حساب TikTok
    tt_acc = u.get("tiktok_username")
    tt_state = ""
    if tt_acc:
        farm_on = u.get("auto_farm") == 1
        tt_state = f'''
        <div class="notice" style="background:linear-gradient(135deg,rgba(6,182,212,.12),rgba(16,185,129,.06));border-color:rgba(6,182,212,.35)">
          <div class="ico">👤</div>
          <div class="body">
            <h3>حساب TikTok: {tt_acc}</h3>
            <p>🌱 التجميع التلقائي: <b style="color:{"#6ee7b7" if farm_on else "#fca5a5"}">{"يعمل ✅" if farm_on else "متوقف ❌"}</b></p>
          </div>
        </div>'''
    else:
        tt_state = f'''
        <div class="card" style="border-color:rgba(251,191,36,.5)">
          <h2>👤 أضف حساب TikTok الخاص بك</h2>
          <p style="color:#cbd5e1;font-size:13.5px;margin-bottom:14px">أضف حسابك ليُستخدم في خدماتك ويساعدك في كسب نقاط أكثر</p>
          <a href="/my-account" class="btn btn-primary btn-block">➕ إضافة حساب TikTok</a>
        </div>'''

    body = f'''
    <div class="hero">
      <h1>TikTok Spark</h1>
      <p class="sub">مرحباً {u["username"]} — اختر ما تريد</p>
    </div>
    {pool_warning}
    {status_html}
    {tt_state}
    <div class="card">
      <h2>⚡ ابدأ الآن</h2>
      <div class="grid g2">
        <a href="/services" class="btn btn-primary btn-block" {use_dis}>🛍️ الخدمات</a>
        <a href="/blast" class="btn btn-pink btn-block" {use_dis}>🚀 الرشق</a>
        <a href="/orders" class="btn btn-ghost btn-block">📋 طلباتي</a>
        <a href="/my-account" class="btn btn-cyan btn-block">👤 حسابي</a>
      </div>
    </div>
    <div class="card">
      <h2>📨 آخر الرسائل</h2>
      {render_msgs(u["id"], 3)}
      <a href="/messages" class="btn btn-ghost btn-block" style="margin-top:12px">عرض الكل</a>
    </div>'''
    return render(body, "الرئيسية", u)

def render_msgs(uid, limit=3):
    try: msgs = msg_all_for(uid, limit)
    except: msgs = []
    if not msgs:
        return '<p style="color:#94a3b8;text-align:center;padding:14px;font-size:13px">لا توجد رسائل بعد</p>'
    html = ""
    for m in msgs:
        cls = "msg-admin" if m.get("from_admin") else "msg-user"
        html += f'<div class="msg-item {cls}">{m["text"]}<span class="msg-time">{m["created_at"][:16]}</span></div>'
    return html

# ═══════════════ Registration / Login ═══════════════
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("uid"): return redirect(url_for("index"))
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = (request.form.get("password") or "").strip()
        p2 = (request.form.get("password2") or "").strip()
        if len(u) < 3: flash("❌ اسم المستخدم قصير (3 أحرف على الأقل)", "danger")
        elif not u.replace("_","").replace("-","").isalnum():
            flash("❌ اسم المستخدم يجب أن يكون بأحرف إنجليزية وأرقام فقط", "danger")
        elif len(p) < 5: flash("❌ كلمة المرور قصيرة (5 أحرف على الأقل)", "danger")
        elif p != p2: flash("❌ كلمتا المرور غير متطابقتين", "danger")
        else:
            uid = user_create(u, p)
            if uid:
                session["uid"] = uid
                session.permanent = True
                try: notify_admin(f"🆕 *مستخدم جديد*\n\n👤 `{u}`\n🆔 `{uid}`\n🎁 تجربة مجانية 24 ساعة")
                except: pass
                flash(f"🎉 مرحباً {u}! تجربتك المجانية 24 ساعة مفعّلة", "success")
                return redirect(url_for("guide"))
            flash("❌ اسم المستخدم مستخدم مسبقاً", "danger")
    body = '''
    <div class="card glow" style="max-width:520px;margin:30px auto">
      <h1 style="text-align:center;font-size:26px;margin-bottom:8px">📝 إنشاء حساب جديد</h1>
      <p style="text-align:center;color:#cbd5e1;font-size:13.5px;margin-bottom:20px">
        ستفتح لك تجربة مجانية <b>24 ساعة</b> مباشرة
      </p>
      <form method="POST">
        <label>👤 اسم المستخدم</label>
        <input name="username" required minlength="3" placeholder="احرف انجليزية وارقام" pattern="[A-Za-z0-9_\\-]+">
        <label>🔒 كلمة المرور</label>
        <input name="password" type="password" required minlength="5" placeholder="5 احرف على الاقل">
        <label>🔒 تأكيد كلمة المرور</label>
        <input name="password2" type="password" required minlength="5">
        <div style="height:16px"></div>
        <button class="btn btn-primary btn-block btn-lg" type="submit">🚀 إنشاء الحساب</button>
      </form>
      <p style="text-align:center;margin-top:16px;color:#94a3b8;font-size:13px">
        لديك حساب؟ <a href="/login">سجل دخول</a>
      </p>
    </div>'''
    return render(body, "تسجيل", None)

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("uid"): return redirect(url_for("index"))
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        user = user_auth(u, p)
        if not user:
            flash("❌ بيانات خاطئة", "danger")
        elif user["status"] == "banned":
            flash("🚫 حسابك محظور", "danger")
        else:
            session["uid"] = user["id"]
            session.permanent = True
            flash(f"👋 مرحباً {user['username']}", "success")
            return redirect(url_for("index"))
    body = '''
    <div class="card glow" style="max-width:480px;margin:30px auto">
      <h1 style="text-align:center;font-size:26px">🔐 تسجيل الدخول</h1>
      <form method="POST" style="margin-top:16px">
        <label>👤 اسم المستخدم</label>
        <input name="username" required>
        <label>🔒 كلمة المرور</label>
        <input name="password" type="password" required>
        <div style="height:16px"></div>
        <button class="btn btn-primary btn-block btn-lg" type="submit">🚀 دخول</button>
      </form>
      <p style="text-align:center;margin-top:16px;color:#94a3b8;font-size:13px">
        جديد؟ <a href="/register">أنشئ حساب</a>
      </p>
    </div>'''
    return render(body, "دخول", None)

@app.route("/logout")
def logout():
    session.pop("uid", None)
    flash("👋 تم الخروج", "info")
    return redirect(url_for("index"))

# ═══════════════ Guide (صور الشرح) ═══════════════
@app.route("/guide")
def guide():
    u = current_user()
    body = f'''
    <div class="card glow">
      <h1 style="text-align:center;font-size:28px">📖 شرح إنشاء حساب TikTok</h1>
      <p style="text-align:center;color:#cbd5e1;font-size:14px;margin-top:8px">
        اتبع الصور خطوة بخطوة لإنشاء حساب TikTok جديد
      </p>
    </div>

    <div class="card">
      <div class="guide-step">
        <div style="font-size:22px;font-weight:900;color:#fff;margin-bottom:14px">
          📱 الخطوة 1 — تحميل التطبيق
        </div>
        <img src="{GUIDE_IMAGES['step1']}" alt="خطوة 1" loading="lazy">
        <div class="cap">
          حمّل تطبيق <b>VidSpark</b> من Google Play
          <br><a href="{APP_DOWNLOAD_LINK}" target="_blank" style="margin-top:8px;display:inline-block">📥 تحميل التطبيق</a>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="guide-step">
        <div style="font-size:22px;font-weight:900;color:#fff;margin-bottom:14px">
          👤 الخطوة 2 — إنشاء الحساب
        </div>
        <img src="{GUIDE_IMAGES['step2']}" alt="خطوة 2" loading="lazy">
        <div class="cap">
          أنشئ حساب في التطبيق واختر <b>اسم مستخدم</b> فريد باللغة الإنجليزية
          <br><span style="color:#fcd34d">⚠️ تأكد من جعل الحساب عاماً (Public)</span>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="guide-step">
        <div style="font-size:22px;font-weight:900;color:#fff;margin-bottom:14px">
          🔐 الخطوة 3 — تأمين الحساب
        </div>
        <img src="{GUIDE_IMAGES['step3']}" alt="خطوة 3" loading="lazy">
        <div class="cap">
          أنشئ <b>كلمة مرور قوية</b> (5-7 أحرف على الأقل)
          <br><span style="color:#fca5a5">⚠️ احفظها جيداً ولا تشاركها مع أحد</span>
        </div>
      </div>
    </div>

    <div class="card glow" style="text-align:center">
      <h2 style="justify-content:center">✅ جاهز للمتابعة؟</h2>
      <p style="color:#cbd5e1;margin:14px 0 20px">بعد إنشاء حساب TikTok، أضفه في الموقع لتفعيل خدماتك</p>
      <a href="{"/my-account" if u else "/register"}" class="btn btn-primary btn-lg btn-block">
        {"➕ إضافة حساب TikTok" if u else "📝 إنشاء حساب أولاً"}
      </a>
    </div>'''
    return render(body, "الشرح", u)

# ═══════════════ My Account (إضافة حساب TikTok + تجميع) ═══════════════
@app.route("/my-account", methods=["GET", "POST"])
@login_required
def my_account():
    u = current_user()

    if request.method == "POST":
        action = request.form.get("action")

        # إضافة حساب TikTok
        if action == "add_tiktok":
            tt_u = (request.form.get("tt_username") or "").strip().lstrip("@")
            tt_p = (request.form.get("tt_password") or "").strip()
            if len(tt_u) < 2: flash("❌ اسم المستخدم قصير", "danger")
            elif len(tt_p) < 5: flash("❌ كلمة المرور قصيرة", "danger")
            else:
                # تحقق من عدم التكرار
                existing = db_one("SELECT * FROM pool WHERE username=?", (tt_u,))
                if existing:
                    flash("❌ هذا الحساب مضاف مسبقاً", "danger")
                else:
                    aid = pool_add(tt_u, tt_p, owner_id=u["id"], owner_type="user")
                    log.info(f"➕ حساب TikTok جديد #{aid} ({tt_u}) للمستخدم #{u['id']}")
                    # سجّل دخول
                    c = pool_login(aid)
                    if c:
                        user_upd(u["id"], tiktok_username=tt_u)
                        # شغّل تجميع تلقائي إذا وافق المستخدم
                        if request.form.get("auto_farm") == "1":
                            if farm_start(aid):
                                user_upd(u["id"], auto_farm=1)
                                flash("✅ تم إضافة حسابك وبدأ التجميع التلقائي", "success")
                            else:
                                flash("✅ تم إضافة حسابك (فشل بدء التجميع)", "warn")
                        else:
                            flash(f"✅ تم إضافة حسابك! النقاط: {c.get('points',0)}", "success")
                    else:
                        flash("⚠️ أضيف الحساب لكن فشل تسجيل الدخول — تحقق من البيانات", "warn")
                return redirect(url_for("my_account"))

        # تشغيل/إيقاف تجميع الحساب
        if action == "toggle_farm":
            on = request.form.get("on") == "1"
            my_accs = pool_by_owner(u["id"])
            if not my_accs:
                flash("❌ أضف حساب TikTok أولاً", "warn")
            else:
                for acc in my_accs:
                    if on: farm_start(acc["id"])
                    else: farm_stop(acc["id"])
                user_upd(u["id"], auto_farm=1 if on else 0)
                flash(f"🌱 التجميع التلقائي {'مفعّل' if on else 'موقوف'}", "success")
            return redirect(url_for("my_account"))

        # حذف حساب
        if action == "remove_tiktok":
            aid = int(request.form.get("aid") or 0)
            acc = pool_get(aid)
            if acc and acc.get("owner_id") == u["id"]:
                farm_stop(aid)
                pool_del(aid)
                user_upd(u["id"], tiktok_username=None, auto_farm=0)
                flash("🗑 تم حذف حسابك", "info")
            return redirect(url_for("my_account"))

    # عرض الحساب
    tt_u = u.get("tiktok_username")
    my_accs = pool_by_owner(u["id"])

    if not tt_u and not my_accs:
        # لا يوجد حساب — عرض الفورم
        body = f'''
        <div class="card glow">
          <h2>👤 أضف حساب TikTok الخاص بك</h2>
          <p style="color:#cbd5e1;font-size:13.5px">
            لم تُضف حساب TikTok بعد. اضغط "الشرح" لمشاهدة كيف تنشئ واحداً
          </p>
          <a href="/guide" class="btn btn-cyan btn-block" style="margin-top:10px">📖 مشاهدة الشرح</a>
        </div>
        <div class="card">
          <h2>➕ إضافة حسابك</h2>
          <form method="POST">
            <input type="hidden" name="action" value="add_tiktok">
            <label>👤 اسم المستخدم TikTok</label>
            <input name="tt_username" required placeholder="مثال: as_3310">
            <label>🔒 كلمة المرور</label>
            <input name="tt_password" type="password" required minlength="5">
            <div style="margin-top:14px;padding:14px;border-radius:14px;background:rgba(168,85,247,.08);border:1px solid rgba(168,85,247,.3)">
              <label style="margin-top:0;display:flex;align-items:center;gap:10px;cursor:pointer">
                <input type="checkbox" name="auto_farm" value="1" checked style="width:auto">
                🌱 تشغيل التجميع التلقائي فوراً (يجمع نقاط لحسابك)
              </label>
            </div>
            <div style="height:16px"></div>
            <button class="btn btn-primary btn-block btn-lg" type="submit">✅ إضافة الحساب</button>
          </form>
        </div>'''
        return render(body, "حسابي", u)

    # يوجد حساب
    farm_on = u.get("auto_farm") == 1
    acc_rows = ""
    for acc in my_accs:
        is_running = farm_running(acc["id"])
        acc_rows += f'''<tr>
          <td><code>{acc['username']}</code></td>
          <td>{acc.get('points',0)}</td>
          <td>{'🌱 يعمل' if is_running else '⏹ متوقف'}</td>
          <td><a href="?remove={acc['id']}" onclick="return confirm('حذف الحساب؟')" class="btn btn-ghost btn-sm">🗑</a></td>
        </tr>'''

    body = f'''
    <div class="card glow">
      <h2>👤 حسابي</h2>
      <div class="grid g2" style="margin-top:14px">
        <div class="stat">
          <div class="num">{tt_u or "-"}</div>
          <div class="lbl">TikTok username</div>
        </div>
        <div class="stat">
          <div class="num g">{'🌱' if farm_on else '⏹'}</div>
          <div class="lbl">التجميع التلقائي: {'يعمل' if farm_on else 'متوقف'}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>🌱 التجميع التلقائي</h2>
      <p style="color:#cbd5e1;font-size:13.5px">
        عند تشغيله، يقوم النظام تلقائياً بجمع النقاط من حسابك — يمكن استخدام هذه النقاط لتسريع خدمتك
      </p>
      <form method="POST" style="margin-top:14px">
        <input type="hidden" name="action" value="toggle_farm">
        <input type="hidden" name="on" value="{'0' if farm_on else '1'}">
        <button class="btn btn-{'pink' if farm_on else 'green'} btn-block btn-lg" type="submit">
          {'⏹ إيقاف التجميع' if farm_on else '🌱 تشغيل التجميع التلقائي'}
        </button>
      </form>
    </div>

    <div class="card">
      <h2>🏦 حساباتك المضافة</h2>
      <table>
        <tr><th>الحساب</th><th>النقاط</th><th>الحالة</th><th></th></tr>
        {acc_rows or '<tr><td colspan="4" style="text-align:center;color:#94a3b8;padding:20px">لا توجد</td></tr>'}
      </table>
    </div>

    <div class="card">
      <h2>➕ إضافة حساب TikTok آخر</h2>
      <form method="POST">
        <input type="hidden" name="action" value="add_tiktok">
        <label>👤 اسم المستخدم TikTok</label>
        <input name="tt_username" required placeholder="مثال: as_3310">
        <label>🔒 كلمة المرور</label>
        <input name="tt_password" type="password" required minlength="5">
        <div style="height:16px"></div>
        <button class="btn btn-primary btn-block" type="submit">✅ إضافة</button>
      </form>
    </div>'''
    return render(body, "حسابي", u)

# ═══════════════ Services ═══════════════
@app.route("/services")
@login_required
def services():
    u = current_user()
    if not can_use(u): flash("⚠️ حسابك غير مفعّل", "warn"); return redirect(url_for("index"))
    if not pool_has_any(): flash("⚠️ الخدمة قيد التهيئة", "warn"); return redirect(url_for("index"))
    st = user_status(u); lims = user_limits(u)
    cd = cooldown_left(u)
    if st == "free" and cd > 0:
        h, m = cd // 3600, (cd % 3600) // 60
        flash(f"⏰ الاستخدام التالي بعد: {h}س {m}د", "warn"); return redirect(url_for("index"))
    cards = ""; cls = {"followers":"f","likes":"l","views":"v","comments":"c"}
    for svc in ["followers","likes","views","comments"]:
        lo, hi = lims[svc]
        if svc == "views" and st == "free" and not can_use_free_views(u):
            cards += f'''<div class="svc {cls[svc]}" style="opacity:.4;pointer-events:none">
              <div class="emo">{SVC_EMO[svc]}</div><div class="name">{SVC_NAMES[svc]}</div>
              <div class="lim">استنفدت</div><div class="arrow">مقفل 🔒</div></div>'''
        else:
            cards += f'''<a href="/service/{svc}" class="svc {cls[svc]}">
              <div class="emo">{SVC_EMO[svc]}</div><div class="name">{SVC_NAMES[svc]}</div>
              <div class="lim">{lo} - {hi:,}</div><div class="arrow">ابدأ ←</div></a>'''
    body = f'''
    <div class="card glow"><h2>🛍️ الخدمات</h2>
      <p style="color:#cbd5e1;font-size:13.5px">الباقة: {"👑 VIP" if st=="vip" else "🎁 مجانية"}</p></div>
    <div class="svc-grid">{cards}</div>'''
    return render(body, "الخدمات", u)

@app.route("/service/<svc>", methods=["GET", "POST"])
@login_required
def service(svc):
    u = current_user()
    if svc not in SVC_NAMES: return redirect(url_for("services"))
    if not can_use(u): flash("⚠️", "warn"); return redirect(url_for("index"))
    st = user_status(u); lims = user_limits(u); lo, hi = lims[svc]
    cd = cooldown_left(u)
    if st == "free" and cd > 0:
        h, m = cd // 3600, (cd % 3600) // 60
        flash(f"⏰ بعد: {h}س {m}د", "warn"); return redirect(url_for("index"))
    if svc == "views" and st == "free" and not can_use_free_views(u):
        flash("❌ استنفدت المشاهدات", "danger"); return redirect(url_for("services"))

    if request.method == "POST":
        target = (request.form.get("target") or "").strip()
        try: amount = int(request.form.get("amount") or 0)
        except: amount = 0
        if not target: flash("❌ أدخل الهدف", "danger")
        elif svc == "followers" and len(target.lstrip("@")) < 2: flash("❌ اسم غير صحيح", "danger")
        elif svc != "followers" and "tiktok.com" not in target: flash("❌ رابط غير صحيح", "danger")
        elif amount < lo or amount > hi: flash(f"❌ الكمية: {lo} - {hi:,}", "danger")
        else:
            if svc == "followers": target = target.lstrip("@")
            try: oid, pool_id, err = execute_order(svc, amount, target)
            except Exception as e: oid, pool_id, err = None, None, str(e)
            if oid:
                try:
                    order_add(u["id"], svc, target, amount, oid, pool_id, "pending", source="service")
                    upd = {"last_use": datetime.now().isoformat(),
                           "total_uses": (u.get("total_uses") or 0) + 1}
                    if svc == "views" and st == "free":
                        upd["views_used"] = (u.get("views_used") or 0) + 1
                    user_upd(u["id"], **upd)
                except: pass
                body = f'''
                <div class="success-page">
                  <div class="big-emo">✅</div>
                  <h1>تم إرسال طلبك بنجاح</h1>
                  <p>بدأ التنفيذ — تابع النتيجة في حسابك على TikTok أو من صفحة الطلبات</p>
                  <div class="details">
                    <div class="row"><span class="lbl">🛍️ الخدمة</span><span class="val">{SVC_EMO[svc]} {SVC_NAMES[svc]}</span></div>
                    <div class="row"><span class="lbl">🎯 الهدف</span><span class="val"><code>{target[:32]}</code></span></div>
                    <div class="row"><span class="lbl">🔢 الكمية</span><span class="val">{amount}</span></div>
                  </div>
                  <div class="grid g2" style="margin-top:20px">
                    <a href="/orders" class="btn btn-primary btn-block">📋 طلباتي</a>
                    <a href="/services" class="btn btn-ghost btn-block">🛍️ طلب آخر</a>
                  </div>
                </div>'''
                return render(body, "تم", u)
            flash(f"❌ {err}", "danger")

    cd_note = ""
    if st == "free":
        cd_note = f'<div class="alert alert-info">⏰ بعد هذا الاستخدام ينتظر {COOLDOWN_HOURS} ساعات</div>'

    body = f'''
    <div class="card glow" style="max-width:560px;margin:0 auto">
      <div style="font-size:56px;text-align:center;line-height:1">{SVC_EMO[svc]}</div>
      <h2 style="justify-content:center;text-align:center;margin-top:10px">{SVC_NAMES[svc]}</h2>
      <p style="text-align:center;color:#94a3b8;margin-bottom:16px">المدى: <code>{lo}</code> - <code>{hi:,}</code></p>
      {cd_note}
      <form method="POST">
        <label>🎯 {SVC_TGT[svc]}</label>
        <input name="target" required placeholder="{SVC_TGT[svc]}">
        <label>🔢 الكمية</label>
        <input name="amount" type="number" min="{lo}" max="{hi}" value="{hi}" required>
        <div style="height:16px"></div>
        <button class="btn btn-primary btn-block btn-lg">🚀 إرسال</button>
      </form>
      <a href="/services" class="btn btn-ghost btn-block" style="margin-top:10px">🔙 رجوع</a>
    </div>'''
    return render(body, SVC_NAMES[svc], u)

# ═══════════════ Blast ═══════════════
@app.route("/blast", methods=["GET", "POST"])
@login_required
def blast():
    try:
        u = current_user()
        if not can_use(u): flash("⚠️", "warn"); return redirect(url_for("index"))
        st = user_status(u); lims = user_limits(u)
        max_active = FREE_BLAST_MAX_ACTIVE if st == "free" else VIP_BLAST_MAX_ACTIVE
        min_hours = FREE_BLAST_MIN_HOURS if st == "free" else VIP_BLAST_MIN_HOURS
        active_now = blast_all(u["id"], "active")

        if st == "free" and cooldown_left(u) > 0:
            cd = cooldown_left(u)
            h, m = cd // 3600, (cd % 3600) // 60
            flash(f"⏰ بعد: {h}س {m}د", "warn"); return redirect(url_for("index"))

        if request.method == "POST":
            if len(active_now) >= max_active:
                flash(f"❌ الحد الأقصى: {max_active} مهمة", "danger"); return redirect(url_for("blast"))
            svc = request.form.get("service")
            target = (request.form.get("target") or "").strip()
            try: amount = int(request.form.get("amount") or 0)
            except: amount = 0
            try: hours = int(request.form.get("hours") or min_hours)
            except: hours = min_hours
            if svc not in lims: flash("❌ خدمة غير صحيحة", "danger")
            else:
                lo, hi = lims[svc]
                if amount < lo or amount > hi: flash(f"❌ {lo}-{hi}", "danger")
                elif st == "free" and hours < min_hours: flash(f"❌ الأدنى {min_hours}س", "danger")
                elif hours < 1 or hours > 24: flash("❌", "danger")
                else:
                    if svc == "followers": target = target.lstrip("@")
                    ok, err = blast_run_first_now(u["id"], svc, target, amount)
                    if not ok:
                        flash(f"❌ فشل: {err}", "danger"); return redirect(url_for("blast"))
                    tid = str(uuid.uuid4())[:16]
                    blast_add(tid, u["id"], svc, target, amount, hours)
                    blast_inc(tid, (datetime.now() + timedelta(hours=hours)).isoformat())
                    blast_start(tid)
                    upd = {"last_use": datetime.now().isoformat(),
                           "total_uses": (u.get("total_uses") or 0) + 1}
                    user_upd(u["id"], **upd)
                    body = f'''
                    <div class="success-page">
                      <div class="big-emo">🚀</div>
                      <h1>تم الرشق بنجاح</h1>
                      <p style="font-size:16px;color:#a5f3fc;font-weight:800;margin-top:16px">
                        🎯 تابع الرشق في حسابك
                      </p>
                      <p style="margin-top:8px">البوت يستمر بالرشق تلقائياً كل {hours} ساعة</p>
                      <div class="details">
                        <div class="row"><span class="lbl">🛍️ الخدمة</span><span class="val">{SVC_EMO[svc]} {SVC_NAMES[svc]}</span></div>
                        <div class="row"><span class="lbl">🎯 الهدف</span><span class="val"><code>{target[:32]}</code></span></div>
                        <div class="row"><span class="lbl">🔢 الكمية/رشقة</span><span class="val">{amount}</span></div>
                        <div class="row"><span class="lbl">⏰ التكرار</span><span class="val">كل {hours} ساعة</span></div>
                      </div>
                      <div class="grid g2" style="margin-top:20px">
                        <a href="/blast" class="btn btn-pink btn-block">🚀 مهامي</a>
                        <a href="/orders" class="btn btn-ghost btn-block">📋 طلباتي</a>
                      </div>
                    </div>'''
                    return render(body, "تم الرشق", u)

        tasks = blast_all(u["id"])
        active = [t for t in tasks if t["status"] == "active"]
        stopped = [t for t in tasks if t["status"] == "stopped"]
        def row(t, is_a):
            try:
                btn = (f'<a href="/blast/stop/{t["task_id"]}" class="btn btn-pink btn-sm" onclick="return confirm(\'إيقاف؟\')">⏹</a>'
                       if is_a else f'<a href="/blast/delete/{t["task_id"]}" class="btn btn-ghost btn-sm" onclick="return confirm(\'حذف؟\')">🗑</a>')
                return f'<tr><td>{SVC_EMO.get(t["service"],"")} {SVC_NAMES.get(t["service"])}</td><td><code>{(t["target"] or "")[:24]}</code></td><td>{t["amount"]}</td><td>{t["hours"]}h</td><td>{t.get("run_count",0)}</td><td>{btn}</td></tr>'
            except: return ''
        ar = "".join(row(t, True) for t in active) or '<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:20px">لا توجد</td></tr>'
        sr = "".join(row(t, False) for t in stopped) or '<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:20px">لا توجد</td></tr>'

        hours_opts = ""
        for h in [1,2,3,4,5,6,8,12,24]:
            if st == "free" and h < min_hours: continue
            sel = " selected" if h == min_hours else ""
            hours_opts += f'<option value="{h}"{sel}>كل {h} ساعة</option>'

        body = f'''
        <div class="card glow">
          <h2>🚀 الرشق التلقائي</h2>
          <p style="color:#cbd5e1;font-size:13.5px">يُنفّذ فوراً عند الضغط ثم يكرر تلقائياً</p>
          <form method="POST" style="margin-top:14px">
            <label>🛍️ الخدمة</label>
            <select name="service">
              <option value="followers">👥 متابعين</option>
              <option value="likes">❤️ لايكات</option>
              <option value="views">👁️ مشاهدات</option>
              <option value="comments">💬 تعليقات</option>
            </select>
            <label>🎯 الهدف</label>
            <input name="target" required>
            <label>🔢 الكمية/رشقة</label>
            <input name="amount" type="number" min="1" value="20" required>
            <label>⏰ الفاصل</label>
            <select name="hours">{hours_opts}</select>
            <div style="height:16px"></div>
            <button class="btn btn-pink btn-block btn-lg">🚀 ابدأ الآن</button>
          </form>
        </div>
        <div class="card"><h2>🟢 المهام النشطة ({len(active)})</h2>
          <table><tr><th>الخدمة</th><th>الهدف</th><th>الكمية</th><th>الفاصل</th><th>الرشقات</th><th></th></tr>{ar}</table></div>
        <div class="card"><h2>🔴 الموقوفة ({len(stopped)})</h2>
          <table><tr><th>الخدمة</th><th>الهدف</th><th>الكمية</th><th>الفاصل</th><th>الرشقات</th><th></th></tr>{sr}</table></div>'''
        return render(body, "الرشق", u)
    except Exception as e:
        log.error(f"blast: {e}\n{traceback.format_exc()}")
        flash(f"⚠️ {str(e)[:80]}", "danger"); return redirect(url_for("index"))

@app.route("/blast/stop/<tid>")
def blast_stop_route(tid):
    blast_stop(tid); flash("⏹ تم الإيقاف", "info"); return redirect(url_for("blast"))

@app.route("/blast/delete/<tid>")
def blast_del_route(tid):
    blast_del(tid); flash("🗑 تم الحذف", "info"); return redirect(url_for("blast"))

# ═══════════════ Orders (رجعت!) ═══════════════
@app.route("/orders")
@login_required
def orders():
    u = current_user()
    items = order_all(u["id"])
    total = len(items)
    pending_c = sum(1 for o in items if o.get("status") == "pending")
    completed_c = sum(1 for o in items if o.get("status") == "completed")

    rows = ""
    for o in items:
        st = o.get("status","pending")
        badge = {"pending":"badge-pending","processing":"badge-processing",
                 "completed":"badge-completed","failed":"badge-failed"}.get(st,"badge-pending")
        st_txt = {"pending":"⏳ انتظار","processing":"🔄 تنفيذ",
                  "completed":"✅ مكتمل","failed":"❌ فشل"}.get(st, st)
        src_badge = ' <span class="badge badge-blast">🚀 رشق</span>' if o.get("source") == "blast" else ''
        rows += f'''<tr>
          <td>{SVC_EMO.get(o.get("service"),"")} {SVC_NAMES.get(o.get("service"),"")}</td>
          <td><code>{(o.get("target") or "")[:28]}</code></td>
          <td>{o.get("amount",0)}</td>
          <td><span class="badge {badge}">{st_txt}</span>{src_badge}</td>
          <td style="color:#64748b;font-size:11.5px">{(o.get("created_at") or "")[:16]}</td>
        </tr>'''
    if not rows:
        rows = '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:40px">لا توجد طلبات بعد<br><a href="/services" style="color:#a855f7">ابدأ من هنا ←</a></td></tr>'

    body = f'''
    <div class="card glow"><h2>📋 طلباتي</h2>
      <div class="grid g3" style="margin-top:12px">
        <div class="stat"><div class="num">{total}</div><div class="lbl">📊 الكل</div></div>
        <div class="stat"><div class="num">{pending_c}</div><div class="lbl">⏳ انتظار</div></div>
        <div class="stat"><div class="num">{completed_c}</div><div class="lbl">✅ مكتمل</div></div>
      </div>
    </div>
    <div class="card">
      <table>
        <tr><th>الخدمة</th><th>الهدف</th><th>الكمية</th><th>الحالة</th><th>التاريخ</th></tr>
        {rows}
      </table>
    </div>'''
    return render(body, "طلباتي", u)

# ═══════════════ Messages / Help ═══════════════
@app.route("/messages")
@login_required
def messages():
    u = current_user()
    try: msg_mark_read(u["id"])
    except: pass
    try: items = msg_all_for(u["id"], 100)
    except: items = []
    html = ""
    for m in items:
        cls = "msg-admin" if m.get("from_admin") else "msg-user"
        html += f'<div class="msg-item {cls}">{m["text"]}<span class="msg-time">{m["created_at"][:16]}</span></div>'
    if not items: html = '<p style="color:#94a3b8;text-align:center;padding:30px">لا توجد رسائل</p>'
    body = f'''
    <div class="card glow"><h2>📨 الرسائل</h2>
      <p style="color:#cbd5e1;font-size:13.5px;margin-bottom:16px">هنا تصلك رسائل المطور</p>{html}</div>
    <div class="card"><h2>💬 أرسل رسالة</h2>
      <form method="POST" action="/help">
        <label>📝 رسالتك</label>
        <textarea name="message" required></textarea>
        <div style="height:16px"></div>
        <button class="btn btn-cyan btn-block">📨 إرسال</button>
      </form>
    </div>'''
    return render(body, "الرسائل", u)

@app.route("/help", methods=["GET", "POST"])
def help_page():
    u = current_user()
    if request.method == "POST":
        if not u:
            flash("🔐 سجل دخول أولاً", "warn"); return redirect(url_for("login"))
        msg = (request.form.get("message") or "").strip()
        if len(msg) < 3: flash("❌ قصيرة", "danger")
        else:
            try:
                ticket_add(u["id"], u["username"], msg)
                msg_add(u["id"], u["username"], msg, from_admin=False)
                notify_admin(f"📨 *رسالة دعم*\n\n👤 `{u['username']}`\n🆔 `{u['id']}`\n\n💬 {msg}")
            except: pass
            flash("✅ تم الإرسال", "success"); return redirect(url_for("messages"))
    body = f'''
    <div class="card glow"><h2>💬 الدعم</h2>
      <p style="color:#cbd5e1;font-size:13.5px">سيتلقى الفريق رسالتك فوراً</p>
      {f'<p style="margin-top:10px"><b>معرّفك:</b> <code>{u["username"]}</code></p>' if u else ""}
      <form method="POST" style="margin-top:16px">
        <label>📝 رسالتك</label>
        <textarea name="message" required placeholder="اكتب مشكلتك أو استفسارك..."></textarea>
        <div style="height:16px"></div>
        <button class="btn btn-cyan btn-block">📨 إرسال</button>
      </form>
    </div>
    <div class="card"><h2>👑 ترقية VIP</h2>
      <ul class="feat">
        <li>متابعين حتى 100,000</li><li>لايكات حتى 100,000</li>
        <li>مشاهدات حتى 1,000,000</li><li>تعليقات حتى 100,000</li>
        <li>رشق تلقائي كل ساعة ♾️</li><li>بلا كولداون</li>
      </ul>
      <a href="{VIP_CONTACT_LINK}" target="_blank" class="btn btn-gold btn-block">👑 {VIP_CONTACT}</a>
    </div>'''
    return render(body, "الدعم", u)

@app.route("/about")
def about():
    try:
        path = os.path.join(os.path.dirname(__file__), "landing.html")
        return send_file(path)
    except: return redirect(url_for("index"))

# ═══════════════════════════════════════════════════════════
#                    🤖 تليجرام
# ═══════════════════════════════════════════════════════════
def is_admin(uid): return uid == ADMIN_CHAT_ID

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات", callback_data="stats"),
         InlineKeyboardButton("🔍 بحث", callback_data="search")],
        [InlineKeyboardButton("👥 المستخدمون", callback_data="users")],
        [InlineKeyboardButton("🏦 حسابات TikTok", callback_data="pool")],
        [InlineKeyboardButton("💎 الباقات", callback_data="plans"),
         InlineKeyboardButton("📦 الطلبات", callback_data="orders")],
        [InlineKeyboardButton("🎫 رسائل الدعم", callback_data="tickets")],
        [InlineKeyboardButton("🌱 تجميع الكل", callback_data="farm_all"),
         InlineKeyboardButton("⏹ إيقاف الكل", callback_data="farm_stop_all")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="home")],
    ])

def kb_back(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="home")]])

def fmt_dur(sec):
    if sec <= 0: return "✅ متاح"
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}س {m}د"

async def send(update, text, kb=None):
    try:
        if update.callback_query:
            try: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            except:
                try: await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
                except: pass
        else:
            try: await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
            except: pass
    except: pass

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 بوت خاص بالمطور."); return
    await update.message.reply_text("👑 *لوحة تحكم المطور*\n\nTikTok Spark v21.0",
        reply_markup=kb_main(), parse_mode="Markdown")

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    await q.answer()
    d = q.data
    if d == "home": await send(update, "👑 *لوحة التحكم*", kb_main()); return

    if d == "stats":
        users = user_all(); pool = pool_all()
        sc = {}
        for u in users:
            s = user_status(u); sc[s] = sc.get(s, 0) + 1
        total_pts = sum((p.get("points") or 0) for p in pool)
        text = (f"📊 *الإحصائيات*\n\n👥 إجمالي المستخدمين: `{len(users)}`\n"
                f"🎁 مجاني: `{sc.get('free',0)}`\n👑 VIP: `{sc.get('vip',0)}`\n"
                f"⌛ منتهي: `{sc.get('expired',0)}`\n🚫 محظور: `{sc.get('banned',0)}`\n\n"
                f"🏦 Pool: `{len(pool)}` حساب · `{total_pts}` نقطة\n"
                f"🌱 تجميع: `{len(FARM_THREADS)}`\n"
                f"📦 طلبات: `{len(order_all(None,10000))}`")
        await send(update, text, kb_back()); return

    if d == "search":
        ctx.user_data["step"] = "search"
        await send(update, "🔍 أرسل اسم المستخدم:", InlineKeyboardMarkup([[InlineKeyboardButton("❌", callback_data="home")]])); return

    if d == "users":
        rows = user_all()[:20]
        if not rows: await send(update, "👥 لا يوجد", kb_back()); return
        kb = []
        for u in rows:
            st = user_status(u)
            emo = {"vip":"👑","free":"🎁","expired":"⌛","banned":"🚫"}.get(st,"❓")
            try: unread = msg_unread(u["id"])
            except: unread = 0
            sfx = f" 📨{unread}" if unread else ""
            kb.append([InlineKeyboardButton(f"{emo} {u['username']}{sfx}", callback_data=f"u_{u['id']}")])
        kb.append([InlineKeyboardButton("🔙", callback_data="home")])
        await send(update, f"👥 آخر {len(rows)}", InlineKeyboardMarkup(kb)); return

    if d.startswith("u_") and not any(d.startswith(f"u_{x}_") for x in ["free","vip","ban","del","reset","msg"]):
        try: uid = int(d.split("_")[1]); await show_user(update, uid)
        except: pass
        return

    if d.startswith("u_free_"):
        uid = int(d.split("_")[2]); user_activate_free(uid)
        await q.answer("🎁"); await show_user(update, uid); return

    if d.startswith("u_vip_"):
        uid = int(d.split("_")[2])
        plans = plan_all()
        days = plans[0]["duration_days"] if plans else 30
        name = plans[0]["name"] if plans else "VIP"
        user_activate_vip(uid, days, name)
        await q.answer(f"👑 {days}"); await show_user(update, uid); return

    if d.startswith("u_ban_"):
        uid = int(d.split("_")[2]); u = user_get(uid)
        user_ban(uid, u["status"] != "banned")
        await q.answer("✅"); await show_user(update, uid); return

    if d.startswith("u_del_"):
        uid = int(d.split("_")[2]); user_del(uid)
        await q.answer("🗑"); await send(update, "👑", kb_main()); return

    if d.startswith("u_reset_"):
        uid = int(d.split("_")[2])
        user_upd(uid, last_use=None, views_used=0, total_uses=0)
        await q.answer("🔄"); await show_user(update, uid); return

    if d.startswith("u_msg_"):
        uid = int(d.split("_")[2])
        ctx.user_data["step"] = "msg_to"; ctx.user_data["msg_to_uid"] = uid
        u = user_get(uid)
        await send(update, f"📨 رسالة إلى `{u['username']}`\n\n✍️ اكتب النص:",
                   InlineKeyboardMarkup([[InlineKeyboardButton("❌", callback_data=f"u_{uid}")]])); return

    if d == "pool": await pool_menu(update); return
    if d == "pool_add":
        ctx.user_data["step"] = "pool_add"
        await send(update, "➕ أرسل:\n`username password`",
                   InlineKeyboardMarkup([[InlineKeyboardButton("❌", callback_data="pool")]])); return
    if d.startswith("pool_"):
        parts = d.split("_")
        if len(parts) >= 3 and parts[2].isdigit():
            action, aid = parts[1], int(parts[2])
            if action == "farm": farm_start(aid); await q.answer("🌱"); await pool_menu(update); return
            if action == "stop": farm_stop(aid); await q.answer("⏹"); await pool_menu(update); return
            if action == "login":
                c = pool_login(aid)
                await q.answer(f"✅ {c['points']}" if c else "❌", show_alert=True)
                await pool_menu(update); return
            if action == "del": farm_stop(aid); pool_del(aid); await q.answer("🗑"); await pool_menu(update); return
    if d == "farm_all": farm_start_all(); await q.answer("🌱"); await pool_menu(update); return
    if d == "farm_stop_all": farm_stop_all(); await q.answer("⏹"); await pool_menu(update); return
    if d == "pool_refresh": pool_refresh_all(); await q.answer("🔄"); await pool_menu(update); return

    if d == "plans": await plans_menu(update); return
    if d == "plan_add":
        ctx.user_data["step"] = "plan_add"
        await send(update, "➕ أرسل: `الاسم الأيام السعر`",
                   InlineKeyboardMarkup([[InlineKeyboardButton("❌", callback_data="plans")]])); return
    if d.startswith("plan_del_"):
        pid = int(d.split("_")[2]); plan_del(pid)
        await q.answer("🗑"); await plans_menu(update); return

    if d == "orders":
        rows = order_all(None, 20)
        if not rows: await send(update, "📦 لا يوجد", kb_back()); return
        text = "📦 *آخر الطلبات*\n\n"
        for o in rows[:12]:
            u = user_get(o["user_id"])
            src = "🚀" if o.get("source") == "blast" else "🛍️"
            text += f"{src} #{o['id']} · `{u['username'] if u else '?'}` · {SVC_NAMES.get(o['service'])} · {o['amount']} · {o['status']}\n"
        await send(update, text, kb_back()); return

    if d == "tickets":
        rows = ticket_all(20)
        if not rows: await send(update, "🎫 لا يوجد", kb_back()); return
        text = "🎫 *رسائل الدعم*\n\n"
        for t in rows[:6]:
            text += f"👤 `{t['code']}` · {t['created_at'][:16]}\n💬 {t['message'][:80]}\n\n"
        await send(update, text, kb_back()); return

async def show_user(update, uid):
    u = user_get(uid)
    if not u: await send(update, "❌", kb_back()); return
    st = user_status(u)
    emo = {"vip":"👑","free":"🎁","expired":"⌛","banned":"🚫"}.get(st,"❓")
    cd = cooldown_left(u)
    text = f"{emo} *{u['username']}*\n\n🆔 `{u['id']}`\n📌 `{st}`\n"
    if u.get("tiktok_username"): text += f"📱 TikTok: `{u['tiktok_username']}`\n"
    if u.get("auto_farm"): text += f"🌱 التجميع: مفعّل\n"
    if u.get("free_expires"): text += f"🎁 `{u['free_expires'][:16]}`\n"
    if u.get("vip_expires"): text += f"👑 `{u['vip_expires'][:16]}`\n"
    if st == "free":
        text += f"⏰ `{fmt_dur(cd)}`\n"
        text += f"👁️ `{u.get('views_used',0)}/{VIEWS_MAX_USES}`\n"
    text += f"📊 `{u.get('total_uses',0)}`\n📅 `{u['created_at'][:16]}`"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 إرسال رسالة", callback_data=f"u_msg_{uid}")],
        [InlineKeyboardButton("🎁 تفعيل مجاني", callback_data=f"u_free_{uid}"),
         InlineKeyboardButton("👑 تفعيل VIP", callback_data=f"u_vip_{uid}")],
        [InlineKeyboardButton("🔄 إعادة ضبط", callback_data=f"u_reset_{uid}")],
        [InlineKeyboardButton("🚫 حظر" if st != "banned" else "🟢 فك", callback_data=f"u_ban_{uid}"),
         InlineKeyboardButton("🗑 حذف", callback_data=f"u_del_{uid}")],
        [InlineKeyboardButton("🔙", callback_data="home")],
    ])
    await send(update, text, kb)

async def pool_menu(update):
    rows = pool_all()
    text = "🏦 *حسابات TikTok (Pool)*\n\n"
    if not rows: text += "_لا توجد — أضف حساباً_"
    else:
        total = sum((r.get("points") or 0) for r in rows)
        text += f"📊 `{len(rows)}` حساب · `{total}` نقطة\n\n"
        for r in rows[:8]:
            is_f = farm_running(r["id"])
            st = "🌱" if is_f else ("✅" if r["status"]=="active" else "☠")
            owner = f"👤 U#{r.get('owner_id',0)}" if r.get("owner_type") == "user" else "👑 admin"
            text += f"*#{r['id']}* {st} · {owner}\n👤 `{r['username']}`\n🔑 `{r['password']}`\n💰 `{r['points']}`\n\n"
    kb = [
        [InlineKeyboardButton("➕ إضافة", callback_data="pool_add"),
         InlineKeyboardButton("🔄 تحديث", callback_data="pool_refresh")],
        [InlineKeyboardButton("🌱 تجميع الكل", callback_data="farm_all"),
         InlineKeyboardButton("⏹ إيقاف الكل", callback_data="farm_stop_all")],
    ]
    for r in rows[:10]:
        is_f = farm_running(r["id"])
        bf = (InlineKeyboardButton("⏹", callback_data=f"pool_stop_{r['id']}")
              if is_f else InlineKeyboardButton("🌱", callback_data=f"pool_farm_{r['id']}"))
        kb.append([
            InlineKeyboardButton(f"#{r['id']}", callback_data=f"pool_login_{r['id']}"),
            InlineKeyboardButton(r["username"][:12], callback_data=f"pool_login_{r['id']}"),
            bf,
            InlineKeyboardButton("🗑", callback_data=f"pool_del_{r['id']}"),
        ])
    kb.append([InlineKeyboardButton("🔙", callback_data="home")])
    await send(update, text, InlineKeyboardMarkup(kb))

async def plans_menu(update):
    rows = plan_all()
    text = "💎 *الباقات*\n\n"
    if rows:
        for p in rows: text += f"• *{p['name']}* · {p['duration_days']} يوم · `{p['price']}`\n"
    else: text += "_لا توجد_"
    kb = [[InlineKeyboardButton("➕ إضافة", callback_data="plan_add")]]
    for p in rows:
        kb.append([InlineKeyboardButton(f"🗑 {p['name']}", callback_data=f"plan_del_{p['id']}")])
    kb.append([InlineKeyboardButton("🔙", callback_data="home")])
    await send(update, text, InlineKeyboardMarkup(kb))

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    step = ctx.user_data.get("step")
    text = update.message.text.strip()

    if step == "search":
        ctx.user_data.pop("step", None)
        u = user_by_name(text.lower()) or user_by_name(text)
        if not u:
            await update.message.reply_text(f"❌ `{text}`", parse_mode="Markdown", reply_markup=kb_back()); return
        class F:
            callback_query = None
            message = update.message
            effective_user = update.effective_user
        await show_user(F(), u["id"]); return

    if step == "msg_to":
        uid = ctx.user_data.get("msg_to_uid")
        u = user_get(uid)
        if not u:
            await update.message.reply_text("❌"); ctx.user_data.pop("step", None); return
        msg_add(uid, u["username"], text, from_admin=True)
        ctx.user_data.pop("step", None); ctx.user_data.pop("msg_to_uid", None)
        await update.message.reply_text(
            f"✅ تم الإرسال إلى `{u['username']}`", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 أخرى", callback_data=f"u_msg_{uid}")],
                [InlineKeyboardButton("🔙", callback_data=f"u_{uid}")],
            ])); return

    if step == "pool_add":
        parts = text.split(None, 1)
        if len(parts) < 2:
            await update.message.reply_text("❌ `username password`", parse_mode="Markdown"); return
        u, p = parts[0].lstrip("@"), parts[1]
        aid = pool_add(u, p, owner_id=0, owner_type="admin")
        ctx.user_data.pop("step", None)
        await update.message.reply_text(f"⏳ تسجيل دخول `{u}`...", parse_mode="Markdown")
        c = pool_login(aid)
        if c:
            await update.message.reply_text(
                f"✅ *تم*\n\n👤 `{u}`\n🔑 `{p}`\n💰 `{c['points']}` نقطة",
                parse_mode="Markdown", reply_markup=kb_back())
        else:
            await update.message.reply_text(f"⚠️ فشل الدخول", reply_markup=kb_back())
        return

    if step == "plan_add":
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text("❌ `الاسم الأيام السعر`", parse_mode="Markdown"); return
        name = " ".join(parts[:-2])
        try: days = int(parts[-2])
        except: await update.message.reply_text("❌"); return
        plan_add(name, days, parts[-1])
        ctx.user_data.pop("step", None)
        await update.message.reply_text(f"✅ *{name}*", parse_mode="Markdown", reply_markup=kb_back()); return

    await update.message.reply_text("اختر من /start", reply_markup=kb_main())

async def run_bot():
    bot = Application.builder().token(BOT_TOKEN).build()
    bot.add_handler(CommandHandler("start", cmd_start))
    bot.add_handler(CallbackQueryHandler(cb_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    await bot.initialize()
    await bot.start()
    await bot.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    log.info("🤖 Bot started")
    stop = asyncio.Event(); await stop.wait()

def run_bot_thread():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    try: loop.run_until_complete(run_bot())
    except Exception as e: log.error(f"bot: {e}\n{traceback.format_exc()}")

def run_web():
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, threaded=True)

# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  ⚡ TikTok Spark v21.0 — Users + Guide + Farm")
    log.info("=" * 60)
    if os.environ.get("FRESH_DB") == "1" and os.path.exists(DB_PATH):
        os.remove(DB_PATH); log.warning("🗑 DB removed")
    try: init_db()
    except Exception as e:
        log.error(f"init_db: {e}\n{traceback.format_exc()}"); sys.exit(1)
    log.info("🔄 Refreshing pool...")
    try:
        n = pool_refresh_all()
        log.info(f"✅ {n} حساب TikTok جاهز")
    except Exception as e: log.error(f"pool: {e}")
    threading.Thread(target=run_bot_thread, daemon=True).start()
    log.info("🤖 Bot started")
    threading.Thread(target=run_web, daemon=True).start()
    log.info(f"🌐 http://0.0.0.0:{WEB_PORT}")
    log.info("=" * 60)
    while True:
        try: time.sleep(60)
        except KeyboardInterrupt:
            log.info("bye"); sys.exit(0)