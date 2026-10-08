# 贡献指南

感谢关注家庭健康助手!欢迎通过 Issue 反馈问题、提出想法,或直接提交 PR。

## 提 Issue

- **Bug**:说明复现步骤、期望行为与实际行为,附上关键日志(注意先抹去 Token、API Key 等敏感信息)
- **功能建议**:描述使用场景 —— 你想在家人的哪条消息流里解决什么问题

## 提交 PR

1. Fork 或从 `main` 拉出功能分支:`git checkout -b feat/xxx`
2. 保持改动聚焦,一次 PR 解决一件事
3. 开发环境:

   ```bash
   pip install -r requirements.txt
   ./start_gateway.sh                                # 启动网关 http://localhost:8900
   python bridge/test_client.py "外婆 血压145/92"      # 无微信验证核心链路
   ```

4. 涉及新配置时,同步更新 `.env.example`(及 `wecom-bot/.env.example`)和 README 的配置表
5. 提交信息用简洁的祈使句,如 `feat: 支持体重补充录入`、`fix: 周报时区偏移`

## 代码约定

- Python 3.11+,类型注解尽量齐全,不做额外格式化配置改动
- 解析相关改动请覆盖常见说法:数字/斤公斤/时间词(昨天早上、今早…)/成员名
- 任何改动不得将用户健康数据发送到本地 SQLite 与所配 LLM 之外的第三方

## 安全

如发现安全问题(如 Token 校验绕过、注入),请勿公开 Issue,联系仓库所有者处理。
