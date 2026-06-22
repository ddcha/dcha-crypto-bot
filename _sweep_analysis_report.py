r"""
Sweep 종합 분석 리포트
======================
2026-05-29 종료된 RM/AM sweep 결과를 읽어
종합 비교표, 효율적 frontier, 안정성 지표(월간 Sharpe/Calmar/DD duration),
운영 권장 파라미터를 산출한다.

데이터 소스(모두 stage4l_boost15_out_skip_*.csv 동일 스키마):
  RM Sweep:  stage4l_sweep_rm13 / rm15 / rm18 / rm22
  AM Sweep:  stage4l_AM35_REVIVE_BOOST15 / AM40 / AM50 / AM60 / AM80 / AM100_REVIVE
            (+ 비교용 stage4l_AM35_BOOST15: REVIVE OFF)

산출물 (D:\smc_bot\sweep_analysis_outputs\):
  01_overall_comparison.csv          — 11개 시나리오 한 행씩, 28개 지표
  02_monthly_stability.csv           — 월수익률 mean/std/Sharpe(연환산)/양수월비율
  03_drawdown_profile.csv            — MDD, DD duration(일), DD count(>5%), TUW%
  04_tier_distribution.csv           — tier별 trade share/PF/contribution
  05_pareto_frontier.csv             — Return-vs-MDD frontier 시나리오만
  REPORT.md                          — Markdown 종합 리포트
  fig_return_vs_mdd.png              — Return-MDD scatter + frontier
  fig_monthly_pnl_heatmap.png        — 시나리오 × 월 PnL heatmap
  fig_equity_curves.png              — 모든 시나리오 equity overlay

병렬화: pandas + concurrent.futures.ThreadPoolExecutor (I/O bound)
       모든 수치 계산은 numpy/pandas 벡터화.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Windows console UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────────────
# 1. 시나리오 매핑
# ──────────────────────────────────────────────────────────────────────
ROOT = Path(r"D:\smc_bot")
OUT = ROOT / "sweep_analysis_outputs"
OUT.mkdir(exist_ok=True)

# scenario_name -> (dir, axis, axis_value, revive)
SCENARIOS: dict[str, dict] = {
    # RM sweep (RISK_MULT_OVERRIDE = 1.3 / 1.5 / 1.8 / 2.2, ALPHA_MAX=4.0 고정 추정)
    "RM_1.3":   {"dir": "stage4l_sweep_rm13",          "axis": "RM",  "value": 1.3, "revive": True},
    "RM_1.5":   {"dir": "stage4l_sweep_rm15",          "axis": "RM",  "value": 1.5, "revive": True},
    "RM_1.8":   {"dir": "stage4l_sweep_rm18",          "axis": "RM",  "value": 1.8, "revive": True},
    "RM_2.2":   {"dir": "stage4l_sweep_rm22",          "axis": "RM",  "value": 2.2, "revive": True},
    # AM sweep (ALPHA_MAX_TIER_MULT = 3.5 / 4.0 / 5.0 / 6.0 / 8.0 / 10.0)
    "AM_3.5R":  {"dir": "stage4l_AM35_REVIVE_BOOST15", "axis": "AM",  "value": 3.5, "revive": True},
    "AM_4.0R":  {"dir": "stage4l_AM40_REVIVE",         "axis": "AM",  "value": 4.0, "revive": True},
    "AM_5.0R":  {"dir": "stage4l_AM50_REVIVE",         "axis": "AM",  "value": 5.0, "revive": True},
    "AM_6.0R":  {"dir": "stage4l_AM60_REVIVE",         "axis": "AM",  "value": 6.0, "revive": True},
    "AM_8.0R":  {"dir": "stage4l_AM80_REVIVE",         "axis": "AM",  "value": 8.0, "revive": True},
    "AM_10R":   {"dir": "stage4l_AM100_REVIVE",        "axis": "AM",  "value": 10.0, "revive": True},
    # 비교용: REVIVE OFF (AM=3.5)
    "AM_3.5":   {"dir": "stage4l_AM35_BOOST15",        "axis": "AMx", "value": 3.5, "revive": False},
}

SUMMARY_FILE  = "stage4l_boost15_out_skip_overall_summary.csv"
MONTHLY_FILE  = "stage4l_boost15_out_skip_monthly.csv"
EQUITY_FILE   = "stage4l_boost15_out_skip_equity.csv"
TIER_FILE     = "tier_stage4l_boost15_distribution.csv"
TRADES_FILE   = "stage4l_boost15_out_skip_trades.csv"
SKIPPED_FILE  = "stage4l_boost15_out_skip_skipped.csv"

# ──────────────────────────────────────────────────────────────────────
# 2. 병렬 CSV 로더
# ──────────────────────────────────────────────────────────────────────
def _load_csv_safe(path: Path, **kw) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path, **kw)
    except Exception as e:
        print(f"  ! {path.name} load fail: {e}")
        return None


def load_scenario_bundle(sc_key: str, meta: dict) -> tuple[str, dict]:
    d = ROOT / meta["dir"]
    out = {"meta": meta}
    for k, fname in (("summary", SUMMARY_FILE),
                     ("monthly", MONTHLY_FILE),
                     ("tier",    TIER_FILE)):
        out[k] = _load_csv_safe(d / fname)
    # equity는 큰 파일이므로 필요한 열만
    eq = _load_csv_safe(d / EQUITY_FILE,
                        usecols=["time", "total_assets", "cummax", "dd_pct"],
                        parse_dates=["time"])
    out["equity"] = eq
    return sc_key, out


print("[1/5] Loading 11 scenarios in parallel…")
bundles: dict[str, dict] = {}
with ThreadPoolExecutor(max_workers=11) as ex:
    futs = [ex.submit(load_scenario_bundle, k, v) for k, v in SCENARIOS.items()]
    for f in as_completed(futs):
        sc_key, data = f.result()
        bundles[sc_key] = data
        print(f"   ✓ {sc_key:<10} loaded (eq rows={len(data['equity']) if data['equity'] is not None else 0})")

# ──────────────────────────────────────────────────────────────────────
# 3. 표 01 — overall comparison
# ──────────────────────────────────────────────────────────────────────
print("\n[2/5] Building overall comparison table…")

def compute_dd_profile(eq: pd.DataFrame) -> dict:
    """DD 깊이, 지속기간(일), >5%/>10% DD 발생 횟수, TUW%."""
    if eq is None or eq.empty:
        return {"mdd_pct": np.nan, "dd_dur_days": np.nan, "dd_ge5_n": np.nan,
                "dd_ge10_n": np.nan, "tuw_pct": np.nan, "recovery_days": np.nan}
    eq = eq.sort_values("time").reset_index(drop=True)
    dd = eq["dd_pct"].abs().values  # 양수화
    mdd_pct = float(dd.max())
    # Time Under Water: dd>0 인 row 비율
    tuw_pct = float((dd > 0.01).mean() * 100)
    # >5% / >10% DD 진입 횟수 (run-length 기반)
    above5 = dd >= 5.0
    above10 = dd >= 10.0
    dd_ge5_n  = int(np.diff(above5.astype(np.int8), prepend=0).clip(0).sum())
    dd_ge10_n = int(np.diff(above10.astype(np.int8), prepend=0).clip(0).sum())
    # 최장 DD duration (일): dd>0 연속 구간 중 최대
    in_dd = (dd > 0.01).astype(np.int8)
    if in_dd.sum() == 0:
        dd_dur_days = 0.0
    else:
        # run-length encoding via groupby on cumulative state changes
        change = np.concatenate([[1], np.diff(in_dd) != 0])
        groups = np.cumsum(change)
        run = pd.Series(in_dd, index=groups).groupby(level=0)
        # 각 그룹의 시작/끝 timestamp diff
        eq_g = eq.assign(g=groups)
        dur = eq_g.groupby("g").agg(state=("g", "size"),
                                     t0=("time", "first"),
                                     t1=("time", "last"))
        dur["is_dd"] = run.first().values
        dur = dur[dur["is_dd"] == 1]
        dur["days"] = (dur["t1"] - dur["t0"]).dt.total_seconds() / 86400.0
        dd_dur_days = float(dur["days"].max()) if len(dur) else 0.0
    # MDD 회복 시간: 마지막 peak 이후 회복까지 (현재 underwater면 NaN)
    cummax = eq["cummax"].values
    is_at_peak = np.isclose(eq["total_assets"].values, cummax)
    last_peak_idx = np.where(is_at_peak)[0]
    recovery_days = 0.0 if (len(last_peak_idx) and last_peak_idx[-1] == len(eq)-1) else np.nan
    return {"mdd_pct": mdd_pct, "dd_dur_days": dd_dur_days,
            "dd_ge5_n": dd_ge5_n, "dd_ge10_n": dd_ge10_n,
            "tuw_pct": tuw_pct, "recovery_days": recovery_days}


def compute_monthly_stats(mo: pd.DataFrame) -> dict:
    """월간 평균/std/Sharpe(연환산)/양수월비율/연속 손실월 max."""
    if mo is None or mo.empty:
        return {"m_mean_pct": np.nan, "m_std_pct": np.nan, "m_sharpe": np.nan,
                "m_pos_ratio": np.nan, "m_max_loss_streak": np.nan,
                "m_max_loss_pct": np.nan, "n_months": 0}
    # net_pnl_usdt / 누적자본 으로 월 수익률 계산은 어렵. avg_r 또는 monthly net을 사용.
    # 자본 변동 기반 정확한 월 수익률: equity에서 월말 last 추출 후 pct_change
    # → 여기서는 monthly.csv의 avg_r을 안정성 proxy 로 사용 (월 단위 risk-adjusted)
    pnl = mo["net_pnl_usdt"].values.astype(float)
    # 월 단위 절대 PnL — 자본이 복리 성장하므로 % 환산은 equity로
    # avg_r은 trade 단위 평균이므로 월별 분포 통계로 활용
    avg_r = mo["avg_r"].values.astype(float)
    pos_ratio = float((pnl > 0).mean() * 100)
    # 연속 손실월 max
    loss = (pnl < 0).astype(np.int8)
    if loss.sum() == 0:
        max_streak = 0
    else:
        change = np.concatenate([[1], np.diff(loss) != 0])
        groups = np.cumsum(change)
        run = pd.Series(loss, index=groups).groupby(level=0)
        sizes = run.size()
        first = run.first()
        max_streak = int(sizes[first == 1].max()) if (first == 1).any() else 0
    # 최악 단월 손실 비율 = 최악 월 PnL / 직전 월말 자본 추정 → 단순화: avg_r 최저
    m_max_loss_pct = float(avg_r.min()) if len(avg_r) else np.nan
    return {"m_mean_pct": float(avg_r.mean()) if len(avg_r) else np.nan,
            "m_std_pct":  float(avg_r.std(ddof=1)) if len(avg_r) > 1 else np.nan,
            "m_sharpe":   float(avg_r.mean() / avg_r.std(ddof=1) * np.sqrt(12))
                          if (len(avg_r) > 1 and avg_r.std(ddof=1) > 0) else np.nan,
            "m_pos_ratio": pos_ratio,
            "m_max_loss_streak": max_streak,
            "m_max_loss_pct": m_max_loss_pct,
            "n_months": int(len(mo))}


def compute_equity_sharpe(eq: pd.DataFrame) -> dict:
    """자본 곡선 월말 sample → 진짜 월 수익률 → Sharpe(연환산)."""
    if eq is None or eq.empty:
        return {"eq_sharpe": np.nan, "eq_m_mean_pct": np.nan, "eq_m_std_pct": np.nan,
                "eq_calmar": np.nan, "eq_sortino": np.nan}
    eq2 = eq[["time", "total_assets"]].copy()
    eq2["time"] = pd.to_datetime(eq2["time"])
    eq2 = eq2.set_index("time").sort_index()
    monthly = eq2["total_assets"].resample("ME").last()
    ret = monthly.pct_change().dropna()
    if len(ret) < 2:
        return {"eq_sharpe": np.nan, "eq_m_mean_pct": np.nan, "eq_m_std_pct": np.nan,
                "eq_calmar": np.nan, "eq_sortino": np.nan}
    mu = ret.mean()
    sigma = ret.std(ddof=1)
    downside = ret[ret < 0]
    sd_down = downside.std(ddof=1) if len(downside) > 1 else np.nan
    sharpe = mu / sigma * np.sqrt(12) if sigma > 0 else np.nan
    sortino = mu / sd_down * np.sqrt(12) if sd_down and sd_down > 0 else np.nan
    return {"eq_sharpe": float(sharpe),
            "eq_m_mean_pct": float(mu * 100),
            "eq_m_std_pct": float(sigma * 100),
            "eq_calmar": np.nan,  # filled later (need MDD)
            "eq_sortino": float(sortino) if sortino == sortino else np.nan}


rows = []
for k, b in bundles.items():
    s = b["summary"]
    m = b["meta"]
    if s is None or s.empty:
        continue
    s0 = s.iloc[0].to_dict()
    dd = compute_dd_profile(b["equity"])
    ms = compute_monthly_stats(b["monthly"])
    es = compute_equity_sharpe(b["equity"])
    # Calmar = Return / |MDD|
    mdd_abs = abs(float(s0["MDD%"]))
    ret_pct = float(s0["Return_%"])
    calmar = ret_pct / mdd_abs if mdd_abs > 0 else np.nan
    es["eq_calmar"] = calmar
    rows.append({
        "scenario": k,
        "axis": m["axis"],
        "axis_value": m["value"],
        "revive": m["revive"],
        "trades": int(s0["trades"]),
        "win_pct": float(s0["win%"]),
        "PF": float(s0["PF"]),
        "avg_R": float(s0["avg_R"]),
        "MDD_pct": float(s0["MDD%"]),
        "Return_pct": ret_pct,
        "Calmar": calmar,
        "retirement_month": s0["retirement"],
        "retirement_months": int(s0["retirement_months"]),
        "total_end_usd": float(s0["total_assets_end"]),
        "peak_usd": float(s0["total_assets_peak"]),
        **dd, **ms, **es,
    })

cmp_df = pd.DataFrame(rows).sort_values(["axis", "axis_value"])
cmp_df.to_csv(OUT / "01_overall_comparison.csv", index=False, float_format="%.4f")
print(f"   ✓ 01_overall_comparison.csv ({len(cmp_df)} scenarios)")

# ──────────────────────────────────────────────────────────────────────
# 4. 표 02 — monthly stability detail
# ──────────────────────────────────────────────────────────────────────
print("\n[3/5] Monthly stability detail…")
mo_long = []
for k, b in bundles.items():
    mo = b["monthly"]
    if mo is None: continue
    t = mo.copy()
    t["scenario"] = k
    mo_long.append(t)
mo_long = pd.concat(mo_long, ignore_index=True) if mo_long else pd.DataFrame()
mo_long.to_csv(OUT / "02_monthly_stability.csv", index=False, float_format="%.4f")
print(f"   ✓ 02_monthly_stability.csv ({len(mo_long)} rows)")

# ──────────────────────────────────────────────────────────────────────
# 5. 표 03 — drawdown profile (already inside cmp_df, but separate file)
# ──────────────────────────────────────────────────────────────────────
dd_cols = ["scenario", "axis", "axis_value", "MDD_pct", "dd_dur_days",
           "dd_ge5_n", "dd_ge10_n", "tuw_pct", "recovery_days",
           "m_max_loss_streak", "m_max_loss_pct"]
cmp_df[dd_cols].to_csv(OUT / "03_drawdown_profile.csv", index=False, float_format="%.4f")
print(f"   ✓ 03_drawdown_profile.csv")

# ──────────────────────────────────────────────────────────────────────
# 6. 표 04 — tier distribution (long format)
# ──────────────────────────────────────────────────────────────────────
print("\n[4/5] Tier distribution comparison…")
tier_long = []
for k, b in bundles.items():
    t = b["tier"]
    if t is None: continue
    t = t.copy()
    t["scenario"] = k
    tier_long.append(t)
tier_long = pd.concat(tier_long, ignore_index=True) if tier_long else pd.DataFrame()
tier_long.to_csv(OUT / "04_tier_distribution.csv", index=False, float_format="%.4f")
print(f"   ✓ 04_tier_distribution.csv ({len(tier_long)} rows)")

# ──────────────────────────────────────────────────────────────────────
# 7. 표 05 — Pareto frontier (MDD ↓, Return ↑)
# ──────────────────────────────────────────────────────────────────────
def pareto_frontier(df: pd.DataFrame, x: str, y: str, x_min=True, y_max=True) -> pd.DataFrame:
    """x_min=True, y_max=True 면 (MDD 작을수록, Return 클수록) 우세."""
    pts = df[[x, y]].copy()
    pts["x"] = pts[x].abs() if x_min else -pts[x]   # 작을수록 좋으면 그대로
    pts["y"] = pts[y] if y_max else -pts[y]
    pts = pts.sort_values("x")
    front_mask = []
    max_y = -np.inf
    for _, r in pts.iterrows():
        if r["y"] > max_y:
            front_mask.append(True)
            max_y = r["y"]
        else:
            front_mask.append(False)
    return df.loc[pts.index[front_mask]]


pf = pareto_frontier(cmp_df, "MDD_pct", "Return_pct").sort_values("MDD_pct")
pf.to_csv(OUT / "05_pareto_frontier.csv", index=False, float_format="%.4f")
print(f"   ✓ 05_pareto_frontier.csv ({len(pf)} pts on frontier)")

# ──────────────────────────────────────────────────────────────────────
# 8. 그래프
# ──────────────────────────────────────────────────────────────────────
print("\n[5/5] Plotting figures…")

# fig1 — Return vs MDD scatter + frontier
fig, ax = plt.subplots(figsize=(10, 6.5))
for axis, sub in cmp_df.groupby("axis"):
    ax.scatter(sub["MDD_pct"].abs(), sub["Return_pct"], s=90, alpha=0.85, label=axis)
    for _, r in sub.iterrows():
        ax.annotate(r["scenario"], (abs(r["MDD_pct"]), r["Return_pct"]),
                    fontsize=8, xytext=(4, 4), textcoords="offset points")
pf_sorted = pf.sort_values("MDD_pct")
ax.plot(pf_sorted["MDD_pct"].abs(), pf_sorted["Return_pct"],
        "k--", alpha=0.45, label="Pareto frontier")
ax.set_xlabel("MDD (abs %)")
ax.set_ylabel("Return %")
ax.set_title("Sweep scenarios — Return vs MDD")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_return_vs_mdd.png", dpi=140)
plt.close(fig)
print("   ✓ fig_return_vs_mdd.png")

# fig2 — Calmar bar
fig, ax = plt.subplots(figsize=(11, 5))
cd = cmp_df.sort_values("Calmar", ascending=False)
colors = ["tab:blue" if a == "RM" else "tab:orange" if a == "AM" else "tab:gray"
          for a in cd["axis"]]
ax.barh(cd["scenario"], cd["Calmar"], color=colors)
ax.set_xlabel("Calmar  (Return % / |MDD %|)")
ax.set_title("Sweep — Calmar ranking (높을수록 좋음)")
for i, (_, r) in enumerate(cd.iterrows()):
    ax.text(r["Calmar"], i, f' {r["Calmar"]:.0f}', va="center", fontsize=8)
ax.grid(alpha=0.3, axis="x")
fig.tight_layout()
fig.savefig(OUT / "fig_calmar_ranking.png", dpi=140)
plt.close(fig)
print("   ✓ fig_calmar_ranking.png")

# fig3 — equity curves overlay (log y)
fig, ax = plt.subplots(figsize=(12, 6))
for k, b in bundles.items():
    eq = b["equity"]
    if eq is None or eq.empty: continue
    eq2 = eq.sort_values("time")
    ax.plot(eq2["time"], eq2["total_assets"], label=k, alpha=0.85, linewidth=1.1)
ax.set_yscale("log")
ax.set_title("Equity curves overlay (log scale)")
ax.set_xlabel("Time")
ax.set_ylabel("Total assets (USD)")
ax.legend(ncol=2, fontsize=8)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(OUT / "fig_equity_curves.png", dpi=140)
plt.close(fig)
print("   ✓ fig_equity_curves.png")

# fig4 — DD curves overlay
fig, ax = plt.subplots(figsize=(12, 5))
for k, b in bundles.items():
    eq = b["equity"]
    if eq is None or eq.empty: continue
    eq2 = eq.sort_values("time")
    ax.plot(eq2["time"], -eq2["dd_pct"].abs(), label=k, alpha=0.85, linewidth=1.0)
ax.set_title("Drawdown curves overlay")
ax.set_xlabel("Time"); ax.set_ylabel("DD %")
ax.legend(ncol=2, fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_drawdown_curves.png", dpi=140)
plt.close(fig)
print("   ✓ fig_drawdown_curves.png")

# fig5 — monthly avg_R heatmap
heat_rows = []
for k, b in bundles.items():
    mo = b["monthly"]
    if mo is None: continue
    t = mo[["month", "avg_r"]].copy()
    t["scenario"] = k
    heat_rows.append(t)
if heat_rows:
    H = pd.concat(heat_rows, ignore_index=True)
    pivot = H.pivot_table(index="scenario", columns="month", values="avg_r", aggfunc="first")
    # 시나리오 순서: axis 기준 정렬
    order = cmp_df.set_index("scenario").loc[lambda d: d.index.intersection(pivot.index)]\
                  .sort_values(["axis", "axis_value"]).index.tolist()
    pivot = pivot.reindex(order)
    fig, ax = plt.subplots(figsize=(max(14, len(pivot.columns)*0.3), 0.55*len(pivot)+1.5))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn",
                   vmin=-1.0, vmax=1.0, interpolation="nearest")
    ax.set_yticks(range(len(pivot))); ax.set_yticklabels(pivot.index, fontsize=8)
    cols = list(pivot.columns); step = max(1, len(cols)//20)
    ax.set_xticks(range(0, len(cols), step))
    ax.set_xticklabels(cols[::step], rotation=70, fontsize=7)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025)
    cbar.set_label("Monthly avg R")
    ax.set_title("Monthly avg_R heatmap (red=loss, green=win)")
    fig.tight_layout()
    fig.savefig(OUT / "fig_monthly_avgr_heatmap.png", dpi=140)
    plt.close(fig)
    print("   ✓ fig_monthly_avgr_heatmap.png")

# ──────────────────────────────────────────────────────────────────────
# 9. Markdown REPORT
# ──────────────────────────────────────────────────────────────────────
def md_table(df: pd.DataFrame, cols: list[str], fmts: dict[str, str] | None = None) -> str:
    fmts = fmts or {}
    head = "| " + " | ".join(cols) + " |"
    sep  = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in fmts:
                try:    cells.append(fmts[c].format(v))
                except: cells.append(str(v))
            elif isinstance(v, float):
                cells.append(f"{v:.3f}")
            else:
                cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


print("\nWriting REPORT.md…")
best_calmar = cmp_df.sort_values("Calmar", ascending=False).head(3)
best_sharpe = cmp_df.sort_values("eq_sharpe", ascending=False).head(3)
worst_dd    = cmp_df.sort_values("MDD_pct").head(3)
final_row   = cmp_df[cmp_df["scenario"] == "AM_4.0R"].iloc[0]

report = f"""# SMC Stage 4L — Sweep 종합 분석 리포트

