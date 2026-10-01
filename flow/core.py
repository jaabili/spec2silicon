"""Deterministic core of the flow: loading data, unit handling and correlation math.

The agent decides *what* to compare (aligning spec names to tester/bench names);
this module decides *whether it passes*. Pass/fail numbers never come from an LLM.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

UNIT_FACTORS = {  # (from, to) -> multiply by
    ("Hz", "MHz"): 1e-6, ("kHz", "MHz"): 1e-3, ("MHz", "MHz"): 1,
    ("A", "uA"): 1e6, ("mA", "uA"): 1e3, ("uA", "uA"): 1,
    ("V", "mV"): 1e3, ("V", "V"): 1, ("dB", "dB"): 1, ("deg", "deg"): 1,
}
CPK_TARGET = 1.33
DELTA_LIMIT_PCT = 10.0


def convert(values, from_unit: str, to_unit: str):
    if (from_unit, to_unit) not in UNIT_FACTORS:
        raise ValueError(f"No conversion from {from_unit} to {to_unit}")
    return values * UNIT_FACTORS[(from_unit, to_unit)]


def load_specs() -> dict:
    return yaml.safe_load((ROOT / "specs" / "opamp_spec.yaml").read_text())


def load_sim() -> pd.DataFrame:
    return pd.read_csv(DATA / "sim_results.csv")


def load_ate() -> pd.DataFrame:
    return pd.read_csv(DATA / "ate_datalog.csv")


def load_bench() -> pd.DataFrame:
    return pd.read_csv(DATA / "bench_measurements.csv")


def list_sources() -> list[dict]:
    """Everything measured on silicon, with units and sample counts."""
    out = []
    for col in load_ate().columns:
        m = re.match(r"(.+)\[(.+)\]$", col)
        if m:
            out.append({"source": "ATE", "name": col, "unit": m.group(2),
                        "n": int(load_ate()[col].notna().sum())})
    bench = load_bench()
    for (name, unit), g in bench.groupby(["measurement", "unit"]):
        out.append({"source": "bench", "name": name, "unit": unit, "n": len(g)})
    return out


def silicon_values(source: str, name: str, to_unit: str) -> np.ndarray:
    if source == "ATE":
        unit = re.match(r".+\[(.+)\]$", name).group(1)
        return convert(load_ate()[name].dropna().to_numpy(), unit, to_unit)
    bench = load_bench()
    rows = bench[bench.measurement == name]
    return convert(rows.value.to_numpy(), rows.unit.iloc[0], to_unit)


def correlate(mapping: list[dict], temp_c=27, vdd=1.8) -> dict:
    """mapping: [{spec_id, source, name}], at most one silicon source per spec."""
    specs = {s["id"]: s for s in load_specs()["specs"]}
    sim = load_sim()
    sim_cond = sim[(sim.temp_c == temp_c) & (np.isclose(sim.vdd, vdd))]
    results, mapped_ids = [], set()

    for m in mapping:
        spec = specs[m["spec_id"]]
        mapped_ids.add(spec["id"])
        lo, hi = spec.get("min"), spec.get("max")
        sim_vals = sim_cond.set_index("corner")[spec["sim_measure"]] * spec["sim_scale"]
        si = silicon_values(m["source"], m["name"], spec["unit"])
        mean, sd = float(si.mean()), float(si.std(ddof=1))
        cpk_parts = []
        if hi is not None:
            cpk_parts.append((hi - mean) / (3 * sd))
        if lo is not None:
            cpk_parts.append((mean - lo) / (3 * sd))
        cpk = min(cpk_parts)
        in_spec = np.ones(len(si), bool)
        if lo is not None:
            in_spec &= si >= lo
        if hi is not None:
            in_spec &= si <= hi
        typ = float(sim_vals["tt"])
        delta = (mean - typ) / typ * 100

        flags = []
        if in_spec.mean() < 0.99:
            flags.append("SPEC_FAIL")
        if not (sim_vals.min() <= mean <= sim_vals.max()):
            flags.append("OUTSIDE_SIM_CORNERS")
        if cpk < CPK_TARGET:
            flags.append("LOW_CPK")
        if abs(delta) > DELTA_LIMIT_PCT:
            flags.append("LARGE_SIM_DELTA")
        status = ("RED" if {"SPEC_FAIL", "OUTSIDE_SIM_CORNERS"} & set(flags)
                  else "AMBER" if flags else "GREEN")

        results.append({
            "spec_id": spec["id"], "spec": spec["name"], "unit": spec["unit"],
            "limit_min": lo, "limit_max": hi,
            "silicon_source": m["source"], "silicon_name": m["name"], "n": int(len(si)),
            "sim_tt": round(typ, 3), "sim_ss": round(float(sim_vals["ss"]), 3),
            "sim_ff": round(float(sim_vals["ff"]), 3),
            "si_mean": round(mean, 3), "si_std": round(sd, 3),
            "si_min": round(float(si.min()), 3), "si_max": round(float(si.max()), 3),
            "delta_vs_tt_pct": round(delta, 1), "cpk": round(cpk, 2),
            "yield_pct": round(float(in_spec.mean()) * 100, 1), "flags": flags, "status": status,
        })

    used = {(m["source"], m["name"]) for m in mapping}
    unmapped_sources = [s for s in list_sources() if (s["source"], s["name"]) not in used]
    unverified_specs = [sid for sid in specs if sid not in mapped_ids]
    return {"conditions": {"temp_c": temp_c, "vdd": vdd}, "results": results,
            "unmapped_silicon_tests": unmapped_sources, "specs_without_silicon_data": unverified_specs}
