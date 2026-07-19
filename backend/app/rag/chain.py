import asyncio
import json
import re
from typing import Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.db import sqlite as db
from app.db.models import (
    ChatResponse,
    Citation,
    EvidenceSnippet,
    LLMConfig,
    RetrievedChunk,
)
from app.index.hybrid import hybrid_search
from app.ingest.search import search_papers as online_search_papers
from app.rag.progress import ProgressCallback, report
from app.rag.prompts import COMPARE_PROMPT, RAG_PROMPT, SURVEY_SINGLE_PROMPT


def get_chat_model(llm_config: Optional[LLMConfig] = None) -> ChatOpenAI:
    if llm_config:
        api_key = llm_config.api_key
        base_url = llm_config.base_url
        model = llm_config.model
        timeout_seconds = llm_config.timeout_seconds
    else:
        settings = get_settings()
        api_key = settings.openai_api_key
        base_url = settings.openai_api_base
        model = settings.openai_chat_model
        timeout_seconds = settings.openai_timeout_seconds
    if not api_key:
        raise RuntimeError(
            "未配置模型 API Key，请在前端的模型设置中填写，或配置后端 OPENAI_API_KEY。"
        )
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0,
        timeout=timeout_seconds,
    )


def build_context(chunks: list[dict]) -> str:
    blocks: list[str] = []
    for i, c in enumerate(chunks, start=1):
        year = c.get("year")
        year_str = str(year) if year is not None else "n.d."
        blocks.append(
            f"[{i}] paper_id={c.get('paper_id')}\n"
            f"title={c.get('title')} ({year_str})\n"
            f"content={c.get('text')}"
        )
    return "\n\n".join(blocks) if blocks else "(无检索结果)"


# Cap stored snippet length so chat meta stays small but readable
_EVIDENCE_TEXT_MAX = 2400


def _citation_from_chunk(c: dict) -> Citation:
    return Citation(
        paper_id=c.get("paper_id") or "",
        title=c.get("title") or "",
        year=c.get("year"),
    )


def _evidence_from_chunks(chunks: list[dict]) -> list[EvidenceSnippet]:
    """One entry per context block: index 0 ↔ answer marker [1]."""
    from app.ingest.textutil import sanitize_text

    out: list[EvidenceSnippet] = []
    for c in chunks:
        if not c.get("paper_id"):
            continue
        text = sanitize_text(c.get("text") or "").strip()
        if len(text) > _EVIDENCE_TEXT_MAX:
            text = text[: _EVIDENCE_TEXT_MAX - 1] + "…"
        out.append(
            EvidenceSnippet(
                paper_id=c.get("paper_id") or "",
                title=sanitize_text(c.get("title") or ""),
                year=c.get("year"),
                chunk_id=c.get("chunk_id") or "",
                text=text,
                score=float(c.get("score") or 0.0),
            )
        )
    return out


def _citations_from_chunks(chunks: list[dict]) -> list[Citation]:
    """Unique papers (for footer), order of first appearance in evidence."""
    seen: set[str] = set()
    citations: list[Citation] = []
    for c in chunks:
        pid = c.get("paper_id") or ""
        if not pid or pid in seen:
            continue
        seen.add(pid)
        citations.append(_citation_from_chunk(c))
    return citations


def _validate_answer_citations(answer: str, hits: list[dict]) -> tuple[str, list[dict]]:
    """Remove invalid [n] markers and return chunks actually cited by the answer."""
    used_indexes: list[int] = []

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1900 <= number <= 2100:
            return match.group(0)
        index = number - 1
        if index < 0 or index >= len(hits):
            return ""
        if index not in used_indexes:
            used_indexes.append(index)
        return match.group(0)

    normalized = re.sub(r"\[(\d+)\]", replace, answer)
    return normalized, [hits[index] for index in used_indexes]


