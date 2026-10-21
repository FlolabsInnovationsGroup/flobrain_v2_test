#!/usr/bin/env bash
# FloBrain V2 local demo (macOS / Linux): ./run-demo.sh
# Installs what is missing (Python and website packages), prepares a local demo database with the
# sample company Nile Labs, starts the API and the website, and opens the browser. Ctrl+C stops both.
# Demo mode only: sample data, no outside services, nothing leaves this computer.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$REPO/flobrain-core/backend"
WEBSITE="$REPO/flobrain-website"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"
LOGS="$REPO/.demo-logs"

step() { printf '\n\033[36m=== %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$1"; exit 1; }
hash_of() { python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$1"; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

step "Checking Python and Node.js"
command -v python3 >/dev/null || fail "Python 3.11 or newer is needed: https://www.python.org/downloads/"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is needed (found $(python3 --version))."
command -v node >/dev/null || fail "Node.js 20 or newer is needed: https://nodejs.org/"
[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] || fail "Node.js 20 or newer is needed (found $(node --version))."
if port_busy 8000 || port_busy 3000; then fail "Port 8000 or 3000 is already in use. Stop whatever uses it and try again."; fi

step "Python packages"
[ -x "$PY" ] || python3 -m venv "$VENV"
REQ="$BACKEND/requirements.txt"
if [ "$(cat "$VENV/.requirements.sha256" 2>/dev/null)" != "$(hash_of "$REQ")" ]; then
  echo "Installing (the first time takes a few minutes)..."
  "$PY" -m pip install --disable-pip-version-check -q --upgrade pip
  "$PY" -m pip install --disable-pip-version-check -q -r "$REQ"
  hash_of "$REQ" > "$VENV/.requirements.sha256"
else echo "Already installed."; fi

step "Website packages"
LOCK="$WEBSITE/package-lock.json"
if [ "$(cat "$WEBSITE/node_modules/.lock.sha256" 2>/dev/null)" != "$(hash_of "$LOCK")" ]; then
  echo "Installing (the first time takes a few minutes)..."
  (cd "$WEBSITE" && npm ci --no-audit --no-fund)
  hash_of "$LOCK" > "$WEBSITE/node_modules/.lock.sha256"
else echo "Already installed."; fi

step "Demo settings and database"
KEYFILE="$BACKEND/.demo-key"
[ -f "$KEYFILE" ] || python3 -c "import secrets;print(secrets.token_hex(32))" > "$KEYFILE"
export DEBUG=True ALLOW_INSECURE_AES_MASTER_KEY=1 SECRET_KEY=local-demo-secret-key-for-this-computer-only-1234567890
export CREDENTIALS_ENCRYPTION_KEY="$(cat "$KEYFILE")" DB_ENGINE=sqlite SQLITE_PATH="$BACKEND/demo.sqlite3"
export DEMO_MODE=True DEMO_AI=True AI_PROVIDER_BACKEND=direct EMBEDDINGS_BACKEND=fake EMBEDDINGS_MODEL=fake-embedder EMBEDDINGS_DIMENSION=1024
export KNOWLEDGE_VECTOR_STORE=json  # SQLite has no pgvector; search vectors are kept as JSON
export CONTENT_STORAGE=local CONTENT_LOCAL_DIR="$BACKEND/local_media/content" DOCS_FILE_STORAGE=local
export CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000 PUBLIC_API_BASE_URL=http://127.0.0.1:8000 FRONTEND_BASE_URL=http://localhost:3000
FRESH=0; [ -f "$SQLITE_PATH" ] || FRESH=1
(cd "$BACKEND" && "$PY" manage.py migrate --noinput)
[ "$FRESH" = 1 ] && (cd "$BACKEND" && "$PY" manage.py seed_demo)

step "Starting the API (http://127.0.0.1:8000) and the website (http://localhost:3000)"
mkdir -p "$LOGS"
(cd "$BACKEND" && exec "$PY" manage.py runserver 127.0.0.1:8000 --noreload) > "$LOGS/api.log" 2>&1 &
API_PID=$!
(cd "$WEBSITE" && NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 exec npm run dev) > "$LOGS/website.log" 2>&1 &
WEB_PID=$!
trap 'echo; echo "Stopping..."; kill $API_PID $WEB_PID 2>/dev/null; wait 2>/dev/null; exit 0' INT TERM
echo "Waiting for the website (the first page can take a minute to build)..."
for _ in $(seq 1 90); do
  curl -s -o /dev/null --max-time 60 http://localhost:3000/w/signin && break
  kill -0 $API_PID 2>/dev/null || fail "The API stopped. See $LOGS/api.log"
  kill -0 $WEB_PID 2>/dev/null || fail "The website stopped. See $LOGS/website.log"
  sleep 4
done
URL=http://localhost:3000/w/signin
if [ "$(uname)" = Darwin ]; then open "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1 || true; fi
printf '\n\033[32mFloBrain demo is running: %s\033[0m\n' "$URL"
echo "Pick a seat (owner, admin, team lead, member) or Take the full tour."
echo "Logs: $LOGS. Press Ctrl+C to stop. To start from a clean demo, delete flobrain-core/backend/demo.sqlite3."
wait
