# 验证记录

环境：Python 3.12.14，Django 5.2.18，Celery 5.6.3。以下为本次交付实际执行的结果。

## 自动测试

```text
python -m coverage run manage.py test --settings=config.test_settings --verbosity=1

Ran 56 tests
OK (skipped=5)
```

51 项通过，5 项跳过。跳过项为 PostgreSQL 上的并发轮换准备、并发改密执行、并发每日快照，以及真实新旧密码认证、远端成功后本地失败恢复。它们需要 PostgreSQL 管理库和开启密码认证的目标库。

基础测试使用 SQLite 隔离测试库。涉及目标改密的基础测试使用受控替身；这些结果不能证明真实 PostgreSQL 改密和行锁已联调通过。本地环境未执行这 5 项集成测试；后续已在 GitHub Actions 的 PostgreSQL 环境完成验证，结果见下文。

核心模块按 `pyproject.toml` 的统计口径，语句覆盖率为 93%；不包含迁移、管理命令、后台和测试代码。这是基础测试覆盖率，不是生产环境可靠性指标。

## HTTP 验证

启动真实 WSGI 服务，通过本地 HTTP 请求验证了以下链路：

| 检查 | 结果 |
| --- | --- |
| 无令牌访问实例列表 | 401 |
| 创建部门、集群、实例 | 201 |
| 实例响应不回显密码或密文 | 通过 |
| 探测本地实际监听端口 | 200，`reachable=true` |
| 修改实例名称 | 200 |
| SQLite 模式拒绝真实密码轮换 | 503，符合限制 |
| 删除实例、部门、集群 | 204 |
| 管理后台登录页和静态 CSS | 200 |
| 不存在的路径 | 404 |
| 上述全部响应的耗时和请求 ID | 存在且有效 |

## 其他检查

- `python manage.py check`：通过。
- `python manage.py makemigrations --check --dry-run`：无缺失迁移。
- `python manage.py migrate`：SQLite 上完整迁移通过。
- `python manage.py collectstatic --noinput`：通过，后台静态资源可访问。
- `ruff check .`、`ruff format --check .`：通过。
- `python -m pip check`：无依赖冲突。
- Compose 与 GitHub Actions 配置：YAML 解析、关键配置检查通过。
- `sh -n docker/init-target.sh`：通过。

Docker 镜像构建、完整 Compose 启动，以及 Redis 与 Celery 的跨进程调度尚未作为完整端到端流程验证。GitHub Actions 已完成代码检查和 PostgreSQL 集成测试，详见下文。


## GitHub Actions 验证（2026-10-20）

已在 GitHub 托管运行器和 PostgreSQL 16 服务上完成自动验证：

```text
Ran 56 tests in 2.035s
OK (skipped=1)
```

55 项通过，1 项跳过。跳过的是仅针对 SQLite 的轮换保护用例，因为本轮管理库为 PostgreSQL。

此前未实跑的 5 项集成测试均已通过：并发轮换准备、并发改密执行、并发每日快照、真实新旧密码认证，以及远端改密成功后本地写入失败的恢复。

Ruff 检查、格式检查、迁移完整性和静态文件采集也均通过。核心模块按原统计口径，语句覆盖率为 94%。这些结果不替代完整 Compose 环境的端到端验证。

[查看本次成功的 GitHub Actions 运行记录](https://github.com/xuelifang1-ui/answer-question/actions/runs/39403617174)
