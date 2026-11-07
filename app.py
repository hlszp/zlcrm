#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PVD 工厂经营系统：合同财务、生产质量、成本风险与老板驾驶舱。"""
import os
import functools
import sqlite3
import datetime
import secrets
import math
import json
from flask import Flask, request, jsonify, session, g, send_from_directory, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from finance import balance_totals, contract_balances
from process import validate_parameters, validate_steps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.abspath(os.environ.get("CRM_DB", os.path.join(DATA_DIR, "crm.db")))
UPLOAD_DIR = os.path.abspath(os.environ.get("CRM_UPLOAD_DIR", os.path.join(os.path.dirname(DB_PATH), "uploads")))
os.makedirs(UPLOAD_DIR, exist_ok=True)

IS_PRODUCTION = os.environ.get("CRM_ENV", "").lower() == "production"
CRM_SECRET = os.environ.get("CRM_SECRET")
if IS_PRODUCTION and not CRM_SECRET:
    raise RuntimeError("生产环境必须设置 CRM_SECRET")

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = CRM_SECRET or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION or os.environ.get("CRM_COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
)


@app.after_request
def protect_response(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


CONTRACT_STATUS = ["草拟", "已签", "履约中", "已完成", "已归档"]  # 兼容旧数据的兜底
INVOICE_TYPES = ["增值税普通发票", "增值税专用发票", "收据", "其他"]
COST_CATEGORIES = ["靶材气体", "电费", "人工", "前处理", "挂具摊销", "检测", "运输", "外协", "返工", "赔偿", "其他"]
REMIND_DAYS = 7  # 到期前 N 天进入提醒


def dict_labels(db, type_code, active_only=True):
    sql = "SELECT label FROM dict_items WHERE type_code=?"
    if active_only:
        sql += " AND active=1"
    return [r[0] for r in db.execute(sql + " ORDER BY sort,id", (type_code,))]


def valid_status(db, ctype, status):
    labels = dict_labels(db, f"contract_status_{ctype}")
    if not labels:
        return True  # 字典未配置时不限制
    return status in labels


# ---------------- DB ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_e=None):
    db = g.pop("db", None)
    if db:
        db.close()


DICT_SEED = {
    "contract_status_product": ("产品合同状态", ["草拟", "已签", "备货中", "部分发货", "已发完", "已完成", "已归档"]),
    "contract_status_service": ("服务合同状态", ["草拟", "已签", "加工中", "部分交付", "已交付", "已完成", "已归档"]),
    "transport_method": ("运输方式", ["公司自送", "物流托运", "快递", "客户自提", "第三方包车"]),
    "coating_process": ("PVD镀膜工艺", ["TiN氮化钛(金色)", "CrN氮化铬(银灰)", "TiCN氮碳化钛(灰黑)",
                                        "TiAlN氮铝化钛(紫黑)", "DLC类金刚石(黑色)", "ZrN氮化锆(香槟金)",
                                        "离子镀玫瑰金", "离子镀黑枪色", "彩色镀膜", "复合涂层"]),
    "pay_method": ("收款方式", ["银行转账", "承兑汇票", "现金", "微信/支付宝", "其他"]),
    "service_type": ("服务类型", ["PVD镀膜", "刀具涂层", "模具涂层", "装饰镀膜", "功能涂层", "来料检测", "维保", "其他"]),
    "cost_category": ("成本类别", COST_CATEGORIES),
}


def migrate_v4(con):
    """v4 迁移：湿法电镀字典替换为等离子镀膜(PVD)行业字典"""
    if con.execute("SELECT COUNT(*) FROM dict_types WHERE code='plating_type'").fetchone()[0]:
        con.execute("DELETE FROM dict_items WHERE type_code='plating_type'")
        con.execute("DELETE FROM dict_types WHERE code='plating_type'")
        print("[migrate] 旧电镀行业字典已移除（plating_type）")
    con.commit()


def migrate_v3(con):
    """v3 迁移：contracts 去掉 status CHECK 并加 type/is_demo；customers 加 is_demo"""
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='contracts'").fetchone()[0]
    if "CHECK" in sql:
        con.executescript("""
        CREATE TABLE contracts_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          contract_no TEXT NOT NULL UNIQUE,
          customer_id INTEGER NOT NULL REFERENCES customers(id),
          title TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'product',
          amount REAL NOT NULL DEFAULT 0,
          sign_date TEXT DEFAULT '',
          delivery_date TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT '已签',
          owner_id INTEGER REFERENCES users(id),
          remark TEXT DEFAULT '',
          attachment TEXT DEFAULT '',
          is_demo INTEGER NOT NULL DEFAULT 0,
          created_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO contracts_new(id,contract_no,customer_id,title,type,amount,sign_date,
          delivery_date,status,owner_id,remark,attachment,created_by,created_at)
          SELECT id,contract_no,customer_id,title,'product',amount,sign_date,
          delivery_date,status,owner_id,remark,attachment,created_by,created_at FROM contracts;
        DROP TABLE contracts;
        ALTER TABLE contracts_new RENAME TO contracts;
        CREATE INDEX IF NOT EXISTS idx_contracts_customer ON contracts(customer_id);
        CREATE INDEX IF NOT EXISTS idx_contracts_owner ON contracts(owner_id);
        """)
        print("[migrate] contracts 表已重建（去除 status CHECK，新增 type/is_demo）")
    cust_cols = {r[1] for r in con.execute("PRAGMA table_info(customers)")}
    if "is_demo" not in cust_cols:
        con.execute("ALTER TABLE customers ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
    # 旧的单附件迁入附件表
    for r in con.execute(
            "SELECT id, attachment FROM contracts WHERE attachment != ''").fetchall():
        n = con.execute("SELECT COUNT(*) FROM contract_files WHERE contract_id=?",
                        (r[0],)).fetchone()[0]
        if n == 0:
            con.execute(
                "INSERT INTO contract_files(contract_id,filename,orig_name) VALUES(?,?,?)",
                (r[0], r[1], r[1].split("_", 2)[-1]))
    con.commit()


def migrate_v5(con):
    """v5 迁移：users 角色增加 manager（工厂经理）"""
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
    if "'manager'" not in sql:
        con.executescript("""
        CREATE TABLE users_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','sales','finance','manager')),
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO users_new(id,username,password_hash,name,role,active,created_at)
          SELECT id,username,password_hash,name,role,active,created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """)
        print("[migrate] users 表已重建（角色增加 manager 工厂经理）")
    con.commit()


def migrate_v6(con):
    for table in ("products", "services"):
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if "is_demo" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
        con.execute(f"UPDATE {table} SET is_demo=1 WHERE remark='演示数据'")
    duplicates = con.execute(
        "SELECT COUNT(*) FROM (SELECT invoice_no FROM invoices GROUP BY invoice_no HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if not duplicates:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_no_unique ON invoices(invoice_no)")
    else:
        print(f"[migrate] 存在 {duplicates} 组重复发票号，未创建唯一索引；请先人工核对")
    con.commit()


def migrate_v7(con):
    con.execute("BEGIN IMMEDIATE")
    con.execute(
        """INSERT INTO payment_allocations(payment_id,plan_id,amount,created_by,created_at)
           SELECT p.id,p.plan_id,p.amount,p.created_by,p.created_at FROM payments p
           WHERE p.plan_id IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM payment_allocations pa WHERE pa.payment_id=p.id)""")
    invoice_sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'").fetchone()[0]
    if "red_invoice_of" not in invoice_sql or "'红冲'" not in invoice_sql:
        con.executescript("""
        CREATE TABLE invoices_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
          invoice_no TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT '增值税普通发票',
          amount REAL NOT NULL,
          invoice_date TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT '已开' CHECK(status IN ('已开','作废','红冲')),
          red_invoice_of INTEGER REFERENCES invoices_new(id),
          remark TEXT DEFAULT '',
          created_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO invoices_new(id,contract_id,invoice_no,type,amount,invoice_date,status,remark,created_by,created_at)
          SELECT id,contract_id,invoice_no,type,amount,invoice_date,status,remark,created_by,created_at FROM invoices;
        DROP TABLE invoices;
        ALTER TABLE invoices_new RENAME TO invoices;
        """)
    duplicates = con.execute(
        "SELECT COUNT(*) FROM (SELECT invoice_no FROM invoices GROUP BY invoice_no HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if not duplicates:
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_no_unique ON invoices(invoice_no)")
    con.commit()


def migrate_v8(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(shipments)")}
    if "batch_id" not in cols:
        con.execute("ALTER TABLE shipments ADD COLUMN batch_id INTEGER REFERENCES material_batches(id)")
    con.commit()


def migrate_v9(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(customers)")}
    if "credit_limit" not in cols:
        con.execute("ALTER TABLE customers ADD COLUMN credit_limit REAL NOT NULL DEFAULT 0")
    if "credit_hold" not in cols:
        con.execute("ALTER TABLE customers ADD COLUMN credit_hold INTEGER NOT NULL DEFAULT 0")
    con.commit()


def migrate_v10(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(equipment)")}
    if "is_demo" not in cols:
        con.execute("ALTER TABLE equipment ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
    con.execute("UPDATE equipment SET is_demo=1 WHERE remark='演示设备'")
    con.commit()


def migrate_v11(con):
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
    if "'engineer'" not in sql:
        con.executescript("""
        CREATE TABLE users_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','sales','finance','manager','engineer')),
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO users_new(id,username,password_hash,name,role,active,created_at)
          SELECT id,username,password_hash,name,role,active,created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """)
    con.commit()


def seed_dicts(con):
    for code, (name, labels) in DICT_SEED.items():
        con.execute("INSERT OR IGNORE INTO dict_types(code,name,builtin) VALUES(?,?,1)", (code, name))
        for i, label in enumerate(labels, 1):
            con.execute("INSERT OR IGNORE INTO dict_items(type_code,label,sort) VALUES(?,?,?)",
                        (code, label, i * 10))
    con.commit()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    migrate_v3(con)
    migrate_v4(con)
    migrate_v5(con)
    migrate_v6(con)
    migrate_v7(con)
    migrate_v8(con)
    migrate_v9(con)
    migrate_v10(con)
    migrate_v11(con)
    seed_dicts(con)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        admin_password = os.environ.get("CRM_ADMIN_PASSWORD")
        if not admin_password:
            raise RuntimeError("首次初始化必须设置 CRM_ADMIN_PASSWORD")
        con.execute(
            "INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,?)",
            ("admin", generate_password_hash(admin_password), "管理员", "admin"),
        )
        con.commit()
        print("[init] 已创建初始账号 admin，请登录后立即修改密码")
    con.close()


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def row(cur):
    r = cur.fetchone()
    return dict(r) if r else None


# ---------------- 权限 ----------------
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute(
        "SELECT id,username,name,role FROM users WHERE id=? AND active=1", (uid,)
    ).fetchone()


def login_required(f):
    @functools.wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u:
            return jsonify({"error": "未登录"}), 401
        g.user = dict(u)
        return f(*a, **kw)
    return w


def roles_required(*roles):
    def deco(f):
        @functools.wraps(f)
        def w(*a, **kw):
            u = current_user()
            if not u:
                return jsonify({"error": "未登录"}), 401
            if u["role"] not in roles:
                return jsonify({"error": "无权执行该操作"}), 403
            g.user = dict(u)
            return f(*a, **kw)
        return w
    return deco


def admin_required(f):
    return roles_required("admin")(f)


def current_data_mode():
    if not getattr(g, "user", None) or g.user["role"] != "admin":
        return "real"
    return session.get("data_mode", "real")


def demo_sql(alias=""):
    p = f"{alias}." if alias else ""
    mode = current_data_mode()
    if mode == "all":
        return "", []
    return f" AND {p}is_demo=? ", [1 if mode == "demo" else 0]


def record_in_data_mode(is_demo):
    mode = current_data_mode()
    return mode == "all" or bool(is_demo) == (mode == "demo")


def scope_sql(alias=""):
    p = f"{alias}." if alias else ""
    where, params = "", []
    if g.user["role"] == "sales":
        where += f" AND {p}owner_id=? "
        params.append(g.user["id"])
    demo, demo_params = demo_sql(alias)
    return where + demo, params + demo_params


def owns_customer(cid):
    r = get_db().execute("SELECT owner_id,is_demo FROM customers WHERE id=?", (cid,)).fetchone()
    if not r or not record_in_data_mode(r["is_demo"]):
        return False
    return g.user["role"] != "sales" or r["owner_id"] == g.user["id"]


def owns_contract(cid):
    r = get_db().execute("SELECT owner_id,is_demo FROM contracts WHERE id=?", (cid,)).fetchone()
    if not r or not record_in_data_mode(r["is_demo"]):
        return False
    return g.user["role"] != "sales" or r["owner_id"] == g.user["id"]


def body():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    return data


def number(value, field, minimum=None, strictly=False):
    try:
        result = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是数字")
    if not math.isfinite(result):
        raise ValueError(f"{field}必须是有限数字")
    if minimum is not None and (result <= minimum if strictly else result < minimum):
        symbol = "大于" if strictly else "不小于"
        raise ValueError(f"{field}必须{symbol} {minimum}")
    return result


def valid_date(value, field="日期"):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{field}格式必须为 YYYY-MM-DD")


@app.errorhandler(ValueError)
def invalid_value(e):
    return jsonify({"error": str(e)}), 400


def write_audit(db, entity_type, entity_id, action, before=None, after=None, reason=""):
    db.execute(
        """INSERT INTO audit_logs(entity_type,entity_id,action,before_json,after_json,reason,actor_id)
           VALUES(?,?,?,?,?,?,?)""",
        (entity_type, entity_id, action,
         json.dumps(before, ensure_ascii=False, default=str) if before is not None else "",
         json.dumps(after, ensure_ascii=False, default=str) if after is not None else "",
         reason, g.user["id"]),
    )


def today():
    return datetime.date.today().isoformat()


# ---------------- 认证 ----------------
@app.post("/api/login")
def login():
    d = body()
    u = get_db().execute(
        "SELECT * FROM users WHERE username=? AND active=1", (d.get("username", ""),)
    ).fetchone()
    if not u or not check_password_hash(u["password_hash"], d.get("password", "")):
        return jsonify({"error": "用户名或密码错误"}), 401
    session.clear()
    session["uid"] = u["id"]
    return jsonify({"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    u = current_user()
    if not u:
        return jsonify({"error": "未登录"}), 401
    g.user = dict(u)
    return jsonify({**dict(u), "data_mode": current_data_mode()})


@app.put("/api/data-mode")
@admin_required
def set_data_mode():
    mode = body().get("mode")
    if mode not in ("real", "demo", "all"):
        return jsonify({"error": "数据模式无效"}), 400
    session["data_mode"] = mode
    return jsonify({"mode": mode})


@app.get("/api/settings/security")
@admin_required
def security_status():
    return jsonify({
        "production": IS_PRODUCTION,
        "secret_configured": bool(CRM_SECRET),
        "secure_cookie": app.config["SESSION_COOKIE_SECURE"],
    })


@app.post("/api/change-password")
@login_required
def change_password():
    d = body()
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if not check_password_hash(u["password_hash"], d.get("old_password", "")):
        return jsonify({"error": "原密码错误"}), 400
    if len(d.get("new_password", "")) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(d["new_password"]), g.user["id"]))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 用户管理（管理员） ----------------
@app.get("/api/users")
@roles_required("admin", "finance", "manager")
def list_users():
    return jsonify(rows(get_db().execute(
        "SELECT id,username,name,role,active,created_at FROM users ORDER BY id")))


@app.post("/api/users")
@admin_required
def create_user():
    d = body()
    if d.get("role") not in ("admin", "sales", "finance", "manager", "engineer"):
        return jsonify({"error": "角色无效"}), 400
    if not d.get("username") or len(d.get("password", "")) < 6:
        return jsonify({"error": "用户名必填，密码至少 6 位"}), 400
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users(username,password_hash,name,role) VALUES(?,?,?,?)",
            (d["username"], generate_password_hash(d["password"]), d.get("name") or d["username"], d["role"]),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "用户名已存在"}), 400


@app.put("/api/users/<int:uid>")
@admin_required
def update_user(uid):
    d = body()
    db = get_db()
    if d.get("password"):
        if len(d["password"]) < 6:
            return jsonify({"error": "密码至少 6 位"}), 400
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (generate_password_hash(d["password"]), uid))
    if "active" in d:
        if uid == g.user["id"] and not d["active"]:
            return jsonify({"error": "不能停用自己的账号"}), 400
        db.execute("UPDATE users SET active=? WHERE id=?", (1 if d["active"] else 0, uid))
    if d.get("name"):
        db.execute("UPDATE users SET name=? WHERE id=?", (d["name"], uid))
    if d.get("role") in ("admin", "sales", "finance", "manager", "engineer"):
        db.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 客户 ----------------
@app.get("/api/customers")
@login_required
def list_customers():
    kw = request.args.get("q", "").strip()
    scope, params = scope_sql("c")
    sql = f"""
      SELECT c.*, u.name AS owner_name
      FROM customers c LEFT JOIN users u ON u.id=c.owner_id
      WHERE 1=1 {scope}
    """
    if kw:
        sql += " AND (c.name LIKE ? OR c.contact LIKE ? OR c.phone LIKE ?)"
        params += [f"%{kw}%"] * 3
    sql += " ORDER BY c.id DESC"
    db = get_db()
    data = rows(db.execute(sql, params))
    contract_scope, contract_params = scope_sql("ct")
    totals = {}
    for item in contract_balances(db, contract_scope, contract_params):
        total = totals.setdefault(item["customer_id"], {"contracted": 0.0, "received": 0.0})
        total["contracted"] += item["amount"]
        total["received"] += item["received"]
    for c in data:
        total = totals.get(c["id"], {"contracted": 0, "received": 0})
        c["contracted"] = round(total["contracted"], 2)
        c["received"] = round(total["received"], 2)
        c["outstanding"] = round(c["contracted"] - c["received"], 2)
    return jsonify(data)


@app.post("/api/customers")
@roles_required("admin", "sales")
def create_customer():
    d = body()
    if not d.get("name"):
        return jsonify({"error": "客户名称必填"}), 400
    owner = d.get("owner_id") if g.user["role"] == "admin" and d.get("owner_id") else g.user["id"]
    cur = get_db().execute(
        """INSERT INTO customers(name,contact,phone,address,industry,level,owner_id,remark,is_demo,created_by)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (d["name"], d.get("contact", ""), d.get("phone", ""), d.get("address", ""),
         d.get("industry", ""), d.get("level", "B"), owner, d.get("remark", ""),
         1 if current_data_mode() == "demo" else 0, g.user["id"]),
    )
    get_db().commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.get("/api/customers/<int:cid>")
@login_required
def customer_detail(cid):
    db = get_db()
    if not owns_customer(cid):
        return jsonify({"error": "无权访问该客户"}), 403
    c = row(db.execute(
        """SELECT c.*, u.name AS owner_name FROM customers c
           LEFT JOIN users u ON u.id=c.owner_id WHERE c.id=?""", (cid,)))
    if not c:
        return jsonify({"error": "客户不存在"}), 404
    c["followups"] = rows(db.execute(
        """SELECT f.*, u.name AS created_by_name FROM followups f
           LEFT JOIN users u ON u.id=f.created_by
           WHERE f.customer_id=? ORDER BY f.id DESC LIMIT 50""", (cid,)))
    contract_scope, contract_params = scope_sql("ct")
    c["contracts"] = rows(db.execute(
        f"""SELECT ct.*,
             COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id),0) AS received,
             COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=ct.id AND i.status!='作废'),0) AS invoiced
           FROM contracts ct WHERE ct.customer_id=? {contract_scope} ORDER BY ct.id DESC""",
        [cid] + contract_params))
    c["received"] = round(sum(x["received"] for x in c["contracts"]), 2)
    c["contracted"] = round(sum(x["amount"] for x in c["contracts"]), 2)
    c["outstanding"] = round(c["contracted"] - c["received"], 2)
    return jsonify(c)


@app.put("/api/customers/<int:cid>")
@roles_required("admin", "sales", "finance")
def update_customer(cid):
    if not owns_customer(cid):
        return jsonify({"error": "无权修改该客户"}), 403
    d = body()
    credit_fields = {"credit_limit", "credit_hold"}
    if g.user["role"] == "sales" and credit_fields.intersection(d):
        return jsonify({"error": "业务无权修改信用额度或停接状态"}), 403
    if g.user["role"] == "finance" and any(k not in credit_fields for k in d):
        return jsonify({"error": "财务只能修改信用额度和停接状态"}), 403
    fields = ["name", "contact", "phone", "address", "industry", "level", "remark", "credit_limit"]
    sets, params = [], []
    for f in fields:
        if f in d:
            sets.append(f"{f}=?")
            params.append(number(d[f], "信用额度", 0) if f == "credit_limit" else d[f])
    if "credit_hold" in d:
        sets.append("credit_hold=?")
        params.append(1 if d["credit_hold"] in (1, True, "1", "true") else 0)
    if "owner_id" in d and g.user["role"] == "admin":
        sets.append("owner_id=?")
        params.append(d["owner_id"])
    if not sets:
        return jsonify({"error": "无更新内容"}), 400
    db = get_db()
    before = row(db.execute("SELECT * FROM customers WHERE id=?", (cid,)))
    db.execute(f"UPDATE customers SET {','.join(sets)} WHERE id=?", params)
    after = row(db.execute("SELECT * FROM customers WHERE id=?", (cid,)))
    if credit_fields.intersection(d):
        write_audit(db, "customer", cid, "credit_update", before, after)
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/customers/<int:cid>")
@admin_required
def delete_customer(cid):
    if not owns_customer(cid):
        return jsonify({"error": "客户不存在或无权删除"}), 403
    db = get_db()
    n = db.execute("SELECT COUNT(*) c FROM contracts WHERE customer_id=?", (cid,)).fetchone()["c"]
    if n:
        return jsonify({"error": f"该客户名下还有 {n} 份合同，不能删除"}), 400
    db.execute("DELETE FROM followups WHERE customer_id=?", (cid,))
    db.execute("DELETE FROM customers WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/customers/<int:cid>/followups")
@roles_required("admin", "sales")
def add_followup(cid):
    if not owns_customer(cid):
        return jsonify({"error": "无权访问该客户"}), 403
    d = body()
    if not d.get("content"):
        return jsonify({"error": "跟进内容必填"}), 400
    cur = get_db().execute(
        "INSERT INTO followups(customer_id,content,next_date,created_by) VALUES(?,?,?,?)",
        (cid, d["content"], d.get("next_date", ""), g.user["id"]),
    )
    get_db().commit()
    return jsonify({"id": cur.lastrowid}), 201


# ---------------- 合同 ----------------
@app.get("/api/contracts")
@login_required
def list_contracts():
    db = get_db()
    scope, params = scope_sql("ct")
    sql = f"""
      SELECT ct.*, c.name AS customer_name, u.name AS owner_name,
        COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id),0) AS received,
        COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=ct.id AND i.status!='作废'),0) AS invoiced
      FROM contracts ct
      JOIN customers c ON c.id=ct.customer_id
      LEFT JOIN users u ON u.id=ct.owner_id
      WHERE 1=1 {scope}
    """
    st = request.args.get("status", "")
    kw = request.args.get("q", "").strip()
    if st:
        sql += " AND ct.status=?"
        params.append(st)
    if kw:
        sql += " AND (ct.contract_no LIKE ? OR ct.title LIKE ? OR c.name LIKE ?)"
        params += [f"%{kw}%"] * 3
    sql += " ORDER BY ct.id DESC"
    data = rows(db.execute(sql, params))
    for c in data:
        c["outstanding"] = round(c["amount"] - c["received"], 2)
        c["uninvoiced"] = round(c["amount"] - c["invoiced"], 2)
    return jsonify(data)


def gen_plans_from_template(db, contract_id, amount, sign_date, template):
    """按模板自动生成回款计划。template: '361'|'541'|'100'|'m30'"""
    base = datetime.date.fromisoformat(sign_date) if sign_date else datetime.date.today()
    plans = []
    if template == "361":
        plans = [("订金", 0.3, 0), ("发货款", 0.6, 30), ("尾款", 0.1, 90)]
    elif template == "541":
        plans = [("订金", 0.5, 0), ("发货款", 0.4, 30), ("质保金", 0.1, 365)]
    elif template == "100":
        plans = [("一次性付款", 1.0, 0)]
    elif template == "m30":
        plans = [("月结30天", 1.0, 30)]
    for i, (name, ratio, days) in enumerate(plans, 1):
        due = (base + datetime.timedelta(days=days)).isoformat()
        amt = round(amount * ratio, 2)
        if i == len(plans):  # 最后一期兜底，避免舍入误差
            prev = round(amount * sum(p[1] for p in plans[:i - 1]), 2)
            amt = round(amount - prev, 2)
        db.execute(
            "INSERT INTO payment_plans(contract_id,seq,name,ratio,amount,due_date) VALUES(?,?,?,?,?,?)",
            (contract_id, i, name, ratio, amt, due),
        )


@app.post("/api/contracts")
@roles_required("admin", "sales")
def create_contract():
    d = body()
    if not d.get("contract_no") or not d.get("title") or not d.get("customer_id"):
        return jsonify({"error": "合同编号、标题、客户必填"}), 400
    if not owns_customer(int(d["customer_id"])):
        return jsonify({"error": "无权为该客户建合同"}), 403
    db = get_db()
    ctype = d.get("type") if d.get("type") in ("product", "service") else "product"
    status = d.get("status", "已签")
    if not valid_status(db, ctype, status):
        return jsonify({"error": "合同状态不在数据字典中"}), 400
    owner = d.get("owner_id") if g.user["role"] == "admin" and d.get("owner_id") else g.user["id"]
    amount = number(d.get("amount"), "合同金额", 0)
    sign_date = valid_date(d["sign_date"], "签订日期") if d.get("sign_date") else ""
    delivery_date = valid_date(d["delivery_date"], "交付日期") if d.get("delivery_date") else ""
    try:
        cur = db.execute(
            """INSERT INTO contracts(contract_no,customer_id,title,type,amount,sign_date,delivery_date,status,owner_id,remark,is_demo,created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["contract_no"], d["customer_id"], d["title"], ctype, amount,
             sign_date, delivery_date, status, owner, d.get("remark", ""),
             1 if current_data_mode() == "demo" else 0, g.user["id"]),
        )
        cid = cur.lastrowid
        if d.get("plan_template"):
            gen_plans_from_template(db, cid, amount, sign_date, d["plan_template"])
        db.commit()
        return jsonify({"id": cid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "合同编号已存在"}), 400


