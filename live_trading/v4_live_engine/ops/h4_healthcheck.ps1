# v6 4h health check — monitor_tick 실행 + 결과를 ops/health.log 에 누적 + 에러 감지 시 flag.
# 4시간마다 스케줄. read-only(엔진 무접촉). ASCII-only.
$ErrorActionPreference = "SilentlyContinue"
$dir = "D:\smc_bot\live_trading\v4_live_engine"
Set-Location $dir
$stamp = [DateTime]::UtcNow.AddHours(9).ToString('yyyy-MM-dd HH:mm')

# monitor_tick 실행 (헬스 스냅샷)
$out = & "$dir\ops\monitor_tick.ps1" 2>&1 | Out-String

# 핵심 라인 추출
$proc = ($out | Select-String "PROC  python count=(\d+)").Matches.Groups[1].Value
$panel = if ($out -match "PANEL 8501 LISTEN ok") { "ok" } else { "DOWN" }
$cache = if ($out -match "STALE_5h") { "STALE" } elseif ($out -match "CACHE.*fresh ok") { "fresh" } else { "regen_wait" }
$skew = ($out | Select-String "SKEW  local-bybit = ([\-0-9.]+)s").Matches.Groups[1].Value
$err = if ($out -match "ERR.*=\s*([1-9]\d*)") { "ERRORS!" } else { "clean" }

# 판정
$alert = @()
if ([int]$proc -lt 3) { $alert += "PROC_LOW($proc)" }
if ($panel -eq "DOWN") { $alert += "PANEL_DOWN" }
if ($cache -eq "STALE") { $alert += "CACHE_STALE" }
if ($err -eq "ERRORS!") { $alert += "LOG_ERRORS" }
$verdict = if ($alert.Count -eq 0) { "OK" } else { "ALERT: " + ($alert -join ",") }

$line = "[{0} KST] {1} | proc={2} panel={3} cache={4} skew={5}s err={6}" -f $stamp, $verdict, $proc, $panel, $cache, $skew, $err
Add-Content -Path "$dir\ops\health.log" -Value $line -Encoding UTF8
# 전체 스냅샷도 별도 저장(최신)
$out | Out-File "$dir\ops\health_latest.txt" -Encoding UTF8
Write-Output $line
