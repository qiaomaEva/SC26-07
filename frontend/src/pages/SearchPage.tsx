import { useState } from 'react'
import { importPapers, searchPapers, type Paper } from '../api/client'
import { PaperCard } from '../components/PaperCard'

export function SearchPage() {
  const [query, setQuery] = useState('graph neural networks recommendation')
  const [papers, setPapers] = useState<Paper[]>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const toggle = (paperId: string) => {
    setSelected((prev) => ({ ...prev, [paperId]: !prev[paperId] }))
  }

  const onSearch = async () => {
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const data = await searchPapers(query.trim(), 10)
      setPapers(data.papers)
      setSelected({})
      setMessage(`找到 ${data.papers.length} 篇`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const onImport = async () => {
    const chosen = papers.filter((p) => selected[p.paper_id])
    if (!chosen.length) {
      setError('请先勾选要导入的论文')
      return
    }
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const data = await importPapers(chosen)
      setMessage(`已导入 ${data.imported} 篇并建立索引`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page">
      <h2>搜索论文</h2>
      <div className="row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入关键词，例如 retrieval augmented generation"
          onKeyDown={(e) => e.key === 'Enter' && onSearch()}
        />
        <button onClick={onSearch} disabled={loading || !query.trim()}>
          搜索
        </button>
        <button className="secondary" onClick={onImport} disabled={loading}>
          导入选中
        </button>
      </div>
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}
      <div className="stack">
        {papers.map((p) => (
          <PaperCard
            key={p.paper_id}
            paper={p}
            selectable
            checked={!!selected[p.paper_id]}
            onToggle={toggle}
          />
        ))}
      </div>
    </section>
  )
}
