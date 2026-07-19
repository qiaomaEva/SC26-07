import { useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import type { Folder, Paper } from '../api/client'
import { resolvePaperUrl } from '../utils/paperUrl'
import { ChunkBrowser } from './ChunkBrowser'

type Props = {
  folders: Folder[]
  papers: Paper[]
  selectedPaperIds: Set<string>
  selectedFolderIds: Set<string>
  onTogglePaper: (id: string) => void
  onToggleFolder: (id: string) => void
  onCreateFolder: (name: string) => Promise<void>
  onDeleteFolder: (id: string) => Promise<void>
  onMovePaper: (paperId: string, folderId: string | null) => Promise<void>
  onUploadPdf: (file: File, folderId: string | null) => Promise<void>
  onRefresh: () => void
  onViewPdf?: (paperId: string, title: string, pdfUrl?: string | null) => void
}

type SectionKey = 'all' | 'none' | string

export function KnowledgePanel({
  folders,
  papers,
  selectedPaperIds,
  selectedFolderIds,
  onTogglePaper,
  onToggleFolder,
  onCreateFolder,
  onDeleteFolder,
  onMovePaper,
  onUploadPdf,
  onRefresh,
  onViewPdf,
}: Props) {
  // 默认折叠，避免「全部 + 各文件夹」同时展开显得拥挤
  const [expanded, setExpanded] = useState<Set<SectionKey>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [folderName, setFolderName] = useState('')
  const [pendingDelete, setPendingDelete] = useState<Folder | null>(null)
  const [dropTarget, setDropTarget] = useState<string | 'none' | null>(null)
  const [uploadFolderId, setUploadFolderId] = useState<string | null>(null)
  const [chunkPaper, setChunkPaper] = useState<Paper | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const modalInputRef = useRef<HTMLInputElement>(null)
  const openModal = () => {
    setFolderName('')
    setShowModal(true)
    setTimeout(() => modalInputRef.current?.focus(), 0)
  }

  const uncategorized = useMemo(
    () => papers.filter((p) => !p.folder_id),
    [papers],
  )

  const papersByFolder = useMemo(() => {
    const map = new Map<string, Paper[]>()
    for (const f of folders) map.set(f.folder_id, [])
    for (const p of papers) {
      if (!p.folder_id) continue
      const list = map.get(p.folder_id) || []
      list.push(p)
      map.set(p.folder_id, list)
    }
    return map
  }, [folders, papers])

  const toggleExpand = (key: SectionKey) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleCreate = async () => {
    if (!folderName.trim()) return
    setBusy(true)
    setError('')
    try {
      await onCreateFolder(folderName.trim())
      setShowModal(false)
      setFolderName('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const triggerUpload = (folderId: string | null) => {
    setUploadFolderId(folderId)
    fileRef.current?.click()
  }

  const handleUpload = async (file: File | null) => {
    if (!file) return
    const target = uploadFolderId
    setBusy(true)
    setError('')
    setStatus(`正在上传并索引 PDF：${file.name}`)
    try {
      await onUploadPdf(file, target)
      setExpanded((prev) => {
        const next = new Set(prev)
        next.add(target ? target : 'none')
        return next
      })
      setStatus(`已上传：${file.name}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('')
    } finally {
      setBusy(false)
      setUploadFolderId(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const onDragStart = (e: DragEvent, paperId: string) => {
    e.dataTransfer.setData('text/paper-id', paperId)
    e.dataTransfer.effectAllowed = 'move'
  }

  const onDragOver = (e: DragEvent, target: string | 'none') => {
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'move'
    if (dropTarget !== target) setDropTarget(target)
  }

  const onDragLeave = (e: DragEvent, target: string | 'none') => {
    e.preventDefault()
    const related = e.relatedTarget as Node | null
    if (related && (e.currentTarget as HTMLElement).contains(related)) return
    setDropTarget((prev) => (prev === target ? null : prev))
  }

  const onDrop = async (e: DragEvent, target: string | 'none') => {
    e.preventDefault()
    e.stopPropagation()
    const paperId = e.dataTransfer.getData('text/paper-id')
    setDropTarget(null)
    if (!paperId) return
    setBusy(true)
    setError('')
    try {
      await onMovePaper(paperId, target === 'none' ? null : target)
      // 拖入后自动展开目标文件夹，避免内容“挤在看不见的地方”
      setExpanded((prev) => {
        const next = new Set(prev)
        next.add(target === 'none' ? 'none' : target)
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="panel knowledge-panel">
      
      <div className="panel-head">
        <h2>知识库</h2>
        <div className="head-actions">
          <button className="btn-sm" onClick={openModal} disabled={busy} title="新建文件夹">
            +
          </button>
          <button className="btn-sm" onClick={onRefresh} disabled={busy}>
            刷新
          </button>
        </div>
      </div>

      <div className="panel-body">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={(e) => void handleUpload(e.target.files?.[0] || null)}
        />
        {error && <p className="error">{error}</p>}
        {status && <p className="muted status-line">{status}</p>}

        <div className="folder-tree">
          <FolderSection
            title="全部"
            count={papers.length}
            expanded={expanded.has('all')}
            onToggle={() => toggleExpand('all')}
            droppable={false}
          >
            <PaperList
              papers={papers}
              selectedPaperIds={selectedPaperIds}
              onTogglePaper={onTogglePaper}
              onDragStart={onDragStart}
              onOpenChunks={setChunkPaper}
              onViewPdf={onViewPdf}
            />
          </FolderSection>

          <FolderSection
            title="未分类"
            count={uncategorized.length}
            expanded={expanded.has('none')}
            onToggle={() => toggleExpand('none')}
            dropActive={dropTarget === 'none'}
            onDragOver={(e) => onDragOver(e, 'none')}
            onDragLeave={(e) => onDragLeave(e, 'none')}
            onDrop={(e) => void onDrop(e, 'none')}
            actions={
              <button
                className="icon-btn hover-only"
                title="上传 PDF"
                onClick={(e) => {
                  e.stopPropagation()
                  triggerUpload(null)
                }}
              >
                ↑
              </button>
            }
          >
            <PaperList
              papers={uncategorized}
              selectedPaperIds={selectedPaperIds}
              onTogglePaper={onTogglePaper}
              onDragStart={onDragStart}
              onOpenChunks={setChunkPaper}
              onViewPdf={onViewPdf}
            />
          </FolderSection>

          {folders.map((f) => {
            const list = papersByFolder.get(f.folder_id) || []
            return (
              <FolderSection
                key={f.folder_id}
                title={f.name}
                count={list.length}
                expanded={expanded.has(f.folder_id)}
                onToggle={() => toggleExpand(f.folder_id)}
                checked={selectedFolderIds.has(f.folder_id)}
                onCheck={() => onToggleFolder(f.folder_id)}
                dropActive={dropTarget === f.folder_id}
                onDragOver={(e) => onDragOver(e, f.folder_id)}
                onDragLeave={(e) => onDragLeave(e, f.folder_id)}
                onDrop={(e) => void onDrop(e, f.folder_id)}
                actions={
                  <>
                    <button
                      className="icon-btn hover-only"
                      title="上传 PDF"
                      onClick={(e) => {
                        e.stopPropagation()
                        triggerUpload(f.folder_id)
                      }}
                    >
                      ↑
                    </button>
                    <button
                      className="icon-btn hover-only"
                      title="删除文件夹"
                      onClick={(e) => {
                        e.stopPropagation()
                        setPendingDelete(f)
                      }}
                    >
                      ×
                    </button>
                  </>
                }
              >
                <PaperList
                  papers={list}
                  selectedPaperIds={selectedPaperIds}
                  onTogglePaper={onTogglePaper}
                  onDragStart={onDragStart}
                  onOpenChunks={setChunkPaper}
                onViewPdf={onViewPdf}
              />
              </FolderSection>
            )
          })}
        </div>
      </div>

      {showModal && (
        <div className="modal-mask" onClick={() => !busy && setShowModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()} role="dialog">
            <h3>新建文件夹</h3>
            <input
              ref={modalInputRef}
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
              placeholder="文件夹名称"
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreate()
                if (e.key === 'Escape') setShowModal(false)
              }}
            />
            <div className="modal-actions">
              <button className="btn-sm" onClick={() => setShowModal(false)} disabled={busy}>
                取消
              </button>
              <button
                className="btn-sm accent"
                onClick={() => void handleCreate()}
                disabled={busy || !folderName.trim()}
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {pendingDelete && (
        <div
          className="modal-mask"
          onClick={() => !busy && setPendingDelete(null)}
        >
          <div
            className="modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-folder-title"
          >
            <h3 id="delete-folder-title">删除文件夹？</h3>
            <p className="modal-desc">
              确定删除「{pendingDelete.name}」吗？文件夹内的论文会移到未分类，此操作不可撤销。
            </p>
            <div className="modal-actions">
              <button
                className="btn-sm"
                disabled={busy}
                onClick={() => setPendingDelete(null)}
              >
                取消
              </button>
              <button
                className="btn-sm danger"
                disabled={busy}
                onClick={() => {
                  const id = pendingDelete.folder_id
                  setPendingDelete(null)
                  void onDeleteFolder(id)
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}

      <ChunkBrowser paper={chunkPaper} onClose={() => setChunkPaper(null)} />
    </aside>
  )
}

function FolderSection({
  title,
  count,
  expanded,
  onToggle,
  checked,
  onCheck,
  actions,
  children,
  droppable = true,
  dropActive,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  title: string
  count: number
  expanded: boolean
  onToggle: () => void
  checked?: boolean
  onCheck?: () => void
  actions?: ReactNode
  children: ReactNode
  droppable?: boolean
  dropActive?: boolean
  onDragOver?: (e: DragEvent) => void
  onDragLeave?: (e: DragEvent) => void
  onDrop?: (e: DragEvent) => void
}) {
  return (
    <div
      className={`folder-block ${dropActive ? 'drop-over' : ''}`}
      onDragOver={droppable ? onDragOver : undefined}
      onDragLeave={droppable ? onDragLeave : undefined}
      onDrop={droppable ? onDrop : undefined}
    >
      <div className={`folder-line ${expanded ? 'is-open' : ''}`} onClick={onToggle}>
        <span className="caret" aria-hidden>
          {expanded ? '▾' : '▸'}
        </span>
        <span className="check-slot">
          {onCheck !== undefined ? (
            <label className="hover-only check-wrap" onClick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={!!checked} onChange={onCheck} />
            </label>
          ) : null}
        </span>
        <span className="folder-title">{title}</span>
        <span className="folder-count">{count}</span>
        <span className="line-actions">{actions}</span>
      </div>
      {expanded && <div className="folder-children">{children}</div>}
    </div>
  )
}

function PaperList({
  papers,
  selectedPaperIds,
  onTogglePaper,
  onDragStart,
  onOpenChunks,
  onViewPdf,
}: {
  papers: Paper[]
  selectedPaperIds: Set<string>
  onTogglePaper: (id: string) => void
  onDragStart: (e: DragEvent, paperId: string) => void
  onOpenChunks: (paper: Paper) => void
  onViewPdf?: (paperId: string, title: string, pdfUrl?: string | null) => void
}) {
  if (papers.length === 0) {
    return <p className="folder-empty">暂无论文</p>
  }
  return (
    <ul className="paper-list tree">
      {papers.map((p) => {
        const selected = selectedPaperIds.has(p.paper_id)
        const origin = resolvePaperUrl(p)
        return (
          <li key={p.paper_id}>
            <div
              className={`paper-item ${selected ? 'is-selected' : ''}`}
              draggable
              onDragStart={(e) => onDragStart(e, p.paper_id)}
              onClick={(e) => {
                const t = e.target as HTMLElement
                if (!t.closest('.check-wrap') && !t.closest('.paper-actions')) {
                  e.preventDefault()
                  onViewPdf?.(p.paper_id, p.title, p.pdf_url)
                }
              }}
            >
              <span className="check-slot">
                <label className={`check-wrap ${selected ? 'is-on' : 'hover-only'}`}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => onTogglePaper(p.paper_id)}
                  />
                </label>
              </span>
              <span className="paper-meta">
                <strong>{p.title}</strong>
                <em>
                  {p.year || 'n.d.'} · {p.source}
                </em>
              </span>
              <span className="paper-actions">
                {origin ? (
                  <a
                    className="paper-origin hover-only"
                    href={origin}
                    target="_blank"
                    rel="noreferrer"
                    title="阅读原文"
                    draggable={false}
                    onClick={(e) => e.stopPropagation()}
                    onDragStart={(e) => e.preventDefault()}
                  >
                    原文
                  </a>
                ) : null}
                <button
                  type="button"
                  className="paper-chunks hover-only"
                  title="查看分块"
                  draggable={false}
                  onClick={(e) => {
                    e.stopPropagation()
                    onOpenChunks(p)
                  }}
                >
                  分块
                </button>
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
