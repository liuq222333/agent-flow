$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

$envMap = @{}
Get-Content ".env" | ForEach-Object {
  if ($_ -match "^\s*([^#][^=]+?)\s*=\s*(.*)\s*$") {
    $envMap[$matches[1].Trim()] = $matches[2].Trim()
  }
}

docker compose up -d postgres redis
if ($LASTEXITCODE -ne 0) {
  throw "docker compose failed with exit code $LASTEXITCODE"
}

& (Join-Path $PSScriptRoot "migrate-db.ps1")

$postgresPort = $envMap["POSTGRES_PORT"]
if (-not $postgresPort) { $postgresPort = "5432" }

$redisPort = $envMap["REDIS_PORT"]
if (-not $redisPort) { $redisPort = "6380" }

Write-Host ""
Write-Host "Infrastructure is starting." -ForegroundColor Green
Write-Host "PostgreSQL: localhost:$postgresPort"
Write-Host "Redis:      localhost:$redisPort"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Backend deps:  cd backend; python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e '.[dev]'"
Write-Host "2. API server:    uvicorn app.main:app --reload --reload-exclude generated_workflows/** --reload-exclude backend/generated_workflows/** --host 0.0.0.0 --port 8000"
Write-Host "3. Frontend deps: cd frontend; npm install"
Write-Host "4. Web server:    npm run dev -- --hostname 0.0.0.0 --port 3000"
