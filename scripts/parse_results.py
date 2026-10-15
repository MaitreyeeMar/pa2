#!/usr/bin/env python3
"""
Collect the numbers asked for in the PA2 deliverables from results/<config>/<trace>.txt
and make the tables (CSV + markdown) and bar plots.

  python3 scripts/parse_results.py            # reads results/, writes analysis/
needs matplotlib for the plots (pip install matplotlib); tables work without it.
"""
import os, re, csv, math, sys

RES, OUT = "results", "analysis"
os.makedirs(OUT, exist_ok=True)

def num(pat, text, grp=1):
    m = re.search(pat, text, re.M)
    return float(m.group(grp)) if m else float("nan")

def parse(path):
    t = open(path, errors="ignore").read()
    d = {}
    d["ipc"] = num(r"^CPU 0 cumulative IPC:\s+([\d.]+)", t)
    d["l1d_load_miss"] = num(r"^L1D LOAD\s+ACCESS:\s+\d+\s+HIT:\s+\d+\s+MISS:\s+(\d+)", t)
    d["l1d_load_mpki"] = num(r"^L1D LOAD\s+ACCESS:.*MPKI:\s+([\d.]+)", t)
    d["l1d_pf_acc"] = num(r"^L1D USEFUL LOAD PREFETCHES:.*ACCURACY:\s+([\d.]+)", t)
    d["l1d_pf_useful"] = num(r"^L1D USEFUL LOAD PREFETCHES:\s+(\d+)", t)
    d["l1d_pf_late"] = num(r"^L1D TIMELY PREFETCHES:.*LATE PREFETCHES:\s+(\d+)", t)
    d["l2c_load_mpki"] = num(r"^L2C LOAD\s+ACCESS:.*MPKI:\s+([\d.]+)", t)
    d["l2c_instr_mpki"] = num(r"^L2C INSTRUCTION LOAD MPKI:\s+([\d.]+)", t)
    d["l2c_data_mpki"] = num(r"^L2C DATA LOAD MPKI:\s+([\d.]+)", t)
    d["irrip_frac"] = num(r"DYN_IRRIP fills under I-RRIP:.*\(([\d.]+)% I-RRIP\)", t)
    return d

configs = sorted(c for c in os.listdir(RES) if os.path.isdir(os.path.join(RES, c)))
data = {}
for c in configs:
    for f in sorted(os.listdir(os.path.join(RES, c))):
        if f.endswith(".txt"):
            d = parse(os.path.join(RES, c, f))
            if not math.isnan(d["ipc"]):
                data.setdefault(c, {})[f[:-4]] = d
if "baseline" not in data:
    sys.exit("results/baseline missing, nothing to normalise against")
traces = sorted(data["baseline"])

def gmean(xs):
    xs = [x for x in xs if x > 0 and not math.isnan(x)]
    return math.exp(sum(map(math.log, xs)) / len(xs)) if xs else float("nan")

def amean(xs):
    xs = [x for x in xs if not math.isnan(x)]
    return sum(xs) / len(xs) if xs else float("nan")

# derived metrics
for c in data:
    for tr, d in data[c].items():
        b = data["baseline"].get(tr)
        d["speedup"] = d["ipc"] / b["ipc"] if b else float("nan")
        bm = b["l1d_load_miss"] if b else float("nan")
        d["l1d_coverage"] = 100.0 * (bm - d["l1d_load_miss"]) / bm if b and bm else float("nan")

