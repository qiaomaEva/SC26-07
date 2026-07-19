import { useEffect, useState } from 'react'

type Props = {
  paperId: string
  title: string
  pdfUrl?: string | null
  onClose: () => void
}

export function PdfViewer({ paperId, title, pdfUrl, onClose }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const apiUrl = '/api/library/papers/' + paperId + '/pdf'

  useEffect(() => {
    if (pdfUrl) return
    let cancelled = false
    setBlobUrl(null)
    setError(false)
    fetch(apiUrl)
      .then((res) => res.blob())
      .then((blob) => { if (!cancelled) setBlobUrl(URL.createObjectURL(blob)) })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [paperId, pdfUrl, apiUrl])

  if (pdfUrl) {
    return (
      <div className="panel pdf-viewer-panel">
        <div className="pdf-viewer-toolbar">
          <button className="btn-sm" onClick={onClose}>{'\u2190'} 返回聊天</button>
          <span className="pdf-viewer-title">{title}</span>
        </div>
        <iframe key={paperId} src={pdfUrl} className="pdf-viewer-embed" title={title} />
      </div>
    )
  }

  const toolbar = (
    <div className="pdf-viewer-toolbar">
      <button className="btn-sm" onClick={onClose}>{'\u2190'} 返回聊天</button>
      <span className="pdf-viewer-title">{title}</span>
    </div>
  )

  if (error) return <div className="panel pdf-viewer-panel">{toolbar}<p className="muted" style={{ padding: 40, textAlign: 'center' }}>无法加载 PDF</p></div>
  if (!blobUrl) return <div className="panel pdf-viewer-panel">{toolbar}<p className="muted" style={{ padding: 40, textAlign: 'center' }}>加载中...</p></div>

  return (
    <div className="panel pdf-viewer-panel">
      {toolbar}
      <iframe key={paperId} src={blobUrl} className="pdf-viewer-embed" title={title} />
    </div>
  )
}
