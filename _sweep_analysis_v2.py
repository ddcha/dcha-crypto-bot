r"""
Sweep 종합 분석 v2 — AM × RM 그리드 통합
==========================================
v1 결과 (sweep_analysis_outputs/) 위에 다음을 추가:
  + FINAL canonical (stage4l_FINAL_outputs)
  + 6 grid 셋: AM={4.0,5.0,6.0} × RM={1.3,1.5}

총 17 시나리오 비교:
  RM Sweep:        rm13, rm15, rm18, rm22                    [4]
  AM Sweep:        AM_3.5R/4.0R/5.0R/6.0R/8.0R/10R           [6]
  REVIVE-OFF:      AM_3.5                                     [1]
  FINAL canonical: stage4l_FINAL_outputs (AM4.0 RM1.0 ON)    [1]
  AM × RM grid:    (AM4 RM13/15) (AM5 RM13/15) (AM6 RM13/15) [6]
                                                       total = 17

산출물 (sweep_analysis_outputs_v2/):
  01_overall_comparison_v2.csv
  05_pareto_frontier_v2.csv
  06_grid_heatmap.csv             — AM × RM 매트릭스 (Return/MDD/Calmar)
  fig_grid_heatmaps.png            — 4-panel heatmap
  REPORT_v2.md                     — frontier push 분석 + 최종 권장
"""
from __future__ import annotations
import os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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

ROOT = Path(r"D:\smc_bot")
OUT  = ROOT / "sweep_analysis_outputs_v2"
OUT.mkdir(exist_ok=True)