def _qa_response(answer: str, hits: list[dict]) -> ChatResponse:
    answer, cited_hits = _validate_answer_citations(answer, hits)
    retrieved = [
        RetrievedChunk(
            chunk_id=h["chunk_id"],
            paper_id=h["paper_id"],
            title=h.get("title") or "",
            year=h.get("year"),
            text=h.get("text") or "",
            score=float(h.get("score") or 0.0),
        )
        for h in hits
    ]
    return ChatResponse(
        session_id="",
        intent="qa",
        answer=answer,
        citations=_citations_from_chunks(cited_hits),
        evidence=_evidence_from_chunks(hits),
        retrieved_chunks=retrieved,
    )

# Common Chinese CS terms → English academic keywords (offline fallback)
_TERM_MAP = {
    "基数估计": "cardinality estimation",
    "势估计": "cardinality estimation",
    "基数": "cardinality",
    "代价估计": "cost estimation",
    "代价模型": "cost model",
    "查询优化": "query optimization",
    "查询优化器": "query optimizer",
    "学习型优化器": "learned query optimizer",
    "文本转sql": "text-to-sql",
    "text2sql": "text-to-sql",
    "图神经网络": "graph neural network",
    "推荐系统": "recommender system",
    "检索增强": "retrieval augmented generation",
    "向量检索": "vector retrieval",
}


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _looks_like_search(question: str) -> bool:
    q = question.strip()
    cues = [
        r"帮我找",
        r"找一下",
        r"搜索",
        r"查找",
        r"推荐.*论文",
        r"相关论文",
        r"相关工作",
        r"有没有.*论文",
        r"找.*论文",
        r"find papers?",
        r"search (for )?papers?",
        r"related work",
        r"literature (on|about)",
    ]
    return any(re.search(p, q, flags=re.I) for p in cues)


def _strip_search_noise(text: str) -> str:
    """Remove chatty wrappers; keep the topical core."""
    q = text.strip()
    for _ in range(3):
        nxt = re.sub(
            r"^(请|麻烦|帮我|我想|我要|给我)?(找一下|寻找|查找|搜索|搜一下|推荐|找)\s*",
            "",
            q,
            flags=re.I,
        )
        nxt = re.sub(
            r"(的)?(相关工作|相关论文|综述|文献|论文|papers?|related works?)\s*$",
            "",
            nxt,
            flags=re.I,
        )
        nxt = re.sub(r"^(关于|有关|针对)\s*", "", nxt)
        nxt = nxt.strip(" ?？。.!！,，、:：")
        if nxt == q:
            break
        q = nxt
    return q


