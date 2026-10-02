/// <reference types="vite/client" />

// Typed access to the optional VITE_* variables (see .env.example).
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_REQUEST_TIMEOUT_MS?: string
}
