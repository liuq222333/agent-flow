$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "smoke_human_approval.py"
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  $python = "python"
}

Push-Location $root
try {
  & $python $script @args
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
}
finally {
  Pop-Location
}
