"""在隔离的 Compose 演示环境中运行 PostgreSQL 集成测试。"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
password = os.environ.get("DEMO_ADMIN_PASSWORD")
if not password:
    sys.exit("缺少 DEMO_ADMIN_PASSWORD；请按 README 在 Compose 演示环境运行此命令。")
if "--in-container" not in sys.argv:
    # 仅为这次测试注入演示管理员密码，常驻服务不持有该密码。
    sys.exit(
        subprocess.call(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "-e",
                "DEMO_ADMIN_PASSWORD",
                "web",
                "python",
                "scripts/test_postgres.py",
                "--in-container",
            ],
            cwd=root,
        )
    )
environment = os.environ.copy()
environment.update(
    {
        "DJANGO_SETTINGS_MODULE": "config.test_settings",
        "RUN_POSTGRES_INTEGRATION": "1",
        "TEST_TARGET_DSN": make_conninfo(
            host=os.getenv("DEMO_TARGET_IP", "172.30.66.10"),
            port=5432,
            dbname="postgres",
            user="postgres",
            password=password,
            sslmode="disable",
        ),
    }
)
sys.exit(
    subprocess.call([sys.executable, "manage.py", "test", "--verbosity=2", "--noinput"], env=environment)
)
