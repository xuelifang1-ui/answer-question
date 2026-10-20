# API

所有接口要求 staff 用户认证。请求头：

```text
Authorization: Token <实际令牌>
Content-Type: application/json
```

列表默认每页 50 条，使用 `?page=2` 翻页，返回 `count`、`next`、`previous`、`results`。

## 基础资源

| 路径 | 方法 | 说明 |
| --- | --- | --- |
| `/api/departments/` | GET、POST | 部门列表、创建 |
| `/api/departments/{id}/` | GET、PUT、PATCH、DELETE | 部门详情、修改、删除 |
| `/api/clusters/` | GET、POST | 集群列表、创建 |
| `/api/clusters/{id}/` | GET、PUT、PATCH、DELETE | 集群详情、修改、删除 |
| `/api/instances/` | GET、POST | 实例列表、登记 |
| `/api/instances/{id}/` | GET、PUT、PATCH、DELETE | 实例详情、修改、删除 |

创建部门：`{"code":"rd","name":"研发部"}`。

创建集群：`{"code":"prod","name":"生产集群","description":"业务数据库分组"}`。

`code` 唯一，允许字母、数字、下划线、连字符。名称可重复。仍有实例引用的部门或集群不可删除，返回 409。

登记实例示例（密码为示例占位值，必须替换为目标库的当前有效密码）：

```json
{
  "name": "订单数据库",
  "department": 1,
  "cluster": 1,
  "host": "172.30.66.10",
  "port": 5432,
  "database": "demo",
  "username": "managed_app",
  "password": "<目标库当前有效密码>",
  "rotation_enabled": true
}
```

账号必须已存在。登记接口校验字段和访问网段，不在登记时验证数据库账号。`password` 只写，响应不包含它或密文。保存时保留密码首尾空格；数据库名、角色名按 PostgreSQL 的 63 字节限制校验。

`password_changed_at`、`next_rotation_at` 由服务端维护，客户端不能修改。修改 host、port、database、username 中任意一个字段时，需要同时提供该连接的当前密码；单独 PATCH 密码会被拒绝，实际改密应走轮换接口。

实例列表支持 `?department=1&cluster=1&rotation_enabled=true`。未完成轮换时不可编辑或删除实例。删除已完成轮换的实例不删除历史记录。

## TCP 探测

`POST /api/instances/{id}/probe/`，无需请求体。

```json
{
  "instance_id": 1,
  "reachable": true,
  "error": "",
  "duration_ms": 1.285,
  "checked_at": "2026-10-20T08:00:00+00:00"
}
```

只探测已登记地址，请求体不能覆盖目标。超时、拒绝连接或网络错误返回 200、`reachable=false` 和分类错误码。网段不允许返回 400；实例不存在返回 404。

## 手动轮换与历史查询

`POST /api/instances/{id}/rotate-password/`，无需请求体，返回 202 和轮换记录。相同实例已有未完成记录时复用该记录。

`GET /api/rotations/?instance=1&status=pending` 查询进度，`GET /api/rotations/{uuid}/` 查询详情。该资源只读。

| 字段 | 含义 |
| --- | --- |
| `status` | `pending`：未确认完成；`succeeded`：已验证新密码并更新当前记录 |
| `attempts` | 已进入目标库处理的尝试次数 |
| `last_error` | 受控错误码；不返回原始数据库异常或连接串 |
| `requested_by` | 触发操作的用户或 `scheduler` |
| `completed_at` | 完成确认时间，未完成时为空 |

`target_database_error` 表示连接、认证或改密失败，需检查目标库状态；`target_not_allowed` 表示当前网段策略不允许；`password_auth_required` 表示未使用密码认证。

## 每日统计

- `GET /api/snapshots/?snapshot_date=2026-10-20`：当天的快照时间和总量。
- `GET /api/statistics/?snapshot_date=2026-10-20&dimension=department`：部门统计。
- `GET /api/statistics/?snapshot_date=2026-10-20&dimension=cluster`：集群统计。
- `GET /api/statistics/?snapshot_date=2026-10-20&dimension=department_cluster`：交叉统计。
- 可继续按 `department_code`、`cluster_code` 过滤。

快照和统计接口只读。没有采集过的日期返回空列表，不自动补造记录。

## 返回码与耗时

| 状态码 | 含义 |
| --- | --- |
| 200、201、204 | 查询/修改成功、创建成功、删除成功 |
| 202 | 已记录轮换请求并投递任务 |
| 400 | 字段、筛选条件或业务参数无效 |
| 401、403 | 未认证、当前账号无操作权限 |
| 404 | 资源不存在 |
| 409 | 外键保护、未完成轮换、数据库唯一约束冲突 |
| 503 | 队列不可用，或当前管理库不支持轮换行锁 |

每个响应包含 `X-Request-Duration-Ms`、`X-Request-ID`。耗时范围是服务端收到请求到产生响应对象，不包含客户端传输时间。日志包含请求方法、路径、状态码、请求 ID 和耗时，不记录查询字符串、请求体或认证头。
