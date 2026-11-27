import base64
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONF = json.loads((ROOT / "settings.json").read_text())
USERS = ("admin", "alice", "bob")
READS = {"Snapshot", "Info", "WhoAmI", "BalanceOf", "OwnerOf", "Token", "Probe"}

def sdk_args(user):
    if user not in USERS:
        raise ValueError("未知账户")
    return [
        "--sdk-conf-path=" + str(ROOT / "config" / f"{user}.yml"),
        "--enable-cert-hash=false"
    ]

def parse_json(output):
    decoder = json.JSONDecoder()
    for i, char in enumerate(output):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(output[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    raise RuntimeError("CMC未返回JSON：" + output[-1500:])

def run(args):
    p = subprocess.run(
        [str(Path(CONF["cmc_dir"]) / "cmc"), *args],
        cwd=CONF["cmc_dir"], capture_output=True,
        text=True, encoding="utf-8", timeout=90
    )
    raw = parse_json(p.stdout + "\n" + p.stderr)
    return p.returncode, raw

def decode(raw):
    cr = raw.get("contract_result")
    if not isinstance(cr, dict):
        raise RuntimeError("E_RECEIPT: missing contract_result")
    encoded = cr.get("result") or ""
    detail = base64.b64decode(encoded, validate=True).decode("utf-8") if encoded else ""
    if str(raw.get("code", 0)) not in ("0", "SUCCESS") or \
       str(cr.get("code", 0)) not in ("0", "SUCCESS"):
        raise RuntimeError(detail or cr.get("message") or raw.get("message") or "E_CHAIN")
    if not detail:
        raise RuntimeError("E_RECEIPT: empty result")
    return json.loads(detail)

def call(user, role, method, params=None):
    if role not in CONF["contracts"]:
        raise ValueError("未知合约")
    write = method not in READS
    params = {k: str(v) for k, v in (params or {}).items()}
    result = {
        "user": user, "role": role, "method": method,
        "params": params, "time": time.time(), "ok": False
    }
    try:
        command = [
            "client", "contract", "user", "invoke" if write else "get",
            "--contract-name=" + CONF["contracts"][role],
            "--method=" + method,
            "--params=" + json.dumps(params, ensure_ascii=False),
            *sdk_args(user)
        ]
        if write:
            command += ["--sync-result=true", "--timeout=60"]
        rc, raw = run(command)
        result.update(
            raw=raw, tx_id=raw.get("tx_id", ""),
            height=raw.get("tx_block_height")
        )
        result["data"] = decode(raw)
        if rc:
            raise RuntimeError("CMC退出码非0，请检查原始回执")
        result["ok"] = True
    except subprocess.TimeoutExpired:
        result["error"] = "E_UNKNOWN: 等待超时，先查链上状态，不要立即重复提交"
    except Exception as exc:
        result["error"] = str(exc)

    if write:
        with (ROOT / "results/operations.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result

def required(user, role, method, params=None):
    r = call(user, role, method, params)
    if not r["ok"]:
        raise RuntimeError(r.get("error", "调用失败"))
    return r["data"]

def snapshots(user="admin"):
    return {r: required(user, r, "Snapshot") for r in ("ft", "nft", "task")}

def identities():
    values = {
        u: required(u, "ft", "WhoAmI")["Sender"]
        for u in USERS
    }
    if len(set(values.values())) != 3:
        raise RuntimeError("三个账户的真实调用身份重复")
    return values

def query(kind, value):
    rc, raw = run([
        "query", kind, str(value), "--chain-id=chain1", *sdk_args("admin")
    ])
    if rc:
        raise RuntimeError(str(raw))
    return raw

def audit(txid):
    tx = query("tx", txid)
    block = query("block-by-txid", txid)["block"]
    height = int(block["header"]["block_height"])
    if tx["transaction"]["payload"]["tx_id"] != txid:
        raise RuntimeError("交易ID不一致")
    if int(tx["block_height"]) != height:
        raise RuntimeError("交易与区块高度不一致")
    matched = [x for x in block["txs"] if x["payload"]["tx_id"] == txid]
    if len(matched) != 1:
        raise RuntimeError("区块中未唯一找到交易")
    if matched[0]["payload"]["contract_name"] != CONF["contracts"]["task"]:
        raise RuntimeError("不是任务合约交易")
    if matched[0]["payload"]["method"] != "Review":
        raise RuntimeError("不是审核交易")

    result = tx["transaction"]["result"]
    if str(result.get("code", 0)) not in ("0", "SUCCESS"):
        raise RuntimeError("审核交易链上结果失败")
    if str(result.get("contract_result", {}).get("code", 0)) not in ("0", "SUCCESS"):
        raise RuntimeError("审核合约结果失败")

    bh = block["header"]["block_hash"]
    by_height = query("block-by-height", height)["block"]
    if by_height["header"]["block_hash"] != bh:
        raise RuntimeError("按高度查询区块不一致")
    is_hex = len(bh) == 64 and all(c in "0123456789abcdefABCDEF" for c in bh)
    hex_hash = bh if is_hex else base64.b64decode(bh, validate=True).hex()
    by_hash = query("block-by-hash", hex_hash)["block"]
    if by_hash["header"]["block_hash"] != bh:
        raise RuntimeError("按哈希查询区块不一致")

    evidence = {
        "tx_id": txid, "height": height, "block_hash": hex_hash,
        "transaction": tx, "block": block
    }
    (ROOT / "results/verified-review.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2)
    )
    return {"tx_id": txid, "height": height, "block_hash": hex_hash}

def deploy():
    cmc = Path(CONF["cmc_dir"])
    certroot = cmc / "testdata/crypto-config"
    keys, certs = [], []
    for n in range(1, 5):
        directory = certroot / f"wx-org{n}.chainmaker.org/user/admin1"
        key, cert = directory / "admin1.sign.key", directory / "admin1.sign.crt"
        if not key.is_file() or not cert.is_file():
            raise RuntimeError("缺少原四组织管理员背书材料")
        keys.append(str(key))
        certs.append(str(cert))

    for role in ("ft", "nft", "task"):
        name = CONF["contracts"][role]
        params = {"role": role}
        if role == "task":
            params.update(ft=CONF["contracts"]["ft"], nft=CONF["contracts"]["nft"])
        rc, raw = run([
            "client", "contract", "user", "create",
            "--contract-name=" + name, "--runtime-type=DOCKER_GO",
            "--byte-code-path=" + str(ROOT / "contract/build" / f"{name}.7z"),
            "--version=1.0", "--sync-result=true", "--timeout=60",
            "--params=" + json.dumps(params),
            "--admin-key-file-paths=" + ",".join(keys),
            "--admin-crt-file-paths=" + ",".join(certs),
            *sdk_args("admin")
        ])
        (ROOT / "results" / f"deploy-{role}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2)
        )
        cr = raw.get("contract_result")
        if rc or str(raw.get("code", 0)) not in ("0", "SUCCESS") or \
           not isinstance(cr, dict) or str(cr.get("code", 0)) not in ("0", "SUCCESS"):
            raise RuntimeError(f"{name}部署结果待核对：{raw}")
        state = required("admin", role, "Snapshot")
        if state["Role"] != role:
            raise RuntimeError("部署角色不一致")
        print(name, "部署后查询成功；交易ID：", raw.get("tx_id"))

def bind():
    ids = identities()
    states = snapshots()
    for role, state in states.items():
        if state["Role"] != role or state["Admin"] != ids["admin"]:
            raise RuntimeError("合约角色或管理员不一致")

    # 从实际跨合约调用观察任务合约地址，避免硬编码地址算法。
    probe = required("admin", "task", "Probe")
    if probe["Origin"] != ids["admin"] or probe["Sender"] in ids.values():
        raise RuntimeError("跨合约身份探测不符合预期")
    issuer = probe["Sender"]
    for role in ("ft", "nft"):
        required("admin", role, "SetIssuer", {"issuer": issuer})
    for user in ("alice", "bob"):
        required("admin", "task", "Register", {"account": ids[user]})

    states = snapshots()
    if any(states[r]["Issuer"] != issuer for r in ("ft", "nft")):
        raise RuntimeError("奖励合约授权不一致")
    evidence = {"accounts": ids, "task_contract_address": issuer}
    (ROOT / "results/identities.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2)
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("绑定成功：只有任务合约可调用Award；Alice和Bob已登记。")

if __name__ == "__main__":
    command = sys.argv[1]
    if command == "deploy":
        deploy()
    elif command == "bind":
        bind()
    elif command == "snapshot":
        print(json.dumps(snapshots(), ensure_ascii=False, indent=2))
    elif command == "audit":
        print(json.dumps(audit(sys.argv[2]), ensure_ascii=False, indent=2))
    else:
        params = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
        r = call(sys.argv[1], sys.argv[2], sys.argv[3], params)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if r["ok"] else 1)
