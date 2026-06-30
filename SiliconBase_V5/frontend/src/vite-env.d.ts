/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_VOICE_API_URL: string
  readonly VITE_WS_BASE_URL: string
  readonly VITE_API_PROXY_TARGET: string
  readonly VITE_WS_PROXY_TARGET: string
  readonly DEV: boolean
  readonly PROD: boolean
  readonly MODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
