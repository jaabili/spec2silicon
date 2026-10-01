"""Run the op-amp testbench across PVT corners with ngspice and collect results.

Output: data/sim_results.csv  (one row per corner x temperature x supply)
"""
import itertools
import re
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NETLISTS = ROOT / "sim" / "netlists"

CORNERS = ["tt", "ff", "ss"]
TEMPS = [-40, 27, 125]
VDDS = [1.62, 1.8, 1.98]


def run_one(corner: str, temp: int, vdd: float) -> dict:
    tmpl = (NETLISTS / "opamp_tb.cir.tmpl").read_text()
    netlist = (tmpl.replace("{corner}", corner).replace("{temp}", str(temp))
                   .replace("{vdd}", str(vdd)).replace("{vcm}", str(round(vdd / 2, 3))))
    with tempfile.NamedTemporaryFile("w", suffix=".cir", dir=NETLISTS, delete=False) as f:
        f.write(netlist)
        path = Path(f.name)
    try:
        out = subprocess.run(["ngspice", "-b", str(path)], capture_output=True,
                             text=True, cwd=NETLISTS, timeout=60).stdout
    finally:
        path.unlink()
    row = {"corner": corner, "temp_c": temp, "vdd": vdd}
    for name, val in re.findall(r"RESULT (\w+) (\S+)", out):
        row[name] = float(val)
    return row


def main() -> pd.DataFrame:
    rows = [run_one(c, t, v) for c, t, v in itertools.product(CORNERS, TEMPS, VDDS)]
    df = pd.DataFrame(rows)
    out = ROOT / "data" / "sim_results.csv"
    df.to_csv(out, index=False)
    print(f"Simulated {len(df)} PVT points -> {out.relative_to(ROOT)}")
    return df


if __name__ == "__main__":
    print(main().round(2).to_string(index=False))