@app.get("/api/contracts/<int:cid>")
@login_required
def contract_detail(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权访问该合同"}), 403
    db = get_db()
    c = row(db.execute(
        """SELECT ct.*, c.name AS customer_name, c.address AS customer_address, u.name AS owner_name
           FROM contracts ct JOIN customers c ON c.id=ct.customer_id
           LEFT JOIN users u ON u.id=ct.owner_id WHERE ct.id=?""", (cid,)))
    if not c:
        return jsonify({"error": "合同不存在"}), 404
    c["plans"] = rows(db.execute(
        """SELECT pp.*, COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
           FROM payment_plans pp WHERE pp.contract_id=? ORDER BY pp.seq""", (cid,)))
    for p in c["plans"]:
        p["remain"] = round(p["amount"] - p["received"], 2)
        p["state"] = "已收" if p["remain"] <= 0 else ("部分" if p["received"] > 0 else "待收")
        p["overdue"] = p["remain"] > 0 and p["due_date"] < today()
    c["files"] = rows(db.execute(
        """SELECT f.id, f.orig_name, f.size, f.created_at, u.name AS uploaded_by_name
           FROM contract_files f LEFT JOIN users u ON u.id=f.uploaded_by
           WHERE f.contract_id=? ORDER BY f.id DESC""", (cid,)))
    c["payments"] = rows(db.execute(
        """SELECT p.*, u.name AS created_by_name FROM payments p
           LEFT JOIN users u ON u.id=p.created_by
           WHERE p.contract_id=? ORDER BY p.pay_date DESC, p.id DESC""", (cid,)))
    for payment in c["payments"]:
        payment["allocations"] = rows(db.execute(
            """SELECT pa.*, pp.name AS plan_name FROM payment_allocations pa
               JOIN payment_plans pp ON pp.id=pa.plan_id WHERE pa.payment_id=? ORDER BY pa.id""",
            (payment["id"],)))
        payment["allocated"] = round(sum(a["amount"] for a in payment["allocations"]), 2)
        payment["unallocated"] = round(payment["amount"] - payment["allocated"], 2)
        payment["plan_name"] = "；".join(
            f"{a['plan_name']} {a['amount']:.2f}" for a in payment["allocations"]) or ""
    c["items"] = rows(db.execute(
        """SELECT ci.*, COALESCE((
             SELECT SUM(si.quantity) FROM shipment_items si
             JOIN shipments s ON s.id=si.shipment_id
             WHERE si.contract_item_id=ci.id),0) AS shipped
           FROM contract_items ci WHERE ci.contract_id=? ORDER BY ci.id""", (cid,)))
    c["invoices"] = rows(db.execute(
        """SELECT i.*, u.name AS created_by_name FROM invoices i
           LEFT JOIN users u ON u.id=i.created_by
           WHERE i.contract_id=? ORDER BY i.invoice_date DESC, i.id DESC""", (cid,)))
    for inv in c["invoices"]:
        red_amount = -db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE red_invoice_of=? AND status!='作废'",
            (inv["id"],)).fetchone()[0]
        inv["red_remaining"] = round(inv["amount"] - red_amount, 2) if inv["status"] == "已开" else 0
    balance = contract_balances(db, "AND ct.id=?", (cid,))[0]
    for key in ("received", "invoiced", "outstanding", "uninvoiced", "planned",
                "planned_remaining", "unscheduled", "unscheduled_outstanding", "unallocated"):
        c[key] = balance[key]
    c["changes"] = rows(db.execute(
        """SELECT cc.*, u.name AS created_by_name FROM contract_changes cc
           LEFT JOIN users u ON u.id=cc.created_by WHERE cc.contract_id=? ORDER BY cc.id DESC""", (cid,)))
    c["audit_logs"] = rows(db.execute(
        """SELECT a.*, u.name AS actor_name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id
           WHERE a.entity_type='contract' AND a.entity_id=? ORDER BY a.id DESC LIMIT 50""", (cid,)))
    return jsonify(c)


