# 项目开发规范

## 技术栈
- 后端：Python FastAPI
- 数据库：PostgreSQL

## 代码规范
- 使用 4 空格缩进
- 每行最多 100 字符
- 所有函数必须有类型注解
- 每个API处理流程必须有清晰的日志

## 测试要求
- 新功能必须包含测试
- 使用 pytest 运行测试

## Git 提交
- 使用 Conventional Commits 格式
- 提交信息描述"为什么"

## Review guidelines
- Don't log PII
- Verify authentication middleware
- Check for SQL injection