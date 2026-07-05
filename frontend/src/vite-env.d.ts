/// <reference types="vite/client" />

// Typed, non-secret build/runtime environment. Only the Backend_API base URL
// and non-secret feature flags are exposed to the client bundle (Req 1.5).
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
