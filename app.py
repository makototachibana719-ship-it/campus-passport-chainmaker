import hashlib
import json
import secrets
from datetime import timedelta

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from bridge import ROOT, USERS, call, identities, required, snapshots

app = Flask(__name__)
app.secret_key = secrets.token_bytes(32)
app.config.update(
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)
PASSWORDS = json.loads((ROOT / "users.json").read_text())
IDS = identities()
LAST = {}

LABELS = {"admin": "校园管理员", "alice": "Alice · 学生A", "bob": "Bob · 学生B"}
CATEGORIES = {"tech": "技术成长", "service": "志愿服务", "green": "绿色校园"}
STATUSES = {
    "CLAIMED": "已领取", "SUBMITTED": "待审核",
    "APPROVED": "已完成", "REJECTED": "待补充材料"
}

@app.before_request
def csrf():
    session.setdefault("csrf", secrets.token_hex(24))
    if request.method == "POST":
        if not secrets.compare_digest(session["csrf"], request.form.get("csrf", "")):
            abort(400, "页面已失效，请刷新后重试")

@app.context_processor
def common():
    return {
        "csrf": session.get("csrf", ""), "labels": LABELS,
        "categories": CATEGORIES, "statuses": STATUSES,
        "accounts": IDS, "users": USERS
    }

def material_hash():
    upload = request.files.get("material")
    if upload and upload.filename:
        data = upload.read()
    else:
        data = request.form.get("evidence", "").encode("utf-8")
    if not data:
        raise ValueError("请填写材料文本或选择文件")
    return hashlib.sha256(data).hexdigest()

@app.get("/")
def index():
    user = session.get("user")
    if user not in USERS:
        return render_template("index.html", user=None, error="")
    try:
        state = snapshots(user)
        address = IDS[user]
        claims = sorted(
            (c for c in state["task"]["Claims"].values()
             if user == "admin" or c["Owner"] == address),
            key=lambda c: (c["TaskID"], c["Owner"])
        )
        badges = sorted(
            (b for b in state["nft"]["Badges"].values()
             if b["Owner"] == address),
            key=lambda b: b["ID"]
        )
        completed = {
            state["task"]["Tasks"][c["TaskID"]]["Category"]
            for c in state["task"]["Claims"].values()
            if c["Owner"] == address and c["Status"] == "APPROVED"
        }
        pending = sum(c["Status"] == "SUBMITTED" for c in claims)
        return render_template(
            "index.html", user=user, error="", state=state, claims=claims,
            badges=badges, completed=completed, pending=pending,
            balance=state["ft"]["Balances"].get(address, 0),
            last=LAST.get(user), rid=secrets.token_hex(16)
        )
    except Exception as exc:
        return render_template("index.html", user=user, error=str(exc)), 503

@app.post("/login")
def login():
    user = request.form.get("user", "")
    if user not in USERS or not check_password_hash(
        PASSWORDS.get(user, ""), request.form.get("password", "")
    ):
        return render_template("index.html", user=None, error="账户或密码错误"), 401
    session.clear()
    session.update(user=user, csrf=secrets.token_hex(24))
    session.permanent = True
    return redirect(url_for("index"))

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.post("/act")
def act():
    user = session.get("user")
    if user not in USERS:
        abort(401)
    f = request.form
    action = f.get("action", "")
    try:
        if action == "create":
            role, method, p = "task", "Create", {
                "id": f.get("id", ""), "title": f.get("title", ""),
                "category": f.get("category", ""), "reward": f.get("reward", "")
            }
        elif action == "claim":
            role, method, p = "task", "Claim", {"task": f.get("task", "")}
        elif action == "submit":
            role, method, p = "task", "Submit", {
                "claim": f.get("claim", ""), "proof": material_hash()
            }
        elif action == "review":
            role, method, p = "task", "Review", {
                "claim": f.get("claim", ""), "approve": f.get("approve", ""),
                "reason": f.get("reason", "")
            }
        elif action == "milestone":
            role, method, p = "task", "Milestone", {}
        elif action in ("transfer", "mint"):
            target = f.get("target", "")
            if target not in USERS:
                raise ValueError("目标账户无效")
            role, method = "ft", "Transfer" if action == "transfer" else "Mint"
            p = {
                "id": f.get("rid", ""), "to": IDS[target],
                "amount": f.get("amount", "")
            }
            if action == "transfer":
                p["from"] = IDS[user]
        elif action == "badge":
            target = f.get("target", "")
            if target not in USERS:
                raise ValueError("目标账户无效")
            role, method, p = "nft", "Mint", {
                "id": f.get("id", ""), "to": IDS[target],
                "title": f.get("title", ""), "category": "special",
                "proof": material_hash(), "claim": ""
            }
        else:
            raise ValueError("不支持的操作")
        LAST[user] = call(user, role, method, p)
    except Exception as exc:
        LAST[user] = {"ok": False, "error": str(exc)}
    return redirect(url_for("index"))

@app.route("/verify", methods=["GET", "POST"])
def verify():
    token_id = request.values.get("id", "").strip()
    badge, error, match = None, "", None
    if token_id:
        try:
            badge = required("admin", "nft", "Token", {"id": token_id})
            if request.method == "POST":
                match = material_hash() == badge["Proof"]
        except Exception as exc:
            error = str(exc)
    return render_template(
        "verify.html", badge=badge, error=error, match=match, token_id=token_id
    )

from shop import install
install(app, IDS)

if __name__ == "__main__":
    print("校园成长护照：chain1；三个真实身份已核对。")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=False)