# speedup -> geomean (ratios), everything else -> arithmetic mean
def table(name, cfgs, metrics):
    cfgs = [c for c in cfgs if c in data]
    if not cfgs: return
    rows = []
    for c in cfgs:
        for m in metrics:
            vals = [data[c].get(tr, {}).get(m, float("nan")) for tr in traces]
            if all(math.isnan(v) for v in vals):   # metric does not apply to this config
                continue
            avg = gmean(vals) if m == "speedup" else amean(vals)
            rows.append([c, m] + vals + [avg])
    hdr = ["config", "metric"] + traces + ["GMEAN/AVG"]
    with open(f"{OUT}/{name}.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
    with open(f"{OUT}/{name}.md", "w") as f:
        f.write("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr) + "\n")
        for r in rows:
            f.write("| " + " | ".join(r[:2] + [f"{v:.4f}" if isinstance(v, float) else str(v) for v in r[2:]]) + " |\n")
    print(f"wrote {OUT}/{name}.csv / .md")

T1 = ["baseline", "ip_stride", "spp", "spp_fix1", "spp_fix6", "spp_thr_lo", "spp_thr_hi"]
T2A = ["baseline", "rrip", "irrip", "irrip_ins_only", "irrip_no_evict", "irrip_ins0"]
T2B = ["baseline", "rrip", "irrip", "dyn_t10", "dyn_t20", "dyn_t25", "dyn_t35", "dyn_t50", "dyn_duel"]
T3 = ["baseline", "spp", "dyn_t25", "spp_rrip", "spp_dyn_nopfa", "spp_dyn"]

table("task1_prefetch", T1, ["ipc", "speedup", "l1d_load_mpki", "l1d_pf_acc", "l1d_coverage"])
table("task2a_irrip", T2A, ["ipc", "speedup", "l2c_load_mpki", "l2c_instr_mpki", "l2c_data_mpki"])
table("task2b_dyn", T2B, ["ipc", "speedup", "l2c_load_mpki", "l2c_instr_mpki", "l2c_data_mpki", "irrip_frac"])
table("task3_spp_dyn", T3, ["ipc", "speedup", "l1d_pf_acc", "l1d_coverage", "l1d_load_mpki",
                            "l2c_load_mpki", "l2c_instr_mpki", "l2c_data_mpki"])

# ---------------- plots ----------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    sys.exit("matplotlib not installed: tables written, plots skipped")

def bars(fname, cfgs, metric, ylabel, title, base_line=None, with_mean=True):
    cfgs = [c for c in cfgs if c in data]
    labels = traces + (["GMEAN" if metric == "speedup" else "AVG"] if with_mean else [])
    n = len(cfgs); w = 0.8 / n
    allv = []
    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(labels) + n * 0.3), 4))
    for i, c in enumerate(cfgs):
        vals = [data[c].get(tr, {}).get(metric, float("nan")) for tr in traces]
        if with_mean:
            vals.append(gmean(vals) if metric == "speedup" else amean(vals))
        xs = [j + (i - (n - 1) / 2) * w for j in range(len(labels))]
        ax.bar(xs, vals, w, label=c, edgecolor="grey")
        allv += [v for v in vals if not math.isnan(v)]
    if base_line is not None:
        ax.axhline(base_line, color="r", ls="--", lw=1, label="baseline")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels)
    if metric == "speedup" and allv:      # zoom in like the handout plots, ratios near 1
        lo, hi = min(allv + [1.0]), max(allv + [1.0])
        pad = max(0.02, 0.15 * (hi - lo))
        ax.set_ylim(lo - pad, hi + pad)
    ax.set_ylabel(ylabel); ax.set_title(title)
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    fig.tight_layout(); fig.savefig(f"{OUT}/{fname}.png", dpi=150); plt.close(fig)
    print(f"wrote {OUT}/{fname}.png")

bars("t1_speedup", ["ip_stride", "spp"], "speedup", "Speedup", "Speedup of L1D prefetchers over baseline (no prefetching)", 1.0)
bars("t1_mpki", ["baseline", "ip_stride", "spp"], "l1d_load_mpki", "L1D load MPKI", "L1D load MPKI")
bars("t1_accuracy", ["ip_stride", "spp"], "l1d_pf_acc", "L1D prefetch accuracy (%)", "L1D prefetch accuracy")
bars("t1_coverage", ["ip_stride", "spp"], "l1d_coverage", "L1D prefetch coverage (%)", "L1D prefetch coverage")
bars("t1_throttle_speedup", ["spp_fix1", "spp_fix6", "spp_thr_lo", "spp", "spp_thr_hi"], "speedup", "Speedup", "SPP throttling variants", 1.0)

bars("t2a_speedup", ["rrip", "irrip"], "speedup", "Speedup", "Speedup over baseline (LRU)", 1.0)
for m, l in [("l2c_load_mpki", "L2C load MPKI"), ("l2c_instr_mpki", "L2C instruction load MPKI"), ("l2c_data_mpki", "L2C data load MPKI")]:
    bars(f"t2a_{m}", ["baseline", "rrip", "irrip"], m, l, l)
    bars(f"t2b_{m}", ["baseline", "rrip", "irrip", "dyn_t25"], m, l, l)
bars("t2a_ablation", ["rrip", "irrip_ins_only", "irrip_no_evict", "irrip_ins0", "irrip"], "speedup", "Speedup", "I-RRIP ablation", 1.0)
bars("t2b_threshold", ["dyn_t10", "dyn_t20", "dyn_t25", "dyn_t35", "dyn_t50", "dyn_duel"], "speedup", "Speedup", "Dynamic I-RRIP: threshold sensitivity", 1.0)
bars("t2b_speedup", ["rrip", "irrip", "dyn_t25"], "speedup", "Speedup", "Speedup over baseline (LRU)", 1.0)

bars("t3_speedup", ["spp", "dyn_t25", "spp_rrip", "spp_dyn_nopfa", "spp_dyn"], "speedup", "Speedup", "Task 3: SPP + Dynamic I-RRIP", 1.0)
for m, l in [("l1d_load_mpki", "L1D load MPKI"), ("l2c_load_mpki", "L2C load MPKI"), ("l2c_instr_mpki", "L2C instruction load MPKI"),
             ("l2c_data_mpki", "L2C data load MPKI"), ("l1d_pf_acc", "L1D prefetch accuracy (%)"), ("l1d_coverage", "L1D coverage (%)")]:
    bars(f"t3_{m}", ["spp", "spp_dyn_nopfa", "spp_dyn"] if "l1d_pf" in m or "cov" in m else ["baseline", "spp", "dyn_t25", "spp_dyn"], m, l, l)