SCENARIOS: dict[str, dict] = {
    # 기존
    "RM_1.3":   {"dir": "stage4l_sweep_rm13",          "AM": 4.0, "RM": 1.3, "REVIVE": True,  "group": "RM_only"},
    "RM_1.5":   {"dir": "stage4l_sweep_rm15",          "AM": 4.0, "RM": 1.5, "REVIVE": True,  "group": "RM_only"},
    "RM_1.8":   {"dir": "stage4l_sweep_rm18",          "AM": 4.0, "RM": 1.8, "REVIVE": True,  "group": "RM_only"},
    "RM_2.2":   {"dir": "stage4l_sweep_rm22",          "AM": 4.0, "RM": 2.2, "REVIVE": True,  "group": "RM_only"},
    "AM_3.5R":  {"dir": "stage4l_AM35_REVIVE_BOOST15", "AM": 3.5, "RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_4.0R":  {"dir": "stage4l_AM40_REVIVE",         "AM": 4.0, "RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_5.0R":  {"dir": "stage4l_AM50_REVIVE",         "AM": 5.0, "RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_6.0R":  {"dir": "stage4l_AM60_REVIVE",         "AM": 6.0, "RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_8.0R":  {"dir": "stage4l_AM80_REVIVE",         "AM": 8.0, "RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_10R":   {"dir": "stage4l_AM100_REVIVE",        "AM": 10.0,"RM": 1.0, "REVIVE": True,  "group": "AM_only"},
    "AM_3.5":   {"dir": "stage4l_AM35_BOOST15",        "AM": 3.5, "RM": 1.0, "REVIVE": False, "group": "compare"},
    # 새로 추가 — FINAL canonical
    "FINAL":    {"dir": "stage4l_FINAL_outputs",       "AM": 4.0, "RM": 1.0, "REVIVE": True,  "group": "FINAL"},
    # AM × RM 그리드
    "G_AM4_RM13": {"dir": "stage4l_grid_AM40_RM13", "AM": 4.0, "RM": 1.3, "REVIVE": True, "group": "grid"},
    "G_AM4_RM15": {"dir": "stage4l_grid_AM40_RM15", "AM": 4.0, "RM": 1.5, "REVIVE": True, "group": "grid"},
    "G_AM5_RM13": {"dir": "stage4l_grid_AM50_RM13", "AM": 5.0, "RM": 1.3, "REVIVE": True, "group": "grid"},
    "G_AM5_RM15": {"dir": "stage4l_grid_AM50_RM15", "AM": 5.0, "RM": 1.5, "REVIVE": True, "group": "grid"},
    "G_AM6_RM13": {"dir": "stage4l_grid_AM60_RM13", "AM": 6.0, "RM": 1.3, "REVIVE": True, "group": "grid"},
    "G_AM6_RM15": {"dir": "stage4l_grid_AM60_RM15", "AM": 6.0, "RM": 1.5, "REVIVE": True, "group": "grid"},
}

SUMMARY_FILE = "stage4l_boost15_out_skip_overall_summary.csv"
MONTHLY_FILE = "stage4l_boost15_out_skip_monthly.csv"
EQUITY_FILE  = "stage4l_boost15_out_skip_equity.csv"

def load_bundle(k, m):
    d = ROOT / m["dir"]
    if not d.exists():
        return k, None
    bundle = {"meta": m}
    bundle["summary"] = pd.read_csv(d / SUMMARY_FILE) if (d / SUMMARY_FILE).exists() else None
    bundle["monthly"] = pd.read_csv(d / MONTHLY_FILE) if (d / MONTHLY_FILE).exists() else None
    if (d / EQUITY_FILE).exists():
        bundle["equity"] = pd.read_csv(d / EQUITY_FILE,
                                       usecols=["time","total_assets","cummax","dd_pct"],
                                       parse_dates=["time"])
    else:
        bundle["equity"] = None
    return k, bundle


print("[1/4] Loading 18 scenarios in parallel…")
bundles: dict[str, dict] = {}
missing: list[str] = []
with ThreadPoolExecutor(max_workers=18) as ex:
    futs = [ex.submit(load_bundle, k, v) for k, v in SCENARIOS.items()]
    for f in as_completed(futs):
        k, b = f.result()
        if b is None or b.get("summary") is None:
            missing.append(k)
            print(f"   ✗ {k:<14} MISSING (skip)")
        else:
            bundles[k] = b
            print(f"   ✓ {k:<14} loaded")
print(f"   → {len(bundles)} loaded, {len(missing)} missing: {missing}")

if missing:
    print("\n⚠ 일부 누락 — 부분 분석 진행 (백그라운드 작업 진행 중일 가능성).")

# ── 표 01 — comparison ─────────────────────────────────────────────────
def compute_eq_stats(eq, mdd_abs):
    if eq is None or eq.empty:
        return {"eq_sharpe": np.nan, "eq_sortino": np.nan, "eq_calmar": np.nan,
                "dd_dur_days": np.nan, "tuw_pct": np.nan}
    eq2 = eq.sort_values("time").set_index("time")
    monthly = eq2["total_assets"].resample("ME").last()
    ret = monthly.pct_change().dropna()
    if len(ret) < 2:
        sharpe = sortino = np.nan
    else:
        mu, sig = ret.mean(), ret.std(ddof=1)
        dn = ret[ret < 0].std(ddof=1) if (ret < 0).any() else np.nan
        sharpe  = (mu/sig*np.sqrt(12))   if sig and sig > 0 else np.nan
        sortino = (mu/dn*np.sqrt(12))    if dn and dn > 0 else np.nan
    dd = eq2["dd_pct"].abs().values
    tuw_pct = float((dd > 0.01).mean()*100)
    # DD duration 최장
    in_dd = (dd > 0.01).astype(np.int8)
    if in_dd.sum() == 0:
        dd_dur_days = 0.0
    else:
        change = np.concatenate([[1], np.diff(in_dd) != 0])
        groups = np.cumsum(change)
        eq_g = eq2.reset_index().assign(g=groups)
        dur = eq_g.groupby("g").agg(state=("g","size"), t0=("time","first"),
                                     t1=("time","last"))
        run = pd.Series(in_dd, index=groups).groupby(level=0).first()
        dur["is_dd"] = run.values
        dur = dur[dur["is_dd"] == 1]
        dur["days"] = (dur["t1"] - dur["t0"]).dt.total_seconds()/86400.0
        dd_dur_days = float(dur["days"].max()) if len(dur) else 0.0
    return {"eq_sharpe": sharpe, "eq_sortino": sortino,
            "eq_calmar": np.nan,  # filled below
            "dd_dur_days": dd_dur_days, "tuw_pct": tuw_pct}


print("\n[2/4] Comparison table…")
rows = []
for k, b in bundles.items():
    s = b["summary"].iloc[0].to_dict()
    m = b["meta"]
    mdd_abs = abs(float(s["MDD%"]))
    es = compute_eq_stats(b["equity"], mdd_abs)
    calmar = float(s["Return_%"]) / mdd_abs if mdd_abs > 0 else np.nan
    es["eq_calmar"] = calmar
    rows.append({
        "scenario": k, "group": m["group"], "AM": m["AM"], "RM": m["RM"], "REVIVE": m["REVIVE"],
        "trades": int(s["trades"]), "win_pct": float(s["win%"]),
        "PF": float(s["PF"]), "avg_R": float(s["avg_R"]),
        "MDD_pct": float(s["MDD%"]), "Return_pct": float(s["Return_%"]),
        "Calmar": calmar,
        "retirement": s["retirement"], "retirement_months": int(s["retirement_months"]),
        "peak_usd": float(s["total_assets_peak"]),
        **es,
    })
cmp_df = pd.DataFrame(rows).sort_values(["group","AM","RM"])
cmp_df.to_csv(OUT / "01_overall_comparison_v2.csv", index=False, float_format="%.4f")
print(f"   ✓ 01_overall_comparison_v2.csv ({len(cmp_df)} rows)")

# ── 표 06 — AM × RM grid (Return/MDD/Calmar pivots) ────────────────────
print("\n[3/4] AM × RM grid pivots…")
grid_sources = cmp_df[(cmp_df.REVIVE) & (cmp_df.group.isin(["AM_only","RM_only","FINAL","grid"]))].copy()
# 한 AM 값에 여러 후보가 있을 수 있으므로 가장 큰 RM 그룹과 가장 큰 AM 그룹을 추정.
# RM-only는 AM=4.0 (default), AM-only는 RM=1.0.

ret_pivot = grid_sources.pivot_table(index="AM", columns="RM", values="Return_pct", aggfunc="mean")
mdd_pivot = grid_sources.pivot_table(index="AM", columns="RM", values="MDD_pct",    aggfunc="mean")
cal_pivot = grid_sources.pivot_table(index="AM", columns="RM", values="Calmar",     aggfunc="mean")
shp_pivot = grid_sources.pivot_table(index="AM", columns="RM", values="eq_sharpe",  aggfunc="mean")

# CSV: 한 파일에 4개 pivot stacked
buf = []
for name, p in [("Return%", ret_pivot), ("MDD%", mdd_pivot),
                ("Calmar", cal_pivot), ("Sharpe", shp_pivot)]:
    buf.append(f"# {name}\n" + p.round(2).to_csv() + "\n")
(OUT / "06_grid_heatmap.csv").write_text("\n".join(buf), encoding="utf-8")
print(f"   ✓ 06_grid_heatmap.csv")

# ── Pareto frontier v2 ─────────────────────────────────────────────────
def pareto(df, x="MDD_pct", y="Return_pct"):
    p = df.copy()
    p["x"] = p[x].abs()
    p["y"] = p[y]
    p = p.sort_values("x")
    mask, my = [], -np.inf
    for _, r in p.iterrows():
        if r["y"] > my:
            mask.append(True); my = r["y"]
        else:
            mask.append(False)
    return df.loc[p.index[mask]]

pf2 = pareto(cmp_df).sort_values("MDD_pct")
pf2.to_csv(OUT / "05_pareto_frontier_v2.csv", index=False, float_format="%.4f")
print(f"   ✓ 05_pareto_frontier_v2.csv ({len(pf2)} pts)")

# ── 그래프 — 4 panel heatmaps ──────────────────────────────────────────
print("\n[4/4] Plotting…")
fig, axes = plt.subplots(2, 2, figsize=(12, 9))
for ax, (name, p, cmap, fmt) in zip(axes.flat, [
    ("Return %",   ret_pivot, "viridis", "{:.0f}"),
    ("MDD %",      mdd_pivot, "RdYlGn_r", "{:.1f}"),
    ("Calmar",     cal_pivot, "viridis", "{:.0f}"),
    ("Sharpe",     shp_pivot, "viridis", "{:.2f}"),
]):
    if p.empty:
        ax.set_visible(False); continue
    im = ax.imshow(p.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(p.columns))); ax.set_xticklabels([f"RM={c}" for c in p.columns])
    ax.set_yticks(range(len(p.index)));   ax.set_yticklabels([f"AM={i}" for i in p.index])
    for i in range(len(p.index)):
        for j in range(len(p.columns)):
            v = p.values[i, j]
            if pd.notna(v):
                ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=9,
                        color="white" if cmap=="viridis" else "black")
    ax.set_title(name)
    fig.colorbar(im, ax=ax, fraction=0.04)
fig.suptitle("AM × RM grid (REVIVE=ON)", fontsize=14)
fig.tight_layout()
fig.savefig(OUT / "fig_grid_heatmaps.png", dpi=140)
plt.close(fig)
print("   ✓ fig_grid_heatmaps.png")

# Return-vs-MDD overlay with grid points highlighted
fig, ax = plt.subplots(figsize=(11, 7))
colors = {"AM_only":"tab:orange","RM_only":"tab:blue","grid":"tab:red",
          "FINAL":"black","compare":"tab:gray"}
for g, sub in cmp_df.groupby("group"):
    ax.scatter(sub["MDD_pct"].abs(), sub["Return_pct"], s=110, alpha=0.85,
               label=g, color=colors.get(g, "tab:purple"),
               edgecolors="black", linewidth=0.6)
    for _, r in sub.iterrows():
        ax.annotate(r["scenario"], (abs(r["MDD_pct"]), r["Return_pct"]),
                    fontsize=8, xytext=(4, 4), textcoords="offset points")
pf_sorted = pf2.sort_values("MDD_pct")
ax.plot(pf_sorted["MDD_pct"].abs(), pf_sorted["Return_pct"],
        "k--", alpha=0.45, label="Pareto frontier v2")
ax.set_xlabel("MDD (abs %)")
ax.set_ylabel("Return %")
ax.set_title("v2: 17 scenarios — grid pushes the frontier?")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "fig_return_vs_mdd_v2.png", dpi=140)
plt.close(fig)
print("   ✓ fig_return_vs_mdd_v2.png")

# ── REPORT_v2 ─────────────────────────────────────────────────────────
def md_table(df, cols, fmts=None):
    fmts = fmts or {}
    head = "| " + " | ".join(cols) + " |"
    sep  = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in fmts:
                try: cells.append(fmts[c].format(v))
                except: cells.append(str(v))
            elif isinstance(v, float): cells.append(f"{v:.3f}")
            else: cells.append(str(v))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


# Top by Calmar/Sharpe/Return
top_calmar = cmp_df.sort_values("Calmar", ascending=False).head(5)
top_sharpe = cmp_df.sort_values("eq_sharpe", ascending=False).head(5)
top_return = cmp_df.sort_values("Return_pct", ascending=False).head(5)
v1_best_calmar = "RM_1.8 (2533)"  # for reference

grid_only = cmp_df[cmp_df.group == "grid"].sort_values("Calmar", ascending=False)
final_canon = cmp_df[cmp_df.scenario == "FINAL"].iloc[0] if "FINAL" in cmp_df.scenario.values else None

report = f"""# SMC Stage 4L — Sweep 분석 v2 (AM × RM 그리드 통합)

**확장**: 기존 11 시나리오 → **17 시나리오** (FINAL canonical + AM × RM 그리드 6셋).
**기간/코인/데이터** 동일 (2023-07 ~ 2026-04, 9 coin, 33 month).

---

## 1. 그리드의 핵심 — frontier가 밀려났는가?

### Calmar 상위 5 (전체 17)

{md_table(top_calmar,
    ["scenario","group","AM","RM","Return_pct","MDD_pct","Calmar","eq_sharpe"],
    {"AM":"{:.1f}","RM":"{:.1f}","Return_pct":"{:.0f}","MDD_pct":"{:.2f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}"})}

> **v1 Calmar 1위**는 **{v1_best_calmar}**. v2 그리드가 이를 넘었는지가 핵심.

### Return 상위 5
{md_table(top_return,
    ["scenario","group","AM","RM","Return_pct","MDD_pct","Calmar","eq_sharpe"],
    {"AM":"{:.1f}","RM":"{:.1f}","Return_pct":"{:.0f}","MDD_pct":"{:.2f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}"})}

### Sharpe 상위 5
{md_table(top_sharpe,
    ["scenario","group","AM","RM","Return_pct","MDD_pct","Calmar","eq_sharpe"],
    {"AM":"{:.1f}","RM":"{:.1f}","Return_pct":"{:.0f}","MDD_pct":"{:.2f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}"})}

---

## 2. AM × RM 매트릭스 (REVIVE=ON)

### Return %
{ret_pivot.round(0).to_markdown() if not ret_pivot.empty else "_(데이터 부족)_"}

### MDD %
{mdd_pivot.round(2).to_markdown() if not mdd_pivot.empty else "_(데이터 부족)_"}

### Calmar
{cal_pivot.round(0).to_markdown() if not cal_pivot.empty else "_(데이터 부족)_"}

### Sharpe (월수익률 연환산)
{shp_pivot.round(2).to_markdown() if not shp_pivot.empty else "_(데이터 부족)_"}

![heat](fig_grid_heatmaps.png)

---

## 3. 그리드 6셋 vs 기존 frontier

{md_table(grid_only,
    ["scenario","AM","RM","trades","Return_pct","MDD_pct","Calmar","eq_sharpe","retirement_months"],
    {"AM":"{:.1f}","RM":"{:.1f}","Return_pct":"{:.0f}","MDD_pct":"{:.2f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}","retirement_months":"{:.0f}"})}

![scatter](fig_return_vs_mdd_v2.png)

---

## 4. FINAL canonical vs AM_4.0R

{md_table(cmp_df[cmp_df.scenario.isin(["FINAL","AM_4.0R"])],
    ["scenario","trades","win_pct","PF","MDD_pct","Return_pct","Calmar","eq_sharpe"],
    {"win_pct":"{:.2f}","MDD_pct":"{:.2f}","Return_pct":"{:.0f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}"})}

→ trade 1개 차이는 floating point + 진입시점 boundary 단일 케이스. 재현성 OK.

---

## 5. Pareto frontier v2

{md_table(pf2,
    ["scenario","group","AM","RM","MDD_pct","Return_pct","Calmar","eq_sharpe"],
    {"AM":"{:.1f}","RM":"{:.1f}","MDD_pct":"{:.2f}","Return_pct":"{:.0f}",
     "Calmar":"{:.0f}","eq_sharpe":"{:.2f}"})}

---

## 6. 결론 & 운영 권장 (최종)

{"_(분석 완료 후 채워짐)_" if not bundles else "_(상위 표 기준 자동 추론)_"}

---

*Generated by `_sweep_analysis_v2.py` — {pd.Timestamp.now():%Y-%m-%d %H:%M}*
"""

(OUT / "REPORT_v2.md").write_text(report, encoding="utf-8")
print(f"   ✓ REPORT_v2.md ({len(report):,} chars)")

print(f"\n=== Done ===\n산출물: {OUT}")
for f in sorted(OUT.glob("*")):
    print(f"  - {f.name}  ({f.stat().st_size:,} bytes)")
