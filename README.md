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
- 支持任务状态查询、取消、重试、执行事件记录
- 内置简单 API Key 认证中间件

## 安装
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## 环境变量
```bash
export DATABASE_URL="mysql+pymysql://user:password@127.0.0.1:3306/amsz"
export API_KEY="replace-me"
export POD_NAME="pod-1"
export WORKER_ID="worker-1"
```

开发环境也可直接使用默认 SQLite：
```bash
export DATABASE_URL="sqlite+pysqlite:///./amsz.db"
```

如果 `WORKER_ID` 未设置，系统会自动使用 `${POD_NAME}-worker`。

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

## 示例请求
```bash
curl -X POST "http://127.0.0.1:8200/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-me" \
  -d '{
    "task_type": "sleep.echo",
    "queue_name": "default",
    "payload": {
      "seconds": 3,
      "echo": "hello"
    }
  }'
```

## 运行测试
```bash
.venv/bin/python -m pytest
```

## 运行单元测试
```bash
./ci/run_unittest.sh
```

## 运行功能测试
```bash
./ci/run_functionaltest.sh
```

## Jenkins 与 OpenShift
新增交付物：
- `Jenkinsfile`：安装依赖、执行单元测试、执行功能测试、构建镜像、部署 OpenShift
- `Dockerfile`：默认以 `combined` 模式启动
- `openshift/template.yaml`：ConfigMap、Secret、Service、Route、Deployment 一体模板
- `requirements.txt` / `requirements-dev.txt`：给 Jenkins 与镜像构建直接使用

Jenkins 约定的凭据 ID：
- `image-registry-creds`
- `openshift-token`
- `amsz-api-key`
- `amsz-database-url`

OpenShift 部署示例：
```bash
oc process -f openshift/template.yaml \
  -p APP_NAME=amsz-task-service \
  -p APP_ENV=dev \
  -p IMAGE=image-registry.openshift-image-registry.svc:5000/amsz-dev/amsz-task-service:1 \
  -p LOG_LEVEL=INFO \
  -p REPLICAS=1 \
  -p WORKER_QUEUE=default \
  -p WORKER_CONCURRENCY=2 \
  -p API_KEY=replace-me \
  -p DATABASE_URL='mysql+pymysql://user:password@mysql:3306/amsz' \
  | oc apply -f -
```
