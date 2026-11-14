param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run .\install.ps1 first."
}

$env:PYTHONPATH = "src"
Write-Host "Starting dashboard at http://$HostAddress`:$Port/"
& ".\.venv\Scripts\python.exe" -m uvicorn email_article_analyzer.main:app --host $HostAddress --port $Port