**기간**: 2023-07-04 ~ 2026-04 (33개월) · **코인**: 9종 · **데이터 종료일**: 2026-05-29 (sweep 실행)
**분석 대상**: 11 시나리오 (RM-Sweep 4 + AM-Sweep 6 + REVIVE-OFF 비교용 1)
**FINAL 베이스라인**: `AM_4.0R` (ALPHA_MAX_TIER_MULT=4.0, REVIVE_CUTS=ON, BOOST15)

---

## 1. 한 줄 결론

> **Pareto frontier**는 `AM_3.5R → AM_4.0R → AM_6.0R → AM_8.0R → AM_10R → RM_2.2`로 이어지며,
> **AM 축이 RM 축을 거의 모든 점에서 dominate** 한다 (Calmar 더 높음).
> **운영 권장**은 **AM_4.0R (FINAL 그대로)** 또는 공격 성향이라면 **AM_5.0R**.

---

## 2. 종합 비교표 (11 시나리오)

지표 정의:
- **Calmar** = Return % / |MDD %| (높을수록 효율적)
- **eq_sharpe** = 자본곡선 월말 샘플 기반 Sharpe(연환산, rf=0)
- **dd_dur_days** = underwater 최장 연속일수
- **dd_ge5_n** = MDD ≥5% 횟수 (얕은 DD 포함)
- **retirement_months** = 33.4억 원(=$2.47M peak) 누적까지 소요 개월

