<#
apply_update.ps1 — install a staged CodeHubb Assistant update (Phase 5).

Launched detached by the tray ("Restart to Update") with:
  -Installer <path>   the verified installer (.exe) or update bundle (.zip)
                      already downloaded to .runtime\updates by the app
  -WaitPid   <pid>    the tray process: we wait for it to exit first
  -Relaunch  <path>   what to start when the install finishes (the app exe)

Every step is logged to apply-update.log next to this script so a failed
update on a buyer's machine leaves evidence instead of silence.
#>
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [int]$WaitPid = 0,
    [string]$Relaunch = ""
)

$ErrorActionPreference = "Stop"
$LogPath = Join-Path $PSScriptRoot "apply-update.log"

function Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Message"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
}

try {
    Log "apply_update started: installer='$Installer' waitPid=$WaitPid relaunch='$Relaunch'"

    if ($WaitPid -gt 0) {
        # The app is quitting; give it up to two minutes to fully exit so
        # its files are unlocked before the installer overwrites them.
        try {
            Wait-Process -Id $WaitPid -Timeout 120 -ErrorAction Stop
            Log "app process $WaitPid exited"
        } catch {
            Log "app process $WaitPid did not exit in time ($($_.Exception.Message)); continuing anyway"
        }
    }

    if (-not (Test-Path $Installer)) {
        throw "installer not found: $Installer"
    }

    $ext = [IO.Path]::GetExtension($Installer).ToLowerInvariant()
    if ($ext -eq ".exe") {
        Log "running installer silently"
        $proc = Start-Process -FilePath $Installer `
            -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
            -Wait -PassThru
        Log "installer exit code: $($proc.ExitCode)"
    } elseif ($ext -eq ".zip") {
        # Zip build: the archive mirrors the app folder layout.
        $appDir = Split-Path -Parent $PSScriptRoot
        Log "expanding zip update over $appDir"
        Expand-Archive -Path $Installer -DestinationPath $appDir -Force
        Log "zip update expanded"
    } else {
        throw "don't know how to install '$Installer' (expected .exe or .zip)"
    }

    if ($Relaunch -and (Test-Path $Relaunch)) {
        Log "relaunching $Relaunch"
        Start-Process -FilePath $Relaunch
    }
    Log "apply_update finished"
} catch {
    Log "FAILED: $($_.Exception.Message)"
    exit 1
}
