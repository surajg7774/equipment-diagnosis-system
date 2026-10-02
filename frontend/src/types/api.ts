/**
 * TypeScript mirror of the backend's API contracts (FastAPI / Pydantic schemas).
 * Keep in sync with the backend's app/schemas/*.py.
 */

export type Severity = 'low' | 'medium' | 'high'

/** What the diagnosis was grounded on. */
export type DiagnosisBasis = 'similar_cases' | 'general_reasoning'

/** Where a knowledge-base record came from. */
export type KnowledgeBaseSource = 'seed' | 'verified'

/** Where a ticket is in the technician-verification workflow. */
export type ReviewStatus = 'pending' | 'confirmed' | 'corrected'

/** How urgently a pending ticket needs review (medium/high severity first). */
export type ReviewPriority = 'high' | 'low'

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
  /** 'verified' = added from a technician-reviewed ticket. Absent on older backends (= seed). */
  source?: KnowledgeBaseSource
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
  review_status: ReviewStatus
  review_priority: ReviewPriority
  /** The technician's own root cause / fix, shown beside the AI's. Null unless corrected. */
  corrected_root_cause: string | null
  corrected_fix: string | null
  reviewed_at: string | null
  /** The knowledge-base record built from this ticket, once reviewed. */
  kb_record_id: string | null
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

// --- Review workflow + knowledge-base statistics ---------------------------------------------
export interface KnowledgeBaseStats {
  total: number
  seed: number
  verified: number
  verified_confirmed: number
  verified_corrected: number
}

export interface CorrectionInput {
  root_cause: string
  recommended_fix: string
  equipment_type?: string | null
}

export interface ReviewResponse {
  ticket_id: number
  review_status: ReviewStatus
  review_priority: ReviewPriority
  reviewed_at: string | null
  corrected_root_cause: string | null
  corrected_fix: string | null
  added_to_knowledge_base: boolean
  kb_record_id: string | null
  knowledge_base: KnowledgeBaseStats
}

// --- GET /api/v1/stats ----------------------------------------------------------------------
export interface StatsResponse {
  total_diagnoses_performed: number
  text_diagnoses: number
  image_diagnoses: number
  resolution: {
    counted: number
    similar_cases: number
    general_reasoning: number
    /** null when nothing has been counted yet (not 0%). */
    similar_cases_pct: number | null
    general_reasoning_pct: number | null
  }
  /** The three knowledge-base numbers are null if the vector store could not be read. */
  knowledge_base_size: number | null
  original_seed_count: number | null
  technician_verified_count: number | null
  review: { pending: number; confirmed: number; corrected: number }
  /** 0-1 scale; null when there is nothing to average. */
  average_confidence: { retrieval: number | null; llm: number | null; image: number | null }
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
