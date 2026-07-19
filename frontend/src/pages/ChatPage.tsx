import { useState } from 'react'
import { chat, type ChatResponse } from '../api/client'
import { CitationList } from '../components/CitationList'

export function ChatPage() {
  const [question, setQuestion] = useState('这些论文主要解决什么问题？')
  const [result, setResult] = useState<ChatResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const onAsk = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await chat({ question: question.trim(), top_k: 6 })
      setResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="page">
      <h2>文献问答</h2>
      <textarea
        rows={4}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="基于已导入文献提问…"
      />
      <div className="row">
        <button onClick={onAsk} disabled={loading || !question.trim()}>
          {loading ? '生成中…' : '提问'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="answer-box">
          <h3>回答</h3>
          <pre className="answer">{result.answer}</pre>
          <h3>引用</h3>
          <CitationList citations={result.citations} />
        </div>
      )}
    </section>
  )
}
