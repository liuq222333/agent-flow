$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$envMap = @{}
if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    if ($_ -match "^\s*([^#][^=]+?)\s*=\s*(.*)\s*$") {
      $envMap[$matches[1].Trim()] = $matches[2].Trim()
    }
  }
}

$postgresDb = $envMap["POSTGRES_DB"]
if (-not $postgresDb) { $postgresDb = "agent_flow" }

$postgresUser = $envMap["POSTGRES_USER"]
if (-not $postgresUser) { $postgresUser = "agent_flow" }

$postgresContainer = docker compose ps -q postgres
if (-not $postgresContainer) {
  throw "PostgreSQL container is not running. Run: docker compose up -d postgres"
}

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  docker compose exec -T postgres pg_isready -U $postgresUser -d $postgresDb *> $null
  if ($LASTEXITCODE -eq 0) {
    $ready = $true
    break
  }
  Start-Sleep -Seconds 2
}

if (-not $ready) {
  throw "PostgreSQL is not ready after waiting."
}

$migrations = @(
  "002_observability_and_governance.sql",
  "003_generated_workflow_code.sql",
  "004_worker_heartbeat_and_runtime_indexes.sql",
  "005_seed_deepseek_default_model.sql",
  "006_human_approval_tasks.sql"
)

foreach ($migration in $migrations) {
  $localMigration = Join-Path $root $migration
  if (-not (Test-Path $localMigration)) {
    $archivedMigration = Join-Path (Join-Path $root "开发文档\v0") $migration
    if (Test-Path $archivedMigration) {
      $localMigration = $archivedMigration
    } else {
      throw "Migration file not found: $localMigration"
    }
  }

  $containerMigration = "/tmp/$migration"
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & docker @("compose", "cp", $localMigration, "postgres:$containerMigration") 2>&1 | Out-Null
  $copyExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  if ($copyExitCode -ne 0) {
    throw "Failed to copy migration into PostgreSQL container: $migration"
  }

  Write-Host "Applying migration: $migration" -ForegroundColor Cyan
  docker compose exec -T postgres psql `
    -v ON_ERROR_STOP=1 `
    -U $postgresUser `
    -d $postgresDb `
    -f $containerMigration
  if ($LASTEXITCODE -ne 0) {
    throw "Migration failed: $migration"
  }
}

Write-Host "Database migrations are up to date." -ForegroundColor Green
