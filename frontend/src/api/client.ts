/**
 * Typed wrapper around the backend REST API.
 *
 * Every function either resolves with the typed payload or rejects with an
 * `ApiError`, so UI code only has to handle one error type.
 */
import type {
  ApiErrorBody,
  CorrectionInput,
  DiagnoseResponse,
  FeedbackResponse,
  FieldError,
  HealthResponse,
  HistoryPage,
  ImageDiagnoseResponse,
  KnowledgeBaseStats,
  ReviewResponse,
  ReviewStatus,
  SessionFeedbackResponse,
  StatsResponse,
} from '../types/api'
import { isSendableCode, setTechnicianCodeRequired } from '../lib/technicianCode'

// Empty by default => same origin, which Vite proxies to the backend (see vite.config.ts).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
// A diagnosis takes 3-7 s warm but can take minutes if the LLM must be loaded first.
const DIAGNOSE_TIMEOUT_MS = Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS) || 190_000
const DEFAULT_TIMEOUT_MS = 15_000

// --- Errors ----------------------------------------------------------------------------
/**
 * network    - could not reach the backend at all (down, wrong URL, offline)
 * timeout    - no answer within the client-side time limit
 * validation - HTTP 422; `details` says which field was wrong
 * server     - any other error response from the backend
 */
export type ApiErrorKind = 'network' | 'timeout' | 'validation' | 'server'

export class ApiError extends Error {
  kind: ApiErrorKind
  status?: number
  code?: string
  details: FieldError[]
  requestId?: string
  /** From the Retry-After header of a 429: how long until the client may try again. */
  retryAfterSeconds?: number

  constructor(
    kind: ApiErrorKind,
    message: string,
    extra: {
      status?: number
      code?: string
      details?: FieldError[]
      requestId?: string
      retryAfterSeconds?: number
    } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = extra.status
    this.code = extra.code
    this.details = extra.details ?? []
    this.requestId = extra.requestId
    this.retryAfterSeconds = extra.retryAfterSeconds
  }

  /** The server refused because this client sent too many requests (HTTP 429). */
  get rateLimited(): boolean {
    return this.status === 429
  }

  /** Worth offering a "Try again" button for. */
  get retryable(): boolean {
    return this.kind === 'network' || this.kind === 'timeout' || this.status === 502 || this.status === 503
  }

  /** The validation message for one form field, if the backend reported one. */
  fieldMessage(field: string): string | undefined {
    return this.details.find((d) => d.field === field)?.message
  }
}

function isErrorBody(payload: unknown): payload is ApiErrorBody {
  const error = (payload as ApiErrorBody | undefined)?.error
  return typeof error === 'object' && error !== null && typeof error.message === 'string'
}

/** "Retry-After: 12" -> 12. Anything else (missing, HTTP-date, junk) -> undefined. */
function parseRetryAfter(value: string | null | undefined): number | undefined {
  const seconds = Number(value)
  return value && Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : undefined
}

function toApiError(status: number, payload: unknown, retryAfter?: string | null): ApiError {
  const retryAfterSeconds = status === 429 ? parseRetryAfter(retryAfter) : undefined
  if (isErrorBody(payload)) {
    const { code, message, details, request_id } = payload.error
    return new ApiError(status === 422 ? 'validation' : 'server', message, {
      status,
      code,
      details,
      requestId: request_id,
      retryAfterSeconds,
    })
  }
  // A 429 without our JSON envelope (e.g. from a gateway) is still "slow down", not a crash.
  if (status === 429) {
    return new ApiError('server', 'Too many requests.', { status, retryAfterSeconds })
  }
  // A 5xx with no JSON envelope did not come from our backend: it is the dev proxy (or a
  // gateway) saying the backend is unreachable.
  if (status >= 500) {
    return new ApiError('network', 'The diagnosis server is not responding.', { status })
  }
  return new ApiError('server', `Unexpected response from the server (HTTP ${status}).`, { status })
}

// --- Core request helper ---------------------------------------------------------------------
interface RequestOptions {
  method?: 'GET' | 'POST'
  json?: unknown
  form?: FormData
  timeoutMs?: number
  /** Lets the caller cancel (e.g. on unmount). A cancelled request rejects with AbortError. */
  signal?: AbortSignal
  /** Non-2xx statuses whose JSON body is still a valid answer (e.g. /health's 503). */
  acceptStatuses?: number[]
  /** Sent as the X-Technician-Code header (only Verify/Confirm and Correct use it). */
  technicianCode?: string
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', json, form, timeoutMs = DEFAULT_TIMEOUT_MS, signal, acceptStatuses = [], technicianCode } = opts

