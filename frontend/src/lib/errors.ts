import { ApiError } from '../api/client'

export interface ErrorView {
  title: string
  message: string
  retryable: boolean
  requestId?: string
}

/** The server refused a technician action because the access code was missing or wrong (HTTP 401). */
export function isCodeRejection(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 401 &&
    (error.code === 'technician_code_required' || error.code === 'invalid_technician_code')
  )
}

/** Turns any thrown value into text a technician can act on (never a raw dump). */
export function describeError(error: unknown): ErrorView {
  if (!(error instanceof ApiError)) {
    return { title: 'Something went wrong', message: 'An unexpected error occurred. Please try again.', retryable: true }
  }

  switch (error.kind) {
    case 'network':
      return {
        title: "Can't reach the diagnosis server",
        message: 'The backend appears to be offline. Make sure it is running, then try again.',
        retryable: true,
      }
    case 'timeout':
      return {
        title: 'The server took too long to respond',
        message:
          'The AI model may still be loading (the first request after a long idle can take a few minutes). Try again in a moment.',
        retryable: true,
      }
    case 'validation':
      return {
        title: 'Please check your input',
        message: error.details.map((d) => d.message).join(' ') || error.message,
        retryable: false,
      }
    default:
      // Rate limited: nothing is wrong, the client just has to slow down. Retrying is safe because a
      // refused request does not count against the limit.
      if (error.rateLimited) {
        const wait = error.retryAfterSeconds
        return {
          title: 'Slow down a moment',
          message: wait
            ? `Too many requests, please wait a moment (about ${wait} second${wait === 1 ? '' : 's'}) and try again.`
            : 'Too many requests, please wait a moment and try again.',
          retryable: true,
        }
      }
      // The technician access code (Verify/Confirm and Correct only).
      if (error.code === 'technician_code_required') {
        return { title: 'Technician code needed', message: 'Enter the technician code to continue.', retryable: false }
      }
      if (error.code === 'invalid_technician_code') {
        return { title: 'Invalid technician code', message: 'Invalid technician code.', retryable: false }
      }
      // Session answers: the session can be gone (the server restarted and wiped its data) or the
      // answer can be about a solution that is no longer the current one.
      if (error.code === 'session_not_found') {
        return {
          title: 'This diagnosis session has expired',
          message: 'The server no longer has it (it may have restarted). Please describe the problem again to start a new one.',
          retryable: false,
        }
      }
      if (error.code === 'session_conflict') {
        return { title: 'This solution is out of date', message: error.message, retryable: false }
      }
      // Image analysis has its own codes: the server's message is already user-facing
      // (e.g. "busy right now (rate limit), wait a minute").
      if (error.code === 'vision_unavailable') {
        return { title: 'Image analysis is unavailable', message: error.message, retryable: true }
      }
      if (error.code === 'vision_bad_response') {
        return {
          title: "The AI couldn't assess this photo",
          message: 'It returned an unusable answer. Try again, or use a different photo.',
          retryable: true,
        }
      }
      if (error.status === 503) {
        return {
          title: 'The AI service is unavailable',
          message: 'The diagnosis model is not available right now. Please try again in a moment.',
          retryable: true,
        }
      }
      if (error.status === 502) {
        return {
          title: 'The AI returned an unusable answer',
          message: 'This is usually temporary. Please try again.',
          retryable: true,
        }
      }
      return {
        title: error.status === 413 || error.status === 415 ? 'File not accepted' : 'The server reported an error',
        message: error.message,
        retryable: error.retryable,
        requestId: error.requestId,
      }
  }
}
