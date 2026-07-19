import { useCallback, useEffect, useState } from 'react'
import { Database, FileText, MessageSquare, Settings } from 'lucide-react'
import {
  createFolder,
  createSession,
  deleteFolder,
  deleteSession,
  listLibrary,
  listMessages,
  listSessions,
  movePaper,
  renameSession,
  uploadPdf,
  type ChatMessage,
  type ChatSession,
  type Folder,
  type LLMConfig,
  type Paper,
} from './api/client'
import { ChatPanel } from './components/ChatPanel'
import { HistoryPanel } from './components/HistoryPanel'
import { KnowledgePanel } from './components/KnowledgePanel'
import { ModelSettingsModal } from './components/ModelSettingsModal'
import { NotesModal } from './components/NotesModal'
import { PdfViewer } from './components/PdfViewer'
import './App.css'

const MODEL_CONFIG_KEY = 'literature-rag.llm-config'
const DEFAULT_MODEL_CONFIG: LLMConfig = {
  api_key: '',
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  timeout_seconds: 30,
}

function loadModelConfig(): LLMConfig {
  try {
    const stored = sessionStorage.getItem(MODEL_CONFIG_KEY)
    if (!stored) return DEFAULT_MODEL_CONFIG
    const parsed = JSON.parse(stored) as Partial<LLMConfig>
    return {
      api_key: typeof parsed.api_key === 'string' ? parsed.api_key : '',
      base_url:
        typeof parsed.base_url === 'string' ? parsed.base_url : DEFAULT_MODEL_CONFIG.base_url,
      model: typeof parsed.model === 'string' ? parsed.model : DEFAULT_MODEL_CONFIG.model,
      timeout_seconds:
        typeof parsed.timeout_seconds === 'number'
          ? parsed.timeout_seconds
          : DEFAULT_MODEL_CONFIG.timeout_seconds,
    }
  } catch {
    return DEFAULT_MODEL_CONFIG
  }
}

