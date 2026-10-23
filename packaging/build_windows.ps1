<#
build_windows.ps1 — the one-command Windows release build (Phase 5).

Run from anywhere (PowerShell):   .\packaging\build_windows.ps1

Steps:
  1. Verify version consistency (agent\version.py vs the Inno script's
     #define AppVersion vs packaging\version_info.txt) — refuse to build
     on any mismatch so a release can never ship mixed versions.
  2. Create .venv if needed and install requirements-gui.txt + PyInstaller.
  3. Stage the Playwright Chromium into packaging\browsers.
  4. Run PyInstaller with packaging\codehubb_assistant.spec (onedir).
  5. npm install inside the built sidecar folder (ships ready to pair).
  6. Compile the installer with Inno Setup when ISCC is available;
     otherwise print the one manual step.

Output: dist\CodeHubbAssistant-Setup-<version>.exe
#>
param(
    [switch]$SkipInno,
    [switch]$SkipChromium
)

$ErrorActionPreference = "Stop"
$PackagingDir = $PSScriptRoot
$Root = Split-Path -Parent $PackagingDir
Set-Location $Root

function Fail([string]$Message) { throw "[build] $Message" }

# ------------------------------------------------------------ 1. versions
Write-Host "[build] checking version consistency..."
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "[build] creating .venv..."
    python -m venv .venv
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}
$Version = (& $Python -c "from agent.version import __version__; print(__version__)").Trim()
if (-not $Version) { Fail "could not read agent\version.py" }

$IssText = Get-Content (Join-Path $PackagingDir "CodeHubbAssistant.iss") -Raw
if ($IssText -notmatch '#define\s+AppVersion\s+"([^"]+)"') {
    Fail "CodeHubbAssistant.iss has no #define AppVersion"
}
$IssVersion = $Matches[1]
if ($IssVersion -ne $Version) {
    Fail "version mismatch: agent\version.py=$Version but CodeHubbAssistant.iss=$IssVersion"
}
$InfoText = Get-Content (Join-Path $PackagingDir "version_info.txt") -Raw
if ($InfoText -notmatch [regex]::Escape("'$Version'")) {
    Fail "version mismatch: packaging\version_info.txt does not carry '$Version'"
}
Write-Host "[build] version $Version consistent across version.py / .iss / version_info.txt"

# ------------------------------------------------------- 2. dependencies
Write-Host "[build] installing Python dependencies..."
& $Python -m pip install --upgrade pip | Out-Null
& $Python -m pip install -r requirements-gui.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }

# ------------------------------------------------- 3. Playwright Chromium
if (-not $SkipChromium) {
    $BrowsersDir = Join-Path $PackagingDir "browsers"
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir
    Write-Host "[build] staging Playwright Chromium into $BrowsersDir ..."
    & $Python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { Fail "playwright install chromium failed" }
} else {
    Write-Host "[build] skipping Chromium staging (-SkipChromium)"
}

# ------------------------------------------------------------ 4. PyInstaller
Write-Host "[build] running PyInstaller..."
& $Python -m PyInstaller --noconfirm --clean (Join-Path $PackagingDir "codehubb_assistant.spec")
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller build failed" }
$DistApp = Join-Path $Root "dist\CodeHubbAssistant"
if (-not (Test-Path (Join-Path $DistApp "CodeHubbAssistant.exe"))) {
    Fail "PyInstaller output missing: $DistApp\CodeHubbAssistant.exe"
}

# ------------------------------------------------- 5. sidecar node_modules
$BuiltSidecar = Get-ChildItem -Path $DistApp -Recurse -Directory -Filter "sidecar" |
    Select-Object -First 1
$Npm = Get-Command npm -ErrorAction SilentlyContinue
if ($BuiltSidecar -and $Npm) {
    Write-Host "[build] npm install in $($BuiltSidecar.FullName)..."
    Push-Location $BuiltSidecar.FullName
    try {
        & npm install --omit=dev
        if ($LASTEXITCODE -ne 0) { Fail "npm install in the built sidecar failed" }
    } finally {
        Pop-Location
    }
} elseif ($BuiltSidecar) {
    Write-Warning "[build] npm not found on this machine: the installer will ship the sidecar WITHOUT node_modules. Install Node.js 18+ and rebuild, or buyers' WhatsApp stays disabled until they run npm install in the sidecar folder."
}

# ------------------------------------------------------------- 6. installer
$InstallerName = "CodeHubbAssistant-Setup-$Version.exe"
if ($SkipInno) {
    Write-Host "[build] skipping Inno Setup (-SkipInno). Onedir app is at $DistApp"
    exit 0
}
$Iscc = $null
$IsccCmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($IsccCmd) { $Iscc = $IsccCmd.Source }
foreach ($candidate in @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)) {
    if (-not $Iscc -and $candidate -and (Test-Path $candidate)) { $Iscc = $candidate }
}
if ($Iscc) {
    Write-Host "[build] compiling installer with $Iscc ..."
    & $Iscc (Join-Path $PackagingDir "CodeHubbAssistant.iss")
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compile failed" }
    Write-Host "[build] DONE: dist\$InstallerName"
} else {
    Write-Host ""
    Write-Host "[build] PyInstaller build finished at $DistApp"
    Write-Host "[build] Inno Setup (ISCC.exe) was NOT found, so the installer was not compiled."
    Write-Host "[build] Manual step: install Inno Setup 6 from https://jrsoftware.org/isdl.php,"
    Write-Host "[build] then run:  ISCC packaging\CodeHubbAssistant.iss"
    Write-Host "[build] which produces: dist\$InstallerName"
}
