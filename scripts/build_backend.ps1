# Build the backend into a single-file PyInstaller EXE.
# Output: backend-dist/repomind-backend.exe
param(
    [string]$Python = "py",
    [string]$WorkPath = "../../backend-build",
    [string]$DistPath = "../../backend-dist"
)

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Resolve-Path (Join-Path $backendRoot "..\\backend")

Push-Location $backendRoot

& $Python -m PyInstaller --onefile --name repomind-backend `
    --paths . `
    --hidden-import service.main `
    --hidden-import service.api `
    --hidden-import service.api.v1 `
    --hidden-import service.config.settings `
    --hidden-import service.storage.sqlite_db `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan.on `
    --hidden-import fastapi `
    --hidden-import pydantic `
    --hidden-import pydantic_settings `
    --hidden-import openai `
    --hidden-import sqlite3 `
    --hidden-import asyncio `
    --workpath $WorkPath `
    --distpath $DistPath `
    --clean --noconfirm `
    service/main.py

Pop-Location

if ($LASTEXITCODE -eq 0) {
    Write-Host "Backend build OK -> $(Resolve-Path (Join-Path $backendRoot $DistPath) )\repomind-backend.exe"
} else {
    Write-Error "Backend build failed"
}
