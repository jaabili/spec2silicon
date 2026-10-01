"""spec2silicon: one command from spec sheet to correlation dashboard.

    python run_flow.py              # agent mode if ANTHROPIC_API_KEY is set, else offline
    python run_flow.py --offline    # rule-based alignment, no API needed
    python run_flow.py --skip-sim   # reuse data/sim_results.csv
"""
import argparse
from pathlib import Path

from flow import agent, make_silicon_data, report, run_sims

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="rule-based alignment, no LLM")
    ap.add_argument("--skip-sim", action="store_true", help="reuse existing simulation results")
    args = ap.parse_args()

    if not args.skip_sim:
        run_sims.main()
    if not (ROOT / "data" / "ate_datalog.csv").exists() or not args.skip_sim:
        make_silicon_data.main()

    result = agent.run(offline=args.offline)
    out = report.render(result, ROOT / "reports" / "correlation_report.html")

    print(f"\nAlignment mode: {result['mode']}")
    for r in result["correlation"]["results"]:
        print(f"  {r['status']:5}  {r['spec_id']}  {r['spec']:<26} sim tt {r['sim_tt']:>8}  "
              f"silicon {r['si_mean']:>8} {r['unit']:<4} Cpk {r['cpk']:>5}  {', '.join(r['flags'])}")
    print(f"\nDashboard: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
