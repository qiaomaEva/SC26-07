import { useEffect, useMemo, useState } from 'react'
import type { Paper, PaperChunk } from '../api/client'
import { listPaperChunks } from '../api/client'
import { formatChunkText } from '../utils/formatChunkText'
import { resolvePaperUrl } from '../utils/paperUrl'

type Props = {
  paper: Paper | null
  onClose: () => void
}

function previewLines(text: string, maxLines = 2): string {
  const lines = text.trim().split(/\r?\n/).filter(Boolean)
  if (lines.length <= maxLines) return lines.join('\n')
  return `${lines.slice(0, maxLines).join('\n')}…`
}

export function ChunkBrowser({ paper, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [chunks, setChunks] = useState<PaperChunk[]>([])
  const [meta, setMeta] = useState<{ title: string; year?: number | null } | null>(null)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const paperId = paper?.paper_id

  useEffect(() => {
    if (!paperId) {
      setChunks([])
      setMeta(null)
      setQuery('')
      setSelectedId(null)
      setError('')
      return
    }

    let cancelled = false
    setLoading(true)
    setError('')
    setQuery('')
    setSelectedId(null)

    void listPaperChunks(paperId)
      .then((res) => {
        if (cancelled) return
        setChunks(res.chunks)
        setMeta({ title: res.title, year: res.year })
        if (res.chunks.length > 0) setSelectedId(res.chunks[0].chunk_id)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
        setChunks([])
        setMeta(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [paperId])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return chunks
    return chunks.filter(
      (c) =>
        c.text.toLowerCase().includes(q) ||
        String(c.chunk_index).includes(q) ||
        c.chunk_id.toLowerCase().includes(q),
    )
  }, [chunks, query])

  const selected = useMemo(
    () => filtered.find((c) => c.chunk_id === selectedId) ?? filtered[0] ?? null,
    [filtered, selectedId],
  )

  if (!paper) return null

  const title = meta?.title || paper.title
  const year = meta?.year ?? paper.year
  const origin = resolvePaperUrl(paper)

  return (
    <div className="chunk-drawer-mask" onClick={onClose}>
      <aside
        className="chunk-drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chunk-drawer-title"
      >
        <header className="chunk-drawer-head">
          <div className="chunk-drawer-title-wrap">
            <h3 id="chunk-drawer-title">{title}</h3>
            <p className="chunk-drawer-sub">
              {year || 'n.d.'} · {loading ? '加载中…' : `${chunks.length} 个分块`}
              {origin ? (
                <>
                  {' '}
                  ·{' '}
                  <a href={origin} target="_blank" rel="noreferrer">
                    原文
                  </a>
                </>
              ) : null}
            </p>
          </div>
          <button className="btn-sm" onClick={onClose} aria-label="关闭">
            关闭
          </button>
        </header>

        <div className="chunk-drawer-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="在此论文的分块内搜索…"
            disabled={loading}
          />
        </div>

        {error ? <p className="error chunk-drawer-error">{error}</p> : null}

        <div className="chunk-drawer-body">
          <div className="chunk-drawer-list" aria-busy={loading}>
            {loading ? (
              <p className="muted chunk-drawer-empty">正在加载分块…</p>
            ) : filtered.length === 0 ? (
              <p className="muted chunk-drawer-empty">
                {chunks.length === 0 ? '该论文尚无分块（可能未导入 PDF 或索引未完成）' : '无匹配分块'}
              </p>
            ) : (
              <ul className="chunk-list">
                {filtered.map((c) => {
                  const active = selected?.chunk_id === c.chunk_id
                  return (
                    <li key={c.chunk_id}>
                      <button
                        type="button"
                        className={`chunk-list-item ${active ? 'is-active' : ''}`}
                        onClick={() => setSelectedId(c.chunk_id)}
                      >
                        <span className="chunk-list-index">#{c.chunk_index}</span>
                        <span className="chunk-list-preview">{previewLines(c.text)}</span>
                        {c.token_est > 0 ? (
                          <span className="chunk-list-tokens">{c.token_est} tok</span>
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {selected ? (
            <div className="chunk-drawer-detail">
              <p className="chunk-id muted">
                #{selected.chunk_index} · chunk: {selected.chunk_id}
              </p>
              <div className="chunk-text">
                {formatChunkText(selected.text) || '（空分块）'}
              </div>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  )
}
