<#
.SYNOPSIS
Runs the local backend and frontend checks.

.DESCRIPTION
Runs backend pytest/ruff and frontend typecheck/lint. The Human Approval smoke
flow is opt-in because it requires the API, workflow worker, and backing
services to be online.

.PARAMETER IncludeHumanApprovalSmoke
Also run scripts/smoke-human-approval.ps1 after the local static checks pass.

.PARAMETER HumanApprovalSmokeArgs
Additional arguments passed through to scripts/smoke-human-approval.ps1.

.EXAMPLE
.\scripts\check-local.ps1

.EXAMPLE
.\scripts\check-local.ps1 -IncludeHumanApprovalSmoke

.EXAMPLE
.\scripts\check-local.ps1 -IncludeHumanApprovalSmoke -HumanApprovalSmokeArgs @("--base-url", "http://localhost:8000/api/v1", "--timeout", "180")
#>
[CmdletBinding()]
param(
  [switch]$IncludeHumanApprovalSmoke,
  [string[]]$HumanApprovalSmokeArgs = @()
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

function Invoke-NativeChecked {
  param(
    [string]$FilePath,
    [string[]]$Arguments = @()
  )

  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    $commandLine = @($FilePath) + $Arguments
    throw "Command failed with exit code ${LASTEXITCODE}: $($commandLine -join ' ')"
  }
}

Push-Location (Join-Path $root "backend")
try {
  if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Backend virtualenv not found. Run: cd backend; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e `".[dev]`""
  }

  Invoke-NativeChecked ".\.venv\Scripts\python.exe" @("-m", "pytest")
  Invoke-NativeChecked ".\.venv\Scripts\python.exe" @("-m", "ruff", "check", ".")
}
finally {
  Pop-Location
}

Push-Location (Join-Path $root "frontend")
try {
  if (-not (Test-Path "node_modules")) {
    throw "Frontend dependencies not found. Run: cd frontend; npm install"
  }

  Invoke-NativeChecked "npm" @("run", "typecheck")
  Invoke-NativeChecked "npm" @("run", "lint")
}
finally {
  Pop-Location
}

if ($IncludeHumanApprovalSmoke) {
  $humanApprovalSmokeScript = Join-Path $PSScriptRoot "smoke-human-approval.ps1"
  if (-not (Test-Path $humanApprovalSmokeScript)) {
    throw "Human Approval smoke script not found: $humanApprovalSmokeScript"
  }

  Write-Host "Running Human Approval smoke..."
  & $humanApprovalSmokeScript @HumanApprovalSmokeArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Human Approval smoke failed with exit code $LASTEXITCODE"
  }
}
else {
  Write-Host "Skipping Human Approval smoke. Pass -IncludeHumanApprovalSmoke when API, worker, and docker-backed services are online."
}
