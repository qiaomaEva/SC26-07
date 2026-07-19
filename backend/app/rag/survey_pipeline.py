"""Multi-stage literature survey pipeline adapted from literature-review skill (STORM)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.db import sqlite as db
from app.index.hybrid import hybrid_search
from app.rag.progress import ProgressCallback, report
from app.rag.prompts import (
    SURVEY_FINAL_PROMPT,
    SURVEY_NOTE_PROMPT,
    SURVEY_OUTLINE_PROMPT,
    SURVEY_PERSONA_PROMPT,
    SURVEY_QUERY_PROMPT,
)

logger = logging.getLogger(__name__)


def _llm_text(content: Any) -> str:
    return content if isinstance(content, str) else str(content)


def _parse_json_blob(text: str) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no json in llm response")
    return json.loads(m.group(0))


def _dedupe_hits(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for h in hits:
        cid = h.get("chunk_id") or ""
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(h)
    return out


def _remap_note_citations(
    note: str,
    local_hits: list[dict],
    global_positions: dict[str, int],
) -> str:
    """Map a persona note's local [n] markers to final merged-context numbers."""

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1900 <= number <= 2100:
            return match.group(0)
        local_index = number - 1
        if local_index < 0 or local_index >= len(local_hits):
            return ""
        chunk_id = local_hits[local_index].get("chunk_id") or ""
        global_index = global_positions.get(chunk_id)
        return f"[{global_index}]" if global_index is not None else ""

    return re.sub(r"\[(\d+)\]", replace, note)


def _build_context(chunks: list[dict]) -> str:
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


async def _generate_personas(
    question: str,
    paper_list: str,
    persona_count: int,
    chat_model: ChatOpenAI,
) -> tuple[str, list[dict[str, str]]]:
    chain = SURVEY_PERSONA_PROMPT | chat_model
    resp = await chain.ainvoke(
        {
            "question": question,
            "paper_list": paper_list,
            "persona_count": persona_count,
        }
    )
    data = _parse_json_blob(_llm_text(resp.content))
    topic = (data.get("topic") or question).strip()
    personas = data.get("personas") or []
    parsed: list[dict[str, str]] = []
    for p in personas:
        if not isinstance(p, dict):
            continue
        role = (p.get("role") or "").strip()
        focus = (p.get("focus") or "").strip()
        if role and focus:
            parsed.append({"role": role, "focus": focus})
    if len(parsed) < 2:
        parsed = [
            {"role": "系统与方法", "focus": "核心算法、系统架构与实现路线"},
            {"role": "实验与评估", "focus": "数据集、基准、指标与实验结论"},
            {"role": "理论与局限", "focus": "假设、理论保证、边界与开放问题"},
        ][:persona_count]
    return topic, parsed[:persona_count]


async def _generate_queries(
    topic: str,
    persona: dict[str, str],
    paper_list: str,
    query_count: int,
    chat_model: ChatOpenAI,
) -> list[str]:
    chain = SURVEY_QUERY_PROMPT | chat_model
    resp = await chain.ainvoke(
        {
            "topic": topic,
            "role": persona["role"],
            "focus": persona["focus"],
            "paper_list": paper_list,
            "query_count": query_count,
        }
    )
    data = _parse_json_blob(_llm_text(resp.content))
    queries = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
    if not queries:
        queries = [f"{topic} {persona['focus']}"]
    return queries[:query_count]


async def _persona_note(
    topic: str,
    persona: dict[str, str],
    queries: list[str],
    hits: list[dict],
    chat_model: ChatOpenAI,
) -> str:
    chain = SURVEY_NOTE_PROMPT | chat_model
    resp = await chain.ainvoke(
        {
            "topic": topic,
            "role": persona["role"],
            "focus": persona["focus"],
            "queries": "；".join(queries),
            "context": _build_context(hits),
        }
    )
    return _llm_text(resp.content).strip()


async def _generate_outline(
    topic: str, paper_list: str, notes: str, chat_model: ChatOpenAI
) -> str:
    chain = SURVEY_OUTLINE_PROMPT | chat_model
    resp = await chain.ainvoke(
        {"topic": topic, "paper_list": paper_list, "notes": notes}
    )
    return _llm_text(resp.content).strip()


