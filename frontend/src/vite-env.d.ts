/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_API_KEY?: string
  readonly VITE_USE_MOCK_API?: string
  readonly VITE_MOCK_LATENCY_SCALE?: string
  readonly VITE_DEFAULT_RUN_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
