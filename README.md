# 数据库实例管理系统

Python 3.12、Django 5.2、Django REST Framework、Celery、Redis、PostgreSQL。

管理企业内部的数据库实例，提供部门、集群和实例的 CRUD 接口，以及 TCP 探测、密码轮换、每日统计和请求耗时记录。

## 实现范围

| 题目要求 | 实现 |
| --- | --- |
| 实例、集群、部门模型 | `inventory/models.py`；实例分别关联部门、集群 |
| CRUD 与 TCP 探测 | `/api/departments/`、`/api/clusters/`、`/api/instances/`、`POST /api/instances/{id}/probe/` |
| 每 12 小时随机换密并加密记录 | Celery 扫描到期实例；真实修改 PostgreSQL 角色密码；Fernet 加密保存当前密码与轮换记录 |
| 每天 00:00 统计并入库 | 北京时间采集快照；保存部门、集群和部门×集群三个维度 |
| 每个请求的处理耗时 | 中间件写日志，并返回 `X-Request-Duration-Ms` 和 `X-Request-ID` |

题目未限定数据库产品，本实现选择 PostgreSQL 作为管理库和被管理的目标库。一个实例按 `IP + 端口` 唯一登记，维护一个数据库账号；集群是实例的逻辑分组，可以包含不同部门的实例。目标数据库需已存在，本系统不负责创建数据库。

## 启动完整演示

需要 Python 3.12 和 Docker Compose v2。以下命令在项目根目录执行。

```bash
python -m venv .venv
```

激活虚拟环境：Linux/macOS 使用 `source .venv/bin/activate`；Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1`。

```bash
python -m pip install -r requirements-dev.txt
python scripts/init_env.py
docker compose --profile demo up -d --wait db redis target-db
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser --username operator
docker compose run --rm web python manage.py drf_create_token operator
docker compose run --rm web python manage.py register_demo
docker compose up -d web worker beat
```

保存 `drf_create_token` 输出的令牌，调用接口时使用 `Authorization: Token <令牌>`。系统只允许已登录且 `is_staff=True` 的用户操作。`createsuperuser` 创建的用户满足条件；普通用户返回 403，未认证请求返回 401。

访问 `http://127.0.0.1:8000/admin/` 可查看登记信息、轮换结果和统计记录。实例连接信息通过 API 登记，管理后台不展示密码和密文，也不提供修改轮换记录的入口。容器内的静态资源由 WhiteNoise 提供。

演示目标库创建普通角色 `managed_app`，使用 `demo` 数据库。管理服务和目标服务分开，`register_demo` 会登记演示实例并打印实例 ID。该命令可以重复执行，不覆盖已登记实例的当前密码。

如果 `172.30.66.0/24` 与本机网络冲突，在首次启动前一起调整 `.env` 中的 `DEMO_SUBNET`、`DEMO_TARGET_IP`、`TARGET_ALLOWED_CIDRS`。使用已有业务数据库时不启动 `target-db`，通过 API 登记目标信息即可。

停止服务使用 `docker compose --profile demo down`。默认保留数据库和调度状态的卷。

## 接口验收

以下为 Bash 示例。将令牌和实例 ID 换成实际值。

```bash
export API_TOKEN='<实际令牌>'
curl -H "Authorization: Token $API_TOKEN" http://127.0.0.1:8000/api/instances/
curl -X POST -H "Authorization: Token $API_TOKEN" http://127.0.0.1:8000/api/instances/1/probe/
curl -X POST -H "Authorization: Token $API_TOKEN" http://127.0.0.1:8000/api/instances/1/rotate-password/
curl -H "Authorization: Token $API_TOKEN" http://127.0.0.1:8000/api/rotations/?instance=1
```

轮换接口返回 202，查询轮换记录确认状态从 `pending` 变为 `succeeded`。队列里只传轮换记录 ID，不传明文密码。若 Redis 暂时不可用，接口返回 503，已保存的记录由下一轮扫描继续调度。

无需等到午夜，可以手动验证统计任务：

```bash
docker compose exec web python manage.py collect_statistics
```

然后查询 `/api/snapshots/` 和 `/api/statistics/`。手动采集也会保存为当天快照，同一天后续任务不会覆盖第一次采集的数据。验证定时触发时应使用独立演示环境。

完整字段和返回码见 [docs/api.md](docs/api.md)。

## 密码轮换的处理方式

1. 新登记实例的下一轮换时间为登记时间加 12 小时；以后为上次成功确认时间加 12 小时。
2. Beat 每分钟扫描一次到期实例，另外扫描未完成的轮换记录。正常情况下调度误差约一分钟，停机或网络异常会延迟，不能视为硬实时承诺。
3. 先在管理库提交加密候选密码，再由 worker 操作目标库。锁住实例，并限制同一实例只有一条未完成记录，防止并发重复换密。
4. 优先尝试候选密码；若尚未生效，再用原密码连接，执行 `ALTER ROLE`，然后重新建连接验证新密码。确认成功后更新当前密文、轮换时间和历史记录。
5. 远端已修改、本地尚未提交时进程中断，下次继续使用同一候选密码恢复，不再生成另一串密码。

实际改密的 SQL 使用转义后的角色标识符和 SCRAM 校验值，避免拼接账号或把新密码明文放入 SQL。目标连接必须启用密码认证；发现 `trust` 等免密配置时记录 `password_auth_required`，不视为换密成功。

