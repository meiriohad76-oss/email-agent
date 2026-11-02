param(
    [switch]$SkipPlaywrightBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Installing Email Article Analyzer in: $Root"

if (-not (Test-Path "pyproject.toml")) {
    throw "pyproject.toml was not found. Run this script from the extracted deployment folder."
}

$pythonCandidates = @(
    @{ Command = "py"; Args = @("-3.14") },
    @{ Command = "py"; Args = @("-3.13") },
    @{ Command = "py"; Args = @("-3.12") },
    @{ Command = "py"; Args = @("-3.11") },
    @{ Command = "python"; Args = @() }
)

$python = $null
foreach ($candidate in $pythonCandidates) {
    $cmd = Get-Command $candidate.Command -ErrorAction SilentlyContinue
    if (-not $cmd) {
        continue
    }
    try {
        $version = & $candidate.Command @($candidate.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"))
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    } catch {
    }
}

if (-not $python) {
    throw "Python 3.11 or newer was not found. Install Python from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'."
}

New-Item -ItemType Directory -Force -Path "data", "config" | Out-Null

if (-not (Test-Path ".env")) {
    Copy-Item ".env.template" ".env"
    Write-Host "Created .env from .env.template. Edit it before running Gmail auth or analysis."
} else {
    Write-Host ".env already exists; leaving it unchanged."
}

& $python.Command @($python.Args + @("-m", "venv", ".venv"))
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e .

if (-not $SkipPlaywrightBrowser) {
    & ".\.venv\Scripts\python.exe" -m playwright install chromium
}

Write-Host ""
Write-Host "Install complete."
Write-Host "Next:"
Write-Host "  1. Edit .env and set OPENAI_API_KEY, POLYGON_API_KEY, and APP_DASHBOARD_PASSWORD."
Write-Host "  2. Put Google OAuth credentials at config\gmail_credentials.json."
Write-Host "  3. Run: .\run-gmail-auth.ps1"
Write-Host "  4. Install the Chrome bridge extension from browser-extension."
Write-Host "  5. Run: .\start-dashboard.ps1"
