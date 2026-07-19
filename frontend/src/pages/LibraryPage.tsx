import { useEffect, useState } from 'react'
import { listLibrary, type Paper } from '../api/client'
import { PaperCard } from '../components/PaperCard'

export function LibraryPage() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listLibrary()
      setPapers(data.papers)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <section className="page">
      <div className="row between">
        <h2>我的文献库</h2>
        <button onClick={load} disabled={loading}>
          刷新
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!loading && papers.length === 0 && (
        <p className="muted">库为空。请先在「搜索」页导入论文。</p>
      )}
      <div className="stack">
        {papers.map((p) => (
          <PaperCard key={p.paper_id} paper={p} />
        ))}
      </div>
    </section>
  )
}
