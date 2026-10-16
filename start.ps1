# Start Machaa on Windows. Leave the window open while you use it.
Set-Location -Path $PSScriptRoot

Write-Host "Machaa will be at http://127.0.0.1:8787"
Write-Host "Leave this window open. Press Ctrl+C to stop."
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Docker is not installed."
  Write-Host "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and run this script again."
  exit 1
}

docker compose up --build
