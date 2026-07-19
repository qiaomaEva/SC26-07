import type { Citation } from '../api/client'

type Props = {
  citations: Citation[]
}

export function CitationList({ citations }: Props) {
  if (!citations.length) {
    return <p className="muted">无引用</p>
  }
  return (
    <ul className="citation-list">
      {citations.map((c) => (
        <li key={c.paper_id}>
          <code>{c.paper_id}</code> — {c.title}
          {c.year ? ` (${c.year})` : ''}
        </li>
      ))}
    </ul>
  )
}
