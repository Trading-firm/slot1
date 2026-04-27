"""Aggregate per-pattern stats across all backtest log files in logs/ matching a glob."""
import sys, re, glob, os

logs_dir = "logs"
pattern_files = sorted(glob.glob(os.path.join(logs_dir, "tf[245]_*.txt")))

agg = {}
for filepath in pattern_files:
    in_pattern_section = False
    with open(filepath) as fh:
        for line in fh:
            if "By pattern" in line:
                in_pattern_section = True
                continue
            if in_pattern_section:
                if line.startswith("  By month") or line.startswith("---") or line.strip() == "":
                    in_pattern_section = False
                    continue
                # Match: "    hammer                  16 trades  | WR 56.2% | NET $-2.52"
                m = re.match(
                    r"\s+(\w+)\s+(\d+)\s+trades\s+\|\s+WR\s+([\d.]+)%\s+\|\s+NET\s+\$([+-]?[\d.]+)",
                    line,
                )
                if m:
                    pat = m.group(1)
                    n   = int(m.group(2))
                    wr  = float(m.group(3))
                    net = float(m.group(4))
                    s = agg.setdefault(pat, {"n": 0, "wins": 0, "pnl": 0.0})
                    s["n"] += n
                    s["wins"] += int(round(n * wr / 100))
                    s["pnl"] += net

print(f"Aggregate across {len(pattern_files)} backtest files:\n")
print(f"  {'pattern':<22} {'trades':>7}  {'WR':>6}  {'NET':>10}  {'$/trade':>10}")
print(f"  {'-'*22} {'-'*7}  {'-'*6}  {'-'*10}  {'-'*10}")
for pat, s in sorted(agg.items(), key=lambda kv: -kv[1]["pnl"]):
    wr = s["wins"] / s["n"] * 100 if s["n"] else 0
    per = s["pnl"] / s["n"] if s["n"] else 0
    print(f"  {pat:<22} {s['n']:>7}  {wr:>5.1f}%  ${s['pnl']:>+9.2f}  ${per:>+8.3f}")