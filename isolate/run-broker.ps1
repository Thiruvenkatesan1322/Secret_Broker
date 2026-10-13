<#
run-broker.ps1 - launched by the Scheduled Task AS the low-privilege 'secretbroker' user.

It reads the token + real key from this ACL-protected folder (which your normal user cannot
read), puts them in THIS process's environment, and starts the broker. Because the broker runs
as a different user, an agent running as you cannot read its environment, memory, or these files.

You normally never run this by hand - setup-broker-user.ps1 wires it into a Scheduled Task.
#>
$ErrorActionPreference = "Stop"

# This script is copied into the config dir (e.g. C:\ProgramData\secret-broker) at setup time,
# so everything it needs sits next to it.
$dir = $PSScriptRoot

$py = (Get-Content (Join-Path $dir "python.txt") -Raw).Trim()

$env:BROKER_TOKEN   = (Get-Content (Join-Path $dir "broker_token.txt") -Raw).Trim()
$env:OPENAI_API_KEY = (Get-Content (Join-Path $dir "openai.key") -Raw).Trim()

# Hand off to the single-file broker (binds 127.0.0.1:8787).
& $py (Join-Path $dir "broker_min.py")
