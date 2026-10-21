import { execFileSync } from "child_process";
import path from "path";

export default async function globalSetup() {
  const backend = path.resolve(__dirname, "../../flobrain-core/backend");
  const py =
    process.platform === "win32"
      ? path.join(backend, ".venv", "Scripts", "python.exe")
      : path.join(backend, ".venv", "bin", "python");
  const env = { ...process.env, DEBUG: "True", DB_ENGINE: "sqlite" };
  execFileSync(py, ["manage.py", "migrate", "--noinput"], { cwd: backend, env, stdio: "inherit" });
  execFileSync(py, ["manage.py", "seed_v2_demo"], { cwd: backend, env, stdio: "inherit" });
}
