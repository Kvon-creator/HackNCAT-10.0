/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MS_CLIENT_ID?: string;
  readonly VITE_MS_TENANT_ID?: string;
  readonly VITE_MS_API_SCOPE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
