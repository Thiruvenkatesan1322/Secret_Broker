<#
uninstall-broker-user.ps1 - undo setup-broker-user.ps1.

Run in an elevated PowerShell:
    .\isolate\uninstall-broker-user.ps1

Removes the Scheduled Task, the locked-down config dir (token + key + copied code),
and the dedicated local user.
#>
[CmdletBinding()]
param(
    [string]$BrokerUser = "secretbroker",
    [string]$ConfigDir  = "C:\ProgramData\secret-broker"
)

$ErrorActionPreference = "SilentlyContinue"

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script in an ELEVATED PowerShell (Run as administrator)."
    return
}

Stop-ScheduledTask       -TaskName "secret-broker"
Unregister-ScheduledTask -TaskName "secret-broker" -Confirm:$false
Write-Host "Removed scheduled task 'secret-broker'."

if (Test-Path $ConfigDir) {
    Remove-Item -Recurse -Force $ConfigDir
    Write-Host "Removed $ConfigDir."
}

if (Get-LocalUser -Name $BrokerUser -ErrorAction SilentlyContinue) {
    Remove-LocalUser -Name $BrokerUser
    Write-Host "Removed local user '$BrokerUser'."
}

Write-Host "Done."