  // Built before the timer starts: a code the browser cannot send fails here, cleanly, as "wrong code".
  const headers: Record<string, string> = {}
  // For FormData the browser sets the multipart Content-Type (with boundary) itself.
  if (json !== undefined) headers['Content-Type'] = 'application/json'
  if (technicianCode) {
    if (!isSendableCode(technicianCode)) {
      throw new ApiError('server', 'Invalid technician code.', { status: 401, code: 'invalid_technician_code' })
    }
    headers['X-Technician-Code'] = technicianCode
  }

  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort)

  try {
    const response = await fetch(BASE_URL + path, {
      method,
      signal: controller.signal,
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: form ?? (json !== undefined ? JSON.stringify(json) : undefined),
    })

    let payload: unknown
    try {
      payload = await response.json()
    } catch (err) {
      if (controller.signal.aborted) throw err // aborted mid-download: handled below
      payload = undefined // empty or non-JSON body
    }

    if (response.ok || acceptStatuses.includes(response.status)) {
      if (payload === undefined) throw toApiError(500, undefined)
      return payload as T
    }
    throw toApiError(response.status, payload, response.headers.get('Retry-After'))
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (timedOut) {
      throw new ApiError('timeout', 'The server took too long to respond.')
    }
    if (signal?.aborted) throw err // the caller cancelled on purpose; not an error to display
    throw new ApiError('network', 'Could not reach the diagnosis server.')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

// --- Endpoints ------------------------------------------------------------------------------------
/**
 * Diagnose a description, optionally together with a photo. Without a photo this is the plain JSON request
 * it always was; with one it is multipart/form-data and the backend analyses the photo and weighs it in the
 * SAME diagnosis (the response says so in `input_sources`).
 */
export function diagnose(
  description: string,
  signal?: AbortSignal,
  equipmentType?: string,
  photo?: File | null,
): Promise<DiagnoseResponse> {
  if (photo) {
    const form = new FormData()
    form.append('description', description)
    if (equipmentType) form.append('equipment_type', equipmentType)
    form.append('image', photo)
    // A photo adds a vision-model call before the diagnosis, so the long diagnosis timeout applies.
    return request<DiagnoseResponse>('/api/v1/diagnose', { method: 'POST', form, timeoutMs: DIAGNOSE_TIMEOUT_MS, signal })
  }
  return request<DiagnoseResponse>('/api/v1/diagnose', {
    method: 'POST',
    json: equipmentType ? { description, equipment_type: equipmentType } : { description },
    timeoutMs: DIAGNOSE_TIMEOUT_MS,
    signal,
  })
}

/** AI visual assessment of a photo (a vision-language model on the backend). */
export function diagnoseImage(file: File, signal?: AbortSignal): Promise<ImageDiagnoseResponse> {
  const form = new FormData()
  form.append('file', file)
  return request<ImageDiagnoseResponse>('/api/v1/diagnose-image', {
    method: 'POST',
    form,
    timeoutMs: 30_000,
    signal,
  })
}

export function getHistory(
  page: number,
  pageSize: number,
  signal?: AbortSignal,
  reviewStatus?: ReviewStatus,
): Promise<HistoryPage> {
  const filter = reviewStatus ? `&review_status=${reviewStatus}` : ''
  return request<HistoryPage>(`/api/v1/history?page=${page}&page_size=${pageSize}${filter}`, { signal })
}

/**
 * The technician agrees with the AI (Confirm), or verifies a fix a user already confirmed (Verify). Adds the case
 * to the knowledge base. A technician action: when the server has a code set it answers 401 without the right one.
 */
export function confirmTicket(
  ticketId: number,
  signal?: AbortSignal,
  technicianCode?: string,
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/api/v1/tickets/${ticketId}/confirm`, { method: 'POST', signal, technicianCode })
}

/**
 * The technician supplies the real root cause and fix. Adds the corrected case to the knowledge base.
 * A technician action: when the server has a code set it answers 401 without the right one.
 */
export function correctTicket(
  ticketId: number,
  correction: CorrectionInput,
  signal?: AbortSignal,
  technicianCode?: string,
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/api/v1/tickets/${ticketId}/correct`, {
    method: 'POST',
    json: correction,
    signal,
    technicianCode,
  })
}

/** How many knowledge-base records are seed vs technician-verified. */
export function getKnowledgeBaseStats(signal?: AbortSignal): Promise<KnowledgeBaseStats> {
  return request<KnowledgeBaseStats>('/api/v1/knowledge-base/stats', { signal })
}

/** Usage numbers and knowledge-base growth for the Stats page. */
export function getStats(signal?: AbortSignal): Promise<StatsResponse> {
  return request<StatsResponse>('/api/v1/stats', { signal })
}

/**
 * Thumbs up / down on a diagnosis. The backend also teaches the knowledge base: a thumbs up records a
 * confirmed working fix, a thumbs down records a fix that did NOT work (see `knowledge_base_outcome`).
 */
export function submitFeedback(
  ticketId: number,
  wasCorrect: boolean,
  signal?: AbortSignal,
): Promise<FeedbackResponse> {
  return request<FeedbackResponse>('/api/v1/feedback', {
    method: 'POST',
    json: { ticket_id: ticketId, was_correct: wasCorrect },
    signal,
  })
}

/**
 * "Did this solve it?" For a no, the backend generates a different solution with an LLM call, so this
 * uses the long diagnosis timeout. `attemptNumber` makes a double click or stale tab fail with a 409
 * instead of silently skipping a solution.
 */
export function sendSessionFeedback(
  sessionId: string,
  wasHelpful: boolean,
  attemptNumber: number,
  signal?: AbortSignal,
): Promise<SessionFeedbackResponse> {
  return request<SessionFeedbackResponse>(`/api/v1/sessions/${sessionId}/feedback`, {
    method: 'POST',
    json: { was_helpful: wasHelpful, attempt_number: attemptNumber },
    timeoutMs: DIAGNOSE_TIMEOUT_MS,
    signal,
  })
}

/**
 * Resolves for both 200 (ok) and 503 (degraded); rejects only if the backend is unreachable.
 * Also notes whether the server asks for a technician code, so Verify/Correct can ask for it up front.
 */
export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>('/health', { signal, timeoutMs: 6_000, acceptStatuses: [503] }).then((health) => {
    setTechnicianCodeRequired(health.technician_code_required)
    return health
  })
}
