import { useCallback, useEffect, useRef, useState } from "react"
import { Check, Edit3, Eye } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

type Note = {
  id: string
  title: string
  content: string
  updatedAt: number
}

const STORAGE_KEY = "literature-rag.notes"

function loadNotes(): Note[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveNotes(notes: Note[]) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(notes)) } catch {}
}

function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

type Props = {
  onClose: () => void
}

export function NotesModal({ onClose }: Props) {
  const [notes, setNotes] = useState<Note[]>(() => loadNotes())
  const [activeId, setActiveId] = useState<string | null>(null)
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [preview, setPreview] = useState(false)
  const [listCollapsed, setListCollapsed] = useState(false)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const initialLoad = useRef(false)

  useEffect(() => {
    if (notes.length > 0 && !initialLoad.current) {
      initialLoad.current = true
      const n = notes[0]
      setActiveId(n.id); setTitle(n.title); setContent(n.content)
    }
  }, [notes])

  const persist = useCallback((updated: Note[]) => {
    setNotes(updated)
    saveNotes(updated)
  }, [])

  const selectNote = (id: string) => {
    const n = notes.find((x) => x.id === id)
    if (!n) return
    setActiveId(id)
    setTitle(n.title)
    setContent(n.content)
    setPreview(false)
  }

  const saveCurrent = () => {
    if (!activeId) {
      if (!title.trim() && !content.trim()) return
      const note: Note = { id: newId(), title: title || "无标题", content, updatedAt: Date.now() }
      persist([note, ...notes])
      setActiveId(note.id)
      return
    }
    const updated = notes.map((n) =>
      n.id === activeId ? { ...n, title, content, updatedAt: Date.now() } : n
    )
    persist(updated)
  }

  const handleNew = () => {
    const note: Note = { id: newId(), title: "", content: "", updatedAt: Date.now() }
    persist([note, ...notes])
    setActiveId(note.id)
    setTitle(note.title)
    setContent(note.content)
    setPreview(false)
  }

  const handleDelete = (noteId?: string) => {
    const id = noteId || activeId
    if (!id) return
    const next = notes.filter((n) => n.id !== id)
    persist(next)
    if (next.length > 0) {
      setActiveId(next[0].id); setTitle(next[0].title); setContent(next[0].content)
    } else {
      setActiveId(null); setTitle(""); setContent("")
    }
  }

  const onDragStart = (e: React.MouseEvent) => {
    const sx = e.clientX, sy = e.clientY, px = pos.x, py = pos.y
    const onMove = (ev: MouseEvent) => setPos({ x: px + (ev.clientX - sx), y: py + (ev.clientY - sy) })
    const onUp = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  return (
    <div className="notes-modal" style={{ transform: "translate(" + pos.x + "px," + pos.y + "px)" }}>
      <div className="notes-header" onMouseDown={onDragStart}>
        <div className="notes-header-left">
          <button className="notes-list-toggle icon-btn" onClick={() => setListCollapsed((v) => !v)} title="切换列表">
            {listCollapsed ? "\u25b8" : "\u25c2"}
          </button>
          笔记
        </div>
        <div className="notes-header-center">
          <button className="icon-btn" onClick={saveCurrent} title="完成"><Check size={16} /></button>
          <button className="icon-btn" onClick={() => { saveCurrent(); setPreview(!preview) }} title={preview ? "编辑" : "预览"}>{preview ? <Edit3 size={16} /> : <Eye size={16} />}</button>
          <button className="icon-btn" onClick={handleNew} title="新建">+</button>
        </div>
        <div className="notes-header-right">
          <button className="icon-btn" onClick={onClose} title="关闭">{'\u2715'}</button>
        </div>
      </div>

      <div className="notes-body">
        <div className={"notes-list" + (listCollapsed ? " collapsed" : "")}>
          {notes.map((n) => (
            <div key={n.id} className={"notes-list-item" + (n.id === activeId ? " active" : "")} onClick={() => selectNote(n.id)}>
              <div className="notes-list-title">{n.title || "无标题"}</div>
              <button className="icon-btn hover-only" onClick={(e) => { e.stopPropagation(); handleDelete(n.id) }} title="删除">{'\u00d7'}</button>
            </div>
          ))}
          {notes.length === 0 && <p className="muted small" style={{ padding: 12 }}>暂无笔记</p>}
        </div>

        <div className="notes-editor">
          <input className="notes-title-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="笔记标题" />
          {preview ? (
            <div className="notes-preview" style={{ flex: 1, overflow: "auto", padding: "12px 14px" }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          ) : (
            <textarea className="notes-textarea" value={content} onChange={(e) => setContent(e.target.value)} placeholder="使用 Markdown 语法编写笔记..." />
          )}
        </div>
      </div>
    </div>
  )
}
