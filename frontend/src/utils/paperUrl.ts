/** Resolve a human-readable "original paper" URL for open-access / arXiv papers. */

export type PaperLike = {
  paper_id: string
  url?: string | null
  pdf_url?: string | null
}

export function resolvePaperUrl(paper: PaperLike): string | null {
  const pdf = (paper.pdf_url || '').trim()
  if (pdf) return pdf

  const url = (paper.url || '').trim()
  if (url) {
    // Prefer abstract page for reading; keep direct PDF links as-is
    return url
  }

  if (paper.paper_id.startsWith('arxiv:')) {
    const id = paper.paper_id.slice('arxiv:'.length).replace(/v\d+$/, '')
    if (id) return `https://arxiv.org/abs/${id}`
  }

  // Local uploads have no public URL
  if (paper.paper_id.startsWith('pdf:')) return null

  // Semantic Scholar graph id
  if (/^[a-f0-9]{40}$/i.test(paper.paper_id) || paper.paper_id.length > 10) {
    return `https://www.semanticscholar.org/paper/${paper.paper_id}`
  }

  return null
}