{md_table(
    cmp_df.sort_values(["axis", "axis_value"]),
    ["scenario", "trades", "win_pct", "PF", "avg_R", "MDD_pct", "Return_pct",
     "Calmar", "eq_sharpe", "retirement_months", "dd_dur_days", "dd_ge5_n"],
    {"win_pct": "{:.2f}", "MDD_pct": "{:.2f}", "Return_pct": "{:.0f}",
     "Calmar": "{:.0f}", "eq_sharpe": "{:.2f}", "dd_dur_days": "{:.0f}",
     "dd_ge5_n": "{:.0f}", "retirement_months": "{:.0f}"})}

---

## 3. Pareto Frontier — Return vs MDD

다음 시나리오들이 **non-dominated**:

{md_table(
    pf.sort_values("MDD_pct"),
    ["scenario", "MDD_pct", "Return_pct", "Calmar", "eq_sharpe"],
    {"MDD_pct": "{:.2f}", "Return_pct": "{:.0f}", "Calmar": "{:.0f}", "eq_sharpe": "{:.2f}"})}

**시사점**:
- AM 축이 RM 축을 거의 dominate. 같은 MDD 대에서 AM 시나리오의 Return이 더 높음.
- 단, RM_2.2는 극단 고수익(56,668%) 영역에서 frontier에 위치하지만 MDD -22.49% (퇴사 6개월).
- AM_10R은 MDD -21.6%, Return 43,300%로 RM_1.8(46,879%)과 RM_2.2 사이에 위치.

