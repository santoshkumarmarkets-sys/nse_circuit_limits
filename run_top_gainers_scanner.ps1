Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

python .\top_gainers_scanner.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
