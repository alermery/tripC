# 小C助手

小C助手是一个面向旅行规划场景的智能对话系统。项目采用 FastAPI 后端和原生 HTML/CSS/JavaScript 前端，提供天气查询、地图导航、旅行规划、多轮会话、行程备注、RAG 知识库上传与 WebSocket 流式回复等功能。

代码中的核心语言模型采用阿里千问系列模型，文本嵌入模型为 Ollama 本地部署的 `nomic-embed-text`。

## 核心功能

- 天气智能体：调用和风天气 API，生成逐日天气、出行风险和季节安全提示。
- 地图智能体：调用高德地图 API，支持地理编码、浏览器定位、驾车路径规划和周边酒店/餐饮搜索。
- 旅行规划智能体：基于 LangChain Agent 和 ReAct 思路，整合天气、地图、套餐、预算、风俗、向量检索和 RAG 知识库信息。
- RAG 知识库：支持管理员上传 `.txt`、`.csv`、`.xlsx` 文件；套餐表写入 Neo4j 与 Chroma，通用文本写入 `rag_kb` 向量库。
- 用户与会话：支持注册、登录、管理员登录、JWT 鉴权、历史会话保存和同会话上下文恢复。
- 前端交互：支持 Markdown 渲染、DOMPurify 安全过滤、流式输出、工具调用进度提示、停止生成、定位、可编辑行程备注和夜间模式。

## 目录结构

```text
小C助手/
├── backend/
│   ├── .env                         # 本地环境变量，不提交到仓库
│   ├── requirements.txt             # Python 依赖
│   └── app/
│       ├── main.py                  # FastAPI 应用入口、路由挂载、启动初始化
│       ├── config.py                # 环境变量与运行配置
│       ├── db.py                    # SQLAlchemy 引擎与会话工厂
│       ├── security.py              # 密码哈希与 JWT 编解码
│       ├── api/                     # REST API 与 WebSocket 路由
│       ├── agents/                  # 天气、地图、旅行规划智能体
│       ├── services/                # 业务服务、HTTP 封装、上下文增强、向量库封装
│       ├── tools/                   # LangChain 工具函数
│       ├── rag/                     # RAG 文件摄入与持久化
│       ├── models/                  # SQLAlchemy ORM 模型
│       ├── schemas/                 # Pydantic 请求/响应模型
│       └── data/                    # 城市代码、风俗等静态数据
├── frontend/
│   ├── index.html                   # 主聊天界面
│   ├── login.html                   # 登录页
│   ├── register.html                # 注册页
│   ├── admin-login.html             # 管理员登录页
│   ├── rag.html                     # RAG 管理页
│   ├── main.js                      # 聊天、WebSocket、历史和定位逻辑
│   ├── theme.js                     # 日间/夜间主题切换与持久化
│   ├── auth.js                      # 登录注册逻辑
│   ├── admin-login.js               # 管理员登录逻辑
│   ├── common.js                    # 通用前端工具函数
│   ├── style.css                    # 页面样式
│   ├── vendor/                      # marked.js 与 DOMPurify
│   └── assets/                      # Logo 等静态资源
├── tests/                           # 基础测试
├── .gitignore
└── README.md
```

## 环境要求

- Python 3.11
- PostgreSQL
- Neo4j
- Ollama，并拉取 `nomic-embed-text`
- 阿里云百炼 DashScope API Key
- 高德地图 Web 服务 Key
- 和风天气 API Key

## 后端配置

在 `backend/.env` 中配置运行所需变量。示例：

```env
DASHSCOPE_API_KEY=your_dashscope_key
PG_DSN=postgresql+psycopg2://postgres:postgres@localhost:5432/xiaoc_assistant
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
JWT_SECRET_KEY=replace_with_a_random_secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_admin_password
QWEATHER_HOST=your_qweather_host
QWEATHER_API_KEY=your_qweather_key
AMAP_API_KEY=your_amap_key
APP_ENV=development
CORS_ORIGINS=http://127.0.0.1:5500,http://localhost:5500
REQUEST_TIMEOUT_SECONDS=10
REQUEST_RETRY_COUNT=3
REQUEST_RETRY_BACKOFF=0.25
```

说明：

- `JWT_SECRET_KEY` 现在必须显式配置，未配置时服务会直接拒绝启动。
- `ADMIN_PASSWORD` 不为空时，后端启动会创建或同步管理员账号。
- 开发环境下后端会自动创建缺失的数据表，并执行轻量迁移。
- RAG 上传接口只允许管理员 JWT 访问。
- `CORS_ORIGINS` 用逗号分隔多个前端来源地址。

## 启动方式

安装依赖：

```bash
pip install -r backend/requirements.txt
```

启动后端：

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd frontend
python -m http.server 5500
```

访问地址：

- 前端：`http://127.0.0.1:5500`
- API 文档：`http://127.0.0.1:8000/docs`
- WebSocket：`ws://127.0.0.1:8000/ws/chat`

## RAG 上传与查询

1. 使用管理员账号登录 `frontend/admin-login.html`。
2. 进入 `frontend/rag.html` 上传文件。
3. 支持格式为 `.txt`、`.csv`、`.xlsx`，单文件最大 25MB。
4. 上传接口会立即返回 `task_id`，随后可通过任务接口查询处理状态。
5. 包含 `departure`、`detail`、`price` 等字段的表格会被识别为旅行套餐表，写入 Neo4j 和 Chroma `travel_deals` 集合。
6. 普通文本或无法识别为套餐表的表格会写入 Chroma `rag_kb` 集合。
7. 当多个上传文件同时命中时，`rag_kb` 和 `travel_deals` 都会优先采用最近上传文件中的结果。

## 常见问题

- 如果 WebSocket 连接后立即断开，优先检查登录 token 是否过期，以及后端 `/ws/chat` 是否正常启动。
- 如果 RAG 检索为空，检查 Ollama 是否运行、`nomic-embed-text` 是否可用，以及 Chroma 目录是否可写。
- 如果地图或天气工具失败，检查 `AMAP_API_KEY`、`QWEATHER_HOST` 和 `QWEATHER_API_KEY`。
- 如果管理员上传返回 403，确认使用的是 `/auth/admin/login` 签发的管理员 token。
- 如果 Chroma 查询结果仍然偏旧，可以重新上传旧文件，使其补齐新的 `uploaded_at` 元数据。
