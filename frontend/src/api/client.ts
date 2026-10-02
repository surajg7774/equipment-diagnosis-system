/**
 * Typed wrapper around the backend REST API.
 *
 * Every function either resolves with the typed payload or rejects with an
 * `ApiError`, so UI code only has to handle one error type.
 */
import type {
  ApiErrorBody,
  DiagnoseResponse,
  FeedbackResponse,
  FieldError,
  HealthResponse,
  HistoryPage,
  ImageDiagnoseResponse,
} from '../types/api'

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

  constructor(
    kind: ApiErrorKind,
    message: string,
    extra: { status?: number; code?: string; details?: FieldError[]; requestId?: string } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = extra.status
    this.code = extra.code
    this.details = extra.details ?? []
    this.requestId = extra.requestId
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

function toApiError(status: number, payload: unknown): ApiError {
  if (isErrorBody(payload)) {
    const { code, message, details, request_id } = payload.error
    return new ApiError(status === 422 ? 'validation' : 'server', message, {
      status,
      code,
      details,
      requestId: request_id,
    })
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
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', json, form, timeoutMs = DEFAULT_TIMEOUT_MS, signal, acceptStatuses = [] } = opts

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
      // For FormData the browser sets the multipart Content-Type (with boundary) itself.
      headers: json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
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
    throw toApiError(response.status, payload)
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
export function diagnose(description: string, signal?: AbortSignal): Promise<DiagnoseResponse> {
  return request<DiagnoseResponse>('/api/v1/diagnose', {
    method: 'POST',
    json: { description },
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

export function getHistory(page: number, pageSize: number, signal?: AbortSignal): Promise<HistoryPage> {
  return request<HistoryPage>(`/api/v1/history?page=${page}&page_size=${pageSize}`, { signal })
}

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

/** Resolves for both 200 (ok) and 503 (degraded); rejects only if the backend is unreachable. */
export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>('/health', { signal, timeoutMs: 6_000, acceptStatuses: [503] })
}
