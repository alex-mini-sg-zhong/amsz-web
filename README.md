# amsz-web

一个支持“同一套代码，两套启动逻辑”的任务执行服务骨架：
- `api` 模式：提供 FastAPI 接口
- `worker` 模式：从数据库领取并执行任务

## 设计特点
- 单一代码库复用同一套领域模型、DAO、服务层
- MySQL 兼容，测试默认用 SQLite
- 无 Redis / MQ，使用数据库租约机制领取任务
- 支持任务状态查询、取消、重试、执行事件记录
- 内置简单 API Key 认证中间件

## 安装
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 环境变量
```bash
export DATABASE_URL="mysql+pymysql://user:password@127.0.0.1:3306/amsz"
export API_KEY="replace-me"
export WORKER_ID="worker-1"
export POD_NAME="pod-1"
```

开发环境也可直接使用默认 SQLite：
```bash
export DATABASE_URL="sqlite+pysqlite:///./amsz.db"
```

## 启动 API
```bash
python -m app.main api
```

## 启动 Worker
```bash
python -m app.main worker --queue default --concurrency 2
```

## 示例请求
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tasks" \
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
pytest
```
