export type Paper = {
  paper_id: string
  title: string
  authors: string[]
  year?: number | null
  abstract?: string | null
  url?: string | null
  pdf_url?: string | null
  source: string
  folder_id?: string | null
  created_at?: string | null
}

export type Folder = {
  folder_id: string
  name: string
  created_at?: string | null
  paper_count: number
}

export type Citation = {
  paper_id: string
  title: string
  year?: number | null
}

/** Per-chunk RAG evidence: evidence[i] ↔ answer marker [i+1]. */
export type EvidenceSnippet = {
  paper_id: string
  title: string
  year?: number | null
  chunk_id?: string
  text?: string
  score?: number
}

export type PaperChunk = {
  chunk_id: string
  paper_id: string
  chunk_index: number
  text: string
  token_est: number
}

export type PaperChunksResponse = {
  paper_id: string
  title: string
  year?: number | null
  chunks: PaperChunk[]
}

export type ChatSession = {
  session_id: string
  title: string
  created_at?: string | null
  updated_at?: string | null
}

export type ChatMessage = {
  message_id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  meta?: {
    intent?: string
    proposed_papers?: Paper[]
    /** Unique source papers (footer). */
    citations?: Citation[]
    /** Per-chunk evidence: evidence[i] ↔ answer marker [i+1]. */
    evidence?: EvidenceSnippet[]
  }
  created_at?: string | null
}

export type ChatResponse = {
  session_id: string
  intent: 'qa' | 'search'
  answer: string
  citations: Citation[]
  proposed_papers: Paper[]
}

export type LLMConfig = {
  api_key: string
  base_url: string
  model: string
  timeout_seconds: number
}

export type LLMTestResponse = {
  ok: boolean
  model: string
  message: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { 'Content-Type': 'application/json' }),
      ...(init?.headers || {}),
    },
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      // ignore
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return resp.json() as Promise<T>
}

export function listLibrary() {
  return request<{ papers: Paper[]; folders: Folder[] }>('/library')
}

export function searchPapers(query: string, limit = 10) {
  return request<{ papers: Paper[] }>('/search', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  })
}

