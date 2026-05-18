$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $root "backend")
try {
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Backend virtualenv not found. Run: cd backend; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e `".[dev]`""
  }

  .\.venv\Scripts\python.exe -m pytest
  .\.venv\Scripts\python.exe -m ruff check .
}
finally {
  Pop-Location
}

Push-Location (Join-Path $root "frontend")
try {
  if (-not (Test-Path "node_modules")) {
    throw "Frontend dependencies not found. Run: cd frontend; npm install"
  }

  npm run typecheck
  npm run lint
}
finally {
  Pop-Location
}
