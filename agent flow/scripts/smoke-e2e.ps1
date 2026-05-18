$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "smoke_e2e.py"

Push-Location $root
try {
  python $script
}
finally {
  Pop-Location
}
