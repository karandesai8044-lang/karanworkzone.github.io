$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
}

if (-not (Test-Path "backend\service-account.json")) {
    Write-Host "Missing backend\service-account.json. Place your Google service-account JSON there before continuing."
    Write-Host "Then run this script again."
    exit 1
}

Write-Host "Starting Print Kiosk with Docker Compose..."
docker compose up --build
