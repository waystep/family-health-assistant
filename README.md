# 🩺 家庭健康助手 Family Health Assistant

<p align="center">
  <a href="#-开源许可"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform">
  <a href="https://github.com/waystep/family-health-assistant/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome"></a>
</p>

<p align="center"><b>微信发条消息，就能给家人记录血压、体重。</b><br>
住家阿姨 / 家人照常用微信发消息 → 自动解析入库 → 回复确认和健康预警 → 每周自动生成健康周报。
数据全部存在自己电脑上,不经过任何第三方服务器。</p>

## ✨ 功能特性

- **聊天即录入**:`外婆 血压145/92 心率78`、`妈妈 体重130斤`、`昨天早上 血压135/85`,自动识别成员、换算斤/公斤、理解"昨天早上"等时间词
- **规则解析兜底,LLM 增强**:内置正则解析覆盖常见说法,**没配大模型也能用**;配了 OpenAI 兼容 LLM(如智谱 GLM)则可理解更自由的表达
- **即时健康预警**:按《中国高血压防治指南》分级(正常/正常高值/1~3级/偏低),超标立刻提醒,并统计"本周第 N 次超标""连续 N 天超标建议就医"
- **照片识别**(可选):血压计/体脂秤拍照发来,视觉大模型提取数值;心率数字漏读时自动启用**七段数码管识别**兜底
- **对话式修正**:`修正 血压138/85`、`撤销`、`今日`、`本周`、`分析`,发错不用去后台改
- **定时提醒 + 周报**:每天早晚推送测量提醒,周日晚上自动生成每位成员的家庭健康周报
- **网页看板**:成员健康卡片、血压趋势图(带 140/90 参考线)、体重曲线、超标记录
- **体检报告归档**:体检报告拍照,自动提取关键指标和结论存档(企业微信通道)

## 🏗 架构

两条可选的接入路线,共用同一个健康网关:

```
路线 A:个人微信(家人零改变)
┌─ 微信(家人/阿姨侧)─┐
│  发消息/转发到监听会话 │
└──────────┬──────────┘
           ▼
微信桥 bridge/wechat_bridge.py   ← 仅 Windows(wxauto UI 自动化)
           │ HTTP
           ▼
┌─────────────────────────────────────────────┐
│  健康网关 app/(FastAPI + SQLite)              │
│  解析 · 分析 · 看板 · 定时任务                  │
│  ├→ data/health.db   全部数据,备份即拷贝        │
│  └→ 待发队列 → 桥取走发送(提醒/周报)            │
└─────────────────────────────────────────────┘

路线 B:企业微信 Bot(跨平台,支持照片识别)
微信 → 企业微信回调 /wecom/callback → wecom-bot/(Flask)
     → 识别/解析/分析 → 回复消息 + 本地 SQLite(可同步飞书多维表格)
```

