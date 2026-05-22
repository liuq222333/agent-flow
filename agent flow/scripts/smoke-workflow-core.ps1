$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "smoke_workflow_core.py"
$envFile = Join-Path $root ".env"

if (-not $env:API_BASE_URL -and -not $env:NEXT_PUBLIC_API_BASE_URL -and (Test-Path $envFile)) {
  $apiBase = Select-String -Path $envFile -Pattern "^NEXT_PUBLIC_API_BASE_URL=(.+)$" | Select-Object -First 1
  if ($apiBase) {
    $env:API_BASE_URL = $apiBase.Matches[0].Groups[1].Value.Trim()
  }
}

Push-Location $root
try {
  python $script
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}
