import fs from "fs";
import path from "path";

import { defineConfig } from "@playwright/test";

const backend = path.resolve(__dirname, "../flobrain-core/backend");
const python =
  process.platform === "win32"
    ? path.join(backend, ".venv", "Scripts", "python.exe")
    : path.join(backend, ".venv", "bin", "python");
const hasBackend = fs.existsSync(python);
if (hasBackend) {
  process.env.E2E_HAS_BACKEND = "1";
}

const djangoEnv = { ...process.env, DEBUG: "True", DB_ENGINE: "sqlite" };

export default defineConfig({
  testDir: "./e2e",
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  globalSetup: hasBackend ? "./e2e/global-setup.ts" : undefined,
  use: { baseURL: "http://127.0.0.1:3000" },
  webServer: [
    ...(hasBackend
      ? [
          {
            command: `"${python}" manage.py runserver 127.0.0.1:8000 --noreload`,
            cwd: backend,
            url: "http://127.0.0.1:8000/healthz",
            reuseExistingServer: false,
            timeout: 120000,
            env: djangoEnv,
          },
        ]
      : []),
    {
      command: "npm run dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
