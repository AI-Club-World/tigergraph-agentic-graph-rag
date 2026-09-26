const env = import.meta.env

export const config = {
  apiBaseUrl: env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
  apiKey: env.VITE_API_KEY ?? '',
  // Set VITE_USE_MOCK_API=true only for local fixture-backed development.
  // Default is false (live backend).
  useMockApi: (env.VITE_USE_MOCK_API ?? 'false').toLowerCase() !== 'false',
  mockLatencyScale: Number(env.VITE_MOCK_LATENCY_SCALE ?? '1'),
  defaultRunId: env.VITE_DEFAULT_RUN_ID ?? 'latest',
  // ⚠ Replace admin@example.com with the real admin address via VITE_ADMIN_EMAIL.
  adminEmail: (env.VITE_ADMIN_EMAIL as string | undefined) ?? 'admin@example.com',
  // Health-check polling interval in ms. Default 10 min — LLM checks are slow.
  pollIntervalMs: Number(env.VITE_POLL_INTERVAL_MS ?? '600000'),
  // Browser limit for /health/llm; keep above the server's HEALTH_LLM_TIMEOUT_S (120 s).
  llmHealthTimeoutMs: Number(env.VITE_LLM_HEALTH_TIMEOUT_MS ?? '130000'),
} as const
