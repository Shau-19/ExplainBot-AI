# Usage (from anywhere):
#   .\evals\run_evals.ps1                 # full run, 1 repeat (~2-3 min, ~150 API calls)
#   .\evals\run_evals.ps1 -Suites guardrails,retrieval     # ~free: regex + a few cached embedding calls
#   .\evals\run_evals.ps1 -Quick          # about 1/3 of the data, fast smoke test
#   .\evals\run_evals.ps1 -Repeats 3      # mean +/- std over 3 runs (LLM output is noisy)
# Output: evals\results\latest.md  (paste this file back)
param(
    [string]$Suites = "all",
    [switch]$Quick,
    [int]$Repeats = 1,
    [switch]$SetBaseline
)

$backend = Join-Path $PSScriptRoot "..\backend"
$python = Join-Path $backend "venv\Scripts\python.exe"
Set-Location $backend
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8   # fixes garbled ▶ / Devanagari in the terminal

$argsList = @("..\evals\run.py", "--suites", $Suites, "--repeats", $Repeats)
if ($Quick) { $argsList += "--quick" }
if ($SetBaseline) { $argsList += "--set-baseline" }

& $python @argsList 2>&1 | Where-Object { $_ -notmatch "TOKEN GUARD|^\[ContentAgent\]" }
Write-Host "`nReport saved to: $(Resolve-Path (Join-Path $PSScriptRoot 'results\latest.md'))"
