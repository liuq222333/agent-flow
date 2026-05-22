<#
.SYNOPSIS
Runs the optional real DeepSeek workflow acceptance check.

.DESCRIPTION
Creates, publishes, and synchronously runs a small workflow using provider
deepseek. This is intentionally opt-in because it requires a valid
DEEPSEEK_API_KEY in the running API/worker environment and may consume model
quota.

.PARAMETER BaseUrl
API base URL. Defaults to AGENT_FLOW_BASE_URL or localhost.

.PARAMETER Token
Bearer token when AUTH_MODE=bearer.

.PARAMETER Timeout
HTTP request timeout in seconds.

.EXAMPLE
$env:DEEPSEEK_API_KEY="..."
docker compose up -d --build
.\scripts\check-deepseek-real.ps1
#>
[CmdletBinding()]
param(
  [string]$BaseUrl = $(if ($env:AGENT_FLOW_BASE_URL) { $env:AGENT_FLOW_BASE_URL } else { "http://localhost:8000/api/v1" }),
  [string]$Token = $(if ($env:AGENT_FLOW_API_TOKEN) { $env:AGENT_FLOW_API_TOKEN } else { $env:API_BEARER_TOKEN }),
  [int]$Timeout = 120
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "check_deepseek_real.py"
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  $python = "python"
}

$argsList = @("--base-url", $BaseUrl, "--timeout", [string]$Timeout)
if (-not [string]::IsNullOrWhiteSpace($Token)) {
  $argsList += @("--token", $Token)
}

Push-Location $root
try {
  & $python $script @argsList
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
finally {
  Pop-Location
}
