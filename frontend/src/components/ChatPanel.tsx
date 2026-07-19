import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { Square } from 'lucide-react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  cancelChatTask,
  ChatCancelledError,
  chatStream,
  importPapersStream,
  type ChatMessage,
  type Citation,
  type EvidenceSnippet,
  type Folder,
  type LLMConfig,
  type Paper,
} from '../api/client'
import { formatChunkText } from '../utils/formatChunkText'
import { resolvePaperUrl } from '../utils/paperUrl'

type Props = {
  sessionId: string | null
  messages: ChatMessage[]
  folders: Folder[]
  libraryPapers: Paper[]
  selectedPaperIds: string[]
  selectedFolderIds: string[]
  llmConfig?: LLMConfig
  onSessionChange: (sessionId: string) => void
  onMessagesReload: (sessionId: string) => Promise<void>
  onLibraryReload: () => Promise<void>
  onCreateFolder: (name: string) => Promise<Folder>
}

type ThinkingStep = {
  id: string
  message: string
}

type ActiveChatRequest = {
  requestId: string
  controller: AbortController
  sessionId?: string
}

function createRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function presentThinkingStep(message: string) {
  const [label, ...details] = message.split('\n')
  return { label, detail: details.join(' · ') }
}

function formatElapsed(seconds: number) {
  if (seconds < 60) return `已等待 ${seconds} 秒`
  return `已等待 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

type Skill = {
  id: string
  label: string
  desc: string
  prompt: string
  needsScope?: boolean
  send?: boolean
}

const SKILLS: Skill[] = [
  {
    id: 'survey',
    label: '文献综述',
    desc: '多视角整理勾选论文',
    needsScope: true,
    send: true,
    prompt:
      '请基于当前勾选的论文写一篇结构化文献综述。系统将按多专家视角检索与整理，输出应包含：背景与动机、主要方法路线、代表性工作对比、关键论文对照表、共识与分歧、知识缺口与后续方向。用中文，引用处用 [n] 标注，须覆盖每一篇勾选论文。',
  },
  {
    id: 'compare',
    label: '方法对比',
    desc: '对比勾选论文',
    needsScope: true,
    send: true,
    prompt:
      '请对比当前勾选论文的方法：问题设定、核心思路、假设与数据、优点与局限。请按「对比维度」分节（### 标题），每节下用列表分论文说明，不要用宽表格，不要输出 HTML。引用用 [n]。',
  },
  {
    id: 'explain',
    label: '讲懂这篇',
    desc: '从背景到贡献',
    needsScope: true,
    send: true,
    prompt:
      '这篇文章主要讲了什么？请从背景、动机、方法到贡献，把我讲懂。用中文，引用用 [n]。',
  },
  {
    id: 'search',
    label: '找论文',
    desc: '在线检索导入',
    send: false,
    prompt: '帮我找找相关论文：',
  },
]

const SUGGESTIONS = [
  '帮我找找基数估计的相关工作论文',
  '帮我找找查询优化相关论文',
  '这篇文章主要讲了什么，从背景动机讲起',
  '请基于勾选论文写一篇文献综述（含对照表与知识缺口）',
]

export function ChatPanel({
  sessionId,
  messages,
  folders,
  libraryPapers,
  selectedPaperIds,
  selectedFolderIds,
  llmConfig,
  onSessionChange,
  onMessagesReload,
  onLibraryReload,
  onCreateFolder,
}: Props) {
  const [question, setQuestion] = useState('')
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([])
  const [thinkingElapsed, setThinkingElapsed] = useState(0)
  const [error, setError] = useState('')
  const [cancelNotice, setCancelNotice] = useState('')
  const [stopping, setStopping] = useState(false)
  const [pendingImport, setPendingImport] = useState<Record<string, boolean>>({})
  const [importTarget, setImportTarget] = useState('') // '' = 未分类, folder_id, or __new__
  const [newFolderName, setNewFolderName] = useState('')
  const [justImportedIds, setJustImportedIds] = useState<Set<string>>(new Set())
  const [importProgress, setImportProgress] = useState<{
    completed: number
    total: number
    message: string
  } | null>(null)
  const [chunkPreview, setChunkPreview] = useState<{
    index: number
    snippet: EvidenceSnippet
  } | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const activeRequestRef = useRef<ActiveChatRequest | null>(null)

  const libraryIds = useMemo(() => {
    const ids = new Set(libraryPapers.map((p) => p.paper_id))
    for (const id of justImportedIds) ids.add(id)
    return ids
  }, [libraryPapers, justImportedIds])

  const scopeCount = selectedPaperIds.length + selectedFolderIds.length
  const scopeActive = scopeCount > 0
  const scopeHint =
    selectedPaperIds.length > 0
      ? `已勾选 ${selectedPaperIds.length} 篇论文`
      : selectedFolderIds.length > 0
        ? `已勾选 ${selectedFolderIds.length} 个文件夹`
        : '未勾选范围 · 问答将检索全库'
  const scopeDetail =
    libraryPapers.length > 0 ? `库中 ${libraryPapers.length} 篇` : ''

  const papersById = useMemo(() => {
    const map = new Map<string, Paper>()
    for (const p of libraryPapers) map.set(p.paper_id, p)
    return map
  }, [libraryPapers])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, pendingUser, thinkingSteps])

  useEffect(() => {
    setPendingImport({})
  }, [messages])

  useEffect(() => {
    if (!loading || !pendingUser) return
    const startedAt = Date.now()
    setThinkingElapsed(0)
    const timer = window.setInterval(() => {
      setThinkingElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [loading, pendingUser])

  const stopActiveChat = useCallback(() => {
    const active = activeRequestRef.current
    if (!active || active.controller.signal.aborted) return
    setStopping(true)
    active.controller.abort()
    void cancelChatTask(active.requestId).catch(() => {
      // The aborted SSE connection also cancels the server task.
    })
  }, [])

  useEffect(() => {
    if (!loading || !pendingUser) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        stopActiveChat()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [loading, pendingUser, stopActiveChat])

  useEffect(
    () => () => {
      const active = activeRequestRef.current
      if (!active) return
      active.controller.abort()
      void cancelChatTask(active.requestId).catch(() => undefined)
    },
    [],
  )

  useEffect(() => {
    if (selectedFolderIds[0] && folders.some((f) => f.folder_id === selectedFolderIds[0])) {
      setImportTarget(selectedFolderIds[0])
    }
  }, [selectedFolderIds, folders])

  const remainingPapers = (papers: Paper[]) =>
    papers.filter((p) => !libraryIds.has(p.paper_id))

  const askWith = async (raw: string) => {
    const q = raw.trim()
    if (!q || loading) return
    const requestId = createRequestId()
    const controller = new AbortController()
    const activeRequest: ActiveChatRequest = { requestId, controller }
    activeRequestRef.current = activeRequest
    setQuestion('')
    setPendingUser(q)
    setLoading(true)
    setStopping(false)
    setThinkingSteps([{ id: 'connect', message: '正在连接助手…' }])
    setError('')
    setCancelNotice('')
    try {
      const resp = await chatStream(
        {
          question: q,
          request_id: requestId,
          session_id: sessionId,
          paper_ids: selectedPaperIds,
          folder_ids: selectedFolderIds,
          llm_config: llmConfig,
        },
        {
          signal: controller.signal,
          onStarted: (event) => {
            if (activeRequestRef.current?.requestId !== requestId) return
            activeRequest.sessionId = event.session_id
            onSessionChange(event.session_id)
          },
          onProgress: (ev) => {
            setThinkingSteps((prev) => {
              const id = ev.step || ev.message
              const current = prev[prev.length - 1]
              if (current?.id === id) {
                if (current.message === ev.message) return prev
                return [...prev.slice(0, -1), { id, message: ev.message }]
              }
              if (current?.message === ev.message) return prev
              return [...prev, { id, message: ev.message }]
            })
          },
        },
      )
      onSessionChange(resp.session_id)
      await onMessagesReload(resp.session_id)
      setPendingUser(null)
      setThinkingSteps([])
    } catch (e) {
      setPendingUser(null)
      setThinkingSteps([])
      const cancelled = controller.signal.aborted || e instanceof ChatCancelledError
      if (cancelled) {
        const cancelledSessionId =
          (e instanceof ChatCancelledError ? e.sessionId : undefined) ||
          activeRequest.sessionId
        setCancelNotice('已停止生成')
        if (cancelledSessionId) {
          onSessionChange(cancelledSessionId)
          try {
            await onMessagesReload(cancelledSessionId)
          } catch (reloadError) {
            setError(
              reloadError instanceof Error ? reloadError.message : String(reloadError),
            )
          }
        } else {
          setQuestion(q)
        }
      } else {
        setQuestion(q)
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      if (activeRequestRef.current?.requestId === requestId) {
        activeRequestRef.current = null
      }
      setLoading(false)
      setStopping(false)
    }
  }

  const onAsk = async () => {
    await askWith(question)
  }

  const onSkill = (skill: Skill) => {
    if (skill.needsScope && scopeCount === 0) {
      setError(`「${skill.label}」需要先在知识库勾选论文或文件夹`)
      return
    }
    setError('')
    if (skill.send) {
      void askWith(skill.prompt)
      return
    }
    setQuestion(skill.prompt)
    inputRef.current?.focus()
  }

  const onSuggestion = (text: string) => {
    setError('')
    setQuestion(text)
    inputRef.current?.focus()
  }

  const toggleProposed = (id: string) => {
    setPendingImport((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const toggleSelectAll = (papers: Paper[]) => {
    const allOn = papers.length > 0 && papers.every((p) => pendingImport[p.paper_id])
    if (allOn) {
      setPendingImport((prev) => {
        const next = { ...prev }
        for (const p of papers) delete next[p.paper_id]
        return next
      })
      return
    }
    setPendingImport((prev) => {
      const next = { ...prev }
      for (const p of papers) next[p.paper_id] = true
      return next
    })
  }

  const resolveFolderId = async (): Promise<string | null> => {
    if (importTarget === '__new__') {
      const name = newFolderName.trim()
      if (!name) {
        throw new Error('请填写新文件夹名称')
      }
      const folder = await onCreateFolder(name)
      setImportTarget(folder.folder_id)
      setNewFolderName('')
      return folder.folder_id
    }
    return importTarget || null
  }

  const importSelected = async (papers: Paper[]) => {
    const chosen = papers.filter((p) => pendingImport[p.paper_id])
    if (!chosen.length) {
      setError('请先勾选要导入的论文')
      return
    }
    setLoading(true)
    setError('')
    setImportProgress({ completed: 0, total: chosen.length, message: '准备导入…' })
    try {
      const folderId = await resolveFolderId()
      await importPapersStream(chosen, folderId, (ev) => {
        setImportProgress({
          completed: ev.completed,
          total: ev.total,
          message: ev.message,
        })
      })
      setJustImportedIds((prev) => {
        const next = new Set(prev)
        for (const p of chosen) next.add(p.paper_id)
        return next
      })
      setPendingImport({})
      await onLibraryReload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setImportProgress(null)
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="panel-head">
        <h2>问答助手</h2>
      </div>

      <div className="chat-stream">
        {messages.length === 0 && !pendingUser && (
          <div className="empty-chat">
            <p className="empty-kicker">Literature RAG</p>
            <h3 className="empty-title">从一篇论文问起，或先检索再入库</h3>
            <div
              className={`scope-badge ${scopeActive ? 'active' : 'idle'}`}
              role="status"
            >
              <span className="scope-badge-dot" aria-hidden="true" />
              <span className="scope-badge-main">{scopeHint}</span>
              {scopeDetail ? (
                <span className="scope-badge-meta">{scopeDetail}</span>
              ) : null}
            </div>
            {!scopeActive && (
              <p className="empty-sub">
                综述 / 对比 / 讲懂这篇会用到左侧勾选；也可先点「找论文」入库。
              </p>
            )}

            <div className="skill-block">
              <div className="suggest-label">技能</div>
              <div className="skill-row">
                {SKILLS.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`skill-chip ${s.needsScope ? 'needs-scope' : ''}`}
                    disabled={loading}
                    onClick={() => onSkill(s)}
                    title={s.desc}
                  >
                    <span className="skill-name">{s.label}</span>
                    <span className="skill-desc">{s.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="suggest-block">
              <div className="suggest-label">猜你想问</div>
              <div className="suggest-row">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="suggest-chip"
                    disabled={loading}
                    onClick={() => onSuggestion(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.message_id} className={`bubble ${m.role}`}>
            {m.role === 'assistant' ? (
              <div className="bubble-content md">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  // Keep cite:// so citation buttons can open chunk preview;
                  // defaultUrlTransform strips unknown protocols → empty href → SPA reload/"首页".
                  urlTransform={(url) =>
                    url.startsWith('cite://') ? url : defaultUrlTransform(url)
                  }
                  components={citationMarkdownComponents(
                    m.meta?.evidence,
                    (index) => {
                      const snippet = m.meta?.evidence?.[index]
                      if (snippet) setChunkPreview({ index: index + 1, snippet })
                    },
                  )}
                >
                  {prepareAssistantMarkdown(m.content, m.meta?.evidence)}
                </ReactMarkdown>
              </div>
            ) : (
              <pre className="bubble-content">{m.content}</pre>
            )}
            {m.role === 'assistant' && m.meta?.citations?.length ? (
              <CitationBlock citations={m.meta.citations} papersById={papersById} />
            ) : null}
            {m.role === 'assistant' && (m.meta?.proposed_papers?.length || 0) > 0
              ? (() => {
                  const all = m.meta!.proposed_papers!
                  const left = remainingPapers(all)
                  if (left.length > 0) {
                    return (
                      <ProposeBlock
                        papers={left}
                        folders={folders}
                        pendingImport={pendingImport}
                        importTarget={importTarget}
                        newFolderName={newFolderName}
                        loading={loading}
                        importProgress={importProgress}
                        onToggle={toggleProposed}
                        onSelectAll={() => toggleSelectAll(left)}
                        onImportTargetChange={setImportTarget}
                        onNewFolderNameChange={setNewFolderName}
                        onImport={() => void importSelected(left)}
                      />
                    )
                  }
                  return <ImportedPaperList papers={all} />
                })()
              : null}
          </div>
        ))}
        {pendingUser && (
          <div className="bubble user pending">
            <pre className="bubble-content">{pendingUser}</pre>
          </div>
        )}
        {loading && pendingUser && (
          <div className="bubble assistant thinking-bubble">
            <div className="thinking-head">
              <span className="thinking-label">思考中</span>
              <span className="thinking-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            </div>
            {thinkingSteps.length > 0 && (
              <ol className="thinking-steps" aria-live="polite">
                {thinkingSteps.map((step, i) => {
                  const isCurrent = i === thinkingSteps.length - 1
                  const { label, detail } = presentThinkingStep(step.message)
                  return (
                    <li key={`${i}-${step.id}`} className={isCurrent ? 'current' : 'done'}>
                      <span
                        className={`thinking-step-mark ${isCurrent ? 'spin' : ''}`}
                        aria-hidden="true"
                      >
                        {isCurrent ? '' : '✓'}
                      </span>
                      <span className="thinking-step-text">
                        <span className="thinking-step-main">{label}</span>
                        {detail && <span className="thinking-step-detail">{detail}</span>}
                        {isCurrent && thinkingElapsed > 0 && (
                          <span className="thinking-step-elapsed">
                            {formatElapsed(thinkingElapsed)}
                          </span>
                        )}
                      </span>
                    </li>
                  )
                })}
              </ol>
            )}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="error chat-error">{error}</p>}
      {cancelNotice && (
        <p className="chat-notice" role="status">
          {cancelNotice}
        </p>
      )}

      {chunkPreview && (
        <ChunkPreviewModal
          index={chunkPreview.index}
          snippet={chunkPreview.snippet}
          paper={papersById.get(chunkPreview.snippet.paper_id)}
          onClose={() => setChunkPreview(null)}
        />
      )}

      <div className="composer-wrap">
        {(messages.length > 0 || pendingUser) && (
          <div className="composer-skills">
            {SKILLS.map((s) => (
              <button
                key={s.id}
                type="button"
                className="suggest-chip compact"
                disabled={loading}
                onClick={() => onSkill(s)}
                title={s.desc}
              >
                {s.label}
              </button>
            ))}
            <span
              className={`scope-badge compact ${scopeActive ? 'active' : 'idle'}`}
              role="status"
              title={scopeHint}
            >
              <span className="scope-badge-dot" aria-hidden="true" />
              <span className="scope-badge-main">{scopeHint}</span>
            </span>
          </div>
        )}
        <div className="composer">
          <textarea
            ref={inputRef}
            rows={3}
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value)
              setCancelNotice('')
            }}
            placeholder="输入问题，点上方 Skill，或让我帮你找相关论文…"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return
                e.preventDefault()
                void onAsk()
              }
            }}
          />
          <button
            type="button"
            className={loading && pendingUser ? 'is-stop' : ''}
            onClick={loading && pendingUser ? stopActiveChat : () => void onAsk()}
            disabled={loading && pendingUser ? stopping : loading || !question.trim()}
            aria-label={loading && pendingUser ? '停止生成' : '发送'}
            title={loading && pendingUser ? '停止生成（Esc）' : '发送'}
          >
            {loading && pendingUser ? (
              <>
                <Square size={13} fill="currentColor" aria-hidden="true" />
                {stopping ? '停止中' : '停止'}
              </>
            ) : (
              '发送'
            )}
          </button>
        </div>
      </div>
    </section>
  )
}

function ProposeBlock({
  papers,
  folders,
  pendingImport,
  importTarget,
  newFolderName,
  loading,
  importProgress,
  onToggle,
  onSelectAll,
  onImportTargetChange,
  onNewFolderNameChange,
  onImport,
}: {
  papers: Paper[]
  folders: Folder[]
  pendingImport: Record<string, boolean>
  importTarget: string
  newFolderName: string
  loading: boolean
  importProgress: { completed: number; total: number; message: string } | null
  onToggle: (id: string) => void
  onSelectAll: () => void
  onImportTargetChange: (value: string) => void
  onNewFolderNameChange: (value: string) => void
  onImport: () => void
}) {
  const selectedCount = papers.filter((p) => pendingImport[p.paper_id]).length
  const allSelected = papers.length > 0 && selectedCount === papers.length
  const pct =
    importProgress && importProgress.total > 0
      ? Math.min(100, Math.round((importProgress.completed / importProgress.total) * 100))
      : 0

  return (
    <div className="propose-inline">
      <div className="propose-toolbar">
        <label className="select-all">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={onSelectAll}
            disabled={loading}
          />
          <span>全选</span>
          <span className="propose-count">
            {selectedCount}/{papers.length}
          </span>
        </label>
        <button className="btn-sm accent" onClick={onImport} disabled={loading || selectedCount === 0}>
          {importProgress ? `导入中 ${importProgress.completed}/${importProgress.total}` : '导入选中'}
        </button>
      </div>

      {importProgress && (
        <div className="import-progress" aria-live="polite">
          <div className="import-progress-track">
            <div className="import-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="import-progress-meta">
            <span className="import-progress-pct">{pct}%</span>
            <span className="import-progress-msg">{importProgress.message}</span>
          </div>
        </div>
      )}

      <div className="propose-dest">
        <span className="propose-dest-label">导入到</span>
        <select
          value={importTarget}
          onChange={(e) => onImportTargetChange(e.target.value)}
          disabled={loading}
        >
          <option value="">未分类</option>
          {folders.map((f) => (
            <option key={f.folder_id} value={f.folder_id}>
              {f.name}
            </option>
          ))}
          <option value="__new__">新建文件夹…</option>
        </select>
        {importTarget === '__new__' && (
          <input
            className="propose-new-folder"
            value={newFolderName}
            onChange={(e) => onNewFolderNameChange(e.target.value)}
            placeholder="文件夹名称"
            disabled={loading}
          />
        )}
      </div>

      <ul className="propose-list">
        {papers.map((p) => {
          const origin = resolvePaperUrl(p)
          return (
            <li key={p.paper_id}>
              <label>
                <input
                  type="checkbox"
                  checked={!!pendingImport[p.paper_id]}
                  onChange={() => onToggle(p.paper_id)}
                />
                <span>
                  {p.title}
                  <em>
                    {p.year ? ` (${p.year})` : ''} · {p.source}
                    {origin ? (
                      <>
                        {' · '}
                        <a
                          className="cite-origin"
                          href={origin}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          原文
                        </a>
                      </>
                    ) : null}
                  </em>
                </span>
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function ImportedPaperList({ papers }: { papers: Paper[] }) {
  return (
    <div className="propose-inline is-done">
      <div className="propose-toolbar">
        <span className="propose-done-label">已导入知识库 · {papers.length} 篇</span>
      </div>
      <ul className="propose-list readonly">
        {papers.map((p) => {
          const origin = resolvePaperUrl(p)
          return (
            <li key={p.paper_id}>
              <span className="propose-title">
                {p.title}
                <em>
                  {p.year ? ` (${p.year})` : ''} · {p.source}
                  {origin ? (
                    <>
                      {' · '}
                      <a className="cite-origin" href={origin} target="_blank" rel="noreferrer">
                        原文
                      </a>
                    </>
                  ) : null}
                </em>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function normalizeAssistantMarkdown(content: string): string {
  return content
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?(?:div|span|p)[^>]*>/gi, '')
}

/**
 * Turn [n] into cite:// links so GFM won't parse [7][10] as reference links.
 * Click opens the retrieved RAG chunk preview.
 */
function prepareAssistantMarkdown(
  content: string,
  evidence: EvidenceSnippet[] | undefined,
): string {
  let text = normalizeAssistantMarkdown(content)
  if (!evidence?.length) {
    return text.replace(/\](\s*)\[(\d+)\]/g, ']\u200B$1[$2]')
  }
  return text.replace(/\[(\d+)\]/g, (_full, n: string) => {
    const idx = Number(n) - 1
    const cite = evidence[idx]
    if (!cite?.paper_id) return `[${n}]`
    const tip = `查看证据片段：${(cite.title || cite.paper_id).replace(/[[\]()"]/g, '')}`
    return `[\\[${n}\\]](cite://${n} "${tip}")`
  })
}

function citationMarkdownComponents(
  evidence: EvidenceSnippet[] | undefined,
  onOpenCite: (zeroBasedIndex: number) => void,
) {
  return {
    a: ({
      href,
      title,
      children,
    }: {
      href?: string
      title?: string
      children?: ReactNode
    }) => {
      if (href?.startsWith('cite://')) {
        const n = Number(href.slice('cite://'.length))
        const idx = n - 1
        const hasChunk = Boolean(evidence?.[idx]?.text || evidence?.[idx]?.paper_id)
        return (
          <button
            type="button"
            className="cite-mark link cite-btn"
            title={title || `查看证据 [${n}]`}
            disabled={!hasChunk}
            onClick={(e) => {
              e.preventDefault()
              if (hasChunk) onOpenCite(idx)
            }}
          >
            {children}
          </button>
        )
      }
      return (
        <a href={href} title={title} target="_blank" rel="noreferrer">
          {children}
        </a>
      )
    },
    table: ({ children }: { children?: ReactNode }) => (
      <div className="md-table-wrap">
        <table>{children}</table>
      </div>
    ),
  }
}

function ChunkPreviewModal({
  index,
  snippet,
  paper,
  onClose,
}: {
  index: number
  snippet: EvidenceSnippet
  paper?: Paper
  onClose: () => void
}) {
  const origin = resolvePaperUrl(paper || { paper_id: snippet.paper_id })
  const year = snippet.year ? ` (${snippet.year})` : ''
  return (
    <div className="modal-mask chunk-modal-mask" onClick={onClose}>
      <div
        className="modal-card chunk-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="chunk-preview-title"
      >
        <h3 id="chunk-preview-title">证据片段 [{index}]</h3>
        <p className="chunk-meta">
          <span className="chunk-paper-title">
            {snippet.title || paper?.title || snippet.paper_id}
            {year}
          </span>
          {origin ? (
            <a className="cite-origin" href={origin} target="_blank" rel="noreferrer">
              原文
            </a>
          ) : null}
        </p>
        {snippet.chunk_id ? (
          <p className="chunk-id muted">chunk: {snippet.chunk_id}</p>
        ) : null}
        <div className="chunk-text">
          {formatChunkText(snippet.text) ||
            '（此条旧消息未保存片段正文，请重新提问以查看完整 chunk）'}
        </div>
        <div className="modal-actions">
          <button className="btn-sm accent" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}

function CitationBlock({
  citations,
  papersById,
}: {
  citations: Citation[]
  papersById: Map<string, Paper>
}) {
  return (
    <ul className="citation-list compact">
      {citations.map((c) => {
        const origin = resolvePaperUrl(papersById.get(c.paper_id) || { paper_id: c.paper_id })
        return (
          <li key={c.paper_id}>
            <span className="cite-title">{c.title}</span>
            {c.year ? <span className="cite-year"> ({c.year})</span> : null}
            {origin ? (
              <>
                {' '}
                <a className="cite-origin" href={origin} target="_blank" rel="noreferrer">
                  原文
                </a>
              </>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
