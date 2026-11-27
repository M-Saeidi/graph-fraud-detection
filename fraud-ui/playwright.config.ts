import { defineConfig, devices } from '@playwright/test'

const pythonCommand = process.env.PYTHON_FOR_E2E ?? 'python'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `${pythonCommand} -m uvicorn main:create_app --factory --app-dir FastAPI --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: '.',
      url: 'http://127.0.0.1:5173/',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
