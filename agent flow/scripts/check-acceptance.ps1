<#
.SYNOPSIS
Runs the second-stage acceptance check entrypoint.

.DESCRIPTION
Aggregates the non-destructive checks that every development round should pass:
toolchain, backend tests and lint, frontend typecheck and lint, Docker Compose
configuration validation, and migration dry-run planning.

Online smoke flows are opt-in because they create test records and require the
Docker-backed API, workers, PostgreSQL, and Redis to be running.

.PARAMETER IncludeDockerBuild
Also run docker compose build after compose configuration validation.

.PARAMETER IncludeOnlineSmoke
Run the core workflow smoke script against a running local API.

.PARAMETER IncludeHumanApprovalSmoke
Run the Human Approval smoke script against a running local API and workers.

.PARAMETER IncludeDeepSeekReal
Run the optional real DeepSeek LLM acceptance script. Requires DEEPSEEK_API_KEY
to be configured for the running API/worker environment.

.PARAMETER BaseUrl
API base URL used by optional Human Approval and DeepSeek checks. The current
core workflow smoke helper targets http://localhost:8000/api/v1.

.PARAMETER ApiToken
Bearer token used by optional online checks when AUTH_MODE=bearer.

.PARAMETER Timeout
Polling timeout in seconds for optional online checks.

.EXAMPLE
.\scripts\check-acceptance.ps1

.EXAMPLE
docker compose up -d --build
.\scripts\migrate-db.ps1
.\scripts\check-acceptance.ps1 -IncludeOnlineSmoke -IncludeHumanApprovalSmoke

.EXAMPLE
.\scripts\check-acceptance.ps1 -IncludeDockerBuild -IncludeOnlineSmoke -IncludeDeepSeekReal
#>
[CmdletBinding()]
param(
  [switch]$IncludeDockerBuild,
  [switch]$IncludeOnlineSmoke,
  [switch]$IncludeHumanApprovalSmoke,
  [switch]$IncludeDeepSeekReal,
  [string]$BaseUrl = "http://localhost:8000/api/v1",
  [string]$ApiToken = $env:AGENT_FLOW_API_TOKEN,
  [int]$Timeout = 120
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $root "compose.yaml"

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

function Invoke-ScriptChecked {
  param(
    [string]$Path,
    [string[]]$Arguments = @()
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Script not found: $Path"
  }

  powershell -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
  if ($LASTEXITCODE -ne 0) {
    $commandLine = @($Path) + $Arguments
    throw "Script failed with exit code ${LASTEXITCODE}: $($commandLine -join ' ')"
  }
}

Write-Host "== Toolchain ==" -ForegroundColor Cyan
Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "check-env.ps1")

Write-Host ""
Write-Host "== Backend and frontend local checks ==" -ForegroundColor Cyan
Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "check-local.ps1")

Write-Host ""
Write-Host "== Frontend production build ==" -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
try {
  Invoke-NativeChecked -FilePath "npm" -Arguments @("run", "build")
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "== Docker Compose configuration ==" -ForegroundColor Cyan
Invoke-NativeChecked -FilePath "docker" -Arguments @("compose", "-f", $composeFile, "--project-directory", $root, "config", "--quiet")

if ($IncludeDockerBuild) {
  Write-Host ""
  Write-Host "== Docker image build ==" -ForegroundColor Cyan
  Invoke-NativeChecked -FilePath "docker" -Arguments @("compose", "-f", $composeFile, "--project-directory", $root, "build")
}
else {
  Write-Host "Skipping Docker build. Pass -IncludeDockerBuild for image build acceptance."
}

Write-Host ""
Write-Host "== Migration dry-run ==" -ForegroundColor Cyan
Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "migrate-db.ps1") -Arguments @("-DryRun")

if ($IncludeOnlineSmoke) {
  Write-Host ""
  Write-Host "== Core workflow smoke ==" -ForegroundColor Cyan
  if ($BaseUrl -ne "http://localhost:8000/api/v1") {
    Write-Host "Core workflow smoke currently targets http://localhost:8000/api/v1 via scripts/smoke_e2e.py." -ForegroundColor Yellow
  }
  Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "smoke-workflow-core.ps1")
}
else {
  Write-Host "Skipping core workflow smoke. Pass -IncludeOnlineSmoke when the API and workers are running."
}

if ($IncludeHumanApprovalSmoke) {
  Write-Host ""
  Write-Host "== Human Approval smoke ==" -ForegroundColor Cyan
  $argsList = @("--base-url", $BaseUrl, "--timeout", [string]$Timeout)
  if (-not [string]::IsNullOrWhiteSpace($ApiToken)) {
    $argsList += @("--token", $ApiToken)
  }
  Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "smoke-human-approval.ps1") -Arguments $argsList
}
else {
  Write-Host "Skipping Human Approval smoke. Pass -IncludeHumanApprovalSmoke when approval flow changed."
}

if ($IncludeDeepSeekReal) {
  Write-Host ""
  Write-Host "== DeepSeek real acceptance ==" -ForegroundColor Cyan
  $argsList = @("--base-url", $BaseUrl, "--timeout", [string]$Timeout)
  if (-not [string]::IsNullOrWhiteSpace($ApiToken)) {
    $argsList += @("--token", $ApiToken)
  }
  Invoke-ScriptChecked -Path (Join-Path $PSScriptRoot "check-deepseek-real.ps1") -Arguments $argsList
}
else {
  Write-Host "Skipping DeepSeek real acceptance. Pass -IncludeDeepSeekReal only with a real key and network access."
}

Write-Host ""
Write-Host "Second-stage acceptance checks completed." -ForegroundColor Green
