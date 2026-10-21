# FloBrain V2 local demo (Windows). Double-click run-demo.bat at the repository root.
# Installs what is missing (Python and website packages), prepares a local demo database with the
# sample company Nile Labs, starts the API and the website, and opens the browser.
# Demo mode only: sample data, no outside services, nothing leaves this computer.
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backend = Join-Path $repo "flobrain-core\backend"
$website = Join-Path $repo "flobrain-website"
$venv = Join-Path $backend ".venv"
$py = Join-Path $venv "Scripts\python.exe"

function Step($text) { Write-Host ""; Write-Host "=== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ""; Write-Host $text -ForegroundColor Red; exit 1 }
function Hash($file) { (Get-FileHash $file -Algorithm SHA256).Hash }
function PortBusy($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

Step "Checking Python and Node.js"
$pyCmd = $null
foreach ($candidate in @("py -3", "python", "python3")) {
    $parts = $candidate.Split(" ")
    if (Get-Command $parts[0] -ErrorAction SilentlyContinue) {
        $rest = @($parts | Select-Object -Skip 1)
        try { $ver = & $parts[0] @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" } catch { $ver = $null }
        if ($ver -and [version]"$ver" -ge [version]"3.11") { $pyCmd = $parts; break }
    }
}
if (-not $pyCmd) { Fail "Python 3.11 or newer is needed: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js 20 or newer is needed: https://nodejs.org/" }
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 20) { Fail "Node.js 20 or newer is needed (found $(node --version)): https://nodejs.org/" }
if ((PortBusy 8000) -or (PortBusy 3000)) { Fail "Port 8000 or 3000 is already in use. Close the other FloBrain windows (or whatever uses them) and try again." }

Step "Python packages"
if (-not (Test-Path $py)) {
    $rest = @($pyCmd | Select-Object -Skip 1)
    & $pyCmd[0] @rest -m venv $venv
}
$req = Join-Path $backend "requirements.txt"
$reqMark = Join-Path $venv ".requirements.sha256"
if (-not (Test-Path $reqMark) -or (Get-Content $reqMark) -ne (Hash $req)) {
    Write-Host "Installing (the first time takes a few minutes)..."
    & $py -m pip install --disable-pip-version-check -q --upgrade pip
    & $py -m pip install --disable-pip-version-check -q -r $req
    if ($LASTEXITCODE -ne 0) { Fail "Installing the Python packages failed (see above)." }
    Hash $req | Set-Content $reqMark
} else { Write-Host "Already installed." }

Step "Website packages"
$lock = Join-Path $website "package-lock.json"
$lockMark = Join-Path $website "node_modules\.lock.sha256"
if (-not (Test-Path $lockMark) -or (Get-Content $lockMark) -ne (Hash $lock)) {
    Write-Host "Installing (the first time takes a few minutes)..."
    Push-Location $website
    npm ci --no-audit --no-fund
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "Installing the website packages failed (see above)." }
    Hash $lock | Set-Content $lockMark
} else { Write-Host "Already installed." }

Step "Demo settings and database"
$keyFile = Join-Path $backend ".demo-key"
if (-not (Test-Path $keyFile)) { (-join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) })) | Set-Content $keyFile }
$env:DEBUG = "True"
$env:ALLOW_INSECURE_AES_MASTER_KEY = "1"
$env:SECRET_KEY = "local-demo-secret-key-for-this-computer-only-1234567890"
$env:CREDENTIALS_ENCRYPTION_KEY = (Get-Content $keyFile).Trim()
$env:DB_ENGINE = "sqlite"
$env:SQLITE_PATH = Join-Path $backend "demo.sqlite3"
$env:DEMO_MODE = "True"
$env:DEMO_AI = "True"
$env:AI_PROVIDER_BACKEND = "direct"
$env:EMBEDDINGS_BACKEND = "fake"
$env:EMBEDDINGS_MODEL = "fake-embedder"
$env:EMBEDDINGS_DIMENSION = "1024"
$env:CONTENT_STORAGE = "local"
$env:CONTENT_LOCAL_DIR = Join-Path $backend "local_media\content"
$env:DOCS_FILE_STORAGE = "local"
$env:CORS_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
$env:PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
$env:FRONTEND_BASE_URL = "http://localhost:3000"
$env:PYTHONUTF8 = "1"
$fresh = -not (Test-Path $env:SQLITE_PATH)
Push-Location $backend
& $py manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Preparing the database failed (see above)." }
if ($fresh) { & $py manage.py seed_demo }
Pop-Location

Step "Starting the API (http://127.0.0.1:8000) and the website (http://localhost:3000)"
Start-Process powershell -WorkingDirectory $backend -ArgumentList @(
    "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'FloBrain demo API'; & '$py' manage.py runserver 127.0.0.1:8000 --noreload"
)
Start-Process powershell -WorkingDirectory $website -ArgumentList @(
    "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'FloBrain demo website'; `$env:NEXT_PUBLIC_API_URL='http://127.0.0.1:8000'; npm run dev"
)
Write-Host "Waiting for the website (the first page can take a minute to build)..."
for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-WebRequest "http://localhost:3000/w/signin" -UseBasicParsing -TimeoutSec 60 | Out-Null; break } catch { Start-Sleep -Seconds 4 }
}
Start-Process "http://localhost:3000/w/signin"
Write-Host ""
Write-Host "FloBrain demo is running: http://localhost:3000/w/signin" -ForegroundColor Green
Write-Host "Pick a seat (owner, admin, team lead, member) or Take the full tour."
Write-Host "To stop: close the windows 'FloBrain demo API' and 'FloBrain demo website'."
Write-Host "To start from a clean demo: delete flobrain-core\backend\demo.sqlite3, or use 'Start the demo over' in the app."
