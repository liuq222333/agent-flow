param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $root "compose.yaml"

if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
  throw "Compose file not found: $composeFile"
}

$envMap = @{}
function Import-EnvFile {
  param(
    [string]$Path,
    [hashtable]$Target
  )

  if (Test-Path -LiteralPath $Path -PathType Leaf) {
    Get-Content -LiteralPath $Path | ForEach-Object {
      if ($_ -match "^\s*([^#][^=]+?)\s*=\s*(.*)\s*$") {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
          $value = $value.Substring(1, $value.Length - 2)
        }
        $Target[$key] = $value
      }
    }
  }
}

function Get-EnvValue {
  param(
    [string]$Name,
    [string]$Default
  )

  if ($envMap.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace($envMap[$Name])) {
    return $envMap[$Name]
  }

  return $Default
}

function Resolve-MigrationPath {
  param(
    [string]$Migration
  )

  $archiveMigrationRoots = Get-ChildItem -LiteralPath $root -Directory | ForEach-Object {
    Join-Path $_.FullName "v0"
  } | Where-Object {
    Test-Path -LiteralPath (Join-Path $_ "001_init_agent_workflow_platform_mvp.sql") -PathType Leaf
  }

  $migrationRoots = @($root) + @($archiveMigrationRoots)

  foreach ($migrationRoot in $migrationRoots) {
    $candidate = Join-Path $migrationRoot $Migration
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }

  throw "Migration file not found: $Migration"
}

Import-EnvFile -Path (Join-Path $root ".env.example") -Target $envMap
Import-EnvFile -Path (Join-Path $root ".env") -Target $envMap

$postgresDb = Get-EnvValue -Name "POSTGRES_DB" -Default "agent_flow"
$postgresUser = Get-EnvValue -Name "POSTGRES_USER" -Default "agent_flow"

$migrations = @(
  "002_observability_and_governance.sql",
  "003_generated_workflow_code.sql",
  "004_worker_heartbeat_and_runtime_indexes.sql",
  "005_seed_deepseek_default_model.sql",
  "006_human_approval_tasks.sql",
  "007_human_approval_node_status.sql"
)

$migrationPlan = foreach ($migration in $migrations) {
  [pscustomobject]@{
    Name = $migration
    Path = Resolve-MigrationPath -Migration $migration
  }
}

$composeArgs = @("compose", "-f", $composeFile, "--project-directory", $root)

Write-Host "Compose file: $composeFile" -ForegroundColor Cyan
Write-Host "PostgreSQL database: $postgresDb"
Write-Host "PostgreSQL user: $postgresUser"
Write-Host ""
Write-Host "Migration plan:" -ForegroundColor Cyan
foreach ($migration in $migrationPlan) {
  Write-Host " - $($migration.Name) <- $($migration.Path)"
}

if ($DryRun) {
  Write-Host ""
  Write-Host "Dry run complete. No database changes were made." -ForegroundColor Green
  exit 0
}

Set-Location $root

$postgresContainer = & docker @($composeArgs + @("ps", "-q", "postgres"))
if ($LASTEXITCODE -ne 0) {
  throw "docker compose ps failed with exit code $LASTEXITCODE"
}

if (-not $postgresContainer) {
  throw "PostgreSQL container is not running. Run: docker compose -f `"$composeFile`" --project-directory `"$root`" up -d postgres"
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  & docker @($composeArgs + @("exec", "-T", "postgres", "pg_isready", "-U", $postgresUser, "-d", $postgresDb)) *> $null
  if ($LASTEXITCODE -eq 0) {
    $ready = $true
    break
  }
  Start-Sleep -Seconds 2
}

if (-not $ready) {
  throw "PostgreSQL is not ready after waiting."
}

foreach ($migration in $migrationPlan) {
  Write-Host ""
  Write-Host "Applying migration: $($migration.Name)" -ForegroundColor Cyan
  Get-Content -LiteralPath $migration.Path -Raw | & docker @(
    $composeArgs + @(
      "exec",
      "-T",
      "postgres",
      "psql",
      "-v",
      "ON_ERROR_STOP=1",
      "-U",
      $postgresUser,
      "-d",
      $postgresDb
    )
  )
  if ($LASTEXITCODE -ne 0) {
    throw "Migration failed: $($migration.Name)"
  }
}

Write-Host ""
Write-Host "Database migrations are up to date." -ForegroundColor Green
