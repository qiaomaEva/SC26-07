# Literature RAG Agent

个人文献检索 + 混合检索 RAG 问答助手。

技术路线与边界见 [`docs/literature-rag-agent-tech-plan.md`](docs/literature-rag-agent-tech-plan.md)。

## 功能（MVP）

1. 三栏工作台：对话历史 | 知识库（文件夹） | 问答助手
2. 在线检索论文（Semantic Scholar / arXiv 回退）并导入；默认下载开放获取 PDF 做全文索引
3. 文件夹管理 + 本地 PDF 上传
4. BM25 + 向量混合检索（RRF）；可按勾选文件夹/论文限定范围（未勾选=全库）
5. 对话历史落库；可在对话中说「帮我找 XXX 相关论文」
6. 问答技能：文献综述 / 方法对比 / 讲懂这篇（基于勾选范围）+ 空态猜你想问
7. 回答生成期间可点击「停止」或按 `Esc` 取消当前任务

## 用 GitHub Desktop 发布（推荐）

本地仓库已初始化在：

`D:\anything\literature-rag-agent`

1. 打开 **GitHub Desktop**
2. **File → Add local repository…**，选择上面的路径
3. 若提示还没有 commit：在 Desktop 里写一句 summary（或等本机已有首次 commit）后 **Commit**
4. 点 **Publish repository**
   - 建议仓库名：`literature-rag-agent`
   - 可勾选 Private
5. 发布后即可在 https://github.com/qiaomaEva 下看到该仓库

> 注意：`backend/.env` 已被 `.gitignore` 忽略，不要把 API Key 提交上去。只提交 `.env.example`。

## 环境准备

### 1. Conda 环境

```bash
cd backend
conda env create -f environment.yml
conda activate literature-rag
```

若环境已存在，可更新依赖：

```bash
conda activate literature-rag
pip install -r requirements.txt
```

### 2. 配置后端环境

```bash
cd backend
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

编辑 `backend/.env`。模型 API Key、Base URL 和模型名可以在前端右上角的「模型设置」中填写并测试；前端未填写时，后端使用以下配置作为回退：

- `OPENAI_API_KEY`：填你的 DeepSeek API Key  
- `OPENAI_API_BASE=https://api.deepseek.com`  
- `OPENAI_CHAT_MODEL=deepseek-chat`（也可换成 `deepseek-v4-flash` / `deepseek-v4-pro`）  
- `OPENAI_TIMEOUT_SECONDS=30`：模型请求超时秒数；前端模型设置可覆盖该值
- `EMBEDDING_PROVIDER=local`：**DeepSeek 不提供向量接口**，默认用本地 embedding（按下方命令初始化）
- 可选：`SEMANTIC_SCHOLAR_API_KEY`

前端填写的 API Key 仅保存在当前浏览器会话，并随聊天请求临时发送到后端，不写入 `.env`、数据库或聊天记录。

若使用默认本地 embedding，请在第一次导入论文前显式初始化模型：

```bash
cd backend
python -m app.index.prepare_embeddings
```

只检查当前状态、且不触发下载：

```bash
python -m app.index.prepare_embeddings --check
```

### 3. 前端依赖

```bash
cd frontend
npm install
```

## 启动

终端 1 — 后端：

```bash
conda activate literature-rag
cd backend
uvicorn app.main:app --reload --port 8888
```

终端 2 — 前端：

```bash
cd frontend
npm run dev
```

- 前端：http://localhost:5173
- API / Swagger：http://localhost:8888/docs

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/search` | 关键词搜论文 |
| POST | `/library/import` | 导入并建索引 |
| GET | `/library` | 已导入列表 |
| POST | `/chat` | 库内 RAG 问答 |
| DELETE | `/chat/tasks/{request_id}` | 取消进行中的流式聊天任务 |
| GET | `/embedding/status` | 检查 embedding 配置与本地模型状态 |
| GET | `/health` | 健康检查 |

## 验证

后端：

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

前端：

```bash
cd frontend
npm run lint
npm run build
```