@app.put("/api/contracts/<int:cid>")
@roles_required("admin", "sales")
def update_contract(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权修改该合同"}), 403
    d = body()
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    before = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
    has_items = db.execute(
        "SELECT COUNT(*) c FROM contract_items WHERE contract_id=?", (cid,)).fetchone()["c"] > 0
    if has_items and "amount" in d and number(d["amount"], "合同金额", 0) != before["amount"]:
        return jsonify({"error": "合同金额由明细合计决定，请通过明细变更调整"}), 400
    fields = ["contract_no", "title", "amount", "sign_date", "delivery_date", "remark"]
    if has_items:
        fields.remove("amount")
    sets, params = [], []
    new_amount = None
    for f in fields:
        if f in d:
            value = d[f]
            if f == "amount":
                value = number(value, "合同金额", 0)
                new_amount = value
            elif f in ("sign_date", "delivery_date") and value:
                value = valid_date(value, "签订日期" if f == "sign_date" else "交付日期")
            sets.append(f"{f}=?")
            params.append(value)
    if "status" in d:
        ct = db.execute("SELECT type FROM contracts WHERE id=?", (cid,)).fetchone()
        if not ct or not valid_status(db, ct["type"], d["status"]):
            return jsonify({"error": "状态无效或不在该类型合同的数据字典中"}), 400
        sets.append("status=?")
        params.append(d["status"])
    if d.get("type") in ("product", "service"):
        sets.append("type=?")
        params.append(d["type"])
    if "owner_id" in d and g.user["role"] == "admin":
        sets.append("owner_id=?")
        params.append(d["owner_id"])
    if not sets:
        return jsonify({"error": "无更新内容"}), 400
    amount_changed = new_amount is not None and new_amount != before["amount"]
    reason = (d.get("change_reason") or "").strip()
    if amount_changed:
        financial_count = db.execute(
            "SELECT (SELECT COUNT(*) FROM payments WHERE contract_id=?) + (SELECT COUNT(*) FROM invoices WHERE contract_id=?)",
            (cid, cid)).fetchone()[0]
        if financial_count and not reason:
            return jsonify({"error": "已有收款或开票记录，改价必须填写变更原因"}), 400
        received = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE contract_id=?", (cid,)).fetchone()[0]
        invoiced = db.execute("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE contract_id=? AND status!='作废'", (cid,)).fetchone()[0]
        planned = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_plans WHERE contract_id=?", (cid,)).fetchone()[0]
        if new_amount + 0.00001 < max(received, invoiced, planned):
            return jsonify({"error": "新合同额不得低于已收款、有效开票或回款计划总额"}), 400
    params.append(cid)
    db.execute(f"UPDATE contracts SET {','.join(sets)} WHERE id=?", params)
    after = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
    write_audit(db, "contract", cid, "update", before, after, reason)
    tracked = ("amount", "sign_date", "delivery_date", "status")
    change_id = None
    if any(before[f] != after[f] for f in tracked):
        change_id = db.execute(
            """INSERT INTO contract_changes(contract_id,before_amount,after_amount,before_json,after_json,reason,created_by)
               VALUES(?,?,?,?,?,?,?)""",
            (cid, before["amount"], after["amount"],
             json.dumps({f: before[f] for f in tracked}, ensure_ascii=False),
             json.dumps({f: after[f] for f in tracked}, ensure_ascii=False),
             reason or "合同信息变更", g.user["id"])).lastrowid
    db.commit()
    return jsonify({"ok": True, "change_id": change_id})


@app.delete("/api/contracts/<int:cid>")
@admin_required
def delete_contract(cid):
    if not owns_contract(cid):
        return jsonify({"error": "合同不存在或无权删除"}), 403
    db = get_db()
    linked_count = 0
    for table in ("shipments", "material_batches", "furnace_batches", "acceptance_records", "reconciliations", "cost_entries", "payments", "invoices", "contract_changes"):
        linked_count += db.execute(f"SELECT COUNT(*) FROM {table} WHERE contract_id=?", (cid,)).fetchone()[0]
    if linked_count:
        return jsonify({"error": "该合同已有财务、生产或变更记录，不能删除；请使用变更、红冲或归档"}), 400
    before = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
    write_audit(db, "contract", cid, "delete", before, None, "删除无业务记录合同")
    db.execute("DELETE FROM payments WHERE contract_id=?", (cid,))
    db.execute("DELETE FROM invoices WHERE contract_id=?", (cid,))
    db.execute("DELETE FROM payment_plans WHERE contract_id=?", (cid,))
    db.execute("DELETE FROM contracts WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/contracts/<int:cid>/attachment")
@roles_required("admin", "sales")
def upload_attachment(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权操作该合同"}), 403
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    fname = f"{cid}_{int(datetime.datetime.now().timestamp())}_{secure_filename(f.filename)}"
    f.save(os.path.join(UPLOAD_DIR, fname))
    db = get_db()
    old = row(db.execute("SELECT attachment FROM contracts WHERE id=?", (cid,)))
    if old and old.get("attachment"):
        try:
            os.remove(os.path.join(UPLOAD_DIR, old["attachment"]))
        except OSError:
            pass
    db.execute("UPDATE contracts SET attachment=? WHERE id=?", (fname, cid))
    db.commit()
    return jsonify({"ok": True, "file": fname})


@app.get("/api/contracts/<int:cid>/attachment")
@login_required
def download_attachment(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权访问"}), 403
    c = row(get_db().execute("SELECT attachment FROM contracts WHERE id=?", (cid,)))
    if not c or not c["attachment"]:
        return jsonify({"error": "无附件"}), 404
    return send_from_directory(UPLOAD_DIR, c["attachment"], as_attachment=True)


# ---------------- 回款计划 ----------------
@app.get("/api/plans")
@login_required
def list_plans():
    db = get_db()
    scope, params = scope_sql("ct")
    flt = request.args.get("filter", "all")
    sql = f"""
      SELECT pp.*, ct.contract_no, ct.title AS contract_title, ct.owner_id,
             c.name AS customer_name, c.contact, c.phone,
             COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
      FROM payment_plans pp
      JOIN contracts ct ON ct.id=pp.contract_id
      JOIN customers c ON c.id=ct.customer_id
      WHERE 1=1 {scope} AND ct.status!='已归档'
    """
    data = rows(db.execute(sql, params))
    t = today()
    soon = (datetime.date.today() + datetime.timedelta(days=REMIND_DAYS)).isoformat()
    out = []
    for p in data:
        p["remain"] = round(p["amount"] - p["received"], 2)
        if p["remain"] <= 0:
            p["state"] = "已收"
        elif p["due_date"] < t:
            p["state"] = "已逾期"
        elif p["due_date"] <= soon:
            p["state"] = "即将到期"
        else:
            p["state"] = "未到期"
        p["overdue_days"] = (datetime.date.today() - datetime.date.fromisoformat(p["due_date"])).days \
            if p["remain"] > 0 and p["due_date"] < t else 0
        if flt == "overdue" and p["state"] != "已逾期":
            continue
        if flt == "soon" and p["state"] != "即将到期":
            continue
        if flt == "unpaid" and p["state"] == "已收":
            continue
        out.append(p)
    out.sort(key=lambda x: (x["state"] == "已收", x["due_date"]))
    return jsonify(out)


@app.post("/api/contracts/<int:cid>/plans")
@roles_required("admin", "finance")
def add_plan(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权操作该合同"}), 403
    d = body()
    if not d.get("name") or not d.get("due_date"):
        return jsonify({"error": "期次名称和应收日期必填"}), 400
    amount = round(number(d.get("amount"), "计划金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "计划金额至少为 0.01 元"}), 400
    ratio = number(d.get("ratio"), "占合同比例", 0)
    if ratio > 1:
        return jsonify({"error": "占合同比例不能超过 1"}), 400
    due_date = valid_date(d["due_date"], "应收日期")
    db = get_db()
    contract = row(db.execute("SELECT amount FROM contracts WHERE id=?", (cid,)))
    planned = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_plans WHERE contract_id=?", (cid,)).fetchone()[0]
    if not contract or amount - (contract["amount"] - planned) > 0.00001:
        return jsonify({"error": "回款计划总额不能超过合同金额"}), 400
    mx = db.execute("SELECT COALESCE(MAX(seq),0) m FROM payment_plans WHERE contract_id=?",
                    (cid,)).fetchone()["m"]
    cur = db.execute(
        "INSERT INTO payment_plans(contract_id,seq,name,ratio,amount,due_date) VALUES(?,?,?,?,?,?)",
        (cid, mx + 1, d["name"], ratio, amount, due_date),
    )
    write_audit(db, "payment_plan", cur.lastrowid, "create", None,
                {"contract_id": cid, "amount": amount, "due_date": due_date})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.delete("/api/plans/<int:pid>")
@roles_required("admin", "finance")
def delete_plan(pid):
    db = get_db()
    p = row(db.execute("SELECT contract_id FROM payment_plans WHERE id=?", (pid,)))
    if not p:
        return jsonify({"error": "计划不存在"}), 404
    if not owns_contract(p["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    n = db.execute("""SELECT (SELECT COUNT(*) FROM payments WHERE plan_id=?) +
                             (SELECT COUNT(*) FROM payment_allocations WHERE plan_id=?)""",
                   (pid, pid)).fetchone()[0]
    if n:
        return jsonify({"error": "该期已有收款记录，不能删除"}), 400
    db.execute("DELETE FROM payment_plans WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 收款登记 ----------------
@app.get("/api/payments")
@login_required
def list_payments():
    scope, params = scope_sql("ct")
    sql = f"""
      SELECT p.*, c.name AS customer_name, ct.contract_no, u.name AS created_by_name
      FROM payments p
      JOIN customers c ON c.id=p.customer_id
      JOIN contracts ct ON ct.id=p.contract_id
      LEFT JOIN users u ON u.id=p.created_by
      WHERE 1=1 {scope} ORDER BY p.pay_date DESC, p.id DESC LIMIT 500
    """
    return jsonify(rows(get_db().execute(sql, params)))


@app.post("/api/payments")
@roles_required("admin", "finance", "sales")
def add_payment():
    d = body()
    cid = int(d.get("contract_id") or 0)
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    amount = round(number(d.get("amount"), "收款金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "收款金额至少为 0.01 元"}), 400
    pay_date = valid_date(d.get("pay_date") or today(), "收款日期")
    plan_id = int(d.get("plan_id") or 0) or None
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    ct = row(db.execute("SELECT customer_id,amount FROM contracts WHERE id=?", (cid,)))
    if not ct:
        return jsonify({"error": "合同不存在"}), 404
    received = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE contract_id=?", (cid,)).fetchone()[0]
    if amount - (ct["amount"] - received) > 0.00001:
        return jsonify({"error": "收款金额超过合同未收余额"}), 400
    if plan_id:
        plan = row(db.execute("SELECT contract_id,amount FROM payment_plans WHERE id=?", (plan_id,)))
        if not plan or plan["contract_id"] != cid:
            return jsonify({"error": "回款期次不属于该合同"}), 400
        plan_received = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE plan_id=?", (plan_id,)).fetchone()[0]
        if amount - (plan["amount"] - plan_received) > 0.00001:
            return jsonify({"error": "收款金额超过该期未收余额"}), 400
    cur = db.execute(
        """INSERT INTO payments(plan_id,contract_id,customer_id,amount,pay_date,method,remark,created_by)
           VALUES(?,?,?,?,?,?,?,?)""",
        (plan_id, cid, ct["customer_id"], amount, pay_date,
         d.get("method", ""), d.get("remark", ""), g.user["id"]),
    )
    payment_id = cur.lastrowid
    if plan_id:
        db.execute(
            "INSERT INTO payment_allocations(payment_id,plan_id,amount,created_by) VALUES(?,?,?,?)",
            (payment_id, plan_id, amount, g.user["id"]))
    after = {"id": payment_id, "contract_id": cid, "plan_id": plan_id, "amount": amount, "pay_date": pay_date}
    write_audit(db, "payment", payment_id, "create", None, after)
    db.commit()
    return jsonify({"id": payment_id}), 201


@app.post("/api/payments/<int:pid>/allocations")
@roles_required("admin", "finance")
def allocate_payment(pid):
    d = body()
    plan_id = int(d.get("plan_id") or 0)
    amount = round(number(d.get("amount"), "核销金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "核销金额至少为 0.01 元"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    payment = row(db.execute("SELECT * FROM payments WHERE id=?", (pid,)))
    if not payment:
        return jsonify({"error": "收款记录不存在"}), 404
    if not owns_contract(payment["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    plan = row(db.execute("SELECT * FROM payment_plans WHERE id=?", (plan_id,)))
    if not plan or plan["contract_id"] != payment["contract_id"]:
        return jsonify({"error": "回款期次不属于该收款合同"}), 400
    allocated = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE payment_id=?", (pid,)).fetchone()[0]
    if amount - (payment["amount"] - allocated) > 0.00001:
        return jsonify({"error": "核销金额超过该收款待核销余额"}), 400
    plan_received = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_allocations WHERE plan_id=?", (plan_id,)).fetchone()[0]
    if amount - (plan["amount"] - plan_received) > 0.00001:
        return jsonify({"error": "核销金额超过该期未收余额"}), 400
    cur = db.execute(
        "INSERT INTO payment_allocations(payment_id,plan_id,amount,created_by) VALUES(?,?,?,?)",
        (pid, plan_id, amount, g.user["id"]))
    after = {"id": cur.lastrowid, "payment_id": pid, "plan_id": plan_id, "amount": amount}
    write_audit(db, "payment", pid, "allocate", None, after, d.get("reason", ""))
    db.commit()
    return jsonify(after), 201


@app.delete("/api/allocations/<int:aid>")
@roles_required("admin", "finance")
def cancel_allocation(aid):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    allocation = row(db.execute(
        """SELECT pa.*, p.contract_id FROM payment_allocations pa
           JOIN payments p ON p.id=pa.payment_id WHERE pa.id=?""", (aid,)))
    if not allocation:
        return jsonify({"error": "核销记录不存在"}), 404
    if not owns_contract(allocation["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    write_audit(db, "payment", allocation["payment_id"], "cancel_allocation", allocation, None, "取消核销")
    db.execute("DELETE FROM payment_allocations WHERE id=?", (aid,))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/payments/<int:pid>")
@admin_required
def delete_payment(pid):
    db = get_db()
    p = row(db.execute("SELECT * FROM payments WHERE id=?", (pid,)))
    if not p:
        return jsonify({"error": "记录不存在"}), 404
    if not owns_contract(p["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    write_audit(db, "payment", pid, "delete", p, None, "管理员删除原始收款")
    db.execute("DELETE FROM payments WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 开票 ----------------
@app.get("/api/invoices")
@login_required
def list_invoices():
    scope, params = scope_sql("ct")
    sql = f"""
      SELECT i.*, ct.contract_no, ct.title AS contract_title, c.name AS customer_name,
             u.name AS created_by_name
      FROM invoices i
      JOIN contracts ct ON ct.id=i.contract_id
      JOIN customers c ON c.id=ct.customer_id
      LEFT JOIN users u ON u.id=i.created_by
      WHERE 1=1 {scope} ORDER BY i.invoice_date DESC, i.id DESC LIMIT 500
    """
    db = get_db()
    data = rows(db.execute(sql, params))
    for inv in data:
        red_amount = -db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE red_invoice_of=? AND status!='作废'",
            (inv["id"],)).fetchone()[0]
        inv["red_remaining"] = round(inv["amount"] - red_amount, 2) if inv["status"] == "已开" else 0
    return jsonify(data)


@app.post("/api/invoices")
@roles_required("admin", "finance")
def add_invoice():
    d = body()
    cid = int(d.get("contract_id") or 0)
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    amount = round(number(d.get("amount"), "开票金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "开票金额至少为 0.01 元"}), 400
    invoice_no = (d.get("invoice_no") or "").strip()
    if not invoice_no:
        return jsonify({"error": "发票号码必填"}), 400
    invoice_date = valid_date(d.get("invoice_date") or today(), "开票日期")
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    ct = row(db.execute("SELECT amount FROM contracts WHERE id=?", (cid,)))
    if not ct:
        return jsonify({"error": "合同不存在"}), 404
    if db.execute("SELECT 1 FROM invoices WHERE invoice_no=?", (invoice_no,)).fetchone():
        return jsonify({"error": "发票号码已存在"}), 400
    invoiced = db.execute("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE contract_id=? AND status!='作废'", (cid,)).fetchone()[0]
    if amount - (ct["amount"] - invoiced) > 0.00001:
        return jsonify({"error": "开票金额超过合同未开票余额"}), 400
    try:
        cur = db.execute(
            """INSERT INTO invoices(contract_id,invoice_no,type,amount,invoice_date,remark,created_by)
               VALUES(?,?,?,?,?,?,?)""",
            (cid, invoice_no, d.get("type") if d.get("type") in INVOICE_TYPES else "增值税普通发票",
             amount, invoice_date, d.get("remark", ""), g.user["id"]),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "发票号码已存在"}), 400
    write_audit(db, "invoice", cur.lastrowid, "create", None,
                {"contract_id": cid, "invoice_no": invoice_no, "amount": amount, "invoice_date": invoice_date})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.put("/api/invoices/<int:iid>/void")
@roles_required("admin", "finance")
def void_invoice(iid):
    db = get_db()
    inv = row(db.execute("SELECT * FROM invoices WHERE id=?", (iid,)))
    if not inv:
        return jsonify({"error": "发票不存在"}), 404
    if not owns_contract(inv["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    if db.execute("SELECT 1 FROM invoices WHERE red_invoice_of=? AND status!='作废'", (iid,)).fetchone():
        return jsonify({"error": "该发票已有红冲记录，不能直接作废"}), 400
    after = dict(inv, status="作废")
    db.execute("UPDATE invoices SET status='作废' WHERE id=?", (iid,))
    write_audit(db, "invoice", iid, "void", inv, after, body().get("reason", ""))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/invoices/<int:iid>/red")
@roles_required("admin", "finance")
def red_invoice(iid):
    d = body()
    amount = round(number(d.get("amount"), "红冲金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "红冲金额至少为 0.01 元"}), 400
    invoice_no = (d.get("invoice_no") or "").strip()
    reason = (d.get("reason") or "").strip()
    if not invoice_no or not reason:
        return jsonify({"error": "红字发票号码和红冲原因必填"}), 400
    invoice_date = valid_date(d.get("invoice_date") or today(), "红冲日期")
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    inv = row(db.execute("SELECT * FROM invoices WHERE id=?", (iid,)))
    if not inv:
        return jsonify({"error": "发票不存在"}), 404
    if inv["status"] != "已开" or inv["red_invoice_of"]:
        return jsonify({"error": "只有正常开具的原发票可以红冲"}), 400
    if not owns_contract(inv["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    if db.execute("SELECT 1 FROM invoices WHERE invoice_no=?", (invoice_no,)).fetchone():
        return jsonify({"error": "发票号码已存在"}), 400
    red_total = -db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE red_invoice_of=? AND status!='作废'", (iid,)
    ).fetchone()[0]
    if amount - (inv["amount"] - red_total) > 0.00001:
        return jsonify({"error": "红冲金额超过原发票剩余可红冲金额"}), 400
    cur = db.execute(
        """INSERT INTO invoices(contract_id,invoice_no,type,amount,invoice_date,status,red_invoice_of,remark,created_by)
           VALUES(?,?,?,?,?,'红冲',?,?,?)""",
        (inv["contract_id"], invoice_no, inv["type"], -amount, invoice_date, iid, reason, g.user["id"]))
    after = {"id": cur.lastrowid, "red_invoice_of": iid, "invoice_no": invoice_no,
             "amount": -amount, "invoice_date": invoice_date, "reason": reason}
    write_audit(db, "invoice", iid, "red", inv, after, reason)
    db.commit()
    return jsonify(after), 201


@app.delete("/api/invoices/<int:iid>")
@admin_required
def delete_invoice(iid):
    db = get_db()
    inv = row(db.execute("SELECT * FROM invoices WHERE id=?", (iid,)))
    if not inv:
        return jsonify({"error": "发票不存在"}), 404
    if not owns_contract(inv["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    if db.execute("SELECT 1 FROM invoices WHERE red_invoice_of=?", (iid,)).fetchone():
        return jsonify({"error": "该发票已有红冲记录，不能删除"}), 400
    write_audit(db, "invoice", iid, "delete", inv, None, "管理员删除发票")
    db.execute("DELETE FROM invoices WHERE id=?", (iid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 产品 / 服务 ----------------
def write_allowed():
    return g.user["role"] in ("admin", "finance")


@app.get("/api/products")
@login_required
def list_products():
    kw = request.args.get("q", "").strip()
    demo, params = demo_sql()
    sql = f"SELECT * FROM products WHERE 1=1 {demo}"
    if kw:
        sql += " AND (name LIKE ? OR model LIKE ? OR spec LIKE ? OR category LIKE ?)"
        params += [f"%{kw}%"] * 4
    if request.args.get("all") != "1":
        sql += " AND active=1"
    sql += " ORDER BY id DESC"
    return jsonify(rows(get_db().execute(sql, params)))


@app.post("/api/products")
@login_required
def create_product():
    if not write_allowed():
        return jsonify({"error": "仅管理员或财务可维护产品"}), 403
    d = body()
    if not d.get("name"):
        return jsonify({"error": "产品名称必填"}), 400
    cur = get_db().execute(
        "INSERT INTO products(name,model,spec,unit,price,category,remark,is_demo) VALUES(?,?,?,?,?,?,?,?)",
        (d["name"], d.get("model", ""), d.get("spec", ""), d.get("unit", "台"),
         number(d.get("price"), "标准价", 0), d.get("category", ""), d.get("remark", ""),
         1 if current_data_mode() == "demo" else 0),
    )
    get_db().commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.put("/api/products/<int:pid>")
@login_required
def update_product(pid):
    if not write_allowed():
        return jsonify({"error": "仅管理员或财务可维护产品"}), 403
    db = get_db()
    product = db.execute("SELECT is_demo FROM products WHERE id=?", (pid,)).fetchone()
    if not product or not record_in_data_mode(product["is_demo"]):
        return jsonify({"error": "产品不存在或不在当前数据范围"}), 404
    d = body()
    fields = ["name", "model", "spec", "unit", "price", "category", "remark"]
    sets, params = [], []
    for f in fields:
        if f in d:
            sets.append(f"{f}=?")
            params.append(number(d[f], "标准价", 0) if f == "price" else d[f])
    if "active" in d:
        sets.append("active=?")
        params.append(1 if d["active"] else 0)
    if not sets:
        return jsonify({"error": "无更新内容"}), 400
    params.append(pid)
    get_db().execute(f"UPDATE products SET {','.join(sets)} WHERE id=?", params)
    get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/services")
@login_required
def list_services():
    kw = request.args.get("q", "").strip()
    demo, params = demo_sql()
    sql = f"SELECT * FROM services WHERE 1=1 {demo}"
    if kw:
        sql += " AND (name LIKE ? OR type LIKE ? OR content LIKE ?)"
        params += [f"%{kw}%"] * 3
    if request.args.get("all") != "1":
        sql += " AND active=1"
    sql += " ORDER BY id DESC"
    return jsonify(rows(get_db().execute(sql, params)))


@app.post("/api/services")
@login_required
def create_service():
    if not write_allowed():
        return jsonify({"error": "仅管理员或财务可维护服务"}), 403
    d = body()
    if not d.get("name"):
        return jsonify({"error": "服务名称必填"}), 400
    cur = get_db().execute(
        "INSERT INTO services(name,type,content,unit,price,remark,is_demo) VALUES(?,?,?,?,?,?,?)",
        (d["name"], d.get("type", ""), d.get("content", ""), d.get("unit", "次"),
         number(d.get("price"), "定价", 0), d.get("remark", ""),
         1 if current_data_mode() == "demo" else 0),
    )
    get_db().commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.put("/api/services/<int:sid>")
@login_required
def update_service(sid):
    if not write_allowed():
        return jsonify({"error": "仅管理员或财务可维护服务"}), 403
    db = get_db()
    service = db.execute("SELECT is_demo FROM services WHERE id=?", (sid,)).fetchone()
    if not service or not record_in_data_mode(service["is_demo"]):
        return jsonify({"error": "服务不存在或不在当前数据范围"}), 404
    d = body()
    fields = ["name", "type", "content", "unit", "price", "remark"]
    sets, params = [], []
    for f in fields:
        if f in d:
            sets.append(f"{f}=?")
            params.append(number(d[f], "定价", 0) if f == "price" else d[f])
    if "active" in d:
        sets.append("active=?")
        params.append(1 if d["active"] else 0)
    if not sets:
        return jsonify({"error": "无更新内容"}), 400
    params.append(sid)
    get_db().execute(f"UPDATE services SET {','.join(sets)} WHERE id=?", params)
    get_db().commit()
    return jsonify({"ok": True})


# ---------------- 合同明细 ----------------
def recalc_contract_amount(db, cid, reason="合同明细变更"):
    before = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
    amount = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM contract_items WHERE contract_id=?", (cid,)).fetchone()[0]
    received = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE contract_id=?", (cid,)).fetchone()[0]
    invoiced = db.execute("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE contract_id=? AND status!='作废'", (cid,)).fetchone()[0]
    planned = db.execute("SELECT COALESCE(SUM(amount),0) FROM payment_plans WHERE contract_id=?", (cid,)).fetchone()[0]
    if amount + 0.00001 < max(received, invoiced, planned):
        raise ValueError("明细合计不得低于已收款、有效开票或回款计划总额")
    db.execute("UPDATE contracts SET amount=? WHERE id=?", (amount, cid))
    if before["amount"] != amount:
        after = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
        db.execute(
            """INSERT INTO contract_changes(contract_id,before_amount,after_amount,before_json,after_json,reason,created_by)
               VALUES(?,?,?,?,?,?,?)""",
            (cid, before["amount"], amount, json.dumps({"amount": before["amount"]}),
             json.dumps({"amount": amount}), reason, g.user["id"]))
        write_audit(db, "contract", cid, "items_amount_change", before, after, reason)


def validate_item_change(db, cid, d):
    linked = 0
    for table in ("shipments", "payments", "invoices"):
        linked += db.execute(f"SELECT COUNT(*) FROM {table} WHERE contract_id=?", (cid,)).fetchone()[0]
    if linked and not (d.get("change_reason") or "").strip():
        raise ValueError("合同已有发货、收款或开票，修改明细必须填写变更原因")
    return (d.get("change_reason") or "").strip() or "合同明细变更"


@app.post("/api/contracts/<int:cid>/items")
@roles_required("admin", "sales")
def add_item(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权操作该合同"}), 403
    d = body()
    itype = d.get("item_type")
    if itype not in ("product", "service", "other"):
        return jsonify({"error": "明细类型无效"}), 400
    db = get_db()
    name, spec, unit = d.get("name", ""), d.get("spec", ""), d.get("unit", "")
    price_provided = d.get("unit_price") not in (None, "")
    price = number(d.get("unit_price"), "单价", 0)
    ref_id = d.get("ref_id")
    if itype in ("product", "service") and ref_id:
        table = "products" if itype == "product" else "services"
        ref = row(db.execute(f"SELECT * FROM {table} WHERE id=?", (int(ref_id),)))
        if not ref:
            return jsonify({"error": "所选产品/服务不存在"}), 400
        name = ref["name"]
        spec = ref.get("spec") or (ref.get("type", "") if itype == "service" else ref.get("model", ""))
        unit = ref.get("unit", "")
        if not price_provided:
            price = ref["price"]
    if not name:
        return jsonify({"error": "明细名称必填"}), 400
    qty = number(d.get("quantity") or 1, "数量", 0, strictly=True)
    price = number(price, "单价", 0)
    amount = round(qty * price, 2)
    cur = db.execute(
        """INSERT INTO contract_items(contract_id,item_type,ref_id,name,spec,quantity,unit,unit_price,amount,remark)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (cid, itype, ref_id, name, spec, qty, unit, price, amount, d.get("remark", "")),
    )
    recalc_contract_amount(db, cid, validate_item_change(db, cid, d))
    db.commit()
    return jsonify({"id": cur.lastrowid, "amount": amount}), 201


@app.put("/api/items/<int:iid>")
@roles_required("admin", "sales")
def update_item(iid):
    db = get_db()
    it = row(db.execute("SELECT * FROM contract_items WHERE id=?", (iid,)))
    if not it:
        return jsonify({"error": "明细不存在"}), 404
    if not owns_contract(it["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    d = body()
    qty = number(d.get("quantity", it["quantity"]), "数量", 0, strictly=True)
    price = number(d.get("unit_price", it["unit_price"]), "单价", 0)
    shipped = db.execute("SELECT COALESCE(SUM(quantity),0) FROM shipment_items WHERE contract_item_id=?", (iid,)).fetchone()[0]
    if qty < shipped:
        return jsonify({"error": "明细数量不能低于累计发货数量"}), 400
    db.execute("UPDATE contract_items SET quantity=?, unit_price=?, amount=?, remark=? WHERE id=?",
               (qty, price, round(qty * price, 2), d.get("remark", it["remark"]), iid))
    recalc_contract_amount(db, it["contract_id"], validate_item_change(db, it["contract_id"], d))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/items/<int:iid>")
@roles_required("admin", "sales")
def delete_item(iid):
    db = get_db()
    it = row(db.execute("SELECT * FROM contract_items WHERE id=?", (iid,)))
    if not it:
        return jsonify({"error": "明细不存在"}), 404
    if not owns_contract(it["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    shipped = db.execute("SELECT COALESCE(SUM(quantity),0) FROM shipment_items WHERE contract_item_id=?", (iid,)).fetchone()[0]
    if shipped:
        return jsonify({"error": "该明细已有发货记录，不能删除"}), 400
    db.execute("DELETE FROM contract_items WHERE id=?", (iid,))
    recalc_contract_amount(db, it["contract_id"], validate_item_change(db, it["contract_id"], {"change_reason": "删除合同明细"}))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 产品/服务维度统计 ----------------
def item_stats(itype, group_by_type=False):
    """按产品(或服务类型)分摊统计：合同额按明细，回款/开票按明细占合同比例分摊"""
    db = get_db()
    scope, sparams = scope_sql("ct")
    where, params = "", []
    if request.args.get("from"):
        where += " AND ct.sign_date>=?"
        params.append(request.args["from"])
    if request.args.get("to"):
        where += " AND ct.sign_date<=?"
        params.append(request.args["to"])
    if request.args.get("status"):
        where += " AND ct.status=?"
        params.append(request.args["status"])
    if request.args.get("owner_id") and g.user["role"] != "sales":
        where += " AND ct.owner_id=?"
        params.append(int(request.args["owner_id"]))
    data = rows(db.execute(
        f"""SELECT ci.ref_id, ci.name AS item_name, ci.spec, ci.amount AS item_amount,
              ct.id AS contract_id, ct.amount AS contract_amount, ct.customer_id,
              c.name AS customer_name,
              COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id),0) AS received,
              COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=ct.id AND i.status!='作废'),0) AS invoiced
            FROM contract_items ci
            JOIN contracts ct ON ct.id=ci.contract_id
            JOIN customers c ON c.id=ct.customer_id
            WHERE ci.item_type=? {scope} {where}""", [itype] + sparams + params))
    svc_types = {}
    if itype == "service" and group_by_type:
        for r in rows(db.execute("SELECT id,type FROM services")):
            svc_types[r["id"]] = r["type"] or "未分类"
    agg = {}
    for r in data:
        if group_by_type:
            key = svc_types.get(r["ref_id"], "未分类")
        else:
            key = r["item_name"] + (f"（{r['spec']}）" if r.get("spec") else "")
        a = agg.setdefault(key, {"name": key, "contracts": set(), "customers": set(),
                                 "amount": 0.0, "received": 0.0, "invoiced": 0.0})
        ratio = (r["item_amount"] / r["contract_amount"]) if r["contract_amount"] else 0
        a["contracts"].add(r["contract_id"])
        a["customers"].add(r["customer_id"])
        a["amount"] += r["item_amount"]
        a["received"] += r["received"] * ratio
        a["invoiced"] += r["invoiced"] * ratio
    out = []
    for a in agg.values():
        out.append({"name": a["name"], "contracts": len(a["contracts"]), "customers": len(a["customers"]),
                    "amount": round(a["amount"], 2), "received": round(a["received"], 2),
                    "invoiced": round(a["invoiced"], 2), "outstanding": round(a["amount"] - a["received"], 2)})
    out.sort(key=lambda x: -x["amount"])
    return out


@app.get("/api/stats/by-product")
@login_required
def stats_by_product():
    return jsonify(item_stats("product"))


@app.get("/api/stats/by-service")
@login_required
def stats_by_service():
    return jsonify(item_stats("service", group_by_type=True))


# ---------------- 系统设置 ----------------
def get_settings():
    d = {r["key"]: r["value"] for r in get_db().execute("SELECT key,value FROM settings")}
    return {"factory_name": d.get("factory_name") or "客户关系管理系统", "logo": d.get("logo") or ""}


@app.get("/api/settings")
def read_settings():  # 公开：登录页也要展示厂名和 LOGO
    return jsonify(get_settings())


@app.put("/api/settings")
@admin_required
def write_settings():
    d = body()
    db = get_db()
    if "factory_name" in d:
        name = (d["factory_name"] or "").strip()[:50]
        if not name:
            return jsonify({"error": "工厂名称不能为空"}), 400
        db.execute("INSERT INTO settings(key,value) VALUES('factory_name',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (name,))
    db.commit()
    return jsonify(get_settings())


@app.post("/api/settings/logo")
@admin_required
def upload_logo():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择图片文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return jsonify({"error": "仅支持 png/jpg/gif/webp 图片"}), 400
    fname = "logo" + ext
    f.save(os.path.join(UPLOAD_DIR, fname))
    db = get_db()
    db.execute("INSERT INTO settings(key,value) VALUES('logo',?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (fname,))
    db.commit()
    return jsonify(get_settings())


@app.get("/api/settings/logo")
def serve_logo():
    d = row(get_db().execute("SELECT value FROM settings WHERE key='logo'"))
    if not d or not d["value"]:
        return jsonify({"error": "未设置 LOGO"}), 404
    response = send_from_directory(UPLOAD_DIR, d["value"])
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


# ---------------- 合同附件（多文件 + 预览） ----------------
PREVIEW_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt"}


@app.post("/api/contracts/<int:cid>/files")
@roles_required("admin", "sales")
def upload_files(cid):
    if not owns_contract(cid):
        return jsonify({"error": "无权操作该合同"}), 403
    files = request.files.getlist("files") or ([request.files["file"]] if request.files.get("file") else [])
    if not files or not files[0].filename:
        return jsonify({"error": "请选择文件"}), 400
    db = get_db()
    saved = []
    for f in files:
        orig = f.filename
        fname = f"{cid}_{int(datetime.datetime.now().timestamp()*1000)}_{secrets.token_hex(4)}_{secure_filename(orig) or 'file'}"
        path = os.path.join(UPLOAD_DIR, fname)
        f.save(path)
        cur = db.execute(
            "INSERT INTO contract_files(contract_id,filename,orig_name,size,uploaded_by) VALUES(?,?,?,?,?)",
            (cid, fname, orig, os.path.getsize(path), g.user["id"]))
        saved.append({"id": cur.lastrowid, "orig_name": orig})
    db.commit()
    return jsonify({"saved": saved}), 201


@app.get("/api/files/<int:fid>")
@login_required
def serve_file(fid):
    db = get_db()
    f = row(db.execute("SELECT * FROM contract_files WHERE id=?", (fid,)))
    if not f:
        return jsonify({"error": "文件不存在"}), 404
    if not owns_contract(f["contract_id"]):
        return jsonify({"error": "无权访问"}), 403
    ext = os.path.splitext(f["orig_name"])[1].lower()
    as_dl = request.args.get("dl") == "1" or ext not in PREVIEW_EXTS
    response = send_from_directory(UPLOAD_DIR, f["filename"],
                                   as_attachment=as_dl, download_name=f["orig_name"])
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@app.delete("/api/files/<int:fid>")
@roles_required("admin", "sales")
def delete_file(fid):
    db = get_db()
    f = row(db.execute("SELECT * FROM contract_files WHERE id=?", (fid,)))
    if not f:
        return jsonify({"error": "文件不存在"}), 404
    if not owns_contract(f["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    db.execute("DELETE FROM contract_files WHERE id=?", (fid,))
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, f["filename"]))
    except OSError:
        pass
    return jsonify({"ok": True})


# ---------------- 发货管理 ----------------
def next_document_no(db, kind, prefix, width):
    table, column = {
        "shipment": ("shipments", "shipment_no"),
        "temp_contract": ("contracts", "contract_no"),
        "material": ("material_batches", "batch_no"),
        "furnace": ("furnace_batches", "furnace_no"),
        "acceptance": ("acceptance_records", "record_no"),
        "reconciliation": ("reconciliations", "statement_no"),
        "process_run": ("process_runs", "run_no"),
        "process_improvement": ("process_improvements", "code"),
    }[kind]
    key = f"{kind}:{prefix}"
    db.execute(
        f"""INSERT OR IGNORE INTO document_counters(key,value)
            SELECT ?,COALESCE(MAX(CAST(substr({column},?) AS INTEGER)),0)
            FROM {table} WHERE {column} LIKE ?""",
        (key, len(prefix) + 1, prefix + "%"),
    )
    while True:
        value = db.execute(
            "UPDATE document_counters SET value=value+1 WHERE key=? RETURNING value", (key,)
        ).fetchone()[0]
        number_text = f"{value:0{width}d}"
        candidate = prefix + number_text
        if not db.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (candidate,)).fetchone():
            return candidate


def next_shipment_no(db):
    prefix = "FH-" + datetime.date.today().strftime("%Y%m%d") + "-"
    return next_document_no(db, "shipment", prefix, 3)


@app.get("/api/shipments")
@login_required
def list_shipments():
    scope, params = scope_sql("ct")
    sql = f"""
      SELECT s.*, c.name AS customer_name, ct.contract_no, ct.title AS contract_title,
        u.name AS created_by_name, mb.batch_no,
        COALESCE((SELECT SUM(si.amount) FROM shipment_items si WHERE si.shipment_id=s.id),0) AS total_amount,
        COALESCE((SELECT SUM(si.quantity) FROM shipment_items si WHERE si.shipment_id=s.id),0) AS total_qty
      FROM shipments s
      JOIN customers c ON c.id=s.customer_id
      LEFT JOIN contracts ct ON ct.id=s.contract_id
      LEFT JOIN material_batches mb ON mb.id=s.batch_id
      LEFT JOIN users u ON u.id=s.created_by
      WHERE 1=1 {scope}
    """
    if request.args.get("type") in ("contract", "temp"):
        sql += " AND s.type=?"
        params.append(request.args["type"])
    kw = request.args.get("q", "").strip()
    if kw:
        sql += " AND (s.shipment_no LIKE ? OR c.name LIKE ? OR ct.contract_no LIKE ?)"
        params += [f"%{kw}%"] * 3
    sql += " ORDER BY s.id DESC LIMIT 500"
    return jsonify(rows(get_db().execute(sql, params)))


@app.get("/api/shipments/<int:sid>")
@login_required
def shipment_detail(sid):
    db = get_db()
    s = row(db.execute(
        """SELECT s.*, c.name AS customer_name, c.contact, c.phone, ct.contract_no,
             u.name AS created_by_name, mb.batch_no
           FROM shipments s JOIN customers c ON c.id=s.customer_id
           LEFT JOIN contracts ct ON ct.id=s.contract_id
           LEFT JOIN material_batches mb ON mb.id=s.batch_id
           LEFT JOIN users u ON u.id=s.created_by WHERE s.id=?""", (sid,)))
    if not s:
        return jsonify({"error": "发货单不存在"}), 404
    if s["contract_id"] and not owns_contract(s["contract_id"]):
        return jsonify({"error": "无权访问该发货单"}), 403
    s["items"] = rows(db.execute(
        "SELECT * FROM shipment_items WHERE shipment_id=? ORDER BY id", (sid,)))
    s["total_amount"] = round(sum(i["amount"] for i in s["items"]), 2)
    return jsonify(s)


@app.post("/api/shipments")
@roles_required("admin", "sales", "manager")
def create_shipment():
    d = body()
    stype = d.get("type")
    if stype not in ("contract", "temp"):
        return jsonify({"error": "发货类型无效"}), 400
    items = d.get("items") or []
    if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
        return jsonify({"error": "发货明细不能为空"}), 400
    ship_date = valid_date(d.get("ship_date") or today(), "发货日期")
    transport_fee = number(d.get("transport_fee"), "运输金额", 0)
    db = get_db()
    cid = int(d.get("contract_id") or 0) if stype == "contract" else None
    customer_id = int(d.get("customer_id") or 0) if stype == "temp" else None
    if stype == "contract" and (not cid or not owns_contract(cid)):
        return jsonify({"error": "合同无效或无权操作"}), 403
    if stype == "temp" and (not customer_id or not owns_customer(customer_id)):
        return jsonify({"error": "客户无效或无权操作"}), 403

    db.execute("BEGIN IMMEDIATE")
    batch_id = int(d.get("batch_id") or 0) or None
    if batch_id:
        batch = row(db.execute("SELECT contract_id FROM material_batches WHERE id=?", (batch_id,)))
        if not batch or stype != "contract" or batch["contract_id"] != cid:
            return jsonify({"error": "来料批次不属于该发货合同"}), 400
    line_ids = []
    if stype == "contract":
        ct = row(db.execute("SELECT * FROM contracts WHERE id=?", (cid,)))
        if not ct:
            return jsonify({"error": "合同不存在"}), 404
        customer_id = ct["customer_id"]
        demo = ct["is_demo"]
        for i in items:
            ciid = int(i.get("contract_item_id") or 0)
            ci = row(db.execute("SELECT * FROM contract_items WHERE id=? AND contract_id=?", (ciid, cid)))
            if not ci:
                return jsonify({"error": "合同发货必须选择属于该合同的明细"}), 400
            qty = number(i.get("quantity"), "发货数量", 0, strictly=True)
            shipped = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM shipment_items WHERE contract_item_id=?", (ciid,)
            ).fetchone()[0]
            if qty - (ci["quantity"] - shipped) > 0.00001:
                return jsonify({"error": f"明细 {ci['name']} 的发货数量超过剩余可发数量"}), 400
            price = ci["unit_price"]
            line_ids.append((ciid, ci["name"], ci["spec"], ci["unit"], qty, price, round(qty * price, 2)))
    else:
        cust = row(db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)))
        if not cust:
            return jsonify({"error": "客户不存在"}), 404
        demo = cust["is_demo"]
        for i in items:
            qty = number(i.get("quantity"), "发货数量", 0, strictly=True)
            price = number(i.get("unit_price"), "单价", 0)
            name = (i.get("name") or "").strip()
            if not name:
                return jsonify({"error": "发货明细名称必填"}), 400
            line_ids.append((None, name, i.get("spec", ""), i.get("unit", ""), qty, price, round(qty * price, 2)))
        total = round(sum(line[6] for line in line_ids), 2)
        ls_no = next_document_no(db, "temp_contract", "LS-" + ship_date.replace("-", "") + "-", 4)
        cur = db.execute(
            """INSERT INTO contracts(contract_no,customer_id,title,type,amount,sign_date,status,owner_id,remark,is_demo,created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (ls_no, customer_id, f"临时发货-{cust['name']}-{ship_date}", "product", total,
             ship_date, "已签", g.user["id"], "临时发货自动创建", demo, g.user["id"]))
        cid = cur.lastrowid
        created_lines = []
        for ciid, name, spec, unit, qty, price, amt in line_ids:
            cur = db.execute(
                """INSERT INTO contract_items(contract_id,item_type,ref_id,name,spec,quantity,unit,unit_price,amount)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (cid, "other", None, name, spec, qty, unit, price, amt))
            created_lines.append((cur.lastrowid, name, spec, unit, qty, price, amt))
        line_ids = created_lines
        due_date = (datetime.date.fromisoformat(ship_date) + datetime.timedelta(days=30)).isoformat()
        db.execute(
            "INSERT INTO payment_plans(contract_id,seq,name,ratio,amount,due_date) VALUES(?,1,'月结30天',1,?,?)",
            (cid, total, due_date))

    no = next_shipment_no(db)
    cur = db.execute(
        """INSERT INTO shipments(shipment_no,type,contract_id,batch_id,customer_id,ship_date,from_address,
             to_address,transport_method,transport_fee,remark,is_demo,created_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (no, stype, cid, batch_id, customer_id, ship_date, d.get("from_address", ""), d.get("to_address", ""),
         d.get("transport_method", ""), transport_fee, d.get("remark", ""), demo, g.user["id"]))
    sid = cur.lastrowid
    write_audit(db, "shipment", sid, "create", None,
                {"shipment_no": no, "contract_id": cid, "batch_id": batch_id})
    for ciid, name, spec, unit, qty, price, amt in line_ids:
        db.execute(
            """INSERT INTO shipment_items(shipment_id,contract_item_id,name,spec,unit,quantity,unit_price,amount)
               VALUES(?,?,?,?,?,?,?,?)""", (sid, ciid, name, spec, unit, qty, price, amt))
    db.commit()
    return jsonify({"id": sid, "shipment_no": no, "contract_id": cid}), 201


@app.delete("/api/shipments/<int:sid>")
@admin_required
def delete_shipment(sid):
    db = get_db()
    s = row(db.execute("SELECT * FROM shipments WHERE id=?", (sid,)))
    if not s:
        return jsonify({"error": "发货单不存在"}), 404
    if s["contract_id"] and not owns_contract(s["contract_id"]):
        return jsonify({"error": "无权删除该发货单"}), 403
    if db.execute("SELECT COUNT(*) FROM acceptance_records WHERE shipment_id=?", (sid,)).fetchone()[0]:
        return jsonify({"error": "该发货单已有签收/验收记录，不能删除"}), 400
    if s["type"] == "temp":
        linked = 0
        for table in ("payments", "invoices", "acceptance_records", "cost_entries", "contract_changes"):
            linked += db.execute(f"SELECT COUNT(*) FROM {table} WHERE contract_id=?", (s["contract_id"],)).fetchone()[0]
        if linked:
            return jsonify({"error": "临时发货已有财务或业务记录，不能删除"}), 400
    write_audit(db, "shipment", sid, "delete", s, None, "删除发货单")
    db.execute("DELETE FROM shipment_items WHERE shipment_id=?", (sid,))
    db.execute("DELETE FROM shipments WHERE id=?", (sid,))
    if s["type"] == "temp" and s["contract_id"]:
        db.execute("DELETE FROM payment_plans WHERE contract_id=?", (s["contract_id"],))
        db.execute("DELETE FROM contract_items WHERE contract_id=?", (s["contract_id"],))
        write_audit(db, "contract", s["contract_id"], "delete_temp", {"id": s["contract_id"]}, None, "临时发货删除联动清理")
        db.execute("DELETE FROM contracts WHERE id=?", (s["contract_id"],))
    db.commit()
    return jsonify({"ok": True})


# ---------------- PVD 生产协同：来料 / 炉次 / 质检 ----------------
@app.get("/api/production/materials")
@login_required
def list_material_batches():
    scope, params = scope_sql("ct")
    data = rows(get_db().execute(f"""
      SELECT mb.*, ct.contract_no, c.name AS customer_name, u.name AS created_by_name,
        COALESCE((SELECT SUM(fb.quantity) FROM furnace_batches fb WHERE fb.batch_id=mb.id),0) AS scheduled_qty
      FROM material_batches mb JOIN contracts ct ON ct.id=mb.contract_id
      JOIN customers c ON c.id=mb.customer_id LEFT JOIN users u ON u.id=mb.created_by
      WHERE 1=1 {scope} ORDER BY mb.id DESC LIMIT 500""", params))
    for item in data:
        item["remaining_qty"] = round(item["received_qty"] - item["scheduled_qty"], 2)
        item["accepted_qty"] = get_db().execute(
            "SELECT COALESCE(SUM(quantity),0) FROM acceptance_records WHERE batch_id=? AND record_type='验收'",
            (item["id"],)).fetchone()[0]
        item["acceptance_remaining"] = round(item["received_qty"] - item["accepted_qty"], 2)
    return jsonify(data)


@app.post("/api/production/materials")
@roles_required("admin", "sales", "manager")
def create_material_batch():
    d = body()
    cid = int(d.get("contract_id") or 0)
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    item_name = (d.get("item_name") or "").strip()
    if not item_name:
        return jsonify({"error": "工件名称必填"}), 400
    qty = number(d.get("received_qty"), "来料数量", 0, strictly=True)
    received_date = valid_date(d.get("received_date") or today(), "来料日期")
    db = get_db()
    ct = row(db.execute("SELECT customer_id,is_demo FROM contracts WHERE id=?", (cid,)))
    batch_no = next_document_no(db, "material", "LL-" + received_date.replace("-", "") + "-", 3)
    cur = db.execute(
        """INSERT INTO material_batches(batch_no,contract_id,customer_id,received_date,item_name,
           drawing_no,drawing_revision,material,received_qty,unit,surface_condition,remark,is_demo,created_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (batch_no, cid, ct["customer_id"], received_date, item_name, d.get("drawing_no", ""),
         d.get("drawing_revision", ""), d.get("material", ""), qty, d.get("unit", "件"),
         d.get("surface_condition", ""), d.get("remark", ""), ct["is_demo"], g.user["id"]))
    write_audit(db, "material_batch", cur.lastrowid, "create", None,
                {"batch_no": batch_no, "contract_id": cid, "received_qty": qty})
    db.commit()
    return jsonify({"id": cur.lastrowid, "batch_no": batch_no}), 201


@app.get("/api/production/furnaces")
@login_required
def list_furnace_batches():
    scope, params = scope_sql("ct")
    data = rows(get_db().execute(f"""
      SELECT fb.*, mb.batch_no, mb.item_name, mb.unit, ct.contract_no, c.name AS customer_name,
        u.name AS created_by_name,
        COALESCE((SELECT SUM(qi.inspected_qty) FROM quality_inspections qi WHERE qi.furnace_batch_id=fb.id),0) AS inspected_qty
      FROM furnace_batches fb JOIN material_batches mb ON mb.id=fb.batch_id
      JOIN contracts ct ON ct.id=fb.contract_id JOIN customers c ON c.id=mb.customer_id
      LEFT JOIN users u ON u.id=fb.created_by
      WHERE 1=1 {scope} ORDER BY fb.id DESC LIMIT 500""", params))
    return jsonify(data)


@app.post("/api/production/furnaces")
@roles_required("admin", "manager")
def create_furnace_batch():
    d = body()
    bid = int(d.get("batch_id") or 0)
    qty = number(d.get("quantity"), "装炉数量", 0, strictly=True)
    process = (d.get("process") or "").strip()
    if not process:
        return jsonify({"error": "镀膜工艺必填"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    batch = row(db.execute("SELECT * FROM material_batches WHERE id=?", (bid,)))
    if not batch:
        return jsonify({"error": "来料批次不存在"}), 404
    if not owns_contract(batch["contract_id"]):
        return jsonify({"error": "无权操作该批次"}), 403
    scheduled = db.execute("SELECT COALESCE(SUM(quantity),0) FROM furnace_batches WHERE batch_id=?", (bid,)).fetchone()[0]
    if qty - (batch["received_qty"] - scheduled) > 0.00001:
        return jsonify({"error": "装炉数量超过该来料批次未排数量"}), 400
    day = today().replace("-", "")
    furnace_no = next_document_no(db, "furnace", "LH-" + day + "-", 3)
    cur = db.execute(
        """INSERT INTO furnace_batches(furnace_no,batch_id,contract_id,process,recipe,equipment,
           operator_name,quantity,started_at,remark,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (furnace_no, bid, batch["contract_id"], process, d.get("recipe", ""), d.get("equipment", ""),
         d.get("operator_name", ""), qty, d.get("started_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
         d.get("remark", ""), g.user["id"]))
    db.execute("UPDATE material_batches SET status='加工中' WHERE id=?", (bid,))
    write_audit(db, "furnace_batch", cur.lastrowid, "create", None,
                {"furnace_no": furnace_no, "batch_id": bid, "quantity": qty, "process": process})
    db.commit()
    return jsonify({"id": cur.lastrowid, "furnace_no": furnace_no}), 201


@app.get("/api/production/quality")
@login_required
def list_quality_inspections():
    scope, params = scope_sql("ct")
    return jsonify(rows(get_db().execute(f"""
      SELECT qi.*, fb.furnace_no, fb.process, mb.batch_no, mb.item_name, ct.contract_no,
        c.name AS customer_name, u.name AS created_by_name
      FROM quality_inspections qi JOIN furnace_batches fb ON fb.id=qi.furnace_batch_id
      JOIN material_batches mb ON mb.id=qi.batch_id JOIN contracts ct ON ct.id=qi.contract_id
      JOIN customers c ON c.id=mb.customer_id LEFT JOIN users u ON u.id=qi.created_by
      WHERE 1=1 {scope} ORDER BY qi.id DESC LIMIT 500""", params)))


@app.post("/api/production/quality")
@roles_required("admin", "manager")
def create_quality_inspection():
    d = body()
    fid = int(d.get("furnace_batch_id") or 0)
    inspected = number(d.get("inspected_qty"), "检验数量", 0, strictly=True)
    passed = number(d.get("pass_qty"), "合格数量", 0)
    failed = number(d.get("fail_qty"), "不合格数量", 0)
    if abs(passed + failed - inspected) > 0.00001:
        return jsonify({"error": "合格数量与不合格数量之和必须等于检验数量"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    furnace = row(db.execute("SELECT * FROM furnace_batches WHERE id=?", (fid,)))
    if not furnace:
        return jsonify({"error": "炉次不存在"}), 404
    if not owns_contract(furnace["contract_id"]):
        return jsonify({"error": "无权操作该炉次"}), 403
    previous_inspected = db.execute(
        "SELECT COALESCE(SUM(inspected_qty),0) FROM quality_inspections WHERE furnace_batch_id=?", (fid,)
    ).fetchone()[0]
    if inspected - (furnace["quantity"] - previous_inspected) > 0.00001:
        return jsonify({"error": "累计检验数量不能超过该炉次装炉数量"}), 400
    result = d.get("result") if d.get("result") == "让步接收" and failed > 0 else ("合格" if failed == 0 else "不合格")
    inspection_date = valid_date(d.get("inspection_date") or today(), "检验日期")
    salt_spray = d.get("salt_spray_hours")
    salt_spray = number(salt_spray, "盐雾小时数", 0) if salt_spray not in (None, "") else None
    cur = db.execute(
        """INSERT INTO quality_inspections(furnace_batch_id,batch_id,contract_id,inspection_date,
           inspector_name,inspected_qty,pass_qty,fail_qty,adhesion,film_thickness,salt_spray_hours,
           result,report_name,remark,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (fid, furnace["batch_id"], furnace["contract_id"], inspection_date, d.get("inspector_name", ""),
         inspected, passed, failed, d.get("adhesion", ""), d.get("film_thickness", ""),
         salt_spray, result, d.get("report_name", ""), d.get("remark", ""), g.user["id"]))
    batch_status = "质量异常" if result == "不合格" else "待验收"
    db.execute("UPDATE material_batches SET status=? WHERE id=?", (batch_status, furnace["batch_id"]))
    db.execute("UPDATE furnace_batches SET status='已质检', finished_at=? WHERE id=?",
               (d.get("finished_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), fid))
    write_audit(db, "quality_inspection", cur.lastrowid, "create", None,
                {"furnace_batch_id": fid, "inspected_qty": inspected, "pass_qty": passed,
                 "fail_qty": failed, "result": result})
    db.commit()
    return jsonify({"id": cur.lastrowid, "result": result}), 201


# ---------------- 签收 / 验收 / 对账 ----------------
@app.get("/api/production/acceptances")
@login_required
def list_acceptances():
    scope, params = scope_sql("ct")
    return jsonify(rows(get_db().execute(f"""
      SELECT ar.*, ct.contract_no, c.name AS customer_name, mb.batch_no,
        s.shipment_no, u.name AS created_by_name
      FROM acceptance_records ar JOIN contracts ct ON ct.id=ar.contract_id
      JOIN customers c ON c.id=ct.customer_id
      LEFT JOIN material_batches mb ON mb.id=ar.batch_id
      LEFT JOIN shipments s ON s.id=ar.shipment_id
      LEFT JOIN users u ON u.id=ar.created_by
      WHERE 1=1 {scope} ORDER BY ar.id DESC LIMIT 500""", params)))


@app.post("/api/production/acceptances")
@roles_required("admin", "sales", "manager")
def create_acceptance():
    d = body()
    record_type = d.get("record_type")
    if record_type not in ("签收", "验收"):
        return jsonify({"error": "记录类型无效"}), 400
    batch_id = int(d.get("batch_id") or 0) or None
    shipment_id = int(d.get("shipment_id") or 0) or None
    if bool(batch_id) == bool(shipment_id):
        return jsonify({"error": "签收/验收必须且只能关联一个批次或发货单"}), 400
    quantity = number(d.get("quantity"), "签收/验收数量", 0, strictly=True)
    record_date = valid_date(d.get("record_date") or today(), "记录日期")
    signed_by = (d.get("signed_by") or "").strip()
    if not signed_by:
        return jsonify({"error": "签收人/验收人必填"}), 400
    allowed_results = ("已签收", "拒收") if record_type == "签收" else ("通过", "部分通过", "不通过")
    result = d.get("result") or allowed_results[0]
    if result not in allowed_results:
        return jsonify({"error": "签收/验收结论无效"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    if shipment_id:
        source = row(db.execute("SELECT * FROM shipments WHERE id=?", (shipment_id,)))
        if not source:
            return jsonify({"error": "发货单不存在"}), 404
        cid = source["contract_id"]
        target = db.execute("SELECT COALESCE(SUM(quantity),0) FROM shipment_items WHERE shipment_id=?", (shipment_id,)).fetchone()[0]
        previous_field = "shipment_id"
    else:
        source = row(db.execute("SELECT * FROM material_batches WHERE id=?", (batch_id,)))
        if not source:
            return jsonify({"error": "来料批次不存在"}), 404
        cid = source["contract_id"]
        target = source["received_qty"]
        previous_field = "batch_id"
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    previous = db.execute(
        f"SELECT COALESCE(SUM(quantity),0) FROM acceptance_records WHERE {previous_field}=? AND record_type=?",
        (shipment_id if shipment_id else batch_id, record_type)).fetchone()[0]
    if quantity - (target - previous) > 0.00001:
        return jsonify({"error": "本次数量超过可签收/验收的剩余数量"}), 400
    prefix = ("QS-" if record_type == "签收" else "YS-") + record_date.replace("-", "") + "-"
    record_no = next_document_no(db, "acceptance", prefix, 3)
    cur = db.execute(
        """INSERT INTO acceptance_records(record_no,record_type,contract_id,shipment_id,batch_id,
           record_date,quantity,result,signed_by,proof_name,remark,created_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (record_no, record_type, cid, shipment_id, batch_id, record_date, quantity, result,
         signed_by, d.get("proof_name", ""), d.get("remark", ""), g.user["id"]))
    if batch_id and record_type == "验收":
        status = "已完成" if result == "通过" and previous + quantity >= target else ("质量异常" if result == "不通过" else "待验收")
        db.execute("UPDATE material_batches SET status=? WHERE id=?", (status, batch_id))
    write_audit(db, "acceptance", cur.lastrowid, "create", None,
                {"record_no": record_no, "record_type": record_type, "quantity": quantity, "result": result})
    db.commit()
    return jsonify({"id": cur.lastrowid, "record_no": record_no}), 201


@app.get("/api/reconciliations")
@login_required
def list_reconciliations():
    scope, params = scope_sql("ct")
    return jsonify(rows(get_db().execute(f"""
      SELECT r.*, ct.contract_no, ct.title AS contract_title, c.name AS customer_name,
        u.name AS created_by_name
      FROM reconciliations r JOIN contracts ct ON ct.id=r.contract_id
      JOIN customers c ON c.id=ct.customer_id LEFT JOIN users u ON u.id=r.created_by
      WHERE 1=1 {scope} ORDER BY r.id DESC LIMIT 500""", params)))


@app.post("/api/reconciliations")
@roles_required("admin", "finance")
def create_reconciliation():
    d = body()
    cid = int(d.get("contract_id") or 0)
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    start = valid_date(d.get("period_start"), "对账开始日期")
    end = valid_date(d.get("period_end"), "对账结束日期")
    if start > end:
        return jsonify({"error": "对账开始日期不能晚于结束日期"}), 400
    amount = round(number(d.get("amount"), "对账金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "对账金额至少为 0.01 元"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    overlap = db.execute(
        """SELECT 1 FROM reconciliations WHERE contract_id=? AND period_start<=? AND period_end>=?
           AND status!='异议' LIMIT 1""", (cid, end, start)).fetchone()
    if overlap:
        return jsonify({"error": "该合同已存在期间重叠的有效对账单"}), 400
    statement_no = next_document_no(db, "reconciliation", "DJ-" + today().replace("-", "") + "-", 3)
    cur = db.execute(
        """INSERT INTO reconciliations(statement_no,contract_id,period_start,period_end,amount,remark,created_by)
           VALUES(?,?,?,?,?,?,?)""",
        (statement_no, cid, start, end, amount, d.get("remark", ""), g.user["id"]))
    write_audit(db, "reconciliation", cur.lastrowid, "create", None,
                {"statement_no": statement_no, "contract_id": cid, "amount": amount,
                 "period_start": start, "period_end": end})
    db.commit()
    return jsonify({"id": cur.lastrowid, "statement_no": statement_no}), 201


@app.put("/api/reconciliations/<int:rid>")
@roles_required("admin", "finance")
def update_reconciliation(rid):
    d = body()
    status = d.get("status")
    if status not in ("已确认", "异议"):
        return jsonify({"error": "只能确认或登记异议"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    before = row(db.execute("SELECT * FROM reconciliations WHERE id=?", (rid,)))
    if not before:
        return jsonify({"error": "对账单不存在"}), 404
    if not owns_contract(before["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    if before["status"] != "待确认":
        return jsonify({"error": "该对账单已处理，不能重复变更状态"}), 400
    reason = (d.get("remark") or "").strip()
    if status == "异议" and not reason:
        return jsonify({"error": "登记异议必须填写原因"}), 400
    after = dict(before, status=status, confirmed_by=g.user["name"],
                 confirmed_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 remark=reason or before["remark"])
    db.execute("UPDATE reconciliations SET status=?,confirmed_by=?,confirmed_at=?,remark=? WHERE id=?",
               (after["status"], after["confirmed_by"], after["confirmed_at"], after["remark"], rid))
    write_audit(db, "reconciliation", rid, status, before, after, reason)
    db.commit()
    return jsonify({"ok": True})


# ---------------- 成本与预估毛利 ----------------
@app.get("/api/costs")
@login_required
def list_costs():
    scope, params = scope_sql("ct")
    where = ""
    if request.args.get("from"):
        where += " AND ce.cost_date>=?"
        params.append(valid_date(request.args["from"], "开始日期"))
    if request.args.get("to"):
        where += " AND ce.cost_date<=?"
        params.append(valid_date(request.args["to"], "结束日期"))
    if request.args.get("category"):
        where += " AND ce.category=?"
        params.append(request.args["category"])
    return jsonify(rows(get_db().execute(f"""
      SELECT ce.*, ct.contract_no, c.name AS customer_name, mb.batch_no, fb.furnace_no,
        u.name AS created_by_name
      FROM cost_entries ce JOIN contracts ct ON ct.id=ce.contract_id
      JOIN customers c ON c.id=ct.customer_id
      LEFT JOIN material_batches mb ON mb.id=ce.batch_id
      LEFT JOIN furnace_batches fb ON fb.id=ce.furnace_batch_id
      LEFT JOIN users u ON u.id=ce.created_by
      WHERE 1=1 {scope} {where} ORDER BY ce.id DESC LIMIT 500""", params)))


@app.post("/api/costs")
@roles_required("admin", "finance", "manager")
def create_cost():
    d = body()
    cid = int(d.get("contract_id") or 0)
    if not cid or not owns_contract(cid):
        return jsonify({"error": "合同无效或无权操作"}), 403
    category = d.get("category")
    if category not in dict_labels(get_db(), "cost_category"):
        return jsonify({"error": "成本类别无效或已停用"}), 400
    amount = round(number(d.get("amount"), "成本金额", 0, strictly=True), 2)
    if amount <= 0:
        return jsonify({"error": "成本金额至少为 0.01 元"}), 400
    cost_date = valid_date(d.get("cost_date") or today(), "成本日期")
    batch_id = int(d.get("batch_id") or 0) or None
    furnace_id = int(d.get("furnace_batch_id") or 0) or None
    db = get_db()
    if batch_id:
        batch = row(db.execute("SELECT contract_id FROM material_batches WHERE id=?", (batch_id,)))
        if not batch or batch["contract_id"] != cid:
            return jsonify({"error": "成本批次不属于该合同"}), 400
    if furnace_id:
        furnace = row(db.execute("SELECT contract_id,batch_id FROM furnace_batches WHERE id=?", (furnace_id,)))
        if not furnace or furnace["contract_id"] != cid:
            return jsonify({"error": "成本炉次不属于该合同"}), 400
        if batch_id and furnace["batch_id"] != batch_id:
            return jsonify({"error": "所选炉次与批次不匹配"}), 400
    cur = db.execute(
        """INSERT INTO cost_entries(contract_id,batch_id,furnace_batch_id,cost_date,category,
           amount,supplier,remark,created_by) VALUES(?,?,?,?,?,?,?,?,?)""",
        (cid, batch_id, furnace_id, cost_date, category, amount,
         d.get("supplier", ""), d.get("remark", ""), g.user["id"]))
    write_audit(db, "cost", cur.lastrowid, "create", None,
                {"contract_id": cid, "batch_id": batch_id, "furnace_batch_id": furnace_id,
                 "category": category, "amount": amount, "cost_date": cost_date})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.delete("/api/costs/<int:cid>")
@admin_required
def delete_cost(cid):
    db = get_db()
    cost = row(db.execute("SELECT * FROM cost_entries WHERE id=?", (cid,)))
    if not cost:
        return jsonify({"error": "成本记录不存在"}), 404
    if not owns_contract(cost["contract_id"]):
        return jsonify({"error": "无权操作"}), 403
    write_audit(db, "cost", cid, "delete", cost, None, "管理员删除成本")
    db.execute("DELETE FROM cost_entries WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/stats/profitability")
@roles_required("admin", "finance")
def stats_profitability():
    db = get_db()
    scope, sparams = scope_sql("ct")
    where, fparams = stat_filters("ct", "sign_date")
    balances = contract_balances(db, scope + where, sparams + fparams)
    ids = [b["id"] for b in balances]
    costs = {}
    categories = {}
    if ids:
        marks = ",".join("?" * len(ids))
        cost_rows = rows(db.execute(
            f"SELECT id,contract_id,category,amount,cost_date FROM cost_entries WHERE contract_id IN ({marks})", ids))
        for cost in cost_rows:
            costs[cost["contract_id"]] = round(costs.get(cost["contract_id"], 0) + cost["amount"], 2)
            categories[cost["category"]] = round(categories.get(cost["category"], 0) + cost["amount"], 2)
    contract_rows = []
    for b in balances:
        cost = costs.get(b["id"], 0)
        profit = round(b["amount"] - cost, 2)
        contract_rows.append({
            "contract_id": b["id"], "contract_no": b["contract_no"], "amount": b["amount"],
            "cost": cost, "gross_profit": profit,
            "margin_rate": round(profit / b["amount"] * 100, 1) if b["amount"] else None,
        })
    amount = round(sum(b["amount"] for b in balances), 2)
    cost_total = round(sum(costs.values()), 2)
    profit = round(amount - cost_total, 2)
    month = datetime.date.today().strftime("%Y-%m")
    demo, dparams = demo_sql("ct")
    cost_month = db.execute(
        f"""SELECT COALESCE(SUM(ce.amount),0) FROM cost_entries ce
            JOIN contracts ct ON ct.id=ce.contract_id
            WHERE strftime('%Y-%m',ce.cost_date)=? {demo}""", [month] + dparams).fetchone()[0]
    return jsonify({
        "amount": amount, "cost": cost_total, "gross_profit": profit,
        "margin_rate": round(profit / amount * 100, 1) if amount else None,
        "cost_month": round(cost_month, 2),
        "by_category": [{"label": k, "amount": v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
        "contracts": sorted(contract_rows, key=lambda x: x["gross_profit"]),
        "loss_contracts": [x for x in contract_rows if x["gross_profit"] < 0][:10],
    })


# ---------------- 设备产能基础资料 ----------------
@app.get("/api/equipment")
@login_required
def list_equipment():
    demo, params = demo_sql()
    return jsonify(rows(get_db().execute(f"SELECT * FROM equipment WHERE 1=1 {demo} ORDER BY active DESC,id", params)))


@app.post("/api/equipment")
@roles_required("admin", "manager")
def create_equipment():
    d = body()
    code = (d.get("code") or "").strip()
    name = (d.get("name") or "").strip()
    if not code or not name:
        return jsonify({"error": "设备编号和名称必填"}), 400
    hours = number(d.get("daily_available_hours") or 16, "每日可用工时", 0, strictly=True)
    if hours > 24:
        return jsonify({"error": "每日可用工时不能超过 24 小时"}), 400
    db = get_db()
    try:
        cur = db.execute("INSERT INTO equipment(code,name,daily_available_hours,remark,is_demo) VALUES(?,?,?,?,?)",
                         (code, name, hours, d.get("remark", ""), 1 if current_data_mode() == "demo" else 0))
    except sqlite3.IntegrityError:
        return jsonify({"error": "设备编号已存在"}), 400
    write_audit(db, "equipment", cur.lastrowid, "create", None,
                {"code": code, "name": name, "daily_available_hours": hours})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.put("/api/equipment/<int:eid>")
@roles_required("admin", "manager")
def update_equipment(eid):
    d = body()
    db = get_db()
    before = row(db.execute("SELECT * FROM equipment WHERE id=?", (eid,)))
    if not before or not record_in_data_mode(before["is_demo"]):
        return jsonify({"error": "设备不存在或不在当前数据范围"}), 404
    name = (d.get("name") or before["name"]).strip()
    hours = number(d.get("daily_available_hours", before["daily_available_hours"]), "每日可用工时", 0, strictly=True)
    if hours > 24:
        return jsonify({"error": "每日可用工时不能超过 24 小时"}), 400
    active = 1 if d.get("active", before["active"]) in (1, True, "1", "true") else 0
    db.execute("UPDATE equipment SET name=?,daily_available_hours=?,active=?,remark=? WHERE id=?",
               (name, hours, active, d.get("remark", before["remark"]), eid))
    after = row(db.execute("SELECT * FROM equipment WHERE id=?", (eid,)))
    write_audit(db, "equipment", eid, "update", before, after)
    db.commit()
    return jsonify({"ok": True})


# ---------------- 工艺配方与版本 ----------------
def process_version_view(v):
    content = json.loads(v["content_json"])
    item = dict(v, **content)
    item.pop("content_json", None)
    return item


def process_version_for_write(db, vid, allow_admin=True):
    v = row(db.execute(
        """SELECT prv.*, pr.is_demo, pr.code AS recipe_code FROM process_recipe_versions prv
           JOIN process_recipes pr ON pr.id=prv.recipe_id WHERE prv.id=?""", (vid,)))
    if not v or not record_in_data_mode(v["is_demo"]):
        return None
    if not allow_admin and g.user["role"] != "admin":
        return None
    return v


@app.get("/api/process/recipes")
@login_required
def list_process_recipes():
    demo, params = demo_sql("pr")
    data = rows(get_db().execute(f"""
      SELECT pr.*, u.name AS created_by_name, prv.version_no AS current_version_no,
        prv.status AS current_version_status, prv.content_json AS current_content
      FROM process_recipes pr LEFT JOIN users u ON u.id=pr.created_by
      LEFT JOIN process_recipe_versions prv ON prv.id=pr.current_version_id
      WHERE 1=1 {demo} ORDER BY pr.id DESC""", params))
    for item in data:
        content = item.pop("current_content", None)
        item["current_version"] = None
        if item["current_version_id"]:
            parsed = json.loads(content)
            item["current_version"] = {"id": item["current_version_id"],
                "version_no": item["current_version_no"], "status": item["current_version_status"],
                "parameters": parsed.get("parameters", []), "steps": parsed.get("steps", [])}
        item.pop("current_version_no", None)
        item.pop("current_version_status", None)
    return jsonify(data)


@app.post("/api/process/recipes")
@roles_required("admin", "engineer")
def create_process_recipe():
    d = body()
    code = (d.get("code") or "").strip().upper()
    name = (d.get("name") or "").strip()
    coating = (d.get("coating_process") or "").strip()
    if not code or not name or not coating:
        return jsonify({"error": "配方编码、名称和镀膜工艺必填"}), 400
    parameters = validate_parameters(d.get("parameters"))
    steps = validate_steps(d.get("steps"))
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = db.execute(
            """INSERT INTO process_recipes(code,name,coating_process,applicable_material,part_category,
               equipment_code,remark,is_demo,created_by) VALUES(?,?,?,?,?,?,?,?,?)""",
            (code, name, coating, d.get("applicable_material", ""), d.get("part_category", ""),
             d.get("equipment_code", ""), d.get("remark", ""),
             1 if current_data_mode() == "demo" else 0, g.user["id"]))
        recipe_id = cur.lastrowid
        content = json.dumps({"parameters": parameters, "steps": steps}, ensure_ascii=False)
        version_no = (d.get("version_no") or "V1.0").strip()
        cur = db.execute(
            """INSERT INTO process_recipe_versions(recipe_id,version_no,content_json,change_reason,created_by)
               VALUES(?,?,?,?,?)""",
            (recipe_id, version_no, content, d.get("change_reason") or "初始工艺版本", g.user["id"]))
    except sqlite3.IntegrityError:
        return jsonify({"error": "配方编码或初始版本已存在"}), 400
    version_id = cur.lastrowid
    write_audit(db, "process_recipe", recipe_id, "create", None,
                {"code": code, "name": name, "version_id": version_id})
    db.commit()
    return jsonify({"id": recipe_id, "version_id": version_id}), 201


@app.get("/api/process/recipes/<int:rid>/versions")
@login_required
def list_process_versions(rid):
    db = get_db()
    recipe = row(db.execute("SELECT is_demo FROM process_recipes WHERE id=?", (rid,)))
    if not recipe or not record_in_data_mode(recipe["is_demo"]):
        return jsonify({"error": "配方不存在或不在当前数据范围"}), 404
    data = rows(db.execute(
        """SELECT prv.*, u.name AS created_by_name, r.name AS reviewed_by_name
           FROM process_recipe_versions prv LEFT JOIN users u ON u.id=prv.created_by
           LEFT JOIN users r ON r.id=prv.reviewed_by WHERE prv.recipe_id=? ORDER BY prv.id DESC""", (rid,)))
    return jsonify([process_version_view(v) for v in data])


@app.post("/api/process/recipes/<int:rid>/versions")
@roles_required("admin", "engineer")
def create_process_version(rid):
    d = body()
    version_no = (d.get("version_no") or "").strip()
    reason = (d.get("change_reason") or "").strip()
    if not version_no or not reason:
        return jsonify({"error": "版本号和变更原因必填"}), 400
    db = get_db()
    recipe = row(db.execute("SELECT * FROM process_recipes WHERE id=?", (rid,)))
    if not recipe or not record_in_data_mode(recipe["is_demo"]):
        return jsonify({"error": "配方不存在或不在当前数据范围"}), 404
    base = row(db.execute(
        "SELECT * FROM process_recipe_versions WHERE recipe_id=? ORDER BY id DESC LIMIT 1", (rid,)))
    content = json.loads(base["content_json"]) if base else {"parameters": [], "steps": []}
    parameters = validate_parameters(d.get("parameters", content.get("parameters")))
    steps = validate_steps(d.get("steps", content.get("steps")))
    content = json.dumps({"parameters": parameters, "steps": steps}, ensure_ascii=False)
    try:
        cur = db.execute(
            """INSERT INTO process_recipe_versions(recipe_id,version_no,content_json,change_reason,created_by)
               VALUES(?,?,?,?,?)""", (rid, version_no, content, reason, g.user["id"]))
    except sqlite3.IntegrityError:
        return jsonify({"error": "该版本号已存在"}), 400
    write_audit(db, "process_recipe_version", cur.lastrowid, "create", None,
                {"recipe_id": rid, "version_no": version_no, "change_reason": reason})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


@app.put("/api/process/recipe-versions/<int:vid>")
@roles_required("admin", "engineer")
def update_process_version(vid):
    d = body()
    db = get_db()
    before = process_version_for_write(db, vid)
    if not before:
        return jsonify({"error": "版本不存在或不在当前数据范围"}), 404
    if before["status"] != "草稿":
        return jsonify({"error": "只有草稿版本可以编辑，请创建新版本"}), 400
    content = json.loads(before["content_json"])
    parameters = validate_parameters(d.get("parameters", content.get("parameters")))
    steps = validate_steps(d.get("steps", content.get("steps")))
    reason = (d.get("change_reason") or before["change_reason"]).strip()
    content = json.dumps({"parameters": parameters, "steps": steps}, ensure_ascii=False)
    db.execute("UPDATE process_recipe_versions SET content_json=?,change_reason=? WHERE id=?",
               (content, reason, vid))
    after = row(db.execute("SELECT * FROM process_recipe_versions WHERE id=?", (vid,)))
    write_audit(db, "process_recipe_version", vid, "update", before, after, reason)
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/process/recipe-versions/<int:vid>/submit")
@roles_required("admin", "engineer")
def submit_process_version(vid):
    db = get_db()
    before = process_version_for_write(db, vid)
    if not before:
        return jsonify({"error": "版本不存在或不在当前数据范围"}), 404
    if before["status"] != "草稿":
        return jsonify({"error": "只有草稿可以提交审核"}), 400
    db.execute("UPDATE process_recipe_versions SET status='待审核' WHERE id=?", (vid,))
    after = row(db.execute("SELECT * FROM process_recipe_versions WHERE id=?", (vid,)))
    write_audit(db, "process_recipe_version", vid, "submit", before, after)
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/process/recipe-versions/<int:vid>/publish")
@admin_required
def publish_process_version(vid):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    before = process_version_for_write(db, vid)
    if not before:
        return jsonify({"error": "版本不存在或不在当前数据范围"}), 404
    if before["status"] != "待审核":
        return jsonify({"error": "只有待审核版本可以发布"}), 400
    db.execute("UPDATE process_recipe_versions SET status='已停用' WHERE recipe_id=? AND status='已发布'",
               (before["recipe_id"],))
    reviewed_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""UPDATE process_recipe_versions
                  SET status='已发布',reviewed_by=?,reviewed_at=? WHERE id=?""",
               (g.user["id"], reviewed_at, vid))
    db.execute("UPDATE process_recipes SET current_version_id=? WHERE id=?",
               (vid, before["recipe_id"]))
    after = row(db.execute("SELECT * FROM process_recipe_versions WHERE id=?", (vid,)))
    write_audit(db, "process_recipe_version", vid, "publish", before, after)
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/process/parameters")
@login_required
def list_process_parameter_defs():
    return jsonify(rows(get_db().execute(
        "SELECT * FROM process_parameter_defs WHERE active=1 ORDER BY sort,id")))


@app.post("/api/process/parameters")
@roles_required("admin", "engineer")
def create_process_parameter_def():
    d = body()
    try:
        item = validate_parameters([d])[0]
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO process_parameter_defs(code,name,stage,value_type,unit,required,sort)
               VALUES(?,?,?,?,?,?,?)""",
            (item["code"], item["name"], item["stage"], item["value_type"], item["unit"],
             1 if item["required"] else 0, int(d.get("sort") or 0)))
    except sqlite3.IntegrityError:
        return jsonify({"error": "参数编码已存在"}), 400
    write_audit(db, "process_parameter", cur.lastrowid, "create", None, item)
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


# ---------------- 工艺执行批次 ----------------
def process_run_for_access(db, rid):
    run = row(db.execute("SELECT * FROM process_runs WHERE id=?", (rid,)))
    if not run or not owns_contract(run["contract_id"]):
        return None
    return run


@app.post("/api/process/runs")
@roles_required("admin", "manager", "engineer")
def create_process_run():
    d = body()
    fid = int(d.get("furnace_batch_id") or 0)
    vid = int(d.get("recipe_version_id") or 0)
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    furnace = row(db.execute("SELECT * FROM furnace_batches WHERE id=?", (fid,)))
    if not furnace:
        return jsonify({"error": "炉次不存在"}), 404
    if not owns_contract(furnace["contract_id"]):
        return jsonify({"error": "无权为该炉次创建工艺记录"}), 403
    version = row(db.execute("SELECT * FROM process_recipe_versions WHERE id=?", (vid,)))
    if not version or version["status"] != "已发布":
        return jsonify({"error": "只能使用已发布的工艺版本"}), 400
    recipe = row(db.execute("SELECT * FROM process_recipes WHERE id=?", (version["recipe_id"],)))
    if not recipe or recipe["current_version_id"] != vid:
        return jsonify({"error": "新版本执行必须使用配方当前发布版本"}), 400
    contract = row(db.execute("SELECT is_demo FROM contracts WHERE id=?", (furnace["contract_id"],)))
    if recipe["is_demo"] != contract["is_demo"]:
        return jsonify({"error": "工艺配方与炉次的数据范围不一致"}), 400
    if db.execute("SELECT 1 FROM process_runs WHERE furnace_batch_id=? AND status!='已作废'", (fid,)).fetchone():
        return jsonify({"error": "该炉次已有执行中的工艺记录"}), 400
    run_no = next_document_no(db, "process_run", "GY-" + today().replace("-", "") + "-", 3)
    try:
        cur = db.execute(
            """INSERT INTO process_runs(run_no,recipe_id,recipe_version_id,batch_id,furnace_batch_id,
               contract_id,snapshot_json,operator_id,started_at,finished_at,remark,created_by)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_no, recipe["id"], vid, furnace["batch_id"], fid, furnace["contract_id"],
             version["content_json"], g.user["id"], furnace["started_at"], furnace["finished_at"],
             d.get("remark", ""), g.user["id"]))
    except sqlite3.IntegrityError:
        return jsonify({"error": "该炉次已有工艺记录"}), 400
    rid = cur.lastrowid
    content = json.loads(version["content_json"])
    for p in content.get("parameters", []):
        db.execute(
            """INSERT INTO process_run_values(run_id,parameter_code,parameter_name,stage,value_type,
               unit,target_value,min_value,max_value) VALUES(?,?,?,?,?,?,?,?,?)""",
            (rid, p["code"], p["name"], p["stage"], p["value_type"], p["unit"],
             "" if p.get("target") is None else str(p["target"]), p.get("min"), p.get("max")))
    write_audit(db, "process_run", rid, "create", None,
                {"run_no": run_no, "furnace_batch_id": fid, "recipe_version_id": vid})
    db.commit()
    return jsonify({"id": rid, "run_no": run_no}), 201


@app.get("/api/process/runs")
@login_required
def list_process_runs():
    scope, params = scope_sql("ct")
    return jsonify(rows(get_db().execute(f"""
      SELECT run.*, recipe.code AS recipe_code, recipe.name AS recipe_name, prv.version_no,
        fb.furnace_no, mb.batch_no, mb.item_name, c.name AS customer_name, ct.contract_no,
        u.name AS operator_name,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='异常'),0) AS abnormal_values,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='缺失'),0) AS missing_values
      FROM process_runs run JOIN process_recipes recipe ON recipe.id=run.recipe_id
      JOIN process_recipe_versions prv ON prv.id=run.recipe_version_id
      JOIN furnace_batches fb ON fb.id=run.furnace_batch_id
      JOIN material_batches mb ON mb.id=run.batch_id
      JOIN contracts ct ON ct.id=run.contract_id JOIN customers c ON c.id=ct.customer_id
      LEFT JOIN users u ON u.id=run.operator_id
      WHERE 1=1 {scope} ORDER BY run.id DESC LIMIT 500""", params)))


@app.get("/api/process/runs/<int:rid>")
@login_required
def process_run_detail(rid):
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权访问"}), 404
    item = dict(run)
    item["snapshot"] = json.loads(item.pop("snapshot_json"))
    item["values"] = rows(db.execute(
        "SELECT * FROM process_run_values WHERE run_id=? ORDER BY id", (rid,)))
    item["events"] = rows(db.execute(
        """SELECT pe.*, u.name AS created_by_name FROM process_events pe
           LEFT JOIN users u ON u.id=pe.created_by WHERE pe.run_id=? ORDER BY pe.event_time DESC,pe.id DESC""", (rid,)))
    item["attachments"] = rows(db.execute(
        """SELECT pa.id,pa.orig_name,pa.size,pa.created_at,u.name AS uploaded_by_name
           FROM process_attachments pa LEFT JOIN users u ON u.id=pa.uploaded_by
           WHERE pa.run_id=? ORDER BY pa.id DESC""", (rid,)))
    return jsonify(item)


@app.put("/api/process/runs/<int:rid>/values")
@roles_required("admin", "manager", "engineer")
def update_process_values(rid):
    d = body()
    values = d.get("values")
    if not isinstance(values, list) or not values:
        return jsonify({"error": "参数实测值不能为空"}), 400
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] not in ("草稿", "已审核"):
        return jsonify({"error": "当前状态不能修改参数"}), 400
    if run["status"] == "已审核" and g.user["role"] == "manager":
        return jsonify({"error": "已审核记录只能由工艺工程师或管理员修订"}), 403
    before_values = rows(db.execute("SELECT * FROM process_run_values WHERE run_id=? ORDER BY id", (rid,)))
    recorded_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in values:
        value = row(db.execute("SELECT * FROM process_run_values WHERE id=? AND run_id=?",
                               (int(item.get("id") or 0), rid)))
        if not value:
            return jsonify({"error": "参数不属于该执行批次"}), 400
        actual = item.get("actual")
        actual_numeric = None
        actual_text = ""
        if actual not in (None, ""):
            if value["value_type"] == "number":
                actual_numeric = number(actual, f"参数 {value['parameter_code']} 实测值")
            else:
                actual_text = str(actual)
        status = item.get("status") or "正常"
        if status not in ("正常", "异常", "缺失", "估读"):
            return jsonify({"error": "参数状态无效"}), 400
        if actual in (None, ""):
            status = "缺失"
        elif value["value_type"] == "number" and ((value["min_value"] is not None and actual_numeric < value["min_value"]) or
                                                  (value["max_value"] is not None and actual_numeric > value["max_value"])):
            status = "异常"
        db.execute(
            """UPDATE process_run_values SET actual_numeric=?,actual_text=?,status=?,recorded_at=?,recorded_by=?
               WHERE id=?""",
            (actual_numeric, actual_text, status, recorded_at, g.user["id"], value["id"]))
    db.execute("UPDATE process_runs SET updated_at=? WHERE id=?", (recorded_at, rid))
    after_values = rows(db.execute("SELECT * FROM process_run_values WHERE run_id=? ORDER BY id", (rid,)))
    write_audit(db, "process_run", rid, "update_values", before_values, after_values, d.get("reason", ""))
    db.commit()
    return jsonify({"ok": True, "abnormal": sum(v["status"] == "异常" for v in after_values)})


@app.post("/api/process/runs/<int:rid>/submit")
@roles_required("admin", "manager", "engineer")
def submit_process_run(rid):
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] != "草稿":
        return jsonify({"error": "只有草稿可以提交审核"}), 400
    snapshot = json.loads(run["snapshot_json"])
    required = {p["code"] for p in snapshot.get("parameters", []) if p.get("required")}
    if required:
        placeholders = ",".join("?" * len(required))
        missing = db.execute(
            f"""SELECT COUNT(*) FROM process_run_values WHERE run_id=? AND status='缺失'
                AND parameter_code IN ({placeholders})""", [rid] + list(required)).fetchone()[0]
        if missing:
            return jsonify({"error": "仍有必填参数缺失，不能提交审核"}), 400
    submitted_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE process_runs SET status='待审核',submitted_at=?,updated_at=? WHERE id=?",
               (submitted_at, submitted_at, rid))
    after = row(db.execute("SELECT * FROM process_runs WHERE id=?", (rid,)))
    write_audit(db, "process_run", rid, "submit", run, after)
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/process/runs/<int:rid>/review")
@roles_required("admin", "engineer")
def review_process_run(rid):
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] != "待审核":
        return jsonify({"error": "只有待审核记录可以审核"}), 400
    reviewed_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE process_runs SET status='已审核',reviewer_id=?,reviewed_at=?,updated_at=? WHERE id=?",
               (g.user["id"], reviewed_at, reviewed_at, rid))
    after = row(db.execute("SELECT * FROM process_runs WHERE id=?", (rid,)))
    write_audit(db, "process_run", rid, "review", run, after)
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/process/runs/<int:rid>/void")
@roles_required("admin", "engineer")
def void_process_run(rid):
    d = body()
    if not (d.get("reason") or "").strip():
        return jsonify({"error": "作废原因必填"}), 400
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] == "已作废":
        return jsonify({"error": "该记录已作废"}), 400
    db.execute("UPDATE process_runs SET status='已作废',updated_at=? WHERE id=?",
               (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rid))
    after = row(db.execute("SELECT * FROM process_runs WHERE id=?", (rid,)))
    write_audit(db, "process_run", rid, "void", run, after, d["reason"])
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/process/runs/<int:rid>/events")
@roles_required("admin", "manager", "engineer")
def create_process_event(rid):
    d = body()
    event_type = (d.get("event_type") or "").strip()
    description = (d.get("description") or "").strip()
    allowed_types = ("工序开始", "工序结束", "参数调整", "停机", "返工", "异常处理", "其他")
    if event_type not in allowed_types or not description:
        return jsonify({"error": "事件类型和事件说明必填"}), 400
    try:
        event_time = datetime.datetime.fromisoformat(
            (d.get("event_time") or "").strip().replace("T", " ")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return jsonify({"error": "事件时间格式无效"}), 400
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] == "已作废":
        return jsonify({"error": "已作废记录不能新增事件"}), 400
    cur = db.execute(
        "INSERT INTO process_events(run_id,event_type,event_time,description,reason,created_by) VALUES(?,?,?,?,?,?)",
        (rid, event_type, event_time, description, (d.get("reason") or "").strip(), g.user["id"]))
    updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE process_runs SET updated_at=? WHERE id=?", (updated_at, rid))
    write_audit(db, "process_run", rid, "add_event", None,
                {"id": cur.lastrowid, "event_type": event_type, "event_time": event_time,
                 "description": description, "reason": (d.get("reason") or "").strip()})
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


PROCESS_ATTACHMENT_EXTS = PREVIEW_EXTS | {".csv", ".xls", ".xlsx"}


@app.post("/api/process/runs/<int:rid>/attachments")
@roles_required("admin", "manager", "engineer")
def upload_process_attachment(rid):
    db = get_db()
    run = process_run_for_access(db, rid)
    if not run:
        return jsonify({"error": "执行批次不存在或无权操作"}), 404
    if run["status"] == "已作废":
        return jsonify({"error": "已作废记录不能上传附件"}), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "请选择文件"}), 400
    orig = f.filename
    if os.path.splitext(orig)[1].lower() not in PROCESS_ATTACHMENT_EXTS:
        return jsonify({"error": "仅支持 PDF、图片、文本、CSV 或 Excel 附件，不支持 SVG/HTML"}), 400
    fname = (f"process_{rid}_{int(datetime.datetime.now().timestamp() * 1000)}_"
             f"{secrets.token_hex(8)}_{secure_filename(orig) or 'evidence'}")
    f.save(os.path.join(UPLOAD_DIR, fname))
    size = os.path.getsize(os.path.join(UPLOAD_DIR, fname))
    cur = db.execute(
        "INSERT INTO process_attachments(run_id,filename,orig_name,size,uploaded_by) VALUES(?,?,?,?,?)",
        (rid, fname, orig, size, g.user["id"]))
    write_audit(db, "process_run", rid, "add_attachment", None,
                {"id": cur.lastrowid, "orig_name": orig, "size": size})
    db.commit()
    return jsonify({"id": cur.lastrowid, "orig_name": orig, "size": size}), 201


@app.get("/api/process/attachments/<int:aid>")
@login_required
def serve_process_attachment(aid):
    db = get_db()
    attachment = row(db.execute("SELECT * FROM process_attachments WHERE id=?", (aid,)))
    if not attachment or not process_run_for_access(db, attachment["run_id"]):
        return jsonify({"error": "附件不存在或无权访问"}), 404
    ext = os.path.splitext(attachment["orig_name"])[1].lower()
    response = send_from_directory(
        UPLOAD_DIR, attachment["filename"], as_attachment=request.args.get("dl") == "1" or ext not in PREVIEW_EXTS,
        download_name=attachment["orig_name"])
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@app.get("/api/process/monitor")
@login_required
def process_monitor():
    scope, params = scope_sql("ct")
    data = rows(get_db().execute(f"""
      SELECT run.id,run.run_no,run.status,run.updated_at,recipe.name AS recipe_name,prv.version_no,
        fb.furnace_no,mb.batch_no,mb.item_name,ct.contract_no,c.name AS customer_name,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='异常'),0) AS abnormal_values,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='缺失'),0) AS missing_values,
        (SELECT GROUP_CONCAT(v.parameter_name || '：' || CAST(COALESCE(v.actual_numeric,v.actual_text) AS TEXT) || v.unit,'、')
           FROM process_run_values v WHERE v.run_id=run.id AND v.status='异常') AS abnormal_parameters,
        (SELECT GROUP_CONCAT(v.parameter_name,'、') FROM process_run_values v
           WHERE v.run_id=run.id AND v.status='缺失') AS missing_parameters,
        ROUND((julianday('now','localtime')-julianday(run.updated_at))*24,1) AS idle_hours
      FROM process_runs run JOIN process_recipes recipe ON recipe.id=run.recipe_id
      JOIN process_recipe_versions prv ON prv.id=run.recipe_version_id
      JOIN furnace_batches fb ON fb.id=run.furnace_batch_id
      JOIN material_batches mb ON mb.id=run.batch_id
      JOIN contracts ct ON ct.id=run.contract_id JOIN customers c ON c.id=ct.customer_id
      WHERE run.status!='已作废' {scope} ORDER BY run.updated_at ASC""", params))
    abnormal = [x for x in data if x["abnormal_values"]]
    missing = [x for x in data if x["missing_values"]]
    stale = [x for x in data if x["status"] in ("草稿", "待审核") and x["idle_hours"] >= 24]
    return jsonify({
        "summary": {"active_runs": sum(x["status"] in ("草稿", "待审核") for x in data),
                    "abnormal_runs": len(abnormal), "missing_runs": len(missing),
                    "pending_review": sum(x["status"] == "待审核" for x in data),
                    "stale_runs": len(stale)},
        "abnormal": abnormal, "missing": missing, "stale": stale,
        "note": "仅反映人工录入的参数偏差和记录时效，不代表设备实时状态。",
    })


# ---------------- 工艺分析与改进 ----------------
def process_run_metrics(db, run_ids):
    if not run_ids:
        return {}
    placeholders = ",".join("?" * len(run_ids))
    data = rows(db.execute(f"""
      SELECT run.id,run.run_no,run.recipe_id,run.recipe_version_id,run.contract_id,run.status,
        run.started_at,run.finished_at,run.created_at,recipe.code AS recipe_code,recipe.name AS recipe_name,
        prv.version_no,fb.furnace_no,mb.batch_no,mb.item_name,ct.contract_no,c.name AS customer_name,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='异常'),0) AS abnormal_values,
        COALESCE((SELECT COUNT(*) FROM process_run_values v WHERE v.run_id=run.id AND v.status='缺失'),0) AS missing_values,
        (SELECT COUNT(*) FROM quality_inspections q WHERE q.furnace_batch_id=run.furnace_batch_id) AS quality_count,
        (SELECT COALESCE(SUM(q.inspected_qty),0) FROM quality_inspections q WHERE q.furnace_batch_id=run.furnace_batch_id) AS quality_inspected,
        (SELECT COALESCE(SUM(q.pass_qty),0) FROM quality_inspections q WHERE q.furnace_batch_id=run.furnace_batch_id) AS quality_passed,
        (SELECT COUNT(*) FROM cost_entries ce WHERE ce.furnace_batch_id=run.furnace_batch_id) AS cost_count,
        (SELECT SUM(ce.amount) FROM cost_entries ce WHERE ce.furnace_batch_id=run.furnace_batch_id) AS cost,
        CASE WHEN fb.started_at!='' AND fb.finished_at!=''
          THEN ROUND((julianday(fb.finished_at)-julianday(fb.started_at))*24,2) END AS duration_hours
      FROM process_runs run JOIN process_recipes recipe ON recipe.id=run.recipe_id
      JOIN process_recipe_versions prv ON prv.id=run.recipe_version_id
      JOIN furnace_batches fb ON fb.id=run.furnace_batch_id
      JOIN material_batches mb ON mb.id=run.batch_id
      JOIN contracts ct ON ct.id=run.contract_id JOIN customers c ON c.id=ct.customer_id
      WHERE run.id IN ({placeholders}) ORDER BY run.created_at,run.id""", run_ids))
    for item in data:
        item["quality_rate"] = (round(item["quality_passed"] * 100 / item["quality_inspected"], 2)
                                if item["quality_inspected"] else None)
    return {item["id"]: item for item in data}


def average(values):
    values = [x for x in values if x is not None]
    return round(sum(values) / len(values), 4) if values else None


@app.get("/api/process/analysis")
@login_required
def process_analysis():
    db = get_db()
    recipe_id = int(request.args.get("recipe_id") or 0)
    version_id = int(request.args.get("version_id") or 0)
    recipe = row(db.execute("SELECT * FROM process_recipes WHERE id=?", (recipe_id,)))
    if not recipe or not record_in_data_mode(recipe["is_demo"]):
        return jsonify({"error": "配方不存在或不在当前数据范围"}), 404
    conditions = ["run.recipe_id=?", "run.status!='已作废'"]
    params = [recipe_id]
    if version_id:
        version = row(db.execute("SELECT id FROM process_recipe_versions WHERE id=? AND recipe_id=?",
                                 (version_id, recipe_id)))
        if not version:
            return jsonify({"error": "版本不属于该配方"}), 400
        conditions.append("run.recipe_version_id=?")
        params.append(version_id)
    scope, scope_params = scope_sql("ct")
    run_ids = [r[0] for r in db.execute(f"""
      SELECT run.id FROM process_runs run JOIN contracts ct ON ct.id=run.contract_id
      WHERE {' AND '.join(conditions)} {scope} ORDER BY run.id""", params + scope_params)]
    metrics = process_run_metrics(db, run_ids)
    run_data = list(metrics.values())
    values = []
    if run_ids:
        placeholders = ",".join("?" * len(run_ids))
        values = rows(db.execute(f"""
          SELECT v.*,run.run_no,run.recipe_version_id FROM process_run_values v
          JOIN process_runs run ON run.id=v.run_id WHERE v.run_id IN ({placeholders})
          ORDER BY run.created_at,run.id,v.id""", run_ids))
    grouped = {}
    for value in values:
        group = grouped.setdefault(value["parameter_code"], {
            "code": value["parameter_code"], "name": value["parameter_name"],
            "unit": value["unit"], "stage": value["stage"], "numbers": [],
            "missing": 0, "abnormal": 0, "estimated": 0, "trend": [],
        })
        group["missing"] += value["status"] == "缺失"
        group["abnormal"] += value["status"] == "异常"
        group["estimated"] += value["status"] == "估读"
        if value["actual_numeric"] is not None:
            group["numbers"].append(value["actual_numeric"])
            group["trend"].append({"run_id": value["run_id"], "run_no": value["run_no"],
                                   "version_id": value["recipe_version_id"],
                                   "actual": value["actual_numeric"], "status": value["status"]})
    parameters = []
    for group in grouped.values():
        numbers = group.pop("numbers")
        avg = average(numbers)
        group.update({"count": len(numbers), "avg": avg,
                      "min": min(numbers) if numbers else None, "max": max(numbers) if numbers else None,
                      "stddev": round(math.sqrt(sum((x - avg) ** 2 for x in numbers) / len(numbers)), 4)
                      if numbers else None,
                      "sample_note": "样本不足 3 个，仅作描述" if len(numbers) < 3 else "描述性统计，不构成自动寻优结论"})
        parameters.append(group)
    versions = {}
    for run in run_data:
        group = versions.setdefault(run["recipe_version_id"], {
            "version_id": run["recipe_version_id"], "version_no": run["version_no"],
            "run_count": 0, "reviewed_runs": 0, "abnormal_runs": 0,
            "quality_inspected": 0, "quality_passed": 0, "costs": [], "durations": [],
        })
        group["run_count"] += 1
        group["reviewed_runs"] += run["status"] == "已审核"
        group["abnormal_runs"] += run["abnormal_values"] > 0
        group["quality_inspected"] += run["quality_inspected"]
        group["quality_passed"] += run["quality_passed"]
        if run["cost"] is not None:
            group["costs"].append(run["cost"])
        if run["duration_hours"] is not None:
            group["durations"].append(run["duration_hours"])
    version_data = []
    for group in versions.values():
        costs = group.pop("costs"); durations = group.pop("durations")
        group["quality_rate"] = (round(group["quality_passed"] * 100 / group["quality_inspected"], 2)
                                 if group["quality_inspected"] else None)
        group["avg_cost"] = average(costs); group["avg_duration_hours"] = average(durations)
        version_data.append(group)
    pareto = sorted(({"code": p["code"], "name": p["name"], "count": p["abnormal"]}
                     for p in parameters if p["abnormal"]), key=lambda x: (-x["count"], x["code"]))
    benchmarks = sorted((x for x in run_data if x["status"] == "已审核" and not x["abnormal_values"]
                         and not x["missing_values"] and x["quality_rate"] == 100),
                        key=lambda x: (x["cost"] if x["cost"] is not None else math.inf,
                                       x["duration_hours"] if x["duration_hours"] is not None else math.inf))[:5]
    return jsonify({"recipe": {"id": recipe["id"], "code": recipe["code"], "name": recipe["name"]},
                    "summary": {"runs": len(run_data), "reviewed_runs": sum(x["status"] == "已审核" for x in run_data),
                                "abnormal_runs": sum(x["abnormal_values"] > 0 for x in run_data),
                                "quality_rate": round(sum(x["quality_passed"] for x in run_data) * 100 /
                                                      sum(x["quality_inspected"] for x in run_data), 2)
                                if sum(x["quality_inspected"] for x in run_data) else None},
                    "runs": run_data, "versions": version_data, "parameters": parameters,
                    "abnormal_pareto": pareto, "benchmark_candidates": benchmarks,
                    "benchmark_note": "标杆候选须已审核、无缺失/异常且质量合格率为 100%；不代表自动寻优结论。"})


@app.get("/api/process/compare")
@login_required
def compare_process_runs():
    try:
        run_ids = [int(x) for x in (request.args.get("run_ids") or "").split(",") if x]
    except ValueError:
        return jsonify({"error": "批次编号格式无效"}), 400
    if len(run_ids) != 2 or len(set(run_ids)) != 2:
        return jsonify({"error": "请选择两个不同的执行批次"}), 400
    db = get_db()
    runs = []
    for rid in run_ids:
        run = process_run_for_access(db, rid)
        if not run or run["status"] == "已作废":
            return jsonify({"error": "执行批次不存在、已作废或无权访问"}), 404
        runs.append(run)
    metrics = process_run_metrics(db, run_ids)
    value_maps = []
    codes = []
    for rid in run_ids:
        data = rows(db.execute("SELECT * FROM process_run_values WHERE run_id=? ORDER BY id", (rid,)))
        value_maps.append({x["parameter_code"]: x for x in data})
        codes.extend(x["parameter_code"] for x in data if x["parameter_code"] not in codes)
    parameters = []
    for code in codes:
        left = value_maps[0].get(code); right = value_maps[1].get(code)
        parameters.append({"code": code, "name": (left or right)["parameter_name"],
                           "unit": (left or right)["unit"], "left": left, "right": right,
                           "difference": right["actual_numeric"] - left["actual_numeric"]
                           if left and right and left["actual_numeric"] is not None and right["actual_numeric"] is not None else None})
    left, right = metrics[run_ids[0]], metrics[run_ids[1]]
    delta = lambda key: right[key] - left[key] if left[key] is not None and right[key] is not None else None
    return jsonify({"runs": [left, right], "parameters": parameters,
                    "quality_delta": delta("quality_rate"), "cost_delta": delta("cost"),
                    "duration_delta": delta("duration_hours")})


def validate_process_improvement(db, d, current=None):
    def value(key, default=None):
        if key in d:
            return d[key]
        if current:
            if key == "variables":
                return json.loads(current["variables_json"])
            if key in current:
                return current[key]
        return default
    recipe_id = int(value("recipe_id", 0) or 0)
    title = (value("title", "") or "").strip()
    problem = (value("problem", "") or "").strip()
    status = value("status", "草稿")
    if not recipe_id or not title or not problem:
        raise ValueError("改进主题、关联配方和问题描述必填")
    if status not in ("草稿", "验证中", "已结案", "已取消"):
        raise ValueError("改进专题状态无效")
    conclusion = (value("conclusion", "") or "").strip()
    if status == "已结案" and not conclusion:
        raise ValueError("结案前必须填写结论")
    recipe = row(db.execute("SELECT * FROM process_recipes WHERE id=?", (recipe_id,)))
    if not recipe or not record_in_data_mode(recipe["is_demo"]):
        raise ValueError("关联配方不存在或不在当前数据范围")
    result = {"recipe_id": recipe_id, "title": title, "problem": problem,
              "hypothesis": (value("hypothesis", "") or "").strip(), "conclusion": conclusion,
              "status": status, "is_demo": recipe["is_demo"]}
    linked = {}
    for key in ("baseline_run_id", "candidate_run_id"):
        rid = int(value(key, 0) or 0) or None
        if rid:
            run = process_run_for_access(db, rid)
            if not run or run["status"] == "已作废" or run["recipe_id"] != recipe_id:
                raise ValueError("对照批次必须属于该配方、未作废且在当前权限范围")
        linked[key] = rid
    if linked["baseline_run_id"] and linked["baseline_run_id"] == linked["candidate_run_id"]:
        raise ValueError("基准批次和候选批次不能相同")
    result.update(linked)
    version_id = int(value("result_version_id", 0) or 0) or None
    if version_id and not row(db.execute(
            "SELECT id FROM process_recipe_versions WHERE id=? AND recipe_id=?", (version_id, recipe_id))):
        raise ValueError("形成版本必须属于该配方")
    result["result_version_id"] = version_id
    variables = value("variables", [])
    if not isinstance(variables, list):
        raise ValueError("改进变量必须是数组")
    result["variables"] = [str(x).strip() for x in variables if str(x).strip()]
    return result


def process_improvement_view(db, item):
    result = dict(item)
    result["variables"] = json.loads(result.pop("variables_json"))
    ids = [x for x in (item["baseline_run_id"], item["candidate_run_id"]) if x]
    metrics = process_run_metrics(db, ids)
    baseline = metrics.get(item["baseline_run_id"]); candidate = metrics.get(item["candidate_run_id"])
    result["baseline"] = baseline; result["candidate"] = candidate
    result["quality_delta"] = (candidate["quality_rate"] - baseline["quality_rate"]
                               if baseline and candidate and baseline["quality_rate"] is not None
                               and candidate["quality_rate"] is not None else None)
    result["cost_delta"] = (candidate["cost"] - baseline["cost"]
                            if baseline and candidate and baseline["cost"] is not None
                            and candidate["cost"] is not None else None)
    return result


@app.get("/api/process/improvements")
@login_required
def list_process_improvements():
    db = get_db()
    demo, params = demo_sql("pi")
    data = rows(db.execute(f"""
      SELECT pi.*,recipe.code AS recipe_code,recipe.name AS recipe_name,u.name AS created_by_name,
        baseline.run_no AS baseline_run_no,candidate.run_no AS candidate_run_no,prv.version_no AS result_version_no
      FROM process_improvements pi JOIN process_recipes recipe ON recipe.id=pi.recipe_id
      LEFT JOIN users u ON u.id=pi.created_by LEFT JOIN process_runs baseline ON baseline.id=pi.baseline_run_id
      LEFT JOIN process_runs candidate ON candidate.id=pi.candidate_run_id
      LEFT JOIN process_recipe_versions prv ON prv.id=pi.result_version_id
      WHERE 1=1 {demo} ORDER BY pi.id DESC LIMIT 200""", params))
    if g.user["role"] == "sales":
        data = [item for item in data
                if [x for x in (item["baseline_run_id"], item["candidate_run_id"]) if x]
                and all(process_run_for_access(db, x) for x in
                        (item["baseline_run_id"], item["candidate_run_id"]) if x)]
    return jsonify([process_improvement_view(db, x) for x in data])


@app.post("/api/process/improvements")
@roles_required("admin", "engineer")
def create_process_improvement():
    db = get_db()
    item = validate_process_improvement(db, body())
    db.execute("BEGIN IMMEDIATE")
    code = next_document_no(db, "process_improvement", "GJ-" + today().replace("-", "") + "-", 3)
    cur = db.execute("""
      INSERT INTO process_improvements(code,title,recipe_id,problem,hypothesis,baseline_run_id,candidate_run_id,
        result_version_id,variables_json,conclusion,status,is_demo,created_by,closed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (code, item["title"], item["recipe_id"], item["problem"], item["hypothesis"],
       item["baseline_run_id"], item["candidate_run_id"], item["result_version_id"],
       json.dumps(item["variables"], ensure_ascii=False), item["conclusion"], item["status"],
       item["is_demo"], g.user["id"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
       if item["status"] == "已结案" else ""))
    write_audit(db, "process_improvement", cur.lastrowid, "create", None, {"code": code, **item})
    db.commit()
    return jsonify({"id": cur.lastrowid, "code": code}), 201


@app.put("/api/process/improvements/<int:iid>")
@roles_required("admin", "engineer")
def update_process_improvement(iid):
    db = get_db()
    before = row(db.execute("SELECT * FROM process_improvements WHERE id=?", (iid,)))
    if not before or not record_in_data_mode(before["is_demo"]):
        return jsonify({"error": "改进专题不存在或不在当前数据范围"}), 404
    if before["status"] in ("已结案", "已取消"):
        return jsonify({"error": "已结案或已取消专题不可修改，请新建专题继续验证"}), 400
    item = validate_process_improvement(db, body(), before)
    updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""
      UPDATE process_improvements SET title=?,recipe_id=?,problem=?,hypothesis=?,baseline_run_id=?,
        candidate_run_id=?,result_version_id=?,variables_json=?,conclusion=?,status=?,is_demo=?,updated_at=?,
        closed_at=CASE WHEN ?='已结案' THEN ? ELSE '' END WHERE id=?""",
      (item["title"], item["recipe_id"], item["problem"], item["hypothesis"], item["baseline_run_id"],
       item["candidate_run_id"], item["result_version_id"], json.dumps(item["variables"], ensure_ascii=False),
       item["conclusion"], item["status"], item["is_demo"], updated_at, item["status"], updated_at, iid))
    after = row(db.execute("SELECT * FROM process_improvements WHERE id=?", (iid,)))
    write_audit(db, "process_improvement", iid, "update", before, after)
    db.commit()
    return jsonify({"ok": True})


# ---------------- 数据字典 ----------------
@app.get("/api/dicts")
@login_required
def get_dicts():
    db = get_db()
    out = {}
    for t in rows(db.execute("SELECT * FROM dict_types ORDER BY code")):
        out[t["code"]] = {
            "name": t["name"], "builtin": t["builtin"],
            "items": rows(db.execute(
                "SELECT id,label,sort,active FROM dict_items WHERE type_code=? ORDER BY sort,id",
                (t["code"],))),
        }
    return jsonify(out)


@app.post("/api/dicts")
@admin_required
def create_dict_type():
    d = body()
    code = (d.get("code") or "").strip()
    if not code or not d.get("name"):
        return jsonify({"error": "字典编码和名称必填"}), 400
    try:
        get_db().execute("INSERT INTO dict_types(code,name,builtin) VALUES(?,?,0)", (code, d["name"]))
        get_db().commit()
        return jsonify({"ok": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "字典编码已存在"}), 400


@app.post("/api/dicts/<code>/items")
@admin_required
def add_dict_item(code):
    d = body()
    if not d.get("label"):
        return jsonify({"error": "字典项名称必填"}), 400
    db = get_db()
    if not row(db.execute("SELECT code FROM dict_types WHERE code=?", (code,))):
        return jsonify({"error": "字典类型不存在"}), 404
    try:
        cur = db.execute("INSERT INTO dict_items(type_code,label,sort) VALUES(?,?,?)",
                         (code, d["label"], int(d.get("sort") or 99)))
        db.commit()
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "该字典项已存在"}), 400


@app.put("/api/dict-items/<int:iid>")
@admin_required
def update_dict_item(iid):
    d = body()
    db = get_db()
    if "label" in d and d["label"]:
        db.execute("UPDATE dict_items SET label=? WHERE id=?", (d["label"], iid))
    if "sort" in d:
        db.execute("UPDATE dict_items SET sort=? WHERE id=?", (int(d["sort"]), iid))
    if "active" in d:
        db.execute("UPDATE dict_items SET active=? WHERE id=?", (1 if d["active"] else 0, iid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/dict-items/<int:iid>")
@admin_required
def delete_dict_item(iid):
    db = get_db()
    db.execute("DELETE FROM dict_items WHERE id=?", (iid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 公司基础信息 ----------------
COMPANY_KEYS = ["company_name", "reg_address", "prod_address", "ship_address",
                "invoice_title", "tax_no", "bank_name", "bank_account", "company_phone"]


@app.get("/api/settings/company")
@login_required
def read_company():
    d = {r["key"]: r["value"] for r in get_db().execute("SELECT key,value FROM settings")}
    return jsonify({k: d.get(k, "") for k in COMPANY_KEYS})


@app.put("/api/settings/company")
@admin_required
def write_company():
    d = body()
    db = get_db()
    for k in COMPANY_KEYS:
        if k in d:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (k, str(d[k])[:200]))
    db.commit()
    return jsonify({"ok": True})


# ---------------- 提醒 ----------------
@app.get("/api/reminders")
@login_required
def reminders():
    plans = list_plans()
    data = plans.get_json()
    return jsonify({
        "overdue": [p for p in data if p["state"] == "已逾期"],
        "soon": [p for p in data if p["state"] == "即将到期"],
        "remind_days": REMIND_DAYS,
    })


# ---------------- 统计 ----------------
@app.get("/api/stats/dashboard")
@login_required
def stats_dashboard():
    db = get_db()
    scope, params = scope_sql("ct")
    month = datetime.date.today().strftime("%Y-%m")

    signed = db.execute(
        f"SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM contracts ct WHERE strftime('%Y-%m',sign_date)=? {scope}",
        [month] + params).fetchone()
    received_month = db.execute(
        f"""SELECT COALESCE(SUM(p.amount),0) s FROM payments p
            JOIN contracts ct ON ct.id=p.contract_id
            WHERE strftime('%Y-%m',p.pay_date)=? {scope}""", [month] + params).fetchone()["s"]

    totals = balance_totals(db, scope + " AND ct.status NOT IN ('已归档')", params)
    outstanding = totals["outstanding"]

    t = today()
    plans = rows(db.execute(
        f"""SELECT pp.amount, pp.due_date,
              COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
            FROM payment_plans pp JOIN contracts ct ON ct.id=pp.contract_id
            WHERE 1=1 {scope} AND ct.status!='已归档'""", params))
    overdue_amt = overdue_n = 0
    future = {}
    for p in plans:
        remain = p["amount"] - p["received"]
        if remain <= 0:
            continue
        if p["due_date"] < t:
            overdue_amt += remain
            overdue_n += 1
        else:
            m = p["due_date"][:7]
            future[m] = round(future.get(m, 0) + remain, 2)

    customers_n = db.execute(
        f"SELECT COUNT(*) c FROM customers c WHERE 1=1 {scope_sql('c')[0]}",
        scope_sql("c")[1]).fetchone()["c"]

    top = rows(db.execute(
        f"""SELECT c.name, ROUND(SUM(ct.amount),2) AS contracted,
              ROUND(COALESCE(SUM((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id)),0),2) AS received
            FROM contracts ct JOIN customers c ON c.id=ct.customer_id
            WHERE 1=1 {scope} AND ct.status!='已归档' GROUP BY c.id
            HAVING contracted-received > 0 ORDER BY (contracted-received) DESC LIMIT 10""", params))
    for r in top:
        r["outstanding"] = round(r["contracted"] - r["received"], 2)

    trend = rows(db.execute(
        f"""SELECT strftime('%Y-%m', p.pay_date) m, ROUND(SUM(p.amount),2) s
            FROM payments p JOIN contracts ct ON ct.id=p.contract_id
            WHERE p.pay_date >= date('now','-11 months','start of month') {scope}
            GROUP BY m ORDER BY m""", params))

    uninvoiced = totals["uninvoiced"]

    return jsonify({
        "month": month,
        "signed_amount": round(signed["s"], 2), "signed_count": signed["n"],
        "received_month": round(received_month, 2),
        "outstanding": round(outstanding, 2),
        "uninvoiced": round(uninvoiced, 2),
        "unscheduled": totals["unscheduled_outstanding"],
        "unallocated": totals["unallocated"],
        "overdue_amount": round(overdue_amt, 2), "overdue_count": overdue_n,
        "customers": customers_n,
        "future_by_month": future,
        "top_debtors": top,
        "received_trend": trend,
    })


@app.get("/api/stats/aging")
@login_required
def stats_aging():
    db = get_db()
    scope, params = scope_sql("ct")
    scope += " AND ct.status!='已归档'"
    data = rows(db.execute(
        f"""SELECT ct.id AS contract_id, c.name AS customer, pp.due_date, pp.amount,
              COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
            FROM payment_plans pp
            JOIN contracts ct ON ct.id=pp.contract_id
            JOIN customers c ON c.id=ct.customer_id
            WHERE 1=1 {scope} ORDER BY pp.due_date,pp.seq""", params))
    plans_by_contract = {}
    for p in data:
        plans_by_contract.setdefault(p["contract_id"], []).append(p)
    t = datetime.date.today()
    buckets = {}

    def bucket(customer):
        return buckets.setdefault(customer, {
            "customer": customer, "未排期": 0, "未到期": 0, "1-30天": 0,
            "31-60天": 0, "61-90天": 0, "90天以上": 0, "total": 0,
        })

    def add(customer, key, amount):
        if amount <= 0:
            return
        b = bucket(customer)
        b[key] = round(b[key] + amount, 2)
        b["total"] = round(b["total"] + amount, 2)

    customer_names = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM customers")}
    for item in contract_balances(db, scope, params):
        customer = customer_names[item["customer_id"]]
        unallocated = item["unallocated"]
        for p in plans_by_contract.get(item["id"], []):
            remain = max(p["amount"] - p["received"], 0)
            applied = min(remain, unallocated)
            remain -= applied
            unallocated -= applied
            if remain <= 0:
                continue
            if not p["due_date"]:
                add(customer, "未排期", remain)
                continue
            days = (t - datetime.date.fromisoformat(p["due_date"])).days
            key = "未到期" if days < 0 else ("1-30天" if days <= 30 else ("31-60天" if days <= 60 else ("61-90天" if days <= 90 else "90天以上")))
            add(customer, key, remain)
        add(customer, "未排期", item["unscheduled_outstanding"])
    return jsonify(sorted(buckets.values(), key=lambda x: -x["total"]))


@app.get("/api/stats/performance")
@roles_required("admin", "finance")
def stats_performance():
    db = get_db()
    year = request.args.get("year") or datetime.date.today().strftime("%Y")
    demo, dparams = demo_sql("ct")
    customer_demo, customer_params = demo_sql("c")
    users = rows(db.execute("SELECT id,name FROM users WHERE role IN ('sales','admin') AND active=1"))
    out = []
    for u in users:
        signed = db.execute(
            f"""SELECT COALESCE(SUM(ct.amount),0) s, COUNT(*) n FROM contracts ct
               WHERE ct.owner_id=? AND strftime('%Y',ct.sign_date)=? {demo}""",
            [u["id"], year] + dparams).fetchone()
        recv = db.execute(
            f"""SELECT COALESCE(SUM(p.amount),0) s FROM payments p
               JOIN contracts ct ON ct.id=p.contract_id
               WHERE ct.owner_id=? AND strftime('%Y',p.pay_date)=? {demo}""",
            [u["id"], year] + dparams).fetchone()["s"]
        outst = db.execute(
            f"""SELECT COALESCE(SUM(ct.amount-COALESCE((
                 SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id),0)),0)
               FROM contracts ct WHERE ct.owner_id=? {demo}""", [u["id"]] + dparams).fetchone()[0] or 0
        cust = db.execute(
            f"SELECT COUNT(*) c FROM customers c WHERE c.owner_id=? {customer_demo}",
            [u["id"]] + customer_params).fetchone()["c"]
        monthly = rows(db.execute(
            f"""SELECT strftime('%m',ct.sign_date) m, ROUND(SUM(ct.amount),2) s FROM contracts ct
               WHERE ct.owner_id=? AND strftime('%Y',ct.sign_date)=? {demo} GROUP BY m""",
            [u["id"], year] + dparams))
        out.append({"user_id": u["id"], "name": u["name"],
                    "signed": round(signed["s"], 2), "contracts": signed["n"],
                    "received": round(recv, 2), "outstanding": round(outst, 2),
                    "customers": cust, "monthly": monthly})
    return jsonify({"year": year, "rows": out})


# ---------------- 报表中心：合同财务与经营管理看板 ----------------
def stat_filters(alias, date_field):
    """通用组合筛选：from/to（作用于指定日期字段）+ owner_id（业务员强制本人）"""
    where, params = "", []
    if request.args.get("from"):
        where += f" AND {alias}.{date_field}>=?"
        params.append(request.args["from"])
    if request.args.get("to"):
        where += f" AND {alias}.{date_field}<=?"
        params.append(request.args["to"])
    if request.args.get("owner_id") and g.user["role"] != "sales":
        where += f" AND {alias}.owner_id=?"
        params.append(int(request.args["owner_id"]))
    return where, params


def month_series(pairs):
    """把 {m: amount} 补全为近12个月有序列表"""
    out = []
    d0 = datetime.date.today().replace(day=1)
    for i in range(11, -1, -1):
        m = (d0 - datetime.timedelta(days=1)).replace(day=1) if i else d0
        for _ in range(i - 1):
            m = (m - datetime.timedelta(days=1)).replace(day=1)
        key = m.strftime("%Y-%m")
        out.append({"m": key, "amount": round(pairs.get(key, 0), 2)})
    return out


@app.get("/api/stats/contracts")
@login_required
def stats_contracts():
    """合同统计：按签订日期/类型/状态/负责人组合筛选"""
    db = get_db()
    scope, sparams = scope_sql("ct")
    where, params = stat_filters("ct", "sign_date")
    if request.args.get("type"):
        where += " AND ct.type=?"
        params.append(request.args["type"])
    if request.args.get("status"):
        where += " AND ct.status=?"
        params.append(request.args["status"])
    base = f"FROM contracts ct WHERE 1=1 {scope} {where}"
    p = sparams + params
    total = db.execute(f"SELECT COUNT(*) n, COALESCE(SUM(ct.amount),0) s {base}", p).fetchone()
    by_status = rows(db.execute(
        f"SELECT ct.status label, COUNT(*) n, ROUND(SUM(ct.amount),2) amount {base} GROUP BY ct.status ORDER BY amount DESC", p))
    by_type = rows(db.execute(
        f"SELECT ct.type label, COUNT(*) n, ROUND(SUM(ct.amount),2) amount {base} GROUP BY ct.type", p))
    by_month = rows(db.execute(
        f"""SELECT strftime('%Y-%m', ct.sign_date) label, COUNT(*) n, ROUND(SUM(ct.amount),2) amount
            {base} AND ct.sign_date!='' GROUP BY label ORDER BY label""".replace("WHERE 1=1", "WHERE 1=1"), p))
    top_customers = rows(db.execute(
        f"""SELECT c.name label, COUNT(*) n, ROUND(SUM(ct.amount),2) amount
            FROM contracts ct JOIN customers c ON c.id=ct.customer_id
            WHERE 1=1 {scope} {where} GROUP BY c.id ORDER BY amount DESC LIMIT 10""", p))
    return jsonify({
        "count": total["n"], "amount": round(total["s"], 2),
        "avg": round(total["s"] / total["n"], 2) if total["n"] else 0,
        "by_status": by_status, "by_type": by_type, "by_month": by_month,
        "top_customers": top_customers,
    })


@app.get("/api/stats/receipts")
@login_required
def stats_receipts():
    """回款统计：按收款日期/方式/负责人组合筛选，含计划达成率"""
    db = get_db()
    scope, sparams = scope_sql("ct")
    where, params = stat_filters("ct", "pay_date")
    # pay_date 在 payments 表上
    where = where.replace("ct.pay_date", "p.pay_date")
    if request.args.get("method"):
        where += " AND p.method=?"
        params.append(request.args["method"])
    base = f"FROM payments p JOIN contracts ct ON ct.id=p.contract_id WHERE 1=1 {scope} {where}"
    p = sparams + params
    total = db.execute(f"SELECT COUNT(*) n, COALESCE(SUM(p.amount),0) s {base}", p).fetchone()
    by_method = rows(db.execute(
        f"SELECT p.method label, COUNT(*) n, ROUND(SUM(p.amount),2) amount {base} GROUP BY p.method ORDER BY amount DESC", p))
    by_month = rows(db.execute(
        f"SELECT strftime('%Y-%m', p.pay_date) label, ROUND(SUM(p.amount),2) amount {base} GROUP BY label ORDER BY label", p))
    top_customers = rows(db.execute(
        f"""SELECT c.name label, COUNT(*) n, ROUND(SUM(p.amount),2) amount
            FROM payments p JOIN contracts ct ON ct.id=p.contract_id JOIN customers c ON c.id=p.customer_id
            WHERE 1=1 {scope} {where} GROUP BY c.id ORDER BY amount DESC LIMIT 10""", p))
    # 回款计划达成：筛选区间内到期的计划，按计划实际收到的金额计算达成率
    f_from, f_to = request.args.get("from") or "0000-01-01", request.args.get("to") or "9999-12-31"
    plan_owner, plan_owner_params = "", []
    if request.args.get("owner_id") and g.user["role"] != "sales":
        plan_owner = " AND ct.owner_id=?"
        plan_owner_params.append(int(request.args["owner_id"]))
    plans = rows(db.execute(
        f"""SELECT pp.id, pp.amount,
              COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
            FROM payment_plans pp JOIN contracts ct ON ct.id=pp.contract_id
            WHERE pp.due_date>=? AND pp.due_date<=? AND ct.status!='已归档' {scope} {plan_owner}""",
        [f_from, f_to] + sparams + plan_owner_params))
    due_amount = sum(pp["amount"] for pp in plans)
    due_received = sum(min(pp["amount"], pp["received"]) for pp in plans)
    return jsonify({
        "count": total["n"], "amount": round(total["s"], 2),
        "by_method": by_method, "by_month": by_month, "top_customers": top_customers,
        "plan_due": round(due_amount, 2), "plan_received": round(due_received, 2),
        "plan_rate": round(due_received / due_amount * 100, 1) if due_amount else None,
        "plan_count": len(plans),
    })


@app.get("/api/stats/invoicing")
@roles_required("admin", "finance")
def stats_invoicing():
    """开票统计：按开票日期/发票类型组合筛选，含未开票排行"""
    db = get_db()
    where, params = "", []
    if request.args.get("from"):
        where += " AND i.invoice_date>=?"
        params.append(request.args["from"])
    if request.args.get("to"):
        where += " AND i.invoice_date<=?"
        params.append(request.args["to"])
    if request.args.get("inv_type"):
        where += " AND i.type=?"
        params.append(request.args["inv_type"])
    demo, dparams = demo_sql("ct")
    base = f"FROM invoices i JOIN contracts ct ON ct.id=i.contract_id WHERE i.status!='作废' {demo} {where}"
    query_params = dparams + params
    total = db.execute(f"SELECT COUNT(CASE WHEN i.status='已开' THEN 1 END) n, COALESCE(SUM(i.amount),0) s {base}", query_params).fetchone()
    by_type = rows(db.execute(
        f"SELECT i.type label, COUNT(*) n, ROUND(SUM(i.amount),2) amount {base} GROUP BY i.type ORDER BY amount DESC", query_params))
    by_month = rows(db.execute(
        f"SELECT strftime('%Y-%m', i.invoice_date) label, ROUND(SUM(i.amount),2) amount {base} GROUP BY label ORDER BY label", query_params))
    top_uninvoiced = rows(db.execute(
        f"""SELECT ct.contract_no, c.name AS customer, ct.amount,
             COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=ct.id AND i.status!='作废'),0) AS invoiced
           FROM contracts ct JOIN customers c ON c.id=ct.customer_id
           WHERE ct.status NOT IN ('已归档') {demo}""", dparams))
    top_uninvoiced = [dict(r, uninvoiced=round(r["amount"] - r["invoiced"], 2)) for r in top_uninvoiced]
    top_uninvoiced = sorted([r for r in top_uninvoiced if r["uninvoiced"] > 0],
                            key=lambda x: -x["uninvoiced"])[:10]
    uninvoiced_total = round(sum(r["uninvoiced"] for r in top_uninvoiced), 2)
    return jsonify({
        "count": total["n"], "amount": round(total["s"], 2),
        "by_type": by_type, "by_month": by_month,
        "top_uninvoiced": top_uninvoiced, "uninvoiced_top10_total": uninvoiced_total,
    })


@app.get("/api/stats/view/boss")
@roles_required("admin")
def stats_view_boss():
    """老板视角：经营全貌（钱 + 人 + 趋势 + 预测）"""
    db = get_db()
    month = datetime.date.today().strftime("%Y-%m")
    demo, dparams = demo_sql("ct")
    signed = db.execute(
        f"SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM contracts ct WHERE strftime('%Y-%m',sign_date)=? {demo}",
        [month] + dparams).fetchone()
    received_m = db.execute(
        f"""SELECT COALESCE(SUM(p.amount),0) s FROM payments p JOIN contracts ct ON ct.id=p.contract_id
            WHERE strftime('%Y-%m',p.pay_date)=? {demo}""", [month] + dparams).fetchone()["s"]
    received_y = db.execute(
        f"""SELECT COALESCE(SUM(p.amount),0) s FROM payments p JOIN contracts ct ON ct.id=p.contract_id
            WHERE strftime('%Y',p.pay_date)=? {demo}""", [month[:4]] + dparams).fetchone()["s"]
    totals = balance_totals(db, demo + " AND ct.status NOT IN ('已归档')", dparams)
    outstanding = totals["outstanding"]
    t = today()
    plans = rows(db.execute(
        f"""SELECT pp.amount, pp.due_date,
             COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
           FROM payment_plans pp JOIN contracts ct ON ct.id=pp.contract_id
           WHERE 1=1 {demo} AND ct.status!='已归档'""", dparams))
    overdue_amt = overdue_n = 0
    future = {}
    for pp in plans:
        remain = pp["amount"] - pp["received"]
        if remain <= 0:
            continue
        if pp["due_date"] < t:
            overdue_amt += remain
            overdue_n += 1
        else:
            m = pp["due_date"][:7]
            future[m] = round(future.get(m, 0) + remain, 2)
    s_pairs = {r["m"]: r["s"] for r in rows(db.execute(
        f"""SELECT strftime('%Y-%m',ct.sign_date) m, SUM(ct.amount) s FROM contracts ct
           WHERE ct.sign_date>=date('now','-11 months','start of month') {demo} GROUP BY m""", dparams))}
    r_pairs = {r["m"]: r["s"] for r in rows(db.execute(
        f"""SELECT strftime('%Y-%m',p.pay_date) m, SUM(p.amount) s FROM payments p
           JOIN contracts ct ON ct.id=p.contract_id
           WHERE p.pay_date>=date('now','-11 months','start of month') {demo} GROUP BY m""", dparams))}
    months = month_series({})
    signed_series = [{"m": x["m"], "amount": round(s_pairs.get(x["m"], 0), 2)} for x in months]
    received_series = [{"m": x["m"], "amount": round(r_pairs.get(x["m"], 0), 2)} for x in months]
    top_debtors = rows(db.execute(
        f"""SELECT c.name, ROUND(SUM(ct.amount),2) contracted,
             ROUND(COALESCE(SUM((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id)),0),2) received
           FROM contracts ct JOIN customers c ON c.id=ct.customer_id
           WHERE 1=1 {demo} AND ct.status!='已归档' GROUP BY c.id HAVING contracted-received>0
           ORDER BY (contracted-received) DESC LIMIT 5""", dparams))
    for r in top_debtors:
        r["outstanding"] = round(r["contracted"] - r["received"], 2)
    top_sales = rows(db.execute(
        f"""SELECT u.name, ROUND(SUM(ct.amount),2) signed
           FROM contracts ct JOIN users u ON u.id=ct.owner_id
           WHERE strftime('%Y',ct.sign_date)=? {demo} GROUP BY u.id ORDER BY signed DESC LIMIT 5""",
        [month[:4]] + dparams))
    contracts_active = db.execute(
        f"SELECT COUNT(*) n FROM contracts ct WHERE ct.status NOT IN ('已完成','已归档') {demo}",
        dparams).fetchone()["n"]
    return jsonify({
        "month": month, "data_mode": current_data_mode(),
        "signed_month": round(signed["s"], 2), "signed_month_count": signed["n"],
        "received_month": round(received_m, 2), "received_year": round(received_y, 2),
        "outstanding": round(outstanding, 2),
        "unscheduled": totals["unscheduled_outstanding"],
        "unallocated": totals["unallocated"],
        "overdue_amount": round(overdue_amt, 2), "overdue_count": overdue_n,
        "future_by_month": future,
        "signed_series": signed_series, "received_series": received_series,
        "top_debtors": top_debtors, "top_sales": top_sales,
        "contracts_active": contracts_active,
    })


@app.get("/api/stats/view/plant")
@roles_required("admin", "manager")
def stats_view_plant():
    """工厂经理视角：交付与发货导向"""
    db = get_db()
    month = datetime.date.today().strftime("%Y-%m")
    t = today()
    demo, dparams = demo_sql("ct")
    active = db.execute(
        f"""SELECT COUNT(*) n, COALESCE(SUM(ct.amount),0) s FROM contracts ct
           WHERE ct.status NOT IN ('已完成','已归档') {demo}""", dparams).fetchone()
    pending_items = rows(db.execute(
        f"""SELECT ci.id, ci.name, ci.spec, ci.unit, ci.quantity,
             COALESCE((SELECT SUM(si.quantity) FROM shipment_items si WHERE si.contract_item_id=ci.id),0) AS shipped,
             ct.contract_no, c.name AS customer, ct.delivery_date
           FROM contract_items ci
           JOIN contracts ct ON ct.id=ci.contract_id
           JOIN customers c ON c.id=ct.customer_id
           WHERE ct.status NOT IN ('已完成','已归档') {demo}""", dparams))
    pending_items = [dict(r, remain=round(r["quantity"] - r["shipped"], 2))
                     for r in pending_items if r["quantity"] - r["shipped"] > 0]
    pending_items.sort(key=lambda x: (x["delivery_date"] or "9999", -x["remain"]))
    ship_month = row(db.execute(
        f"""SELECT COUNT(*) n, COALESCE(SUM((SELECT SUM(si.amount) FROM shipment_items si
             WHERE si.shipment_id=s.id)),0) amt
           FROM shipments s JOIN contracts ct ON ct.id=s.contract_id
           WHERE strftime('%Y-%m',s.ship_date)=? {demo}""", [month] + dparams))
    temp_month = db.execute(
        f"""SELECT COUNT(*) n FROM shipments s JOIN contracts ct ON ct.id=s.contract_id
            WHERE s.type='temp' AND strftime('%Y-%m',s.ship_date)=? {demo}""",
        [month] + dparams).fetchone()["n"]
    overdue_delivery = rows(db.execute(
        f"""SELECT ct.contract_no, ct.title, c.name AS customer, ct.delivery_date, ct.status
           FROM contracts ct JOIN customers c ON c.id=ct.customer_id
           WHERE ct.delivery_date!='' AND ct.delivery_date<? AND ct.status NOT IN ('已完成','已归档') {demo}
           ORDER BY ct.delivery_date LIMIT 20""", [t] + dparams))
    ship_by_month = rows(db.execute(
        f"""SELECT strftime('%Y-%m', s.ship_date) label,
             ROUND(COALESCE(SUM((SELECT SUM(si.amount) FROM shipment_items si WHERE si.shipment_id=s.id)),0),2) amount,
             COUNT(*) n
           FROM shipments s JOIN contracts ct ON ct.id=s.contract_id
           WHERE s.ship_date>=date('now','-11 months','start of month') {demo} GROUP BY label ORDER BY label""", dparams))
    production = row(db.execute(f"""
      SELECT
        (SELECT COUNT(*) FROM material_batches mb JOIN contracts ct ON ct.id=mb.contract_id
         WHERE mb.status='待排产' {demo}) AS materials_pending,
        (SELECT COUNT(*) FROM furnace_batches fb JOIN contracts ct ON ct.id=fb.contract_id
         WHERE fb.status='加工中' {demo}) AS furnaces_active,
        (SELECT COUNT(*) FROM quality_inspections qi JOIN contracts ct ON ct.id=qi.contract_id
         WHERE qi.result='不合格' {demo}) AS quality_exceptions
    """, dparams * 3))
    return jsonify({
        "month": month, **production,
        "active_count": active["n"], "active_amount": round(active["s"], 2),
        "pending_item_count": len(pending_items),
        "pending_contract_count": len({r["contract_no"] for r in pending_items}),
        "pending_items": pending_items[:15],
        "ship_month_count": ship_month["n"], "ship_month_amount": round(ship_month["amt"], 2),
        "temp_month_count": temp_month,
        "overdue_delivery": overdue_delivery, "overdue_delivery_count": len(overdue_delivery),
        "ship_by_month": ship_by_month,
    })


@app.get("/api/stats/view/finance")
@roles_required("admin", "finance")
def stats_view_finance():
    """财务经理视角：回款、逾期、开票、现金流"""
    db = get_db()
    month = datetime.date.today().strftime("%Y-%m")
    t = today()
    demo, dparams = demo_sql("ct")
    received_m = db.execute(
        f"""SELECT COALESCE(SUM(p.amount),0) s, COUNT(*) n FROM payments p
            JOIN contracts ct ON ct.id=p.contract_id WHERE strftime('%Y-%m',p.pay_date)=? {demo}""",
        [month] + dparams).fetchone()
    invoiced_m = db.execute(
        f"""SELECT COALESCE(SUM(i.amount),0) s, COUNT(CASE WHEN i.status='已开' THEN 1 END) n FROM invoices i
            JOIN contracts ct ON ct.id=i.contract_id
            WHERE i.status!='作废' AND strftime('%Y-%m',i.invoice_date)=? {demo}""",
        [month] + dparams).fetchone()
    plans = rows(db.execute(
        f"""SELECT pp.id, pp.contract_id, pp.name, pp.amount, pp.due_date,
             COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received,
             c.name AS customer, ct.contract_no
           FROM payment_plans pp
           JOIN contracts ct ON ct.id=pp.contract_id
           JOIN customers c ON c.id=ct.customer_id
           WHERE 1=1 {demo} AND ct.status!='已归档'""", dparams))
    overdue, due_month_amt = [], 0.0
    due_month_recv = 0.0
    future90 = 0.0
    for pp in plans:
        if not pp["due_date"]:
            continue
        remain = pp["amount"] - pp["received"]
        if remain <= 0:
            if pp["due_date"][:7] == month:
                due_month_amt += pp["amount"]
                due_month_recv += pp["amount"]
            continue
        days = (datetime.date.today() - datetime.date.fromisoformat(pp["due_date"])).days
        if days > 0:
            overdue.append({"customer": pp["customer"], "contract_no": pp["contract_no"],
                            "plan": pp["name"], "remain": round(remain, 2), "days": days})
        elif days >= -90:
            future90 += remain
        if pp["due_date"][:7] == month:
            due_month_amt += pp["amount"]
            due_month_recv += min(pp["amount"], pp["received"])
    overdue.sort(key=lambda x: -x["remain"])
    by_method = rows(db.execute(
        f"""SELECT p.method label, ROUND(SUM(p.amount),2) amount, COUNT(*) n FROM payments p
           JOIN contracts ct ON ct.id=p.contract_id
           WHERE strftime('%Y',p.pay_date)=? {demo} GROUP BY p.method ORDER BY amount DESC""",
        [month[:4]] + dparams))
    totals = balance_totals(db, demo + " AND ct.status NOT IN ('已归档')", dparams)
    uninvoiced = totals["uninvoiced"]
    return jsonify({
        "month": month,
        "received_month": round(received_m["s"], 2), "received_month_count": received_m["n"],
        "invoiced_month": round(invoiced_m["s"], 2), "invoiced_month_count": invoiced_m["n"],
        "due_month_amount": round(due_month_amt, 2),
        "due_month_rate": round(due_month_recv / due_month_amt * 100, 1) if due_month_amt else None,
        "overdue": overdue[:10], "overdue_count": len(overdue),
        "overdue_amount": round(sum(o["remain"] for o in overdue), 2),
        "uninvoiced": round(uninvoiced, 2),
        "unscheduled": totals["unscheduled_outstanding"],
        "unallocated": totals["unallocated"],
        "future90": round(future90, 2),
        "by_method": by_method,
    })


# ---------------- 产能 / 质量 / 客户风险 ----------------
@app.get("/api/stats/operations")
@roles_required("admin", "finance", "manager")
def stats_operations():
    db = get_db()
    scope, params = scope_sql("ct")
    start = valid_date(request.args.get("from") or datetime.date.today().replace(day=1).isoformat(), "开始日期")
    end = valid_date(request.args.get("to") or today(), "结束日期")
    if start > end:
        return jsonify({"error": "开始日期不能晚于结束日期"}), 400
    days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1
    furnaces = rows(db.execute(
        f"""SELECT fb.* FROM furnace_batches fb JOIN contracts ct ON ct.id=fb.contract_id
            WHERE substr(fb.started_at,1,10)>=? AND substr(fb.started_at,1,10)<=? {scope}
            ORDER BY fb.id""", [start, end] + params))
    equipment_config = rows(db.execute("SELECT * FROM equipment"))
    hours_by_key = {}
    for e in equipment_config:
        hours_by_key[e["code"]] = e["daily_available_hours"]
        hours_by_key[e["name"]] = e["daily_available_hours"]
    groups = {}
    for f in furnaces:
        key = f["equipment"] or "未配置设备"
        a = groups.setdefault(key, {"equipment": key, "furnaces": 0, "quantity": 0.0, "actual_hours": 0.0})
        a["furnaces"] += 1
        a["quantity"] += f["quantity"]
        try:
            started = datetime.datetime.fromisoformat(f["started_at"])
            finished = datetime.datetime.fromisoformat(f["finished_at"])
            hours = (finished - started).total_seconds() / 3600
            if hours > 0:
                a["actual_hours"] += hours
        except (TypeError, ValueError):
            pass
    equipment_rows = []
    for a in groups.values():
        daily = hours_by_key.get(a["equipment"])
        available = daily * days if daily else None
        equipment_rows.append({
            **a, "quantity": round(a["quantity"], 2), "actual_hours": round(a["actual_hours"], 2),
            "average_hours": round(a["actual_hours"] / a["furnaces"], 2) if a["furnaces"] else None,
            "available_hours": round(available, 2) if available else None,
            "utilization": round(a["actual_hours"] / available * 100, 1) if available else None,
        })
    actual_total = sum(x["actual_hours"] for x in equipment_rows)
    available_total = sum(x["available_hours"] or 0 for x in equipment_rows)
    quality_rows = rows(db.execute(
        f"""SELECT qi.* FROM quality_inspections qi JOIN contracts ct ON ct.id=qi.contract_id
            WHERE qi.inspection_date>=? AND qi.inspection_date<=? {scope}
            ORDER BY qi.furnace_batch_id,qi.id""", [start, end] + params))
    seen = set()
    first_pass = first_inspected = 0.0
    for q in quality_rows:
        if q["furnace_batch_id"] in seen:
            continue
        seen.add(q["furnace_batch_id"])
        first_inspected += q["inspected_qty"]
        first_pass += q["pass_qty"]

    customer_demo, customer_params = demo_sql("c")
    customers = {r["id"]: dict(r) for r in db.execute(
        f"SELECT c.* FROM customers c WHERE 1=1 {customer_demo}", customer_params)}
    balances = contract_balances(db, scope + " AND ct.status!='已归档'", params)
    per_customer = {}
    for b in balances:
        a = per_customer.setdefault(b["customer_id"], {"contracted": 0.0, "outstanding": 0.0})
        a["contracted"] += b["amount"]
        a["outstanding"] += b["outstanding"]
    overdue_map = {}
    plan_rows = rows(db.execute(
        f"""SELECT c.id AS customer_id, pp.due_date, pp.amount,
             COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa WHERE pa.plan_id=pp.id),0) AS received
           FROM payment_plans pp JOIN contracts ct ON ct.id=pp.contract_id
           JOIN customers c ON c.id=ct.customer_id
           WHERE 1=1 {scope} AND ct.status!='已归档'""", params))
    for p in plan_rows:
        remain = p["amount"] - p["received"]
        if remain <= 0 or not p["due_date"]:
            continue
        days_overdue = (datetime.date.today() - datetime.date.fromisoformat(p["due_date"])).days
        if days_overdue <= 0:
            continue
        a = overdue_map.setdefault(p["customer_id"], {"overdue": 0.0, "max_days": 0})
        a["overdue"] += remain
        a["max_days"] = max(a["max_days"], days_overdue)
    total_contracted = sum(a["contracted"] for a in per_customer.values())
    risks = []
    risk_counts = {"停接": 0, "关注": 0, "正常": 0}
    for cid, a in per_customer.items():
        customer = customers.get(cid)
        if not customer:
            continue
        overdue = overdue_map.get(cid, {"overdue": 0.0, "max_days": 0})
        limit = customer["credit_limit"]
        usage = a["outstanding"] / limit * 100 if limit > 0 else None
        reasons = []
        if customer["credit_hold"]:
            reasons.append("已人工停接")
        if limit > 0 and a["outstanding"] > limit:
            reasons.append("未收超过信用额度")
        if overdue["overdue"] > 0:
            reasons.append(f"逾期 {overdue['max_days']} 天")
        risk = "停接" if customer["credit_hold"] or (limit > 0 and a["outstanding"] > limit) or overdue["max_days"] > 30 else ("关注" if reasons or (usage is not None and usage >= 80) else "正常")
        risk_counts[risk] += 1
        risks.append({
            "customer_id": cid, "customer": customer["name"], "contracted": round(a["contracted"], 2),
            "outstanding": round(a["outstanding"], 2), "overdue": round(overdue["overdue"], 2),
            "max_overdue_days": overdue["max_days"], "credit_limit": limit,
            "credit_usage": round(usage, 1) if usage is not None else None,
            "credit_hold": customer["credit_hold"], "risk": risk, "reasons": reasons,
            "concentration": round(a["contracted"] / total_contracted * 100, 1) if total_contracted else None,
        })
    severity = {"停接": 0, "关注": 1, "正常": 2}
    risks.sort(key=lambda x: (severity[x["risk"]], -x["outstanding"]))
    shares = sorted((x["concentration"] or 0 for x in risks), reverse=True)
    return jsonify({
        "from": start, "to": end,
        "equipment": equipment_rows,
        "furnace_count": len(furnaces), "quantity": round(sum(f["quantity"] for f in furnaces), 2),
        "actual_hours": round(actual_total, 2), "available_hours": round(available_total, 2),
        "capacity_utilization": round(actual_total / available_total * 100, 1) if available_total else None,
        "first_inspected": round(first_inspected, 2), "first_pass": round(first_pass, 2),
        "first_pass_rate": round(first_pass / first_inspected * 100, 1) if first_inspected else None,
        "risk_counts": risk_counts, "customers": risks,
        "top1_concentration": round(shares[0], 1) if shares else 0,
        "top5_concentration": round(sum(shares[:5]), 1),
    })


# ---------------- 报表导出 Excel ----------------
def _wb_sheets(sheets):
    """sheets: [(sheet名, [表头], [[行]...]), ...] → Workbook"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    hfont = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="1A56DB")
    for title, headers, data in sheets:
        ws = wb.create_sheet(title[:31])
        ws.append(headers)
        for c in ws[1]:
            c.font = hfont
            c.fill = hfill
        for r in data:
            ws.append(["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in r])
        for i, h in enumerate(headers, 1):
            col = ws.column_dimensions[ws.cell(row=1, column=i).column_letter]
            col.width = max(10, min(38, len(str(h)) * 2 + 4))
    return wb


def _send_wb(wb, name):
    from io import BytesIO
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = f"{name}_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    return send_file(bio, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _call_stat(fn):
    """在当前请求上下文中调用统计函数（复用其权限与筛选口径）"""
    resp = fn()
    if getattr(resp, "status_code", 200) != 200:
        return None
    return resp.get_json()


def _filter_desc():
    parts = []
    label = {"from": "开始", "to": "截止", "type": "类型", "status": "状态",
             "owner_id": "负责人ID", "method": "收款方式", "inv_type": "票种"}
    for k, v in request.args.items():
        parts.append(f"{label.get(k, k)}={v}")
    return "；".join(parts) or "全部"


@app.get("/api/stats/export/<kind>")
@login_required
def stats_export(kind):
    role_map = {
        "boss": ("admin",), "plant": ("admin", "manager"),
        "finance": ("admin", "finance"), "invoicing": ("admin", "finance"),
        "performance": ("admin", "finance"), "profit": ("admin", "finance"),
        "operations": ("admin", "finance", "manager"),
    }
    allowed = role_map.get(kind)
    if allowed and g.user["role"] not in allowed:
        return jsonify({"error": "无权导出该报表"}), 403
    TYPE_NAMES = {"product": "产品合同", "service": "服务合同"}

    if kind == "contracts":
        d = _call_stat(stats_contracts)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("汇总", ["指标", "数值"], [
                ["筛选条件", _filter_desc()], ["合同数（份）", d["count"]],
                ["合同总额（元）", d["amount"]], ["平均单额（元）", d["avg"]]]),
            ("按状态", ["状态", "份数", "金额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["by_status"]]),
            ("按类型", ["类型", "份数", "金额（元）"],
             [[TYPE_NAMES.get(r["label"], r["label"]), r["n"], r["amount"]] for r in d["by_type"]]),
            ("月度趋势", ["月份", "份数", "金额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["by_month"]]),
            ("客户TOP10", ["客户", "合同数", "签约额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["top_customers"]]),
        ])
        return _send_wb(wb, "合同统计")

    if kind == "receipts":
        d = _call_stat(stats_receipts)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("汇总", ["指标", "数值"], [
                ["筛选条件", _filter_desc()], ["回款总额（元）", d["amount"]],
                ["回款笔数", d["count"]], ["计划到期金额（元）", d["plan_due"]],
                ["计划实际核销（元）", d["plan_received"]],
                ["计划达成率", f"{d['plan_rate']}%" if d["plan_rate"] is not None else "无到期计划"]]),
            ("收款方式", ["方式", "笔数", "金额（元）"],
             [[r["label"] or "未填", r["n"], r["amount"]] for r in d["by_method"]]),
            ("月度趋势", ["月份", "金额（元）"],
             [[r["label"], r["amount"]] for r in d["by_month"]]),
            ("客户TOP10", ["客户", "笔数", "回款额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["top_customers"]]),
        ])
        return _send_wb(wb, "回款统计")

    if kind == "invoicing":
        d = _call_stat(stats_invoicing)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("汇总", ["指标", "数值"], [
                ["筛选条件", _filter_desc()], ["已开票总额（元）", d["amount"]],
                ["开票张数", d["count"]], ["未开票TOP10合计（元）", d["uninvoiced_top10_total"]]]),
            ("票种分布", ["票种", "张数", "金额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["by_type"]]),
            ("月度趋势", ["月份", "金额（元）"],
             [[r["label"], r["amount"]] for r in d["by_month"]]),
            ("未开票排行", ["合同编号", "客户", "合同额（元）", "已开票（元）", "未开票（元）"],
             [[r["contract_no"], r["customer"], r["amount"], r["invoiced"], r["uninvoiced"]]
              for r in d["top_uninvoiced"]]),
        ])
        return _send_wb(wb, "开票统计")

    if kind == "aging":
        d = _call_stat(stats_aging)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("账龄分析", ["客户", "未排期", "未到期", "1-30天", "31-60天", "61-90天", "90天以上", "合计（元）"],
             [[a["customer"], a["未排期"], a["未到期"], a["1-30天"], a["31-60天"], a["61-90天"], a["90天以上"], a["total"]]
              for a in d]),
        ])
        return _send_wb(wb, "账龄分析")

    if kind in ("by-product", "by-service"):
        d = _call_stat(stats_by_product if kind == "by-product" else stats_by_service)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        label = "产品" if kind == "by-product" else "服务类型"
        wb = _wb_sheets([
            (f"{label}统计", [label, "合同数", "客户数", "合同额（元）", "回款分摊（元）", "未收（元）", "开票分摊（元）"],
             [[r["name"], r["contracts"], r["customers"], r["amount"], r["received"], r["outstanding"], r["invoiced"]]
              for r in d]),
        ])
        return _send_wb(wb, f"{label}维度统计")

    if kind == "performance":
        d = _call_stat(stats_performance)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            (f"{d['year']}年业绩", ["业务员", "客户数", "签约合同", "签约额（元）", "回款额（元）", "未收余额（元）", "回款率"],
             [[r["name"], r["customers"], r["contracts"], r["signed"], r["received"], r["outstanding"],
               f"{round(r['received'] / r['signed'] * 100)}%" if r["signed"] else "-"]
              for r in d["rows"]]),
        ])
        return _send_wb(wb, "业绩统计")

    if kind == "boss":
        d = _call_stat(stats_view_boss)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("经营汇总", ["指标", "数值"], [
                ["统计月份", d["month"]], ["本月签约（元）", d["signed_month"]],
                ["本月签约份数", d["signed_month_count"]], ["本月回款（元）", d["received_month"]],
                ["本年回款（元）", d["received_year"]], ["应收未收（元）", d["outstanding"]],
                ["逾期金额（元）", d["overdue_amount"]], ["逾期笔数", d["overdue_count"]],
                ["在手合同（份）", d["contracts_active"]]]),
            ("月度签约回款", ["月份", "签约额（元）", "回款额（元）"],
             [[s["m"], s["amount"], r["amount"]]
              for s, r in zip(d["signed_series"], d["received_series"])]),
            ("未来回款预测", ["月份", "预计回款（元）"],
             [[m, v] for m, v in sorted(d["future_by_month"].items())]),
            ("欠款客户TOP5", ["客户", "合同额（元）", "已回款（元）", "欠款（元）"],
             [[r["name"], r["contracted"], r["received"], r["outstanding"]] for r in d["top_debtors"]]),
            ("业务员签约TOP5", ["业务员", "签约额（元）"],
             [[r["name"], r["signed"]] for r in d["top_sales"]]),
        ])
        return _send_wb(wb, "老板经营报表")

    if kind == "plant":
        d = _call_stat(stats_view_plant)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("生产汇总", ["指标", "数值"], [
                ["统计月份", d["month"]], ["在手合同（份）", d["active_count"]],
                ["在手合同金额（元）", d["active_amount"]], ["待发货明细（项）", d["pending_item_count"]],
                ["涉及合同（份）", d["pending_contract_count"]], ["本月发货单数", d["ship_month_count"]],
                ["本月发货金额（元）", d["ship_month_amount"]], ["本月临时发货", d["temp_month_count"]],
                ["交付逾期合同", d["overdue_delivery_count"]]]),
            ("待发货明细", ["合同编号", "客户", "产品/服务", "规格", "合同量", "已发", "待发", "交付日期"],
             [[r["contract_no"], r["customer"], r["name"], r["spec"] or "", r["quantity"],
               r["shipped"], r["remain"], r["delivery_date"] or ""] for r in d["pending_items"]]),
            ("交付逾期", ["合同编号", "标题", "客户", "交付日期", "状态"],
             [[r["contract_no"], r["title"], r["customer"], r["delivery_date"], r["status"]]
              for r in d["overdue_delivery"]]),
            ("月度发货", ["月份", "单数", "金额（元）"],
             [[r["label"], r["n"], r["amount"]] for r in d["ship_by_month"]]),
        ])
        return _send_wb(wb, "工厂生产报表")

    if kind == "operations":
        d = _call_stat(stats_operations)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("经营汇总", ["指标", "数值"], [
                ["统计期间", f"{d['from']} 至 {d['to']}"], ["炉次", d["furnace_count"]],
                ["装炉量", d["quantity"]], ["实际工时", d["actual_hours"]],
                ["可用工时", d["available_hours"]],
                ["产能利用率", f"{d['capacity_utilization']}%" if d["capacity_utilization"] is not None else "未配置"],
                ["一次合格率", f"{d['first_pass_rate']}%" if d["first_pass_rate"] is not None else "暂无质检"],
                ["TOP1集中度", f"{d['top1_concentration']}%"], ["TOP5集中度", f"{d['top5_concentration']}%"]]),
            ("设备产能", ["设备", "炉次", "数量", "实际工时", "平均工时", "可用工时", "利用率"],
             [[x["equipment"], x["furnaces"], x["quantity"], x["actual_hours"], x["average_hours"],
               x["available_hours"], f"{x['utilization']}%" if x["utilization"] is not None else "未配置"] for x in d["equipment"]]),
            ("客户风险", ["客户", "风险", "合同额", "未收", "逾期", "最长逾期天", "信用额度", "信用使用率", "集中度", "触发原因"],
             [[x["customer"], x["risk"], x["contracted"], x["outstanding"], x["overdue"],
               x["max_overdue_days"], x["credit_limit"],
               f"{x['credit_usage']}%" if x["credit_usage"] is not None else "未设置",
               f"{x['concentration']}%", "；".join(x["reasons"])] for x in d["customers"]]),
        ])
        return _send_wb(wb, "产能质量与客户风险")

    if kind == "profit":
        d = _call_stat(stats_profitability)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("经营汇总", ["指标", "数值"], [
                ["合同额（元）", d["amount"]], ["已归集成本（元）", d["cost"]],
                ["当月成本（元）", d["cost_month"]], ["预估毛利（元）", d["gross_profit"]],
                ["预估毛利率", f"{d['margin_rate']}%" if d["margin_rate"] is not None else "-"]]),
            ("成本类别", ["类别", "金额（元）"], [[x["label"], x["amount"]] for x in d["by_category"]]),
            ("合同毛利", ["合同编号", "合同额（元）", "成本（元）", "预估毛利（元）", "毛利率"],
             [[x["contract_no"], x["amount"], x["cost"], x["gross_profit"],
               f"{x['margin_rate']}%" if x["margin_rate"] is not None else "-"] for x in d["contracts"]]),
        ])
        return _send_wb(wb, "合同预估毛利")

    if kind == "finance":
        d = _call_stat(stats_view_finance)
        if d is None:
            return jsonify({"error": "导出失败"}), 500
        wb = _wb_sheets([
            ("资金汇总", ["指标", "数值"], [
                ["统计月份", d["month"]], ["本月回款（元）", d["received_month"]],
                ["本月回款笔数", d["received_month_count"]], ["本月开票（元）", d["invoiced_month"]],
                ["本月到期计划（元）", d["due_month_amount"]],
                ["计划达成率", f"{d['due_month_rate']}%" if d["due_month_rate"] is not None else "无到期计划"],
                ["逾期金额（元）", d["overdue_amount"]], ["逾期笔数", d["overdue_count"]],
                ["未开票金额（元）", d["uninvoiced"]], ["未来90天预计回款（元）", d["future90"]]]),
            ("逾期明细", ["客户", "合同编号", "期次", "未收金额（元）", "逾期天数"],
             [[o["customer"], o["contract_no"], o["plan"], o["remain"], o["days"]] for o in d["overdue"]]),
            ("收款方式", ["方式", "笔数", "金额（元）"],
             [[r["label"] or "未填", r["n"], r["amount"]] for r in d["by_method"]]),
        ])
        return _send_wb(wb, "财务资金报表")

    return jsonify({"error": "未知报表类型"}), 404


# ---------------- 老板移动端 ----------------
@app.get("/api/mobile/boss")
@roles_required("admin")
def mobile_boss():
    boss = _call_stat(stats_view_boss)
    finance = _call_stat(stats_view_finance)
    plant = _call_stat(stats_view_plant)
    profit = _call_stat(stats_profitability)
    operations = _call_stat(stats_operations)
    process = _call_stat(process_monitor)
    db = get_db()
    demo, demo_params = demo_sql("pi")
    improvement_counts = row(db.execute(f"""
      SELECT COALESCE(SUM(status='验证中'),0) AS active,
        COALESCE(SUM(status='已结案'),0) AS closed
      FROM process_improvements pi WHERE 1=1 {demo}""", demo_params))
    improvements = rows(db.execute(f"""
      SELECT pi.*,baseline.run_no AS baseline_run_no,candidate.run_no AS candidate_run_no
      FROM process_improvements pi LEFT JOIN process_runs baseline ON baseline.id=pi.baseline_run_id
      LEFT JOIN process_runs candidate ON candidate.id=pi.candidate_run_id
      WHERE pi.status='已结案' {demo} ORDER BY pi.closed_at DESC,pi.id DESC LIMIT 5""", demo_params))
    improvement_views = [process_improvement_view(db, x) for x in improvements]
    return jsonify({
        "month": boss["month"], "data_mode": current_data_mode(),
        "kpis": {
            "signed_month": boss["signed_month"], "received_month": boss["received_month"],
            "received_year": boss["received_year"], "outstanding": boss["outstanding"],
            "overdue_amount": boss["overdue_amount"], "overdue_count": boss["overdue_count"],
            "uninvoiced": finance["uninvoiced"], "future90": finance["future90"],
            "unscheduled": boss["unscheduled"], "unallocated": boss["unallocated"],
            "active_contracts": boss["contracts_active"],
            "delivery_overdue": plant["overdue_delivery_count"],
            "materials_pending": plant["materials_pending"],
            "furnaces_active": plant["furnaces_active"],
            "quality_exceptions": plant["quality_exceptions"],
            "cost_month": profit["cost_month"], "gross_profit": profit["gross_profit"],
            "margin_rate": profit["margin_rate"],
            "capacity_utilization": operations["capacity_utilization"],
            "first_pass_rate": operations["first_pass_rate"],
            "risk_counts": operations["risk_counts"],
            "top5_concentration": operations["top5_concentration"],
        },
        "overdue": finance["overdue"], "top_debtors": boss["top_debtors"],
        "future_by_month": boss["future_by_month"],
        "overdue_delivery": plant["overdue_delivery"],
        "customer_risks": [x for x in operations["customers"] if x["risk"] != "正常"][:10],
        "process": {**process["summary"], "improvements_active": improvement_counts["active"],
                    "improvements_closed": improvement_counts["closed"]},
        "process_alerts": process["abnormal"][:5],
        "process_improvements": [{k: x[k] for k in ("id", "code", "title", "conclusion", "baseline_run_no",
            "candidate_run_no", "quality_delta", "cost_delta", "closed_at")} for x in improvement_views],
    })


# ---------------- 前端 ----------------
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/mobile")
def mobile_index():
    return send_from_directory("static", "mobile.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
