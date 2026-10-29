param([string]$Out = "runs/v2_demo_local")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m tracepatch v2-demo --out $Out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-Item (Join-Path $Out "dev/report.html")
