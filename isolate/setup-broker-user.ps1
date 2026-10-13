<#
setup-broker-user.ps1 - isolate secret-broker on THIS Windows machine, no Docker.

What it does (run ONCE, in an elevated PowerShell):
  1. Creates a dedicated low-privilege local user 'secretbroker' (random password you never need).
  2. Creates C:\ProgramData\secret-broker and locks it down with NTFS ACLs so only that user,
     SYSTEM, and Administrators can read it - your normal (agent) user cannot.
  3. Stores the real API key + a shared broker token there, and copies the broker code in.
  4. Registers a Scheduled Task that runs the broker AS 'secretbroker', bound to 127.0.0.1:8787.
  5. Prints the BROKER_TOKEN to give your agent.

Run:
  Start an elevated PowerShell (Run as administrator), then:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\isolate\setup-broker-user.ps1

BOUNDARY NOTE: this is a HARD boundary only if your agent runs as a STANDARD (non-admin) user.
A local administrator can bypass any same-machine isolation (read other users' memory, decrypt
DPAPI, etc.). If your agent runs as admin, use a separate VM/host instead.

Python must be available to the broker user. Prefer an ALL-USERS Python install. Pass
-PythonExe "C:\Path\to\python.exe" if auto-detection picks a per-user install.
#>
[CmdletBinding()]
param(
    [string]$BrokerUser = "secretbroker",
    [string]$ConfigDir  = "C:\ProgramData\secret-broker",
    [string]$RepoPath   = (Split-Path -Parent $PSScriptRoot),   # parent of isolate\
    [string]$PythonExe  = ""                                      # auto-detect if empty
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script in an ELEVATED PowerShell (Run as administrator)."
    }
}

function New-RandomPassword {
    # 24 chars with at least one of each class, to satisfy local password policy.
    $upper = (65..90)  | Get-Random -Count 4 | ForEach-Object {[char]$_}
    $lower = (97..122) | Get-Random -Count 4 | ForEach-Object {[char]$_}
    $digit = (48..57)  | Get-Random -Count 4 | ForEach-Object {[char]$_}
    $spec  = ('!','@','#','%','^','*','-','_','=','+') | Get-Random -Count 4
    $rest  = (33..126) | Get-Random -Count 8 | ForEach-Object {[char]$_}
    -join (($upper + $lower + $digit + $spec + $rest) | Get-Random -Count 24)
}

Assert-Admin

$account = "$env:COMPUTERNAME\$BrokerUser"

# --- 1) resolve a Python the broker user can run -------------------------------------
if (-not $PythonExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $cmd) { throw "Python not found. Install Python (all users) or pass -PythonExe." }
    $PythonExe = $cmd.Source
}
if ($PythonExe -like "*\Users\*") {
    Write-Warning "Python at '$PythonExe' is under a user profile; '$BrokerUser' may not be able to run it."
    Write-Warning "If the task fails, install Python for ALL USERS and re-run with -PythonExe <path>."
}

# --- 2) create / reset the low-privilege user ----------------------------------------
$pw  = New-RandomPassword
$sec = ConvertTo-SecureString $pw -AsPlainText -Force
if (Get-LocalUser -Name $BrokerUser -ErrorAction SilentlyContinue) {
    Set-LocalUser -Name $BrokerUser -Password $sec
    Write-Host "Reset password for existing user '$BrokerUser'."
} else {
    New-LocalUser -Name $BrokerUser -Password $sec -FullName "secret-broker service" `
        -Description "Runs secret-broker in isolation" -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    Write-Host "Created local user '$BrokerUser'."
}
# Keep it out of interactive groups (it only needs to run the task).
try { Remove-LocalGroupMember -Group "Users" -Member $BrokerUser -ErrorAction SilentlyContinue } catch {}

# --- 3) config dir, locked down with ACLs --------------------------------------------
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
# Remove inherited permissions, then grant ONLY SYSTEM, Administrators, and the broker user.
icacls $ConfigDir /inheritance:r | Out-Null
icacls $ConfigDir /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "${account}:(OI)(CI)R" | Out-Null
Write-Host "Locked down $ConfigDir (your normal user can no longer read it)."

# --- 4) write token, key, python path, and copy the broker code ----------------------
$token = "tok_" + (-join (((48..57)+(65..90)+(97..122)) | Get-Random -Count 32 | ForEach-Object {[char]$_}))
Set-Content -Path (Join-Path $ConfigDir "broker_token.txt") -Value $token -NoNewline -Encoding ASCII
Set-Content -Path (Join-Path $ConfigDir "python.txt")       -Value $PythonExe -NoNewline -Encoding ASCII

$keySecure = Read-Host -AsSecureString "Enter the OPENAI_API_KEY to store (input hidden)"
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($keySecure)
try {
    $keyPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if (-not $keyPlain) { throw "No key entered; aborting." }
Set-Content -Path (Join-Path $ConfigDir "openai.key") -Value $keyPlain -NoNewline -Encoding UTF8
$keyPlain = $null

Copy-Item -Force (Join-Path $RepoPath "minimal\broker_min.py") (Join-Path $ConfigDir "broker_min.py")
Copy-Item -Force (Join-Path $PSScriptRoot "run-broker.ps1")    (Join-Path $ConfigDir "run-broker.ps1")

# --- 5) register the Scheduled Task that runs the broker as the broker user -----------
$runner  = Join-Path $ConfigDir "run-broker.ps1"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "secret-broker" -Action $action -Trigger $trigger -Settings $settings `
    -User $account -Password $pw -RunLevel Limited -Force | Out-Null
$pw = $null

Start-ScheduledTask -TaskName "secret-broker"
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "==================================================================="
Write-Host " secret-broker is now running as '$BrokerUser' on http://127.0.0.1:8787"
Write-Host "==================================================================="
Write-Host " Give this token to your AGENT (run in YOUR normal shell):"
Write-Host ""
Write-Host "   `$env:BROKER_TOKEN = `"$token`""
Write-Host ""
Write-Host " Test it:"
Write-Host "   curl http://127.0.0.1:8787/health"
Write-Host ""
Write-Host " To remove everything later:  .\isolate\uninstall-broker-user.ps1"
