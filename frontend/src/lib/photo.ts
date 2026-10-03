import { formatBytes } from './format'

/** What the backend accepts for a photo (it still checks the real file type and size itself). */
export const ACCEPTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024 // matches the backend default

/** The same caveat on every view of a photo assessment. */
export const PHOTO_CAVEAT = 'AI-generated visual assessment — not a substitute for professional inspection.'

/** A user-facing reason the file cannot be used, or null if it looks fine. */
export function photoProblem(file: File): string | null {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) return 'Please choose a JPEG, PNG or WebP image.'
  if (file.size > MAX_IMAGE_BYTES) {
    return `That image is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_IMAGE_BYTES)}.`
  }
  return null
}