目标账号需要具有 `LOGIN`、连接指定数据库以及修改自身密码的权限，无需赋予超级用户权限。账号若已被外部修改、过期或受到密码管理扩展限制，记录保持 `pending`；运维应先核对目标库认证配置及账号状态，再由任务继续恢复。未完成轮换时禁止修改和删除该实例，避免遗失恢复所需的凭据。

`rotation_enabled=false` 只暂停后续自动轮换；已发起的轮换仍需完成恢复。手动轮换接口可用于主动触发一次换密。已经完成的轮换再次收到相同任务时直接返回，不重复改密。

## 统计口径

- 00:00 按 `Asia/Shanghai` 调度，数据库时间使用带时区时间。
- 统计登记的全部实例，暂停自动换密的实例仍计入总数。
- 部门和集群分别保留零实例记录；交叉维度只保存实际存在的组合。
- PostgreSQL 使用可重复读事务，三个口径来源于同一份分组数据；整份快照一起提交。
- 统计日期有唯一约束，重复投递不会生成重复结果。名称和编号保存为快照文本，后续重命名、迁移或删除不会改写历史。
- 保存实际采集时间 `captured_at`，不将停机后的当前库存伪装成过去某日 00:00 的历史库存。午夜任务允许一小时排队窗口，错过后可人工采集当天的实际快照。

## 配置与边界

`.env` 由脚本生成随机密钥和演示密码，已被 Git 和 Docker 构建上下文排除。不要直接复制示例占位符运行。脚本拒绝覆盖已有 `.env`，避免误换密钥后无法解密现有记录。

目标地址限定为 IP，登记、探测、改密时均检查 `TARGET_ALLOWED_CIDRS`；端口检查 1～65535。这样不会由接口任意探测外部地址，也不依赖可变的 DNS 解析结果。TCP 可达仅表示能建立连接，不代表账号有效或 SQL 服务健康。

`FERNET_KEY` 与管理数据库需分开保管并备份；丢失密钥后无法恢复已有密码。密码不在响应、后台、任务参数或耗时日志中出现。本示例不提供密码导出接口。对接应用若需要自动获取新凭据，需要另行设计受控的凭据交付机制，避免业务仍使用旧密码。

Compose 绑定本机 8000 端口，PostgreSQL 和 Redis 没有对宿主机暴露端口。真实部署应配置 HTTPS、按实际网段收窄目标白名单，并按企业证书配置 `TARGET_SSLMODE=verify-full` 等连接策略。管理库迁移账号与运行账号的权限也应分别配置；Compose 中的初始化用户用于演示。

只运行一个 Beat 进程；worker 可以多进程。轮换超时或任务被终止后，持久化记录仍可用于重试。轮换记录、统计记录通过接口只读。

## 测试

不启动容器也可以执行基础测试：

```bash
python manage.py test --settings=config.test_settings --verbosity=2
ruff check .
ruff format --check .
```

管理库使用 SQLite 时会跳过 5 项 PostgreSQL 集成测试。基础测试覆盖加密、接口权限、密码不回显、端口检查、外键删除保护、轮换失败恢复、重复任务、每日快照和耗时日志。

真实 PostgreSQL 的并发和改密测试放在 `.github/workflows/test.yml`，推送 GitHub 后可在 Actions 中查看实际结果。该配置已提供，远端执行结果以 Actions 为准。

也可在完整演示启动后执行下列命令。它使用独立的 Django 测试库，并在演示目标库创建临时测试角色，测试结束后删除临时角色：

```bash
python scripts/test_postgres.py
```

这个命令只适用于本项目的 Compose 演示环境，不要把真实业务库作为集成测试目标。当前交付的实际验证情况见 [docs/verification.md](docs/verification.md)。

## 仅浏览接口

如果暂时没有 Docker，可在一个新的项目副本中执行：

```bash
python scripts/init_env.py --sqlite
python manage.py migrate
python manage.py createsuperuser --username operator
python manage.py drf_create_token operator
python manage.py runserver
```

SQLite 模式可浏览 CRUD、TCP 探测和手动采集统计，不能用于并发轮换。程序会拒绝在 SQLite 管理库上执行真实换密。基础测试里的 SQLite 轮换仅验证逻辑，不能代替 PostgreSQL 行锁测试。

## Git 提交

先在自己的 GitHub 或 Gitee 账号创建空仓库，再在项目根目录执行：

```bash
git init -b main
git add .
git diff --cached --stat
git status --short
git commit -m "Implement database instance management"
git remote add origin <自己的空仓库地址>
git push -u origin main
```

如果 Git 尚未设置作者姓名和邮箱，先配置自己的真实信息。提交前检查暂存列表中没有 `.env`、数据库、日志或令牌。不要创建包含 README 的远端初始化提交，以免首次推送产生分支冲突。

提交给招聘方的地址为仓库首页地址。仓库需能被招聘方访问；私有仓库需要按对方要求授予访问权限。本源码包没有预设远端仓库，也没有代为向招聘方提交。

## 设计依据

- [Django 行锁与事务](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [Celery 定时任务与时区](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
- [PostgreSQL 密码认证](https://www.postgresql.org/docs/16/auth-password.html)
- [psycopg 的密码认证检查和密码校验值生成](https://www.psycopg.org/psycopg3/docs/api/pq.html)
- [Fernet 加密](https://cryptography.io/en/latest/fernet/)