async def _write_final(
    question: str,
    paper_list: str,
    outline: str,
    notes: str,
    hits: list[dict],
    chat_model: ChatOpenAI,
) -> str:
    chain = SURVEY_FINAL_PROMPT | chat_model
    resp = await chain.ainvoke(
        {
            "question": question,
            "paper_list": paper_list,
            "outline": outline,
            "notes": notes,
            "context": _build_context(hits),
        }
    )
    return _llm_text(resp.content).strip()


async def run_survey_pipeline(
    question: str,
    paper_list: str,
    scope: Optional[set[str]],
    top_k: int,
    chat_model: ChatOpenAI,
    on_progress: Optional[ProgressCallback] = None,
) -> tuple[str, list[dict]]:
    """
    STORM-inspired pipeline: personas → per-persona retrieval → notes → outline → final review.
    Returns (answer_markdown, deduped_hits).
    """
    settings = get_settings()
    persona_count = settings.survey_personas
    query_count = settings.survey_queries_per_persona
    n_papers = len(scope) if scope else 1
    per_persona_k = max(settings.survey_persona_top_k, min(top_k, n_papers * 2))

    report(on_progress, "正在提炼主题并生成研究视角…", "personas")
    topic, personas = await _generate_personas(
        question, paper_list, persona_count, chat_model
    )
    logger.info("survey pipeline topic=%s personas=%d", topic, len(personas))
    report(
        on_progress,
        (
            f"已确定主题「{topic}」，将从 {len(personas)} 个视角展开\n"
            f"范围：已选择 {len(scope) if scope else 0} 篇论文"
        ),
        "personas_done",
    )

    all_hits: list[dict] = []
    persona_notes: list[tuple[int, dict[str, str], str, list[dict]]] = []

    for i, persona in enumerate(personas, start=1):
        role = persona["role"]
        report(on_progress, f"视角 {i}/{len(personas)}「{role}」：生成检索问句…", f"persona_{i}_query")
        queries = await _generate_queries(
            topic, persona, paper_list, query_count, chat_model
        )
        persona_hits: list[dict] = []
        report(on_progress, f"视角 {i}/{len(personas)}「{role}」：检索勾选论文片段…", f"persona_{i}_retrieve")
        for q in queries:
            persona_hits.extend(
                await asyncio.to_thread(
                    hybrid_search,
                    q,
                    top_k=per_persona_k,
                    allowed_paper_ids=scope,
                )
            )
        persona_hits = _dedupe_hits(persona_hits)
        if not persona_hits and scope:
            persona_hits = _dedupe_hits(
                await asyncio.to_thread(
                    hybrid_search,
                    topic,
                    top_k=per_persona_k,
                    allowed_paper_ids=scope,
                )
            )
        all_hits.extend(persona_hits)

        report(on_progress, f"视角 {i}/{len(personas)}「{role}」：整理笔记…", f"persona_{i}_note")
        note = await _persona_note(
            topic,
            persona,
            queries,
            persona_hits,
            chat_model,
        )
        persona_notes.append((i, persona, note, persona_hits))

    if scope:
        coverage_rows = db.list_chunks_for_papers(scope, limit=len(scope))
        all_hits.extend({**row, "score": 0.0} for row in coverage_rows)
    merged_hits = _dedupe_hits(all_hits)
    if not merged_hits:
        raise RuntimeError("no retrieval hits for survey pipeline")
    evidence_papers = len(
        {hit.get("paper_id") for hit in merged_hits if hit.get("paper_id")}
    )
    report(
        on_progress,
        f"已汇总 {len(merged_hits)} 个证据片段，覆盖 {evidence_papers} 篇论文",
        "evidence_done",
    )

    global_positions = {
        hit.get("chunk_id") or "": index
        for index, hit in enumerate(merged_hits, start=1)
        if hit.get("chunk_id")
    }
    note_blocks = [
        f"## 视角 {index}：{persona['role']}\n"
        f"关注点：{persona['focus']}\n\n"
        f"{_remap_note_citations(note, local_hits, global_positions)}"
        for index, persona, note, local_hits in persona_notes
    ]
    notes_text = "\n\n".join(note_blocks)
    report(on_progress, "正在合成综述大纲…", "outline")
    outline = await _generate_outline(topic, paper_list, notes_text, chat_model)
    report(on_progress, "正在撰写终稿综述…", "final")
    answer = await _write_final(
        question, paper_list, outline, notes_text, merged_hits, chat_model
    )
    report(
        on_progress,
        f"综述完成\n已基于 {len(merged_hits)} 个证据片段生成并标注引用",
        "done",
    )
    return answer, merged_hits