| | 路线 A:微信桥 | 路线 B:企业微信 Bot |
|---|---|---|
| 平台 | 仅 Windows(依赖微信客户端) | Windows / macOS / Linux |
| 文字录入 | ✅ | ✅ |
| 照片识别血压计 | ❌ | ✅(视觉模型 + 七段码兜底) |
| 修正/撤销/查询命令 | ❌ | ✅ |
| 搭建成本 | 低(双击 bat 即可) | 中(需注册企业微信 + 内网穿透) |
| 详见 | [快速开始](#-快速开始) | [wecom-bot/README.md](wecom-bot/README.md) |

## 🚀 快速开始

### 路线 A:Windows 微信桥(推荐起步,5 分钟打通)

1. 安装 [Python 3.11+](https://www.python.org/downloads/)(勾选 Add to PATH)
2. 双击 `start_gateway.bat` 启动健康网关(首次自动装依赖),浏览器打开 <http://localhost:8900> 添加家庭成员
3. 复制 `.env.example` 为 `.env`,修改 `GATEWAY_TOKEN`,按需配置监听会话与提醒时间
4. 双击 `start_bridge.bat` 启动微信桥(首次自动装 wxauto)
5. 用微信给「文件传输助手」发:`外婆 血压145/92`,收到确认回复即打通 ✅

**Windows 常驻要点**

- 电源设置:永不睡眠、不锁屏(微信桥依赖微信客户端窗口)
- 开机自启:任务计划程序 → 创建基本任务 → 启动两个 bat
- 建议注册微信小号登录 Windows 微信客户端做桥,主号零风险
- 阿姨的使用方式:让她照常微信发你,你**转发**到「文件传输助手」即可;熟练后可让她直接加小号发

### 路线 B:macOS / Linux(网关本身跨平台)

```bash
pip install -r requirements.txt
./start_gateway.sh                                   # 网关,http://localhost:8900
python bridge/test_client.py "外婆 血压145/92"         # 无微信也能测核心链路
```

需要完整的微信收发请走[路线 B:企业微信 Bot](wecom-bot/README.md)(约 20 分钟配置,支持照片识别)。

## ⚙️ 配置(.env)

复制 `.env.example` 为 `.env` 后修改:

| 变量 | 说明 | 默认 |
|---|---|---|
| `GATEWAY_TOKEN` | 接口令牌(桥和 API 调用需携带) | change-me-please |
| `PORT` | 网关端口 | 8900 |
| `MONITOR_CHATS` | 监听哪些微信会话,逗号分隔 | 文件传输助手 |
| `TARGET_CHAT` | 提醒/周报发到哪个会话 | 文件传输助手 |
| `REMINDER_TIMES` | 每日提醒时间,逗号分隔,留空关闭 | 08:00,20:00 |
| `REPORT_WEEKDAY` / `REPORT_TIME` | 周报:周几(0=周一..6=周日)+ 时间 | 6 / 20:30 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenAI 兼容文本模型(自由表达兜底解析) | 空 |
| `LLM_VISION_MODEL` | 视觉模型(照片识别) | 空 |

任何 OpenAI 兼容接口均可。智谱示例:`LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`,模型如 `glm-4-flash` / 视觉 `glm-4v-flash`(以你账号可用模型为准)。

企业微信 Bot 的额外配置见 [`wecom-bot/.env.example`](wecom-bot/.env.example)。

## 💬 使用示例

```
外婆 血压145/92 心率78        → ⚠️ 外婆 血压 1级偏高(145/92)…
妈妈 体重130斤                → ✅ 已记录 妈妈 体重 65.0kg
昨天早上 血压135/85           → ✅ 已补记昨天早上的血压
修正 血压138/85 心率76        → 修改最近一条记录(企微 Bot)
撤销                          → 删除最近一条记录(企微 Bot)
今日 / 本周 / 分析 / 帮助      → 查询与 AI 分析(企微 Bot)
```

## 📁 项目结构

```
├── app/                    健康网关(FastAPI)
│   ├── main.py             入口:定时任务、看板路由
│   ├── models.py           Member / Reading / Outbox / ProcessedMsg
│   ├── nlp/parser.py       规则解析(正则,离线可用)
│   ├── nlp/llm.py          LLM 兜底解析(OpenAI 兼容)
│   ├── services/ingest.py  录入 + 预警分析
│   ├── services/analysis.py 周报与统计
│   ├── routers/            Web 看板 + REST API(/ingest /outbox …)
│   └── templates/ static/  看板页面
├── bridge/
│   ├── wechat_bridge.py    Windows 微信桥(wxauto)
│   └── test_client.py      无微信测试客户端
├── wecom-bot/              企业微信 Bot(照片识别/修正命令/周报)
│   └── app/                handlers · vision · seven_seg · chart · feishu …
├── data/                   运行时生成:health.db(SQLite)、images/
├── start_gateway.bat/.sh   启动网关
└── start_bridge.bat        启动微信桥(仅 Windows)
```

## 🔒 数据与隐私

- 所有数据存本地 `data/health.db`(SQLite),备份即拷贝此文件;照片存 `data/images/`
- 不经过任何第三方服务器(LLM 解析除外,且仅发送待解析的文本/图片)
- 回复中的分析仅供参考,不构成医疗建议;血压分级依据《中国高血压防治指南》常用界值(≥140/90)

## 🗺 路线图

- [ ] 微信测试号(公众号沙箱)+ 内网穿透版通道,摆脱 UI 自动化
- [ ] 企微 Bot 定时主动推送:早/晚测量提醒、周报
- [ ] 住院记录结构化录入(`住院 2026-03-01~03-10 XX医院 诊断…`)
- [ ] 用药提醒、体检报告趋势对比
- [ ] 常驻部署方案整理(Mac mini / Mac Studio + launchd)

## 🤝 参与贡献

欢迎 Issue 和 PR!提交前请:

1. 从 `main` 拉出功能分支
2. 保持改动聚焦,一次 PR 解决一件事
3. 涉及新配置时同步更新 `.env.example` 与 README

更多细节见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 📄 开源许可

[MIT](LICENSE) © 2026 waystep