def _map_zh_terms(topic: str) -> Optional[str]:
    compact = topic.lower().replace(" ", "")
    for zh, en in sorted(_TERM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if zh in topic or zh.replace(" ", "") in compact:
            return en
    return None


async def _llm_normalize_search(
    question: str, chat_model: ChatOpenAI
) -> tuple[str, str, str]:
    """Returns (intent, topic_display, query_en)."""
    prompt = (
        "你是学术检索查询改写器。根据用户话判断意图，并产出适合论文检索或库内 RAG 的英文检索词。\n"
        "只输出 JSON，不要其它文字：\n"
        '{"intent":"qa|search","topic":"简短中文主题","query_en":"english academic keywords"}\n'
        "规则：\n"
        "- search：用户想找/搜/推荐论文、去网上检索 literature（不是写综述）\n"
        "- qa：对已有文献库提问、总结、对比、写文献综述、讲懂某篇\n"
        "- topic：去掉「帮我找/相关论文」等套话后的主题，如「基数估计」\n"
        "- query_en：无论 qa/search 都给出 2-8 个英文关键词，不要带 find/papers/please\n"
        "- 例：用户「找基数估计的相关工作论文」→ "
        '{"intent":"search","topic":"基数估计","query_en":"cardinality estimation"}\n'
        f"用户：{question}"
    )
    resp = await chat_model.ainvoke(
        [
            SystemMessage(content="只输出合法 JSON。"),
            HumanMessage(content=prompt),
        ]
    )
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no json")
    data = json.loads(m.group(0))
    intent = (data.get("intent") or "qa").strip().lower()
    topic = (data.get("topic") or "").strip() or _strip_search_noise(question)
    query_en = (data.get("query_en") or "").strip()
    if intent not in {"qa", "search"}:
        intent = "search" if _looks_like_search(question) else "qa"
    return intent, topic, query_en


def _qa_skill(question: str) -> str:
    """qa | survey | compare — chooses specialized RAG prompt."""
    q = question.strip()
    if re.search(r"文献综述|写.*综述|综述一下|related work survey|literature review", q, re.I):
        return "survey"
    if re.search(r"方法对比|对比一下|比较.*方法|异同|compare", q, re.I):
        return "compare"
    return "qa"


def _progress_value(value: str, limit: int = 80) -> str:
    """Keep user/model-derived values compact and single-line in progress events."""
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _scope_summary(scope: Optional[set[str]]) -> str:
    if scope is None:
        return "范围：整个知识库"
    return f"范围：已选择 {len(scope)} 篇论文"


async def detect_intent(
    question: str,
    chat_model: ChatOpenAI,
) -> tuple[str, str, str]:
    """
    Returns (intent, topic_display, search_query_en).
    The third value is an English retrieval query for paper APIs or local RAG.
    """
    q = question.strip()

    # 综述/对比强制走库内问答，但仍生成英文词用于失败回退或直接对比。
    if _qa_skill(q) in {"survey", "compare"}:
        try:
            _, topic, query_en = await _llm_normalize_search(q, chat_model)
            return "qa", topic or q, query_en
        except Exception:
            return "qa", q, _map_zh_terms(q) or ""

    # Obvious searches with an English/already-mapped topic do not need an LLM
    # round trip before the paper API request.
    if _looks_like_search(q):
        topic = _strip_search_noise(q)
        query_en = _map_zh_terms(topic) or _map_zh_terms(q) or topic
        if query_en and not _contains_cjk(query_en):
            return "search", topic, query_en

    try:
        intent, topic, query_en = await _llm_normalize_search(q, chat_model)
        if intent == "search":
            if not query_en:
                query_en = _map_zh_terms(topic) or _map_zh_terms(q) or topic or q
            if _contains_cjk(query_en):
                query_en = _map_zh_terms(query_en) or _map_zh_terms(topic) or query_en
            return "search", topic, query_en
        return "qa", topic or q, query_en
    except Exception:
        pass

    if _looks_like_search(q):
        topic = _strip_search_noise(q)
        query_en = _map_zh_terms(topic) or _map_zh_terms(q) or topic
        return "search", topic, query_en
    return "qa", q, ""


def _format_paper_list(scope: Optional[set[str]]) -> str:
    if not scope:
        return "（未指定；请覆盖上下文中出现的全部论文）"
    lines: list[str] = []
    for i, pid in enumerate(sorted(scope), start=1):
        paper = db.get_paper(pid)
        if not paper:
            lines.append(f"{i}. paper_id={pid}")
            continue
        year = str(paper.year) if paper.year is not None else "n.d."
        lines.append(f"{i}. {paper.title} ({year}) [paper_id={pid}]")
    return "\n".join(lines) if lines else "（无）"


async def _run_single_survey(
    question: str,
    paper_list: str,
    hits: list[dict],
    chat_model: ChatOpenAI,
) -> str:
    chain = SURVEY_SINGLE_PROMPT | chat_model
    response = await chain.ainvoke(
        {
            "question": question,
            "paper_list": paper_list,
            "context": build_context(hits),
        }
    )
    return response.content if isinstance(response.content, str) else str(response.content)


async def answer_question(
    question: str,
    chat_model: ChatOpenAI,
    top_k: int | None = None,
    paper_ids: Optional[list[str]] = None,
    folder_ids: Optional[list[str]] = None,
    retrieval_query: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> ChatResponse:
    settings = get_settings()
    skill = _qa_skill(question)
    k = top_k or settings.default_top_k
    scope = db.resolve_scope(paper_ids or [], folder_ids or [])
    paper_list = _format_paper_list(scope)
    search_query = (retrieval_query or "").strip() or question

    if skill == "survey" and settings.survey_pipeline:
        if scope is None or len(scope) == 0:
            return ChatResponse(
                session_id="",
                intent="qa",
                answer="做文献综述前，请先在知识库勾选至少一篇相关论文。",
                citations=[],
                retrieved_chunks=[],
            )
        try:
            from app.rag.survey_pipeline import run_survey_pipeline

            answer, hits = await run_survey_pipeline(
                question,
                paper_list,
                scope,
                k,
                chat_model,
                on_progress=on_progress,
            )
        except Exception:
            report(on_progress, "多视角流水线失败，改用快速综述…", "fallback")
            n = len(scope)
            k = max(k, 12, n * 4)
            hits = await asyncio.to_thread(
                hybrid_search,
                search_query,
                top_k=k,
                allowed_paper_ids=scope,
            )
            if not hits:
                return ChatResponse(
                    session_id="",
                    intent="qa",
                    answer="当前文献库中未找到足够信息。可扩大勾选范围，或让我帮你搜索相关论文后导入。",
                    citations=[],
                    retrieved_chunks=[],
                )
            report(on_progress, "正在生成综述…", "generate")
            answer = await _run_single_survey(
                question,
                paper_list,
                hits,
                chat_model,
            )

        return _qa_response(answer, hits)

    if skill in {"survey", "compare"}:
        n = len(scope) if scope else 1
        # 每篇至少约 4 段，保证综述/对比有多篇证据
        k = max(k, 12, n * 4)

    report(
        on_progress,
        f"正在检索文献证据…\n{_scope_summary(scope)} · 检索词：{_progress_value(search_query)}",
        "retrieve",
    )
    hits = await asyncio.to_thread(
        hybrid_search,
        search_query,
        top_k=k,
        allowed_paper_ids=scope,
    )

    if not hits:
        msg = "当前文献库中未找到足够信息。"
        if scope is not None:
            msg += "可扩大勾选范围，或让我帮你搜索相关论文后导入。"
        else:
            msg += "请先导入论文，或让我帮你搜索相关论文。"
        if skill in {"survey", "compare"}:
            msg += "做综述/对比前，请先在知识库勾选相关论文。"
        return ChatResponse(
            session_id="",
            intent="qa",
            answer=msg,
            citations=[],
            retrieved_chunks=[],
        )

    evidence_papers = len({hit.get("paper_id") for hit in hits if hit.get("paper_id")})
    report(
        on_progress,
        f"已召回 {len(hits)} 个相关片段，覆盖 {evidence_papers} 篇论文",
        "retrieve_done",
    )

    prompt = RAG_PROMPT
    invoke_vars: dict = {
        "question": question,
        "context": build_context(hits),
    }
    if skill == "survey":
        report(
            on_progress,
            f"正在撰写综述…\n依据：{len(hits)} 个文献片段 · {_scope_summary(scope)}",
            "generate",
        )
        answer = await _run_single_survey(
            question,
            paper_list,
            hits,
            chat_model,
        )
        return _qa_response(answer, hits)
    elif skill == "compare":
        prompt = COMPARE_PROMPT
        invoke_vars["paper_list"] = paper_list
        report(
            on_progress,
            f"正在生成方法对比…\n依据：{len(hits)} 个文献片段 · 按问题设定、方法与局限组织",
            "generate",
        )
    else:
        report(
            on_progress,
            f"正在生成回答…\n依据：{len(hits)} 个文献片段，回答将附带引用编号",
            "generate",
        )

    chain = prompt | chat_model
    response = await chain.ainvoke(invoke_vars)
    answer = response.content if isinstance(response.content, str) else str(response.content)

    return _qa_response(answer, hits)


def make_session_title(text: str, fallback: str = "新对话") -> str:
    """Derive a short session title from the first user message."""
    cleaned = _strip_search_noise(re.sub(r"\s+", " ", (text or "").strip()))
    if not cleaned:
        return fallback
    return cleaned[:28] + ("…" if len(cleaned) > 28 else "")


def _maybe_auto_title(session_id: str, question: str) -> None:
    session = db.get_session(session_id)
    if not session:
        return
    # Only auto-name placeholder titles; keep user renames
    if session.title in {"新对话", "未命名", ""}:
        db.touch_session(session_id, title=make_session_title(question))


async def handle_chat(
    question: str,
    session_id: Optional[str] = None,
    paper_ids: Optional[list[str]] = None,
    folder_ids: Optional[list[str]] = None,
    top_k: int | None = None,
    llm_config: Optional[LLMConfig] = None,
    on_progress: Optional[ProgressCallback] = None,
    on_session: Optional[Callable[[str], None]] = None,
) -> ChatResponse:
    chat_model = get_chat_model(llm_config)
    if session_id and db.get_session(session_id):
        sid = session_id
    else:
        sid = db.create_session(make_session_title(question)).session_id

    db.add_message(sid, "user", question)
    _maybe_auto_title(sid, question)
    if on_session is not None:
        on_session(sid)

    report(on_progress, "正在理解问题意图…", "intent")
    intent, topic, query_en = await detect_intent(question, chat_model)
    intent_label = "在线论文检索" if intent == "search" else "知识库问答"
    details = [f"主题：{_progress_value(topic)}"]
    if query_en:
        details.append(f"英文检索词：{_progress_value(query_en)}")
    report(
        on_progress,
        f"已识别为：{intent_label}\n" + " · ".join(details),
        "intent_done",
    )
    if intent == "search":
        report(
            on_progress,
            f"正在检索相关论文…\n检索词：{query_en or topic}",
            "search",
        )
        try:
            papers = await online_search_papers(
                query_en, limit=8, on_progress=on_progress
            )
        except Exception as exc:
            answer = (
                f"主题「{topic}」→ 检索词「{query_en}」，"
                f"在线检索暂时失败（{type(exc).__name__}）。"
                "请稍后重试，或检查网络 / 代理后对 arXiv、Semantic Scholar 的访问。"
            )
            db.add_message(sid, "assistant", answer, meta={"intent": "search", "error": str(exc)})
            return ChatResponse(
                session_id=sid,
                intent="search",
                answer=answer,
                proposed_papers=[],
            )
        report(
            on_progress,
            f"检索完成：找到 {len(papers)} 篇候选论文\n已按标题与摘要相关性排序",
            "search_done",
        )
        if papers:
            answer = (
                f"主题「{topic}」已改写为英文检索词「{query_en}」，"
                f"找到 {len(papers)} 篇候选论文。可在下方勾选后导入知识库。"
            )
        else:
            answer = (
                f"主题「{topic}」→ 检索词「{query_en}」暂无结果，"
                "可换更短的英文关键词再试（例如 cardinality estimation）。"
            )
        meta = {
            "intent": "search",
            "topic": topic,
            "query_en": query_en,
            "proposed_papers": [p.model_dump() for p in papers],
        }
        db.add_message(sid, "assistant", answer, meta=meta)
        return ChatResponse(
            session_id=sid,
            intent="search",
            answer=answer,
            proposed_papers=papers,
        )

    result = await answer_question(
        question,
        chat_model,
        top_k=top_k,
        paper_ids=paper_ids,
        folder_ids=folder_ids,
        retrieval_query=query_en,
        on_progress=on_progress,
    )
    result.session_id = sid
    # evidence[i] aligns with answer citation [i+1] (includes chunk text)
    evidence = list(result.evidence) or _evidence_from_chunks(
        [
            {
                "paper_id": c.paper_id,
                "title": c.title,
                "year": c.year,
                "chunk_id": c.chunk_id,
                "text": c.text,
                "score": c.score,
            }
            for c in result.retrieved_chunks
        ]
    )
    meta = {
        "intent": "qa",
        "citations": [c.model_dump() for c in result.citations],
        "evidence": [c.model_dump() for c in evidence],
    }
    db.add_message(sid, "assistant", result.answer, meta=meta)
    return result
