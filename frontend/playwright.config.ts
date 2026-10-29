import { defineConfig } from '@playwright/test'

// End to end tests against a real backend with a fresh, seeded database and the fake LLM.
const env = [
  'ATRIUM_DATABASE_URL=postgresql+psycopg://atrium:atrium@127.0.0.1:55432/atrium_e2e',
  'ATRIUM_BASE_URL=http://localhost:8010',
  'ATRIUM_LLM_PROVIDER=fake',
  'ATRIUM_ANTHROPIC_API_KEY=',
  'ATRIUM_OPENAI_COMPAT_BASE_URL=',
  // Voice tests run only with a LiveKit dev server: E2E_LIVEKIT_URL=ws://localhost:7880 npx playwright test
  process.env.E2E_LIVEKIT_URL
    ? `ATRIUM_LIVEKIT_URL=${process.env.E2E_LIVEKIT_URL} ATRIUM_LIVEKIT_API_KEY=devkey ATRIUM_LIVEKIT_API_SECRET=secret`
    : 'ATRIUM_LIVEKIT_URL=',
  'ATRIUM_WHISPER_MODEL=fake',
  'ATRIUM_DATA_DIR=/tmp/atrium-e2e-data',
].join(' ')

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL: 'http://localhost:8010',
    viewport: { width: 1400, height: 900 },
    launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] },
  },
  webServer: {
    command: `cd ../backend && ${env} uv run python -m atrium.seed --reset --json ../frontend/e2e/.seed.json && ${env} uv run uvicorn atrium.main:app --port 8010 --no-access-log --log-level warning`,
    url: 'http://localhost:8010/api/openapi.json',
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
