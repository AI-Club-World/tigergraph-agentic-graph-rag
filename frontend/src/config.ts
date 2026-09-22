const env = import.meta.env

export const config = {
  apiBaseUrl: env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
  apiKey: env.VITE_API_KEY ?? '',
  useMockApi: (env.VITE_USE_MOCK_API ?? 'true').toLowerCase() !== 'false',
  mockLatencyScale: Number(env.VITE_MOCK_LATENCY_SCALE ?? '1'),
  defaultRunId: env.VITE_DEFAULT_RUN_ID ?? 'latest',
} as const
