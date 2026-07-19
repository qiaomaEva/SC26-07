import type { Paper } from '../api/client'

type Props = {
  paper: Paper
  selectable?: boolean
  checked?: boolean
  onToggle?: (paperId: string) => void
}

export function PaperCard({ paper, selectable, checked, onToggle }: Props) {
  return (
    <article className="paper-card">
      <header className="paper-card__header">
        {selectable && (
          <input
            type="checkbox"
            checked={!!checked}
            onChange={() => onToggle?.(paper.paper_id)}
          />
        )}
        <div>
          <h3>{paper.title}</h3>
          <p className="meta">
            {(paper.authors || []).slice(0, 4).join(', ') || 'Unknown authors'}
            {paper.year ? ` · ${paper.year}` : ''}
          </p>
        </div>
      </header>
      {paper.abstract && <p className="abstract">{paper.abstract}</p>}
      {paper.url && (
        <a href={paper.url} target="_blank" rel="noreferrer">
          打开原文
        </a>
      )}
    </article>
  )
}