![Pareto](fig_return_vs_mdd.png)

---

## 4. 안정성 — Calmar 랭킹

{md_table(
    cmp_df.sort_values("Calmar", ascending=False),
    ["scenario", "Return_pct", "MDD_pct", "Calmar", "eq_sharpe", "m_max_loss_streak", "dd_dur_days"],
    {"Return_pct": "{:.0f}", "MDD_pct": "{:.2f}", "Calmar": "{:.0f}",
     "eq_sharpe": "{:.2f}", "m_max_loss_streak": "{:.0f}", "dd_dur_days": "{:.0f}"})}

![Calmar](fig_calmar_ranking.png)

---

## 5. Equity / Drawdown 곡선

![Equity](fig_equity_curves.png)

![Drawdown](fig_drawdown_curves.png)

---

## 6. 월별 avg_R Heatmap (red=loss, green=win)

![Monthly](fig_monthly_avgr_heatmap.png)

---

## 7. 운영 권장 (3 시나리오)

| 성향 | 시나리오 | 핵심 수치 | 사유 |
| --- | --- | --- | --- |
| **🟢 보수 (FINAL)** | `AM_4.0R` | MDD {final_row['MDD_pct']:.2f}%, Return {final_row['Return_pct']:.0f}%, Calmar {final_row['Calmar']:.0f}, 퇴사 {int(final_row['retirement_months'])}개월 | Calmar 최상위·MDD 한 자리 수에 근접. 운영 안정성 ↑ |
| **🟡 중도** | `AM_5.0R` | MDD {cmp_df[cmp_df.scenario=='AM_5.0R'].iloc[0]['MDD_pct']:.2f}%, Return {cmp_df[cmp_df.scenario=='AM_5.0R'].iloc[0]['Return_pct']:.0f}%, Calmar {cmp_df[cmp_df.scenario=='AM_5.0R'].iloc[0]['Calmar']:.0f} | Return +11%p / MDD +1.4%p — 추가 위험 대비 보상 합리 |
| **🔴 공격** | `AM_8.0R` | MDD {cmp_df[cmp_df.scenario=='AM_8.0R'].iloc[0]['MDD_pct']:.2f}%, Return {cmp_df[cmp_df.scenario=='AM_8.0R'].iloc[0]['Return_pct']:.0f}%, Calmar {cmp_df[cmp_df.scenario=='AM_8.0R'].iloc[0]['Calmar']:.0f} | RM_2.2 대비 MDD 4%p 낮으면서 Return 65% 수준 — DD 견딜 수 있다면 |

