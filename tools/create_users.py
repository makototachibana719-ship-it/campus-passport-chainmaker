"""Create Web login hashes interactively without replacing existing users.json."""
import getpass
import json
import os
from pathlib import Path
from werkzeug.security import generate_password_hash


def main():
    target = Path(__file__).resolve().parents[1] / "users.json"
    if target.exists():
        raise SystemExit("users.json 已存在；保留原登录设置，不覆盖。")
    users = {}
    for user in ("admin", "alice", "bob"):
        password = getpass.getpass(f"设置 {user} 的 Web 登录密码：")
        repeated = getpass.getpass("再次输入：")
        if not password or password != repeated:
            raise SystemExit("密码为空或两次不同；未写入文件。")
        users[user] = generate_password_hash(password)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(users, stream, ensure_ascii=False, indent=2)
    print("已生成本地 users.json。未创建链上身份，未执行链上操作。")


if __name__ == "__main__":
    main()
