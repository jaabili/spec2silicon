"""Generate SYNTHETIC silicon data standing in for real ATE and bench results.

Real flows would read STDF from the tester and CSV/notebook exports from the lab.
Here the data is generated from the typical simulation point plus deliberate,
realistic sim-vs-silicon effects, so the correlation flow has something to find:

  * GBW ~22% lower than simulated (unmodelled layout parasitics on the Miller node)
  * Phase margin ~9 deg lower on the bench (probe + board capacitance on the output)
  * DC gain and IQ correlate well

Test names and units mimic a tester datalog and a lab notebook, and deliberately
differ from the spec sheet.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RNG = np.random.default_rng(7)


def main():
    sim = pd.read_csv(ROOT / "data" / "sim_results.csv")
    typ = sim[(sim.corner == "tt") & (sim.temp_c == 27) & (sim.vdd == 1.8)].iloc[0]

    # --- ATE datalog: 2 wafers x 120 dies, one row per die, SI units -------------
    rows = []
    for wafer in (1, 2):
        wafer_shift = RNG.normal(0, 0.01)
        for die in range(120):
            rows.append({
                "LOT": "LOT2609A", "WAFER": wafer, "DIE_X": die % 12, "DIE_Y": die // 12,
                "TEMP_C": 27, "VDD_V": 1.8,
                "CONT_OPEN_SHORT[V]": RNG.normal(0.62, 0.01),
                "OPA2S_IDDQ_VDD1P8[A]": typ.iq_ua * 1e-6 * (1 + wafer_shift) * RNG.normal(1.0, 0.017),
                "OPA2S_AOL_LF[dB]": RNG.normal(typ.dc_gain_db - 0.8, 0.9),
                "OPA2S_GBW_CL5P[Hz]": typ.ugbw_hz * 0.78 * (1 + wafer_shift) * RNG.normal(1, 0.045),
                "OPA2S_VOS[V]": RNG.normal(0.4e-3, 1.1e-3),
            })
    ate = pd.DataFrame(rows)
    ate.to_csv(ROOT / "data" / "ate_datalog.csv", index=False, float_format="%.6g")

    # --- Bench: 10 packaged samples, long format, mixed naming --------------------
    bench = []
    for s in range(1, 11):
        bench.append({"sample_id": f"PKG-{s:02d}", "measurement": "Phase margin (CL=5pF, scope)",
                      "value": RNG.normal(typ.phase_margin_deg - 9, 1.6), "unit": "deg",
                      "temp_c": 27, "vdd": 1.8, "operator": "lab-MUC"})
        bench.append({"sample_id": f"PKG-{s:02d}", "measurement": "Supply current (DMM)",
                      "value": RNG.normal(typ.iq_ua, 1.2), "unit": "uA",
                      "temp_c": 27, "vdd": 1.8, "operator": "lab-MUC"})
    pd.DataFrame(bench).to_csv(ROOT / "data" / "bench_measurements.csv", index=False,
                               float_format="%.4g")
    print(f"Wrote {len(ate)} ATE die records and {len(bench)} bench measurements (synthetic)")


if __name__ == "__main__":
    main()
