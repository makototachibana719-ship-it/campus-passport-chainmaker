import hashlib
import json

from bridge import ROOT, audit, call, identities, required, snapshots

def check(condition, message):
    if not condition:
        raise RuntimeError(message)

def write_json(name, value):
    (ROOT / "results" / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def pause(message):
    print("\n" + "=" * 70 + "\n" + message + "\n" + "=" * 70)
    input("完成网页操作及截图后，回到这里按回车继续：")

def good(user, role, method, params=None):
    r = call(user, role, method, params)
    print(json.dumps({
        k: r.get(k) for k in ("user", "role", "method", "ok", "tx_id", "height", "error")
    }, ensure_ascii=False))
    check(r["ok"], f"预期成功但失败：{r}")
    return r

def rejected(user, role, method, params, expected):
    before = snapshots()
    r = call(user, role, method, params)
    after = snapshots()
    print(json.dumps({
        "test": method, "user": user, "expected": expected,
        "ok": r["ok"], "error": r.get("error"),
        "tx_id": r.get("tx_id"), "state_unchanged": before == after
    }, ensure_ascii=False, indent=2))
    check(not r["ok"] and expected in r.get("error", ""),
          "未取得预期的业务拒绝，网络错误不能算测试通过")
    check(before == after, "失败操作改变了链上状态")
    return r

ids = identities()
initial = snapshots()
check(initial["ft"]["Supply"] == 0, "新积分合约发行量不是0，请核对测试进度")
check(not initial["task"]["Tasks"] and not initial["nft"]["Badges"],
      "已有任务或徽章，请勿重跑整套验收")
write_json("initial-state.json", initial)

tasks = [
    ("CAMPUS_TECH", "开源技术分享", "tech", 100, "lecture-demo-v1"),
    ("CAMPUS_SERVICE", "校园志愿服务", "service", 60, "service-demo-v1"),
    ("CAMPUS_GREEN", "绿色校园行动", "green", 40, "green-demo-v1"),
]

for task_id, title, category, reward, evidence in tasks:
    good("admin", "task", "Create", {
        "id": task_id, "title": title, "category": category, "reward": reward
    })

pause(
    "截图06：管理员登录并刷新，展示三个任务及100/60/40奖励。\n"
    "随后退出管理员，登录alice。\n"
    "分别领取三个任务，在“我的任务”提交以下纯文本材料，不上传文件：\n"
    "开源技术分享：lecture-demo-v1\n"
    "校园志愿服务：service-demo-v1\n"
    "绿色校园行动：green-demo-v1\n"
    "不要添加空格或换行。\n"
    "截图07：Alice三个任务均为待审核，展示材料摘要。"
)

state = snapshots()
claims = {}
for task_id, title, category, reward, evidence in tasks:
    matches = [
        c for c in state["task"]["Claims"].values()
        if c["TaskID"] == task_id and c["Owner"] == ids["alice"]
    ]
    check(len(matches) == 1, f"{task_id}没有唯一领取记录")
    c = matches[0]
    check(c["Status"] == "SUBMITTED", f"{task_id}未提交")
    expected_hash = hashlib.sha256(evidence.encode()).hexdigest()
    check(c["Proof"] == expected_hash, f"{task_id}提交文本与要求不一致")
    claims[task_id] = c

first = claims["CAMPUS_TECH"]
rejected("alice", "task", "Milestone", {}, "E_CONDITION")

good("admin", "nft", "Pause", {"value": "true"})
try:
    rollback = rejected("admin", "task", "Review", {
        "claim": first["ID"], "approve": "true", "reason": "故障注入测试"
    }, "E_PAUSED")
    write_json("atomic-failure-test.json", rollback)
finally:
    good("admin", "nft", "Pause", {"value": "false"})

print("一致性检查通过：徽章暂停时，积分未增加、徽章未生成、任务仍待审核。")
pause(
    "截图08：保存终端中的E_PAUSED、state_unchanged=true与一致性检查结果。\n"
    "网页登录admin，依次通过三个任务，审核意见填写“模拟材料已核对”。\n"
    "截图09：首个任务审核成功的交易ID与回执。\n"
    "截图10：三个任务全部完成。\n"
    "退出并登录alice，刷新：积分应为200，徽章应为3枚。\n"
    "截图11：Alice成长护照、三类进度和三枚徽章。"
)

state = snapshots()
check(state["ft"]["Balances"].get(ids["alice"], 0) == 200, "Alice应有200积分")
check(state["ft"]["Supply"] == 200, "总量应为200")
check(len(state["nft"]["Badges"]) == 3, "应有3枚任务徽章")
for task_id, original in claims.items():
    current = state["task"]["Claims"][original["ID"]]
    check(current["Status"] == "APPROVED", f"{task_id}未审核通过")
    badge = state["nft"]["Badges"][current["BadgeID"]]
    check(badge["Owner"] == ids["alice"], "徽章持有人错误")
    check(badge["Proof"] == current["Proof"], "徽章材料摘要错误")
    check(badge["Tx"] == current["ReviewTx"], "徽章与审核不是同一交易")
    claims[task_id] = current
write_json("approved-state.json", state)

first = claims["CAMPUS_TECH"]
pause(
    "保持alice登录，点击“领取成长奖励+30”，余额应变为230。\n"
    "截图12：成长奖励成功回执与230积分。\n"
    "在积分流转中向bob转账50，Alice应变为180。\n"
    "截图13：转账成功回执。\n"
    "退出并登录admin，选择“管理员发行积分”，向bob发行10。\n"
    "再登录bob，余额应为60。\n"
    "截图14：Bob独立登录查询到账60，总发行量240。"
)

state = snapshots()
expected = {"admin": 0, "alice": 180, "bob": 60}
actual = {u: state["ft"]["Balances"].get(a, 0) for u, a in ids.items()}
check(actual == expected and state["ft"]["Supply"] == 240,
      f"实际余额或发行量不符：{actual}, supply={state['ft']['Supply']}")
check(sum(state["ft"]["Balances"].values()) == state["ft"]["Supply"],
      "全体账户余额之和与发行量不一致")

tests = []
tests.append(rejected("admin", "task", "Review", {
    "claim": first["ID"], "approve": "true", "reason": "重复审核"
}, "E_STATE"))
tests.append(rejected("alice", "task", "Milestone", {}, "E_DUPLICATE"))
tests.append(rejected("alice", "task", "Claim", {
    "task": "CAMPUS_TECH"
}, "E_DUPLICATE"))
tests.append(rejected("alice", "task", "Create", {
    "id": "FORGED", "title": "越权任务", "category": "tech", "reward": "1"
}, "E_ROLE"))
tests.append(rejected("alice", "ft", "Mint", {
    "id": "forged-mint", "to": ids["alice"], "amount": "1"
}, "E_ROLE"))
tests.append(rejected("alice", "ft", "Award", {
    "id": "forged-award", "to": ids["alice"], "amount": "1"
}, "E_ISSUER"))
tests.append(rejected("alice", "nft", "Mint", {
    "id": "forged-badge", "to": ids["alice"], "title": "越权徽章",
    "proof": "0"*64
}, "E_ROLE"))
tests.append(rejected("alice", "nft", "Transfer", {
    "id": first["BadgeID"], "to": ids["bob"]
}, "E_SOULBOUND"))
tests.append(rejected("alice", "ft", "Transfer", {
    "id": "bad-from", "from": ids["bob"], "to": ids["admin"], "amount": "1"
}, "E_FROM"))
tests.append(rejected("alice", "ft", "Transfer", {
    "id": "too-much", "from": ids["alice"], "to": ids["bob"], "amount": "999999"
}, "E_BALANCE"))
for n in ("0", "-1"):
    tests.append(rejected("alice", "ft", "Transfer", {
        "id": "bad-amount-"+n, "from": ids["alice"],
        "to": ids["bob"], "amount": n
    }, "E_AMOUNT"))
write_json("negative-tests.json", tests)

pause(
    "截图15：终端中的重复奖励、越权调用、不可转让测试结果。\n"
    "截图16：伪造转出账户、余额不足和非法数量测试结果。\n"
    "浏览器打开开源技术分享徽章的查验页面。\n"
    "先输入lecture-demo-v1核验，截图17：材料摘要匹配。\n"
    "再输入lecture-demo-v2核验，截图18：材料摘要不匹配。\n"
    "这两个查验操作不会改变链上状态。"
)

evidence = audit(first["ReviewTx"])
final = snapshots()
write_json("final-state.json", final)
write_json("acceptance-summary.json", {
    "balances": actual, "supply": 240, "badges": 3,
    "negative_test_count": len(tests), "review": evidence
})
print(json.dumps({
    "accounts": ids, "balances": actual, "supply": final["ft"]["Supply"],
    "badges": len(final["nft"]["Badges"]), "review": evidence
}, ensure_ascii=False, indent=2))
print("验收通过：正常流程、奖励去重、权限、失败状态不变及交易区块回查均通过。")
print("截图19：保存最终余额、徽章数量、审核交易ID、区块高度和区块哈希。")
