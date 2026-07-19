# 个人文献检索与 RAG 问答助手 — 技术路线与边界说明

> 版本：v0.2  
> 定位：为期约 3 天的 vibe coding / 课程实训项目  
> 一句话目标：用户给关键词 → 检索并收藏论文 → 建成个人文献库 → 用混合检索 RAG 回答问题（带引用）  
> 前端：npm 生态（Vite + React + TypeScript），后端 FastAPI 分离部署

---

## 1. 项目目标

### 1.1 要做成什么

做一个**个人文献助手**，支持：

1. 通过关键词从学术数据源检索相关论文；
2. 将选中论文（元数据 + 摘要，可选 PDF 全文）导入本地文献库；
3. 对入库文本建立索引，支持**混合检索（BM25 + 向量）**；
4. 提供基于文献库的问答助手，回答时**必须带论文引用**。

### 1.2 明确不做成什么

本项目**不是**：

- 自动生成完整、可投稿的 literature review 长文；
- 面向多租户的商业化学术搜索引擎；
- 依赖爬取 Google Scholar 的不稳定爬虫系统；
- 全自动多 Agent「科研团队」仿真（可作为后期扩展，不作为 MVP）。

---

## 2. 用户故事与核心流程

### 2.1 主用户故事

> 作为研究者/学生，我输入研究方向关键词，系统帮我找到相关论文并保存到个人库；之后我可以针对库内文献提问，系统基于检索到的内容回答，并标明引用了哪些论文。

### 2.2 端到端流程

```text
[采集] 关键词 → 调用学术 API → 论文候选列表 → 用户确认导入
   ↓
[解析] 提取 title / authors / year / abstract / url（PDF 可选）
   ↓
[入库] 文本切分 (chunk) → Embedding → 向量索引 + BM25 索引
   ↓
[问答] 用户提问 →（可选查询改写）→ 混合检索 → LLM 生成 → 返回答案 + 引用
```

---

## 3. 功能范围（P0 / P1 / P2）

### 3.1 P0 — MVP（必须完成）

| 编号 | 功能 | 验收标准 |
|------|------|----------|
| P0-1 | 关键词检索论文 | 输入 query，返回结构化论文列表（标题、作者、年份、摘要、链接） |
| P0-2 | 导入个人库 | 可将选中论文写入本地存储，列表可查询 |
| P0-3 | 索引构建 | 对摘要（及已导入全文）完成 chunk + 向量化 + BM25 索引 |
| P0-4 | 混合检索 | 同一 query 能融合 BM25 与向量结果，返回 Top-K chunks |
| P0-5 | RAG 问答 | `/chat` 基于库内文献回答，答案中含引用（论文标题 + 年份，最好含 paper_id） |
| P0-6 | FastAPI 接口 | 核心能力均可通过 API 调用；Swagger 可演示 |
| P0-7 | npm 前端（最小可用） | 能完成「搜索 → 勾选导入 → 库内列表 → 问答（含引用展示）」主路径 |

### 3.2 P1 — 有时间再做

| 编号 | 功能 | 说明 |
|------|------|------|
| P1-1 | 查询改写 | 将口语问题改写成更适合检索的 query |
| P1-2 | 相似论文 | 以某篇已入库论文为种子，返回库内或在线 related papers |
| P1-3 | 相关工作小结 | 对当前检索结果生成分段小结（非完整综述） |
| P1-4 | 前端增强 | 流式输出、加载态优化、引用点击跳转原文、基础 Markdown 渲染 |
| P1-5 | 引用质检 | 检查回答是否出现未检索到的文献幻觉 |

### 3.3 P2 — 明确延期（不做进本次范围）

- Google Scholar 官方级体验 / 大规模爬虫
- 复杂 PDF 版面解析、公式/表格结构化
- 多用户登录、权限、云端同步、复杂设计系统
- Next.js SSR / 服务端渲染、组件库重度定制、移动端 App
- 自动撰写完整综述并管理参考文献格式（GB/T 7714 等）
- 评估平台、大规模标注数据集
- Supervisor 多 Agent 辩论式科研流程

---

## 4. 技术路线

### 4.1 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│          Frontend (npm: Vite + React + TypeScript)          │
│          页面：搜索导入 / 我的文献库 / 问答                   │
└─────────────────────────────┬───────────────────────────────┘
                              │ HTTP (JSON)  开发期 Vite 代理
