$ErrorActionPreference = "Stop"

Write-Host "Checking local toolchain..." -ForegroundColor Cyan

python --version
node --version
npm --version
docker --version
docker compose version

Write-Host ""
Write-Host "Expected MVP stack:" -ForegroundColor Cyan
Write-Host "- Frontend: Next.js + React Flow"
Write-Host "- API: FastAPI"
Write-Host "- Worker: RQ + Redis"
Write-Host "- Database: PostgreSQL + pgvector"
Write-Host "- Deployment: Docker Compose"