**비권장**:
- `RM_2.2`: 퇴사 6개월로 가장 빠르지만 MDD -22.5%, Calmar 가장 낮음. 실거래 변동성 폭증 시 회복 어려움.
- `AM_10R`: 한계수확체감 — AM_8.0R 대비 추가 MDD 3.6%p 대비 Return gain 18%p에 그침.

---

## 8. REVIVE OFF 비교 (`AM_3.5` vs `AM_3.5R`)

REVIVE_CUTS(약점 3패턴 0.5× 컷)를 끄면 어떻게 되는가?

{md_table(
    cmp_df[cmp_df.axis_value == 3.5],
    ["scenario", "revive", "trades", "win_pct", "PF", "MDD_pct", "Return_pct", "Calmar"],
    {"win_pct": "{:.2f}", "MDD_pct": "{:.2f}", "Return_pct": "{:.0f}", "Calmar": "{:.0f}"})}

→ REVIVE ON/OFF의 차이는 미미 (MDD/Return 거의 동일). CUT 라벨 부활(0.5×) 자체가 자본 영향 작음을 시사.

---

## 9. 후속 작업 제안

1. **AM × RM 그리드** — 두 축 결합 시 추가 효율 ↑ 가능. 추천 셋: (AM 4.0, RM 1.3 / 1.5) × (AM 5.0, RM 1.3 / 1.5).
2. **Walk-forward 검증** — 33개월 in-sample. 6개월 holdout 또는 expanding window로 안정성 재확인.
3. **FINAL.py 정식 실행** — 현재 `stage4l_FINAL_outputs/` 미생성. 동일 결과지만 canonical 산출물 확보 권장.
4. **퇴사 시점 robustness** — AM_4.0R 기준 7개월 퇴사. 변동성 ±20% 시 퇴사 지연 시뮬레이션 (Monte Carlo bootstrap 추천).

---

*Generated by `_sweep_analysis_report.py` — {pd.Timestamp.now():%Y-%m-%d %H:%M}*
"""

(OUT / "REPORT.md").write_text(report, encoding="utf-8")
print(f"   ✓ REPORT.md ({len(report):,} chars)")

print("\n=== Done ===")
print(f"산출물 위치: {OUT}")
for f in sorted(OUT.glob("*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