┌─────────────────────────────▼───────────────────────────────┐
│                     FastAPI 应用层                           │
│  /search  /library/*  /chat  /similar(optional)             │
│  + CORS（允许本地前端源）                                      │
└───────┬─────────────────────┬─────────────────┬─────────────┘
        │                     │                 │
        ▼                     ▼                 ▼
┌───────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ Ingest 模块    │   │ Index / RAG     │   │ Orchestration    │
│ 学术 API 客户端 │   │ 切分/索引/检索   │   │ LCEL 或 LangGraph│
└───────┬───────┘   └────────┬────────┘   └────────┬─────────┘
        │                    │                     │
        ▼                    ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ SQLite        │   │ Chroma (向量)    │   │ LLM / Embedding  │
│ 论文元数据     │   │ + BM25 索引      │   │ API              │
└───────────────┘   └─────────────────┘   └──────────────────┘
```

### 4.2 技术选型（冻结）

| 层级 | 选型 | 备注 |
|------|------|------|
| 后端语言 | Python 3.11+ | |
| API | FastAPI + Uvicorn | |
| 前端 | **npm + Vite + React + TypeScript** | 前后端分离；不用 Streamlit/Gradio |
| 前端请求 | `fetch` 或 `axios` | 封装一个 `api.ts` 即可 |
| 前端路由 | React Router（可选） | 两三个页面，也可用简单 Tab 切换省事 |
| UI | 原生 CSS / 轻量方案即可 | 不做大型组件库深度定制；可用极简样式 |
| 学术数据源（主） | **Semantic Scholar API** 或 **arXiv API** | 二选一作为主源，另一个可选 |
| 学术数据源（不选作主路径） | Google Scholar 直爬 | 无稳定官方 API，易封禁，不纳入 P0 |
| 若必须 Google Scholar | SerpAPI 等第三方 | 仅 P1/P2，需密钥与预算 |
| 元数据存储 | SQLite | 单机足够 |
| 向量库 | Chroma（本地持久化） | 开工最快；后续可换 Qdrant |
| 稀疏检索 | `rank_bm25` | 与向量结果融合 |
| Embedding / LLM | 项目可用的兼容 API（如 OpenAI 兼容接口） | 具体模型名在配置中冻结 |
| 编排 | **问答链路统一用一种**：优先 **LCEL**；若做 P1 多步再升 **LangGraph** | 禁止同一链路两套编排混用 |
| PDF（可选） | pypdf / pymupdf | 仅提取文本，不做版面还原 |

### 4.2.1 前端页面范围（冻结）

MVP 只做 **3 个界面**（可用 Tab，不一定要复杂路由）：

| 页面 | 作用 | 调用接口 |
|------|------|----------|
| 搜索 | 输入关键词，展示候选论文，勾选后导入 | `POST /search`, `POST /library/import` |
| 文献库 | 展示已导入论文列表 | `GET /library` |
| 问答 | 提问、展示回答与引用列表 | `POST /chat` |

前端**不做**：登录注册、权限、暗黑主题体系、富文本编辑器、虚拟滚动优化论文百万级列表。

### 4.3 编排层用在哪里

编排（LCEL / LangGraph）**只用于问答及相关多步推理**，不用于普通入库脚本。

| 模块 | 是否用编排 | 说明 |
|------|------------|------|
| 调学术 API、去重、写 SQLite | 否 | 普通 Python 异步/同步函数 |
| chunk、embedding、建索引 | 否 | 批处理流水线 |
| `/chat`：检索 → 组装 prompt → LLM | 是（LCEL 即可） | 标准 RAG 链 |
| 查询改写 / 检索不足重试 / 引用质检 | 是（建议 LangGraph） | 有分支与状态 |

**选型规则：**

- MVP 只有直线 RAG → 使用 **LCEL**；
- 一旦出现「改写 → 检索 → 判断是否够用 → 再生成 → 质检」→ 升级为 **LangGraph**，并移除并行的 LCEL 同构实现，避免大杂烩。

### 4.4 混合检索方案

对每个 chunk 同时支持：

1. **稠密检索**：query embedding ↔ chunk embedding（余弦相似度 / 向量库默认距离）；
2. **稀疏检索**：BM25(query, chunk_text)；
3. **融合**：RRF（Reciprocal Rank Fusion）或简单加权求和（需在实现里固定一种，默认 **RRF**）；
4. **截断**：取融合后 Top-K（默认 K=6）作为 LLM 上下文。

### 4.5 RAG 生成约束

- LLM 只能依据检索到的 chunk 作答；不知道就明确说「当前文献库中未找到足够信息」。
- 回答必须附 **citations** 列表，字段至少包括：`paper_id`, `title`, `year`。
- 禁止编造未入库/未检索到的论文标题。

---

## 5. 数据模型（最小集）

### 5.1 `papers`（SQLite）

| 字段 | 类型 | 说明 |
|------|------|------|
| paper_id | TEXT PK | 数据源 ID 或本地生成 ID |
| title | TEXT | |
| authors | TEXT/JSON | 作者列表序列化 |
| year | INTEGER | 可空 |
| abstract | TEXT | 可空 |
| url | TEXT | 落地页或 PDF 链接 |
| source | TEXT | `semanticscholar` / `arxiv` 等 |
| created_at | TEXT | ISO 时间 |

### 5.2 `chunks`（SQLite 或与向量库 metadata 对齐）

| 字段 | 类型 | 说明 |
|------|------|------|
| chunk_id | TEXT PK | |
| paper_id | TEXT FK | |
| text | TEXT | chunk 正文 |
| chunk_index | INTEGER | 篇内序号 |
| token_est | INTEGER | 可选，估算长度 |

向量存储于 Chroma，metadata 中冗余 `paper_id`, `title`, `year`, `chunk_id`，便于引用回溯。

### 5.3 切分策略（冻结默认值）

- 优先切 **abstract**；若用户导入 PDF 全文，再切全文。
- 默认：`chunk_size ≈ 500–800 字符`，`overlap ≈ 100–150`（实现时选一组常数写进配置，不随手改）。
- 一篇论文至少保证 **abstract 作为一个（或少数几个）chunk** 入库，避免只有标题无法问答。

---

## 6. API 草案（P0）

### 6.1 `POST /search`

请求：

```json
{
  "query": "graph neural networks recommendation",
  "limit": 10
}
```

响应：论文候选列表（未入库也可返回）。

### 6.2 `POST /library/import`

请求：

```json
{
  "papers": [
    {
      "paper_id": "...",
      "title": "...",
      "authors": ["..."],
      "year": 2024,
      "abstract": "...",
      "url": "...",
      "source": "semanticscholar"
    }
  ]
}
```

行为：写入 SQLite + 建立/更新检索索引。

### 6.3 `GET /library`

返回已导入论文列表。

### 6.4 `POST /chat`

请求：

```json
{
  "question": "这些论文在冷启动问题上有哪些常见做法？",
  "top_k": 6
}
```

响应：

```json
{
  "answer": "...",
  "citations": [
    {"paper_id": "...", "title": "...", "year": 2023}
  ],
  "retrieved_chunks": []
}
```

`retrieved_chunks` 可在 Debug 模式返回，Demo 时可精简。

### 6.5 `POST /similar`（P1）

以 `paper_id` 返回相似论文。

---

## 7. 目录结构建议

```text
literature-rag-agent/
├── README.md
├── docs/
│   └── literature-rag-agent-tech-plan.md   # 本文档
├── backend/                         # Python / FastAPI
│   ├── pyproject.toml / requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 + CORS
│   │   ├── api/
│   │   │   ├── routes_search.py
│   │   │   ├── routes_library.py
│   │   │   └── routes_chat.py
│   │   ├── ingest/
│   │   │   ├── s2_client.py     # Semantic Scholar 或 arxiv_client.py
│   │   │   └── importer.py
│   │   ├── index/
│   │   │   ├── chunking.py
│   │   │   ├── embedder.py
│   │   │   ├── bm25_store.py
│   │   │   └── hybrid.py
│   │   ├── rag/
│   │   │   ├── chain.py         # LCEL 版；或 graph.py (LangGraph)
│   │   │   └── prompts.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── sqlite.py
│   │   └── core/
│   │       └── config.py
│   ├── data/
│   │   ├── app.db
│   │   └── chroma/
│   └── tests/
│       └── test_hybrid_smoke.py
└── frontend/                        # npm / Vite / React
    ├── package.json
    ├── vite.config.ts               # 开发代理 /api → FastAPI
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/client.ts            # 封装后端请求
        ├── pages/
        │   ├── SearchPage.tsx
        │   ├── LibraryPage.tsx
        │   └── ChatPage.tsx
        └── components/
            ├── PaperCard.tsx
            └── CitationList.tsx
```

### 7.1 本地开发启动约定

```bash
# 终端 1：后端
cd backend
uvicorn app.main:app --reload --port 8888

# 终端 2：前端
cd frontend
npm install
npm run dev          # 默认 Vite :5173，代理到 :8888
```

`vite.config.ts` 建议代理示例：

```ts
server: {
  proxy: {
    "/api": {
      target: "http://127.0.0.1:8888",
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ""),
    },
  },
}
```

后端需启用 CORS（至少允许 `http://localhost:5173`）。前后端字段名与本文 API 草案保持一致，前端不自行发明另一套命名。

---

## 8. 边界与约定（提前冻结）

### 8.1 数据源边界

| 事项 | 约定 |
|------|------|
| 主数据源 | Semantic Scholar **或** arXiv，开写前在 README 冻结一个 |
| Google Scholar | **不作为 P0**；禁止作为唯一数据依赖 |
| 成功率 | 外部 API 失败时返回明确错误，不静默伪造论文 |
| 版权 | 默认只存元数据 + 摘要；全文 PDF 仅在用户显式提供/合法可取时入库 |

### 8.2 检索与问答边界

| 事项 | 约定 |
|------|------|
| 问答范围 | **仅基于已导入文献库**（P0）；未入库的在线结果不直接进回答 |
| 搜索 vs 问答 | `/search` 面向「发现论文」；`/chat` 面向「库内问答」，职责分离 |
| 幻觉 | 无证据则承认不知道；不得编造引用 |
| 语言 | 问答应支持中文问题；库内文献多为英文时，允许中文回答 + 英文引用 |

### 8.3 技术边界

| 事项 | 约定 |
|------|------|
| 编排框架 | 同一问答链路只保留 LCEL **或** LangGraph 一套 |
| 向量库 | MVP 固定 Chroma 本地目录，不做分布式 |
| 鉴权 | MVP 无多用户；单机本地信任模型 |
| 配置 | 密钥只放 `.env`，不进仓库；提供 `.env.example` |
| 前端框架 | 固定 **Vite + React + TypeScript（npm）**；不用 Next.js / Streamlit |
| 前后端通信 | JSON over HTTP；开发期用 Vite proxy，避免浏览器跨域纠缠 |
| 前端状态 | 组件内 `useState` 足够；不上 Redux/Zustand，除非真出现全局状态痛点 |
| UI 完成度 | 能走通主路径即可；不追求设计系统与动效 |

### 8.4 产品叙事边界

| 可以说 | 不要说 |
|--------|--------|
| 个人文献库 + 混合检索 RAG 问答 | 「全自动文献综述生成器」 |
| 支持关键词发现论文并收藏 | 「替代 Google Scholar」 |
| 回答带引用，便于写相关工作 | 「保证学术结论正确 / 可直接投稿」 |

### 8.5 评估边界（解决「没有大量数据怎么判断好不好」）

不依赖大规模标注集，采用**手工小样本验收**：

1. 自建 **1 个主题**（如你们熟悉的方向），导入 **8–15 篇**论文；
2. 准备 **10 个问题**，分为三类：
   - 事实型（某篇摘要里有的信息）；
   - 对比型（两篇之间差异）；
   - 拒答型（库中明显没有的信息，应拒绝编造）；
3. 人工检查：
   - 引用是否真实存在于检索结果；
   - 拒答型是否仍瞎编；
   - 对比型是否明显跑题。

通过标准（建议）：10 题中 **≥7 题可接受**，且 **拒答型不得幻觉引用**。

---

## 9. 三天实施计划（建议）

### Day 1 — 搜得到、存得下

- [ ] 选好数据源并打通 search client
- [ ] SQLite `papers` 表 + `/search` + `/library/import` + `/library`
- [ ] 用真实关键词跑通「搜 10 篇 → 导入 5 篇」

### Day 2 — 检得到、答得出

- [ ] chunk + embedding + Chroma
- [ ] BM25 + RRF 混合检索
- [ ] LCEL（或等价清晰流水线）实现 `/chat` + citations
- [ ] 用 5 个问题做手工验收

### Day 3 — 能演示、可交代

- [ ] npm 前端三页打通：搜索导入 / 文献库 / 问答（含引用展示）
- [ ] 配好 CORS + Vite 代理；补齐错误处理、`.env.example`、README
- [ ] 选做 P1 之一：查询改写 / 相似论文 / 前端 Markdown 与加载态
- [ ] 准备 Demo 故事：一个主题 → 导入 → 三问三答（含一问拒答）

---

## 10. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| Google Scholar 难稳定获取 | 采集失败 | 主路径改用 Semantic Scholar / arXiv |
| 仅有摘要信息量不足 | 问答偏浅 | Demo 选摘要信息较完整的论文；P1 再加 PDF |
| LLM 编造引用 | 可信度崩盘 | prompt 约束 + 只允许引用 retrieved 集合；可选质检节点 |
| 3 天范围膨胀 | 做不完 | 严格按 P0；综述长文、多 Agent、Next 重度前端一律 P2 |
| 前后端联调卡住 | Demo 失败 | 先 Swagger 验 API，再接前端；代理与 CORS 第一天就配好 |
| 编排双栈混用 | 难维护 | 开写前锁定 LCEL 或 LangGraph |

---

## 11. 开写前检查清单（DoD 前置）

在写第一行业务代码前，团队确认：

1. **主数据源**：Semantic Scholar / arXiv（圈定一个）；
2. **编排方式**：LCEL（MVP）或直接 LangGraph；
3. **LLM / Embedding** 模型名与 API Base；
4. **前端**：确认 Node/npm 可用，按 `frontend/` + Vite React TS 脚手架初始化；
5. **Demo 主题**与拟导入的论文领域；
6. 所有人读过本文 **§3 功能范围** 与 **§8 边界约定**。

---

## 12. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-07-17 | 初稿：技术路线、P0/P1/P2、边界与三天计划 |
| v0.2 | 2026-07-17 | 前端冻结为 npm + Vite + React + TS；调整目录、P0-7 与联调约定 |