export function createFolder(name: string) {
  return request<Folder>('/library/folders', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function deleteFolder(folderId: string) {
  return request<{ ok: boolean }>(`/library/folders/${folderId}`, {
    method: 'DELETE',
  })
}

export function movePaper(paperId: string, folderId: string | null) {
  return request<Paper>(`/library/papers/${paperId}/folder`, {
    method: 'PATCH',
    body: JSON.stringify({ folder_id: folderId }),
  })
}

export function listPaperChunks(paperId: string) {
  return request<PaperChunksResponse>(`/library/papers/${paperId}/chunks`)
}

export function importPapers(papers: Paper[], folderId?: string | null) {
  return request<{ imported: number; paper_ids: string[] }>('/library/import', {
    method: 'POST',
    body: JSON.stringify({ papers, folder_id: folderId || null }),
  })
}

export type ImportProgressEvent = {
  type: 'progress'
  current: number
  total: number
  completed: number
  title: string
  stage: string
  message: string
}

export async function importPapersStream(
  papers: Paper[],
  folderId: string | null | undefined,
  onProgress?: (ev: ImportProgressEvent) => void,
): Promise<{ imported: number; paper_ids: string[] }> {
  const resp = await fetch('/api/library/import/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ papers, folder_id: folderId || null }),
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      // ignore
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (!resp.body) throw new Error('stream unavailable')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: { imported: number; paper_ids: string[] } | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const dataLine = part
        .split('\n')
        .map((l) => l.trimEnd())
        .find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const raw = dataLine.slice(5).trim()
      if (!raw) continue
      let event: {
        type: string
        message?: string
        response?: { imported: number; paper_ids: string[] }
        current?: number
        total?: number
        completed?: number
        title?: string
        stage?: string
      }
      try {
        event = JSON.parse(raw)
      } catch {
        continue
      }
      if (event.type === 'progress') {
        onProgress?.({
          type: 'progress',
          current: event.current ?? 0,
          total: event.total ?? papers.length,
          completed: event.completed ?? 0,
          title: event.title || '',
          stage: event.stage || '',
          message: event.message || '',
        })
      } else if (event.type === 'done' && event.response) {
        final = event.response
      } else if (event.type === 'error') {
        throw new Error(event.message || 'import stream failed')
      }
    }
  }

  if (!final) throw new Error('import stream ended without response')
  return final
}

export function uploadPdf(file: File, folderId?: string | null, title?: string) {
  const form = new FormData()
  form.append('file', file)
  if (folderId) form.append('folder_id', folderId)
  if (title) form.append('title', title)
  return request<Paper>('/library/upload-pdf', {
    method: 'POST',
    body: form,
  })
}

export function listSessions() {
  return request<ChatSession[]>('/sessions')
}

export function createSession() {
  return request<ChatSession>('/sessions', { method: 'POST' })
}

export function deleteSession(sessionId: string) {
  return request<{ ok: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' })
}

export function renameSession(sessionId: string, title: string) {
  return request<ChatSession>(`/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export function listMessages(sessionId: string) {
  return request<ChatMessage[]>(`/sessions/${sessionId}/messages`)
}

export function chat(payload: {
  question: string
  request_id?: string
  session_id?: string | null
  paper_ids?: string[]
  folder_ids?: string[]
  top_k?: number
  llm_config?: LLMConfig
}) {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type ChatProgressEvent = {
  type: 'progress'
  step?: string
  message: string
}

export type ChatStartedEvent = {
  type: 'started'
  request_id: string
  session_id: string
}

export class ChatCancelledError extends Error {
  sessionId?: string

  constructor(message = '已停止生成', sessionId?: string) {
    super(message)
    this.name = 'ChatCancelledError'
    this.sessionId = sessionId
  }
}

export type ChatStreamHandlers = {
  signal?: AbortSignal
  onStarted?: (event: ChatStartedEvent) => void
  onProgress?: (event: ChatProgressEvent) => void
}

/** SSE chat: progress steps then final ChatResponse. */
export async function chatStream(
  payload: {
    question: string
    request_id?: string
    session_id?: string | null
    paper_ids?: string[]
    folder_ids?: string[]
    top_k?: number
    llm_config?: LLMConfig
  },
  handlers: ChatStreamHandlers = {},
): Promise<ChatResponse> {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: handlers.signal,
  })
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      // ignore
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (!resp.body) {
    throw new Error('stream unavailable')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: ChatResponse | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const dataLine = part
        .split('\n')
        .map((l) => l.trimEnd())
        .find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const raw = dataLine.slice(5).trim()
      if (!raw) continue
      let event: {
        type: string
        message?: string
        step?: string
        request_id?: string
        session_id?: string
        response?: ChatResponse
      }
      try {
        event = JSON.parse(raw)
      } catch {
        continue
      }
      if (
        event.type === 'started' &&
        event.request_id &&
        event.session_id
      ) {
        handlers.onStarted?.({
          type: 'started',
          request_id: event.request_id,
          session_id: event.session_id,
        })
      } else if (event.type === 'progress' && event.message) {
        handlers.onProgress?.({
          type: 'progress',
          step: event.step,
          message: event.message,
        })
      } else if (event.type === 'done' && event.response) {
        final = event.response
      } else if (event.type === 'error') {
        throw new Error(event.message || 'chat stream failed')
      } else if (event.type === 'cancelled') {
        throw new ChatCancelledError(
          event.message || '已停止生成',
          event.session_id,
        )
      }
    }
  }

  if (!final) {
    throw new Error('stream ended without response')
  }
  return final
}

export function cancelChatTask(requestId: string) {
  return request<{ ok: boolean; cancelled: boolean; request_id: string }>(
    `/chat/tasks/${encodeURIComponent(requestId)}`,
    { method: 'DELETE' },
  )
}

export async function testModel(config: LLMConfig) {
  const controller = new AbortController()
  const timeoutMs = config.timeout_seconds * 1000
  const timer = window.setTimeout(() => controller.abort(), timeoutMs + 1500)

  try {
    return await request<LLMTestResponse>('/model/test', {
      method: 'POST',
      body: JSON.stringify(config),
      signal: controller.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`模型连接超时：超过 ${config.timeout_seconds} 秒未返回结果`)
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export type Note = {
  note_id: string
  title: string
  content: string
  pinned: boolean
  created_at: string
  updated_at: string
}

export async function listNotes(): Promise<Note[]> {
  const resp = await fetch("/api/notes")
  if (!resp.ok) return []
  return resp.json()
}

export async function createNote(title?: string, content?: string): Promise<Note> {
  try {
  const resp = await fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || "Untitled", content: content || "" }),
  })
  if (!resp.ok) throw new Error()
  return resp.json()
  } catch { return { note_id: "", title: "Untitled", content: "", pinned: false, created_at: "", updated_at: "" } as Note }
}

export async function updateNote(noteId: string, data: { title?: string; content?: string; pinned?: boolean }): Promise<Note | null> {
  try {
  const resp = await fetch("/api/notes/" + noteId, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!resp.ok) throw new Error()
  return resp.json()
  } catch { return { note_id: "", title: "Untitled", content: "", pinned: false, created_at: "", updated_at: "" } as Note }
}

export async function deleteNote(noteId: string): Promise<void> {
  try { await fetch("/api/notes/" + noteId, { method: "DELETE" }) } catch {}
}
