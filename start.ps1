# Article Generation Pipeline — start backend + UI (articles only)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

$apiPort = 8000
$uiPort = 3000

Write-Host "Starting Article Generation Pipeline"
Write-Host "  API: http://localhost:$apiPort"
Write-Host "  UI:  http://localhost:$uiPort"
Write-Host ""

$backendCmd = @"
Set-Location '$Root'
`$env:API_PORT = '$apiPort'
`$env:CLIENTS_DATA_DIR = 'clients'
`$env:MONGODB_DB = 'article_generation_pipeline'
python main.py
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Set-Location (Join-Path $Root "atlas-ui")
$env:PORT = "$uiPort"
$env:REACT_APP_API_URL = "http://localhost:$apiPort"
$env:REACT_APP_PROJECT_MODE = "article"
npm start
