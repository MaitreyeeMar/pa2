#!/bin/bash
# Build every configuration needed for PA2 and run it on all traces.
#
#   ./scripts/run_all.sh <trace_dir> [jobs] [extra]
#     trace_dir : folder with the *.champsimtrace.xz files
#     jobs      : simulations to run in parallel (default 4, keep <= #cores)
#     extra     : "sweep" also builds the SPP throttling / I-RRIP ablation variants
#
# WARMUP / SIM can be overridden from the environment (defaults 25M / 25M as in the handout).
# Results go to results/<config>/<trace>.txt, then run scripts/parse_results.py.

set -u
TRACE_DIR=${1:?usage: run_all.sh <trace_dir> [jobs] [sweep]}
JOBS=${2:-4}
EXTRA=${3:-}
WARMUP=${WARMUP:-25000000}
SIM=${SIM:-25000000}
cd "$(dirname "$0")/.."

# config name  -> "<l1d prefetcher> <l2c replacement>"
declare -A CFG
CFG[baseline]="no lru"
CFG[ip_stride]="ip_stride lru"
CFG[spp]="spp lru"
CFG[rrip]="no rrip"
CFG[irrip]="no irrip"
for t in 10 20 25 35 50; do CFG[dyn_t$t]="no dyn_irrip_t$t"; done
CFG[dyn_duel]="no dyn_irrip_duel"
CFG[spp_dyn]="spp dyn_irrip"              # Task 3 (prefetch aware)
CFG[spp_dyn_nopfa]="spp dyn_irrip_nopfa"  # Task 3 ablation: awareness off
CFG[spp_rrip]="spp rrip"

# ---- generate the variant source files (deleted again at the end) ----
GEN=()
trap 'rm -f "${GEN[@]}"' EXIT     # remove generated variants even if the script is interrupted
mkvar() {  # mkvar <src> <dst> <sed expression>
    sed "$3" "replacement/$1.l2c_repl" > "replacement/$2.l2c_repl"; GEN+=("replacement/$2.l2c_repl"); }
mkpf() {
    sed "$3" "prefetcher/$1.l1d_pref" > "prefetcher/$2.l1d_pref"; GEN+=("prefetcher/$2.l1d_pref"); }

for t in 10 20 25 35 50; do mkvar dyn_irrip dyn_irrip_t$t "s/^#define THRESH_PCT 25/#define THRESH_PCT $t/"; done
mkvar dyn_irrip dyn_irrip_duel  's/^#define DYN_MODE 0/#define DYN_MODE 1/'
mkvar dyn_irrip dyn_irrip_nopfa 's/^#define PF_AWARE 1/#define PF_AWARE 0/'

if [ "$EXTRA" == "sweep" ]; then
    # SPP throttling: fixed degrees (no throttling) and two other threshold sets
    mkpf spp spp_fix1   's/^#define ACC_HI   75/#define ACC_HI   101/; s/^#define ACC_MID  50/#define ACC_MID  101/; s/^#define ACC_LO   30/#define ACC_LO   101/'
    mkpf spp spp_fix6   's/^#define ACC_HI   75/#define ACC_HI   0/'
    mkpf spp spp_thr_lo 's/^#define ACC_HI   75/#define ACC_HI   60/; s/^#define ACC_MID  50/#define ACC_MID  40/; s/^#define ACC_LO   30/#define ACC_LO   20/'
    mkpf spp spp_thr_hi 's/^#define ACC_HI   75/#define ACC_HI   85/; s/^#define ACC_MID  50/#define ACC_MID  65/; s/^#define ACC_LO   30/#define ACC_LO   40/'
    for v in fix1 fix6 thr_lo thr_hi; do CFG[spp_$v]="spp_$v lru"; done
    # I-RRIP ablation: which of insertion / promotion / eviction changes matter
    mkvar irrip irrip_ins_only 's/^#define DATA_PROMOTE 1/#define DATA_PROMOTE 0/; s/^#define EVICT_DATA_FIRST 1/#define EVICT_DATA_FIRST 0/; s/^#define INSTR_AGE_EVERY 2/#define INSTR_AGE_EVERY 1/'
    mkvar irrip irrip_no_evict 's/^#define EVICT_DATA_FIRST 1/#define EVICT_DATA_FIRST 0/; s/^#define INSTR_AGE_EVERY 2/#define INSTR_AGE_EVERY 1/'
    mkvar irrip irrip_ins0     's/^#define INSTR_INSERT 1/#define INSTR_INSERT 0/'
    for v in ins_only no_evict ins0; do CFG[irrip_$v]="no irrip_$v"; done
fi

# ---- build ----
mkdir -p bin results logs
declare -A BIN
for c in "${!CFG[@]}"; do
    read pf repl <<< "${CFG[$c]}"
    echo "[build] $c  ($pf / $repl)"
    if ! ./build_champsim.sh "$pf" "$repl" "$c" > "logs/build_$c.log" 2>&1; then
        echo "  build failed, see logs/build_$c.log"; exit 1
    fi
    BIN[$c]=$(ls bin/*-1core-$c | head -1)
done
rm -f "${GEN[@]}"

# ---- run ----
run_one() {  # bin config trace
    local n=$(basename "$3"); n=${n%.gz}; n=${n%.xz}; n=${n%.champsimtrace}
    local out="results/$2/$n.txt"
    if [ -s "$out" ] && grep -q "cumulative IPC" "$out"; then return; fi   # already done
    "$1" -warmup_instructions $WARMUP -simulation_instructions $SIM -traces "$3" > "$out" 2>&1
    echo "[done] $2 $(basename "$3")"
}
export -f run_one; export WARMUP SIM
for c in "${!CFG[@]}"; do
    mkdir -p "results/$c"
    for t in "$TRACE_DIR"/*.xz "$TRACE_DIR"/*.gz; do
        [ -e "$t" ] || continue
        echo "${BIN[$c]} $c $t"
    done
done | xargs -P "$JOBS" -L 1 bash -c 'run_one "$0" "$1" "$2"'

echo "All runs finished. Now: python3 scripts/parse_results.py"
