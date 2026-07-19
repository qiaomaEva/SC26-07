from typing import Any, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Paper(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: str = "semanticscholar"
    folder_id: Optional[str] = None
    created_at: Optional[str] = None


class Folder(BaseModel):
    folder_id: str
    name: str
    created_at: Optional[str] = None
    paper_count: int = 0


class Citation(BaseModel):
    paper_id: str
    title: str
    year: Optional[int] = None


class EvidenceSnippet(BaseModel):
    """One retrieved chunk; evidence[i] ↔ answer marker [i+1]."""

    paper_id: str
    title: str
    year: Optional[int] = None
    chunk_id: str = ""
    text: str = ""
    score: float = 0.0


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    papers: list[Paper]


class ImportRequest(BaseModel):
    papers: list[Paper]
    folder_id: Optional[str] = None


class ImportResponse(BaseModel):
    imported: int
    paper_ids: list[str]


class PaperChunk(BaseModel):
    chunk_id: str
    paper_id: str
    chunk_index: int
    text: str
    token_est: int = 0


class PaperChunksResponse(BaseModel):
    paper_id: str
    title: str
    year: Optional[int] = None
    chunks: list[PaperChunk] = Field(default_factory=list)


class LibraryResponse(BaseModel):
    papers: list[Paper]
    folders: list[Folder] = Field(default_factory=list)




class Note(BaseModel):
    note_id: str = ""
    title: str = ""
    content: str = ""
    pinned: bool = False
    created_at: str = ""
    updated_at: str = ""


class CreateNoteRequest(BaseModel):
    title: str = "Untitled"
    content: str = ""


class UpdateNoteRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    pinned: bool | None = None


class CreateFolderRequest(BaseModel):
    name: str


class MovePaperRequest(BaseModel):
    folder_id: Optional[str] = None


class ChatSession(BaseModel):
    session_id: str
    title: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RenameSessionRequest(BaseModel):
    title: str


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    api_key: str = Field(min_length=1, max_length=4096, repr=False)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    timeout_seconds: float = Field(default=30, ge=5, le=300)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be a valid HTTP(S) URL")
        return value.rstrip("/")


class LLMTestResponse(BaseModel):
    ok: bool
    model: str
    message: str


class ChatRequest(BaseModel):
    question: str
    request_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    session_id: Optional[str] = None
    paper_ids: list[str] = Field(default_factory=list)
    folder_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=6, ge=1, le=20)
    llm_config: Optional[LLMConfig] = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    paper_id: str
    title: str
    year: Optional[int] = None
    text: str
    score: float = 0.0


class ChatResponse(BaseModel):
    session_id: str
    intent: Literal["qa", "search"] = "qa"
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    # Parallel to answer [n]: evidence[0] ↔ [1], includes chunk text for UI
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    proposed_papers: list[Paper] = Field(default_factory=list)
