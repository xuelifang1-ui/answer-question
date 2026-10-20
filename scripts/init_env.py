import argparse
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

parser = argparse.ArgumentParser(description="生成本地配置，已有文件时拒绝覆盖")
parser.add_argument("--sqlite", action="store_true", help="只浏览接口，不运行并发轮换")
args = parser.parse_args()
path = Path(__file__).resolve().parents[1] / ".env"
content = "\n".join(
    [
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}",
        f"FERNET_KEY={Fernet.generate_key().decode()}",
        "DJANGO_DEBUG=false",
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]",
        f"DB_ENGINE={'sqlite' if args.sqlite else 'postgresql'}",
        "DB_NAME=instance_manager",
        "DB_USER=manager",
        f"DB_PASSWORD={secrets.token_urlsafe(32)}",
        "DB_HOST=127.0.0.1",
        "DB_PORT=5432",
        "CELERY_BROKER_URL=redis://127.0.0.1:6379/0",
        "TARGET_ALLOWED_CIDRS=127.0.0.1/32,::1/128,172.30.66.0/24",
        "TARGET_SSLMODE=prefer",
        "DEMO_SUBNET=172.30.66.0/24",
        "DEMO_TARGET_IP=172.30.66.10",
        f"DEMO_ADMIN_PASSWORD={secrets.token_urlsafe(32)}",
        f"DEMO_APP_PASSWORD={secrets.token_urlsafe(32)}",
        "",
    ]
)
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)
except FileExistsError:
    parser.exit(1, ".env 已存在，未覆盖；保留原 FERNET_KEY 才能解密已有密码。\n")
print("已生成 .env")