function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [folders, setFolders] = useState<Folder[]>([])
  const [papers, setPapers] = useState<Paper[]>([])
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(new Set())
  const [selectedFolderIds, setSelectedFolderIds] = useState<Set<string>>(new Set())
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [leftTab, setLeftTab] = useState<'history' | 'knowledge'>('history')
  const [viewPdfPaper, setViewPdfPaper] = useState<{ id: string; title: string; pdfUrl?: string | null } | null>(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const [modelConfig, setModelConfig] = useState<LLMConfig>(loadModelConfig)
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false)

  const modelConfigured = Boolean(
    modelConfig.api_key.trim() && modelConfig.base_url.trim() && modelConfig.model.trim(),
  )

  const reloadSessions = useCallback(async () => {
    const data = await listSessions()
    setSessions(data)
  }, [])

  const reloadLibrary = useCallback(async () => {
    const data = await listLibrary()
    setPapers(data.papers)
    setFolders(data.folders)
  }, [])

  const reloadMessages = useCallback(async (sessionId: string) => {
    const data = await listMessages(sessionId)
    setMessages(data)
  }, [])

  useEffect(() => {
    void reloadSessions()
    void reloadLibrary()
  }, [reloadSessions, reloadLibrary])

  const onSelectSession = async (id: string) => {
    setActiveSessionId(id)
    await reloadMessages(id)
    await reloadSessions()
  }

  const onNewSession = async () => {
    const s = await createSession()
    setActiveSessionId(s.session_id)
    setMessages([])
    await reloadSessions()
  }

  const onDeleteSession = async (id: string) => {
    await deleteSession(id)
    if (activeSessionId === id) {
      setActiveSessionId(null)
      setMessages([])
    }
    await reloadSessions()
  }

  const togglePaper = (id: string) => {
    const paper = papers.find((p) => p.paper_id === id)
    setSelectedPaperIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)

      if (paper?.folder_id) {
        const folderId = paper.folder_id
        const siblings = papers.filter((p) => p.folder_id === folderId)
        const allOn = siblings.length > 0 && siblings.every((p) => next.has(p.paper_id))
        setSelectedFolderIds((fprev) => {
          const fnext = new Set(fprev)
          if (allOn) fnext.add(folderId)
          else fnext.delete(folderId)
          return fnext
        })
      }
      return next
    })
  }

  const handleViewPdf = (id: string, title: string, pdfUrl?: string | null) => setViewPdfPaper({ id, title, pdfUrl })

  const toggleFolder = (id: string) => {
    const memberIds = papers.filter((p) => p.folder_id === id).map((p) => p.paper_id)
    const selecting = !selectedFolderIds.has(id)
    setSelectedFolderIds((prev) => {
      const next = new Set(prev)
      if (selecting) next.add(id)
      else next.delete(id)
      return next
    })
    setSelectedPaperIds((prev) => {
      const next = new Set(prev)
      for (const pid of memberIds) {
        if (selecting) next.add(pid)
        else next.delete(pid)
      }
      return next
    })
  }

  const gridClass = [
    'workspace-grid',
    leftCollapsed ? 'left-collapsed' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="workspace">
      <header className="topbar">
        <div className="topbar-title">
          <img src="/logo.png" alt="Logo" className="topbar-logo" />
          <div>
            <p className="brand">Literature RAG</p>
            <h1>个人文献助手</h1>
          </div>
        </div>
        <button
          type="button"
          className={`model-settings-trigger ${modelConfigured ? 'is-configured' : ''}`}
          onClick={() => setModelSettingsOpen(true)}
          title="模型设置"
        >
          <span className="model-status-dot" aria-hidden="true" />
          <span className="model-status-label">
            {modelConfigured ? modelConfig.model : 'AI模型'}
          </span>
          <Settings size={16} aria-hidden="true" />
        </button>
      </header>

      <div className={gridClass}>
        <div className="col-icon-rail">
          <button
            type="button"
            className={`icon-rail-btn ${leftTab === 'history' && !leftCollapsed ? 'active' : ''}`}
            title="对话历史"
            onClick={() => {
              setViewPdfPaper(null)
              if (leftTab === 'history' && !leftCollapsed) setLeftCollapsed(true)
              else { setLeftTab('history'); setLeftCollapsed(false) }
            }}
          >
            <MessageSquare size={20} />
          </button>
          <button
            type="button"
            className={`icon-rail-btn ${leftTab === 'knowledge' && !leftCollapsed ? 'active' : ''}`}
            title="知识库"
            onClick={() => {
              setViewPdfPaper(null)
              if (leftTab === 'knowledge' && !leftCollapsed) setLeftCollapsed(true)
              else { setLeftTab('knowledge'); setLeftCollapsed(false) }
            }}
          >
            <Database size={20} />
          </button>
          <button
            type="button"
            className={"icon-rail-btn ${notesOpen ? 'active' : ''}"}
            title="笔记"
            onClick={() => setNotesOpen((v) => !v)}
          >
            <FileText size={20} />
          </button>
        </div>
        <div className={`col-shell ${leftCollapsed ? 'is-collapsed' : ''}`}>
          {!leftCollapsed && (
            leftTab === 'history' ? (
              <HistoryPanel
                sessions={sessions}
                activeId={activeSessionId}
                onSelect={(id) => void onSelectSession(id)}
                onNew={() => void onNewSession()}
                onDelete={(id) => void onDeleteSession(id)}
                onRename={async (id, title) => {
                  await renameSession(id, title)
                  await reloadSessions()
                }}
              />
            ) : (
              <KnowledgePanel
                folders={folders}
                papers={papers}
                selectedPaperIds={selectedPaperIds}
                selectedFolderIds={selectedFolderIds}
                onTogglePaper={togglePaper}
                onToggleFolder={toggleFolder}
                onCreateFolder={async (name) => {
                  await createFolder(name)
                  await reloadLibrary()
                }}
                onDeleteFolder={async (id) => {
                  await deleteFolder(id)
                  setSelectedFolderIds((prev) => {
                    const next = new Set(prev)
                    next.delete(id)
                    return next
                  })
                  await reloadLibrary()
                }}
                onMovePaper={async (paperId, folderId) => {
                  await movePaper(paperId, folderId)
                  await reloadLibrary()
                }}
                onUploadPdf={async (file, folderId) => {
                  await uploadPdf(file, folderId)
                  await reloadLibrary()
                }}

                onRefresh={() => void reloadLibrary()}
                onViewPdf={handleViewPdf}
              />
            )
          )}
        </div>

        {viewPdfPaper ? (
          <PdfViewer
            paperId={viewPdfPaper.id}
            title={viewPdfPaper.title}
            pdfUrl={viewPdfPaper.pdfUrl}
            onClose={() => setViewPdfPaper(null)}
          />
        ) : (
          <ChatPanel
            sessionId={activeSessionId}
            messages={messages}
            folders={folders}
            libraryPapers={papers}
            selectedPaperIds={[...selectedPaperIds]}
            selectedFolderIds={[...selectedFolderIds]}
            llmConfig={modelConfigured ? modelConfig : undefined}
            onSessionChange={(id) => {
              setActiveSessionId(id)
              void reloadSessions()
            }}
            onMessagesReload={async (id) => {
              setActiveSessionId(id)
              await reloadMessages(id)
              await reloadSessions()
            }}
            onLibraryReload={reloadLibrary}
            onCreateFolder={async (name) => {
              const folder = await createFolder(name)
              await reloadLibrary()
              return folder
            }}
          />
        )}
      </div>

      {notesOpen && <NotesModal onClose={() => setNotesOpen(false)} />}

      {modelSettingsOpen && (
        <ModelSettingsModal
          config={modelConfig}
          onSave={(config) => {
            setModelConfig(config)
            sessionStorage.setItem(MODEL_CONFIG_KEY, JSON.stringify(config))
          }}
          onReset={() => {
            setModelConfig(DEFAULT_MODEL_CONFIG)
            sessionStorage.removeItem(MODEL_CONFIG_KEY)
          }}
          onClose={() => setModelSettingsOpen(false)}
        />
      )}
    </div>
  )
}

export default App
