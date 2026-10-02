/**
 * TypeScript mirror of the backend's API contracts (FastAPI / Pydantic schemas).
 * Keep in sync with the backend's app/schemas/*.py.
 */

export type Severity = 'low' | 'medium' | 'high'

/** What the diagnosis was grounded on. */
export type DiagnosisBasis = 'similar_cases' | 'general_reasoning'

/** A knowledge-base record returned by the similarity search. */
export interface SimilarCase {
  id: string
  equipment_type: string
  issue_description: string
  root_cause: string
  recommended_fix: string
  severity: string
  /** Cosine similarity, 0-1. */
  similarity_score: number
}

// --- POST /api/v1/diagnose ----------------------------------------------------
export interface DiagnoseRequest {
  /** 10-2000 characters after trimming. */
  description: string
}

export interface DiagnoseResponse {
  /** False when the input is not an equipment problem; then nothing was stored. */
  is_valid_issue: boolean
  /** null when is_valid_issue is false. */
  ticket_id: number | null
  /** null when is_valid_issue is false. */
  severity: Severity | null
  diagnosis: string
  recommended_action: string
  /** 0-1. Retrieval similarity of the best past case: how well the knowledge base covers this issue. */
  retrieval_confidence: number
  /** 0-1. The LLM's own self-reported certainty in its diagnosis, independent of any retrieval match. */
  llm_confidence: number
  /** True when the model gave no usable number and `llm_confidence` is just the 0.5 default. */
  llm_confidence_defaulted?: boolean
  /** @deprecated Alias of `retrieval_confidence`, kept by the backend for compatibility. */
  confidence_score: number
  /** Can be empty (always empty when is_valid_issue is false). */
  similar_cases: SimilarCase[]
  diagnosis_basis: DiagnosisBasis
  note: string | null
}

// --- POST /api/v1/diagnose-image (AI visual assessment by a vision-language model) ---
export interface ImageDiagnoseResponse {
  /** False when the photo does not show equipment; then nothing was stored. */
  is_equipment_photo: boolean
  /** null when is_equipment_photo is false. */
  ticket_id: number | null
  damage_detected: boolean
  /** null when is_equipment_photo is false. */
  severity: Severity | null
  /** What the model sees: its findings. */
  description: string
  recommended_action: string
  /** 0-1, the model's self-reported certainty; null if it gave no usable number. */
  confidence: number | null
  model_name: string
  provider: string
  /** Set when the photo was not stored. */
  note: string | null
}

// --- GET /api/v1/history ------------------------------------------------------------
export interface HistoryItem {
  id: number
  /** ISO-8601 UTC timestamp. */
  created_at: string
  source: 'text' | 'image'
  description: string
  severity: Severity
  diagnosis: string
  recommended_action: string
  confidence_score: number
  /** Technician feedback, or null if none was given yet. */
  feedback_was_correct: boolean | null
}

export interface HistoryPage {
  items: HistoryItem[]
  total: number
  /** 1-based. */
  page: number
  page_size: number
  total_pages: number
}

// --- POST /api/v1/feedback ------------------------------------------------------------
export interface FeedbackRequest {
  ticket_id: number
  was_correct: boolean
}

export interface FeedbackResponse {
  id: number
  ticket_id: number
  was_correct: boolean
  created_at: string
}

// --- GET /health -------------------------------------------------------------------------
export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  database: 'ok' | 'error'
  vector_store: 'ok' | 'error'
  llm: 'ok' | 'error'
  knowledge_base_size: number
}

// --- Error envelope (every non-2xx response from the backend) -------------------------------
export interface FieldError {
  /** Dotted path of the invalid field, e.g. "description". */
  field: string
  message: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    /** Present on 422 validation errors. */
    details?: FieldError[]
    /** Present on 500s; quote it when reporting a problem. */
    request_id?: string
  }
}
