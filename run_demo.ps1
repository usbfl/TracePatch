param([string]$Out = "runs/demo_local")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m tracepatch demo --out $Out --provider offline
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-Item (Join-Path $Out "report.html")
