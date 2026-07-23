# Daily authoritative parity check (verify_today --rebuild) with self-computed UTC trade-day.
# Scheduler-friendly (no args). Rebuilds structure cache -> prepared_cache_today.pkl, then full compare.
# ASCII-only source (PS5.1 + schtasks safe). DAY keyed to UTC. Manual equiv: ops/daily_verify.ps1 <YYYY-MM-DD>
$ErrorActionPreference = "SilentlyContinue"
$dir = "D:\smc_bot\live_trading\v4_live_engine"
Set-Location $dir

$utc = [DateTime]::UtcNow
$day = $utc.ToString('yyyy-MM-dd')                       # UTC trade-day
$stamp = $utc.AddHours(9).ToString('yyyy-MM-dd HH:mm')   # KST for human log
$out = "verify_" + ($day -replace '-', '') + ".txt"
Write-Output ("[daily_verify_auto] {0}(UTC) --rebuild -> {1}" -f $day, $out)

# byte-safe run (cmd redirection preserves UTF-8 under schtasks)
cmd /c "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& set STAGE4D_DLCACHE=./data_cache&& python -u verify_today.py $day --rebuild > `"$out`" 2>&1"
$rc = $LASTEXITCODE

$summary = & python "ops\_parse_verdict.py" $out 2>$null
if (-not $summary) { $summary = "(parse failed)" }
Add-Content -Path "ops\hourly_verify.log" -Value ("[{0} KST] DAILY-REBUILD rc={1} day={2}(UTC) :: {3} -> {4}" -f $stamp, $rc, $day, $summary, $out) -Encoding UTF8
Write-Output ("[daily_verify_auto] exit={0} :: {1}" -f $rc, $summary)
