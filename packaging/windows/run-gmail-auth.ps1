$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Virtual environment not found. Run .\install.ps1 first."
}

$env:PYTHONPATH = "src"
& ".\.venv\Scripts\python.exe" -m email_article_analyzer.cli gmail-auth
& ".\.venv\Scripts\python.exe" -m email_article_analyzer.cli setup-status
