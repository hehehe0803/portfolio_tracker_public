import { defineConfig } from '@playwright/test'

const frontendPort = Number(process.env.PORT ?? 3000)
const apiPort = Number(process.env.AUTH_SMOKE_API_PORT ?? 8001)
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${frontendPort}`
const apiBaseURL = process.env.NEXT_PUBLIC_API_URL ?? `http://localhost:${apiPort}`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL,
    trace: 'on-first-retry',
    viewport: {
      width: 1280,
      height: 800,
    },
  },
  webServer: [
    {
      command: 'bash e2e/start-auth-smoke-backend.sh',
      port: apiPort,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --hostname localhost --port ${frontendPort}`,
      port: frontendPort,
      reuseExistingServer: false,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        ...process.env,
        NEXT_PUBLIC_API_URL: apiBaseURL,
      },
    },
  ],
})
