import { ApiError } from '../api/client'

export interface ErrorView {
  title: string
  message: string
  retryable: boolean
  requestId?: string
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
