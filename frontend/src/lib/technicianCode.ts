/**
 * The technician access code, for the two actions that need it (Verify/Confirm and Correct).
 *
 * It is kept ONLY in memory, for the life of the tab: never in localStorage, a cookie or the URL, so a reload
 * (or closing the tab) forgets it and the technician types it again. This is a shared access code, not a login.
 */

let remembered: string | null = null
// What GET /health last said about whether the server asks for a code. null = not known (yet).
let required: boolean | null = null

export function getTechnicianCode(): string | null {
  return remembered
}

export function rememberTechnicianCode(code: string): void {
  remembered = code.trim() || null
}

/** Called when the server rejects the code, so a wrong one is never sent twice. */
export function forgetTechnicianCode(): void {
  remembered = null
}

/** Fed by every /health response; an older backend that does not send the flag leaves it unchanged. */
export function setTechnicianCodeRequired(value: boolean | undefined): void {
  if (typeof value === 'boolean') required = value
}

/** True when the server is known to ask for a code and we have none yet: ask BEFORE calling the backend. */
export function mustAskForTechnicianCode(): boolean {
  return required === true && remembered === null
}

/**
 * fetch() throws a TypeError for header values with characters above U+00FF, which would otherwise show up as a
 * bogus "cannot reach the server" error. Such a code cannot be the right one, so it is reported as wrong instead.
 */
export function isSendableCode(code: string): boolean {
  return /^[\x20-\x7E\xA0-\xFF]+$/.test(code)
}
