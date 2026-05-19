# amsz-web

一个支持“同一套代码，两套启动逻辑”的任务执行服务骨架：
- `api` 模式：提供 FastAPI 接口
- `worker` 模式：从数据库领取并执行任务
- `combined` 模式：在同一个 Pod 内同时运行 API 和 Worker 两个进程

## 设计特点
- 单一代码库复用同一套领域模型、DAO、服务层
- 支持同 Pod 双进程部署，适合低 API 负载场景
- MySQL 兼容，测试默认用 SQLite
- 无 Redis / MQ，使用数据库租约机制领取任务
- 支持父子任务 fan-out / fan-in、状态查询、取消、重试、执行事件记录
- 运行配置存储在数据库，并支持版本化管理

## 安装
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## 运行时环境变量
运行配置改为“数据库模板 + 环境变量占位符”的模式。

本地至少需要准备：
```bash
export DATABASE_URL="mysql+pymysql://user:password@127.0.0.1:3306/amsz"
export API_KEY="replace-me"
export APP_ENV="dev"
export POD_NAME="pod-1"
export WORKER_ID="worker-1"
export WORKER_QUEUE="default"
export WORKER_CONCURRENCY="2"
```

开发环境也可直接使用默认 SQLite：
```bash
export DATABASE_URL="sqlite+pysqlite:///./amsz.db"
```

说明：
- `DATABASE_URL` 仍然直接来自环境变量
- 普通运行配置来自数据库中的 active runtime config revision
- `API_KEY`、`WORKER_ID`、`POD_NAME`、`APP_ENV`、`WORKER_QUEUE`、`WORKER_CONCURRENCY` 通过环境变量为数据库模板中的 `${...}` placeholder 提供值
- 应用不再自动推导 `WORKER_ID`
- 缺失 active revision、placeholder 无法解析、或配置不合法时，应用会 fail-fast
- 默认日志会同时输出到控制台和 `data/amsz-task-service.log`，单文件 50MB 滚动

## 配置版本管理 API
新增管理接口：
- `GET /api/v1/admin/runtime-config/active`
- `GET /api/v1/admin/runtime-config/revisions`
- `GET /api/v1/admin/runtime-config/revisions/{id}`
- `POST /api/v1/admin/runtime-config/revisions`
- `POST /api/v1/admin/runtime-config/revisions/{id}/activate`
- `POST /api/v1/admin/runtime-config/revisions/{id}/archive`

数据库中保存的是配置模板，例如：
```json
{
  "api_key": "${API_KEY}",
  "worker_id": "${WORKER_ID}",
  "pod_name": "${POD_NAME}",
  "worker_queue": "${WORKER_QUEUE}"
}
```

敏感项不能明文写入数据库，必须使用 placeholder。

## 启动 API
```bash
python -m app.main api
```

## 启动 Worker
```bash
python -m app.main worker --queue default --concurrency 2
```

## 启动 Combined
```bash
python -m app.main combined --queue default --concurrency 2
```

`combined` 模式会启动两个子进程：
- API 进程，提供 HTTP 接口和 `/healthz`
- Worker 进程，负责领取和执行任务

任一子进程异常退出时，父进程会退出，让 Kubernetes 重启整个 Pod。

## 运行测试
```bash
.venv/bin/python -m pytest
```

## Schema Migration
Schema 变更已从 Pod 启动流程中剥离。API、Worker、combined 模式都不会自动建表。

本地或 CI 执行迁移：
```bash
python3 -m pip install -r requirements-dev.txt
./ci/run_migration.sh
```

迁移机制说明：
- 使用 Alembic 维护版本化 schema，基线文件位于 `alembic/versions/`
- MySQL 环境下会先申请 `GET_LOCK('amsz_schema_migration', 60)` 再执行迁移
- 新增 `runtime_config_revision` 和 `runtime_config_state` 表用于配置版本管控
- baseline migration 会初始化一条默认 active runtime config revision

## Jenkins 与 OpenShift
新增交付物：
- `Jenkinsfile`：安装依赖、执行单元测试、执行功能测试、构建镜像、部署 OpenShift
- `Dockerfile`：默认以 `combined` 模式启动
- `openshift/template.yaml`：Secret、Service、Route、Deployment 一体模板
- `requirements.txt` / `requirements-dev.txt`：给 Jenkins 与镜像构建直接使用
- `.drone.yml`：独立执行 schema migration

OpenShift 部署约定：
- `DATABASE_URL` 和 `API_KEY` 通过 Secret 注入
- `APP_ENV`、`WORKER_QUEUE`、`WORKER_CONCURRENCY` 通过环境变量注入
- `POD_NAME` 和 `WORKER_ID` 通过 Pod metadata 注入环境变量
- 普通运行配置不再通过 ConfigMap 下发，而是从数据库读取

OpenShift 部署示例：
```bash
oc process -f openshift/template.yaml   -p APP_NAME=amsz-task-service   -p APP_ENV=dev   -p IMAGE=image-registry.openshift-image-registry.svc:5000/amsz-dev/amsz-task-service:1   -p REPLICAS=1   -p WORKER_QUEUE=default   -p WORKER_CONCURRENCY=2   -p API_KEY=replace-me   -p DATABASE_URL='mysql+pymysql://user:password@mysql:3306/amsz'   | oc apply -f -
```
