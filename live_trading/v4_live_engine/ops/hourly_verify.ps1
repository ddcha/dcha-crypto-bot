# H4-aligned light parity check (verify_today WITHOUT --rebuild = reuse structure cache, gen only).
# Scheduled 6x/day (every 4h, right after each H4 close). Authoritative full-rebuild is daily_verify_auto.ps1.
# ASCII-only source (PS5.1 + schtasks safe). DAY keyed to UTC (live journal + backtest are UTC).
$ErrorActionPreference = "SilentlyContinue"
$dir = "D:\smc_bot\live_trading\v4_live_engine"
Set-Location $dir

$utc = [DateTime]::UtcNow
$day = $utc.ToString('yyyy-MM-dd')                       # UTC trade-day (matches data keys)
$stamp = $utc.AddHours(9).ToString('yyyy-MM-dd HH:mm')   # KST for human log
$out = "verify_hourly_latest.txt"
$log = "ops\hourly_verify.log"

# byte-safe run: cmd redirection preserves python UTF-8 bytes (PowerShell *> corrupts under schtasks console).
cmd /c "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& set STAGE4D_DLCACHE=./data_cache&& python -u verify_today.py $day > `"$out`" 2>&1"
$rc = $LASTEXITCODE

# robust verdict parse via python (encoding-safe)
$summary = & python "ops\_parse_verdict.py" $out 2>$null
if (-not $summary) { $summary = "(parse failed)" }

$line = "[{0} KST] H4-LIGHT rc={1} day={2}(UTC) :: {3}" -f $stamp, $rc, $day, $summary
Add-Content -Path $log -Value $line -Encoding UTF8
Write-Output $line
