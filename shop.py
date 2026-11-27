import base64
import json
import re
import sqlite3
import uuid
from contextlib import closing

from flask import abort, redirect, render_template, request, session
from bridge import ROOT, CONF, call, query, required

CATALOG = {
    "orbit": {
        "name": "星环头像框", "price": 20, "slot": "avatar",
        "description": "蓝金星环，让个人标识更有辨识度。"
    },
    "aurora": {
        "name": "极光个人背景", "price": 35, "slot": "background",
        "description": "柔和的蓝绿光晕，为校园成长留下一片极光。"
    }
}
DB = ROOT / "shop.sqlite3"

def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    return db

with closing(connect()) as db, db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user TEXT NOT NULL,
        sku TEXT NOT NULL,
        price INTEGER NOT NULL,
        owner TEXT NOT NULL,
        merchant TEXT NOT NULL,
        status TEXT NOT NULL,
        tx TEXT,
        error TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user, sku)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS unique_paid_tx
        ON orders(tx) WHERE status='paid';
    CREATE TABLE IF NOT EXISTS preferences(
        user TEXT NOT NULL,
        slot TEXT NOT NULL,
        sku TEXT NOT NULL,
        PRIMARY KEY(user, slot)
    );
    """)

class PaymentRejected(Exception):
    pass

def parameter_text(value):
    # CMC查询中的protobuf bytes字段通常以Base64输出。
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return value

def prove_payment(order, txid):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", txid):
        raise ValueError("交易编号应为64位十六进制字符")
    record = query("tx", txid)
    transaction = record["transaction"]
    payload = transaction["payload"]

    if (
        payload.get("tx_id") != txid
        or payload.get("chain_id") != "chain1"
        or payload.get("contract_name") != CONF["contracts"]["ft"]
        or payload.get("method") != "Transfer"
    ):
        raise ValueError("该交易不是本平台的积分转账")

    params = {
        x["key"]: parameter_text(x["value"])
        for x in payload.get("parameters", [])
    }
    expected = {
        "id": order["id"],
        "from": order["owner"],
        "to": order["merchant"],
        "amount": str(order["price"])
    }
    if any(params.get(k) != v for k, v in expected.items()):
        raise ValueError("交易的订单号、付款人、接收人或金额不匹配")

    result = transaction.get("result")
    if not isinstance(result, dict):
        raise ValueError("交易尚未取得可核验结果")
    cr = result.get("contract_result")
    if not isinstance(cr, dict):
        raise ValueError("缺少合约执行结果")
    if (
        str(result.get("code", 0)) not in ("0", "SUCCESS")
        or str(cr.get("code", 0)) not in ("0", "SUCCESS")
    ):
        raise PaymentRejected("链上确认该次支付失败，可以重试原订单")
    if int(record.get("block_height", 0)) <= 0:
        raise ValueError("尚未取得有效区块高度")

    path = ROOT / "results" / ("shop-payment-" + order["id"] + ".json")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return txid

def confirm(order, txid):
    try:
        prove_payment(order, txid)
    except PaymentRejected as exc:
        with closing(connect()) as db, db:
            db.execute(
                "UPDATE orders SET status='failed',tx=?,error=? "
                "WHERE id=? AND status!='paid'",
                (txid, str(exc), order["id"])
            )
        raise
    with closing(connect()) as db, db:
        db.execute(
            "UPDATE orders SET status='paid',tx=?,error='' WHERE id=?",
            (txid, order["id"])
        )

def install(app, identities):
    @app.template_filter("person")
    def person(address):
        names = {
            identities["admin"]: "校园管理员",
            identities["alice"]: "Alice · 学生A",
            identities["bob"]: "Bob · 学生B"
        }
        return names.get(address, "其他链上账户")

    @app.context_processor
    def appearance():
        user = session.get("user")
        equipped = {}
        if user:
            with closing(connect()) as db:
                rows = db.execute("""
                    SELECT p.slot,p.sku FROM preferences p
                    JOIN orders o ON o.user=p.user AND o.sku=p.sku
                    WHERE p.user=? AND o.status='paid'
                """, (user,)).fetchall()
                equipped = {r["slot"]: r["sku"] for r in rows}
        return {"appearance": equipped}

    def login_user():
        user = session.get("user")
        if user not in identities:
            abort(401)
        return user

    @app.get("/shop")
    def shop_page():
        user = login_user()
        with closing(connect()) as db:
            own = {
                r["sku"]: dict(r) for r in db.execute(
                    "SELECT * FROM orders WHERE user=?", (user,)
                )
            }
            records = [
                dict(r) for r in db.execute(
                    "SELECT * FROM orders ORDER BY created DESC"
                    if user == "admin" else
                    "SELECT * FROM orders WHERE user=? ORDER BY created DESC",
                    () if user == "admin" else (user,)
                )
            ]
        error = ""
        balance = None
        try:
            balance = required(user, "ft", "BalanceOf", {
                "account": identities[user]
            })
        except Exception:
            error = "暂时无法读取链上余额，请检查节点连接后刷新。"
        message = session.pop("shop_message", "")
        return render_template(
            "shop.html", user=user, goods=CATALOG, own=own,
            records=records, balance=balance, error=error, message=message
        )

    @app.post("/shop/buy")
    def buy():
        user = login_user()
        if user == "admin":
            abort(403)
        sku = request.form.get("sku", "")
        if sku not in CATALOG:
            abort(400)
        product = CATALOG[sku]
        try:
            balance = required(user, "ft", "BalanceOf", {
                "account": identities[user]
            })
            with closing(connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM orders WHERE user=? AND sku=?", (user, sku)
                ).fetchone()
                if row and row["status"] == "paid":
                    raise ValueError("你已拥有该装扮，没有再次扣款。")
                if row and row["status"] == "pending":
                    raise ValueError("该订单正在等待核对，请先回查，不重复支付。")
                if int(balance) < product["price"]:
                    raise ValueError("可用积分不足，没有创建支付。")
                if row:
                    db.execute(
                        "UPDATE orders SET status='pending',tx=NULL,error='' WHERE id=?",
                        (row["id"],)
                    )
                    order_id = row["id"]
                else:
                    order_id = "shop-" + uuid.uuid4().hex
                    db.execute("""
                        INSERT INTO orders
                        (id,user,sku,price,owner,merchant,status)
                        VALUES(?,?,?,?,?,?,'pending')
                    """, (
                        order_id, user, sku, product["price"],
                        identities[user], identities["admin"]
                    ))
                order = dict(db.execute(
                    "SELECT * FROM orders WHERE id=?", (order_id,)
                ).fetchone())

            receipt = call(user, "ft", "Transfer", {
                "id": order["id"], "from": order["owner"],
                "to": order["merchant"], "amount": str(order["price"])
            })
            txid = receipt.get("tx_id") or ""
            with closing(connect()) as db, db:
                db.execute(
                    "UPDATE orders SET tx=?,error=? WHERE id=?",
                    (txid or None, receipt.get("error", ""), order["id"])
                )
            if not txid:
                raise ValueError("支付状态待核对。请保留订单，不要再次转账。")
            # 不仅看网页回执，还核对真实交易的参数和执行结果。
            confirm(order, txid)
            session["shop_message"] = "兑换成功，可以启用装扮。"
        except Exception as exc:
            session["shop_message"] = str(exc)
        return redirect("/shop")

    @app.post("/shop/reconcile")
    def reconcile():
        user = login_user()
        with closing(connect()) as db:
            row = db.execute(
                "SELECT * FROM orders WHERE id=? AND user=?",
                (request.form.get("order", ""), user)
            ).fetchone()
        if not row:
            abort(404)
        order = dict(row)
        try:
            if order["status"] == "paid":
                raise ValueError("订单已经核验成功，无需重复处理。")
            txid = request.form.get("tx", "").strip() or order["tx"] or ""
            confirm(order, txid)
            session["shop_message"] = "回查成功，装扮权益已恢复，没有重复扣款。"
        except Exception as exc:
            session["shop_message"] = str(exc)
        return redirect("/shop")

    @app.post("/shop/equip")
    def equip():
        user = login_user()
        sku = request.form.get("sku", "")
        if sku not in CATALOG:
            abort(400)
        with closing(connect()) as db, db:
            row = db.execute(
                "SELECT status FROM orders WHERE user=? AND sku=?", (user, sku)
            ).fetchone()
            if not row or row["status"] != "paid":
                abort(403, "尚未拥有该装扮")
            db.execute("""
                INSERT INTO preferences(user,slot,sku) VALUES(?,?,?)
                ON CONFLICT(user,slot) DO UPDATE SET sku=excluded.sku
            """, (user, CATALOG[sku]["slot"], sku))
        session["shop_message"] = "装扮已启用，返回首页即可查看。"
        return redirect("/shop")

    @app.post("/shop/reset")
    def reset():
        user = login_user()
        with closing(connect()) as db, db:
            db.execute("DELETE FROM preferences WHERE user=?", (user,))
        session["shop_message"] = "已恢复默认外观，已兑换权益仍然保留。"
        return redirect("/shop")
