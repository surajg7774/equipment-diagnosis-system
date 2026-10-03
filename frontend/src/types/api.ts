/**
 * TypeScript mirror of the backend's API contracts (FastAPI / Pydantic schemas).
 * Keep in sync with the backend's app/schemas/*.py.
 */

export type Severity = 'low' | 'medium' | 'high'

/** What the diagnosis was grounded on. */
export type DiagnosisBasis = 'similar_cases' | 'general_reasoning'

/** Where a knowledge-base record came from: shipped 'seed', a confirmed 'verified' fix, or 'feedback' (a fix that did not work). */
export type KnowledgeBaseSource = 'seed' | 'verified' | 'feedback'

/** Whether a feedback-derived record is a fix that worked or one that did NOT. Seed records have none (= worked). */
export type KnowledgeOutcome = 'verified_fix' | 'failed_fix'

/** Where a ticket is in the technician-verification workflow. */
export type ReviewStatus = 'pending' | 'confirmed' | 'corrected'

/** How urgently a pending ticket needs review (medium/high severity first). */
export type ReviewPriority = 'high' | 'low'

/** Where an iterative diagnosis session is. 'abandoned' = every attempt failed: escalate to a human. */
export type SessionStatus = 'in_progress' | 'resolved' | 'abandoned'

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
  /** 'verified' = added from a confirmed ticket. Absent on older backends (= seed). */
  source?: KnowledgeBaseSource
  /** 'failed_fix' = this diagnosis + fix was suggested before and did NOT work. */
  outcome?: KnowledgeOutcome | null
}

/** What a vision model saw in a photo that was attached to a diagnosis. */
export interface ImageFindings {
  description: string
  damage_detected: boolean
  /** The vision model's own rating of the visible condition. */
  severity: Severity
  /** 0-1, the model's self-reported certainty; null if it gave no usable number. */
  confidence: number | null
  model_name: string
  provider: string
}

// --- POST /api/v1/diagnose ----------------------------------------------------
export interface DiagnoseRequest {
  /** 10-2000 characters after trimming. */
  description: string
  /** Optional kind of equipment, stored with the session (max 64 characters). */
  equipment_type?: string
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
  /** Close past cases whose fix a user reported did NOT work (thumbs down); the LLM was told to avoid them. */
  similar_failed_cases?: SimilarCase[]
  diagnosis_basis: DiagnosisBasis
  note: string | null
  /**
   * The session this solution belongs to. null when is_valid_issue is false; absent on a backend that
   * predates sessions (then the UI simply offers no "Did this solve it?" question).
   */
  session_id?: string | null
  /** 1-based number of this solution within its session. */
  attempt_number?: number | null
  /** How many different solutions are offered before the user is told to escalate. */
  max_attempts?: number | null
  /** What the diagnosis was based on: ['text'], or ['text', 'image'] when a photo's findings were used too. */
  input_sources?: ('text' | 'image')[]
  /** What the vision model saw in the attached photo; set when input_sources includes 'image'. */
  image_analysis?: ImageFindings | null
  /** Set when a photo was attached but NOT used (not equipment, or image analysis unavailable). */
  image_note?: string | null
}

// --- POST /api/v1/sessions/{id}/feedback ---------------------------------------------------
export interface SessionFeedbackResponse {
  session_id: string
  status: SessionStatus
  resolved: boolean
  /** True when every allowed attempt failed: hand the problem to a human technician. */
  escalate: boolean
  /** The attempt the user just answered about. */
  attempt_number: number
  max_attempts: number
  message: string | null
  added_to_knowledge_base: boolean
  /** A new, different solution (same shape as /diagnose); null when resolved or escalated. */
  next_attempt: DiagnoseResponse | null
}

/** One solution attempt as listed in history. */
export interface SolutionAttemptOut {
  attempt_number: number
  diagnosis: string
  recommended_action: string
  severity: Severity
  diagnosis_basis: DiagnosisBasis
  retrieval_confidence: number
  llm_confidence: number | null
  /** true = it solved the problem, false = it did not, null = no answer yet. */
  was_helpful: boolean | null
  created_at: string
}

export interface SessionOut {
  session_id: string
  status: SessionStatus
  attempt_count: number
  /** For a resolved session, how many attempts it took; otherwise null. */
  attempts_to_resolve: number | null
  created_at: string
  resolved_at: string | null
  attempts: SolutionAttemptOut[]
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
  /** The iterative session behind a text ticket; null for photos and tickets from before sessions. */
  session?: SessionOut | null
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
  /**
   * What the knowledge base now holds for this verdict: 'verified_fix' (thumbs up), 'failed_fix' (thumbs
   * down), or null if nothing was recorded. Absent on a backend that predates this behaviour.
   */
  knowledge_base_outcome?: KnowledgeOutcome | null
  /** Whether this request wrote to the knowledge base. */
  knowledge_base_updated?: boolean
  kb_record_id?: string | null
}

// --- Review workflow + knowledge-base statistics ---------------------------------------------
export interface KnowledgeBaseStats {
  total: number
  seed: number
  verified: number
  verified_confirmed: number
  verified_corrected: number
  /** 'failed_fix' records. Absent on a backend that predates thumbs-down learning. */
  failed?: number
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
  /** Records of fixes that WORKED / did NOT work (absent on an older backend). */
  verified_fix_count?: number | null
  failed_fix_count?: number | null
  review: { pending: number; confirmed: number; corrected: number }
  /** 0-1 scale; null when there is nothing to average. */
  average_confidence: { retrieval: number | null; llm: number | null; image: number | null }
  /** Absent on a backend that predates sessions. */
  sessions?: {
    total: number
    in_progress: number
    resolved: number
    /** Closed after every allowed attempt failed (escalated to a human). */
    abandoned: number
    /** Mean attempts across resolved sessions; null if none resolved yet. */
    average_attempts_to_resolve: number | null
  }
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
