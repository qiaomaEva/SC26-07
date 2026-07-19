import { useEffect, useRef, useState } from 'react'
import type { ChatSession } from '../api/client'

type Props = {
  sessions: ChatSession[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => Promise<void>
}

export function HistoryPanel({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId) inputRef.current?.focus()
  }, [editingId])

  const startEdit = (s: ChatSession) => {
    setEditingId(s.session_id)
    setDraft(s.title || '')
  }

  const commitEdit = async () => {
    if (!editingId) return
    const title = draft.trim()
    const id = editingId
    setEditingId(null)
    if (!title) return
    await onRename(id, title)
  }

  return (
    <aside className="panel history-panel">
      <div className="panel-head">
        <h2>对话历史</h2>
        <button className="btn-sm" onClick={onNew}>
          新对话
        </button>
      </div>
      <div className="panel-body">
        <ul className="session-list">
          {sessions.length === 0 && <p className="muted small">暂无会话</p>}
          {sessions.map((s) => (
            <li
              key={s.session_id}
              className={s.session_id === activeId ? 'active' : ''}
            >
              {editingId === s.session_id ? (
                <input
                  ref={inputRef}
                  className="session-edit"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => void commitEdit()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void commitEdit()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                />
              ) : (
                <button
                  className="session-main"
                  onClick={() => onSelect(s.session_id)}
                  onDoubleClick={() => startEdit(s)}
                  title="双击重命名"
                >
                  {s.title || '未命名'}
                </button>
              )}
              <span className="line-actions">
                <button
                  className="icon-btn hover-only"
                  title="重命名"
                  onClick={() => startEdit(s)}
                >
                  ✎
                </button>
                <button
                  className="icon-btn hover-only"
                  title="删除"
                  onClick={() => setPendingDelete(s)}
                >
                  ×
                </button>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {pendingDelete && (
        <div className="modal-mask" onClick={() => setPendingDelete(null)}>
          <div
            className="modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-session-title"
          >
            <h3 id="delete-session-title">删除对话？</h3>
            <p className="modal-desc">
              确定删除「{pendingDelete.title || '未命名'}」吗？对话记录将无法恢复。
            </p>
            <div className="modal-actions">
              <button className="btn-sm" onClick={() => setPendingDelete(null)}>
                取消
              </button>
              <button
                className="btn-sm danger"
                onClick={() => {
                  const id = pendingDelete.session_id
                  setPendingDelete(null)
                  onDelete(id)
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
