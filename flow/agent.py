"""Agentic step: align spec-sheet names with tester/bench names, run the
deterministic correlation, and explain discrepancies for the design team.

Two modes:
  * agent (default when ANTHROPIC_API_KEY is set): Claude uses tools to inspect
    the spec sheet and silicon data, proposes the mapping, runs the correlation
    and writes findings with likely root causes.
  * offline: a rule-based aligner + templated findings, so the flow runs anywhere.
"""
import json
import os

from flow import core

MODEL = os.environ.get("SPEC2SI_MODEL", "claude-sonnet-5-5")

TOOLS = [
    {"name": "get_spec_sheet",
     "description": "Return the block's spec sheet: ids, names, symbols, units, limits, and whether each spec is verified on ATE or bench.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_silicon_sources",
     "description": "List every silicon measurement available (ATE datalog columns and bench measurements) with unit and sample count. Names do not match spec names.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_correlation",
     "description": "Deterministically correlate specs vs simulation corners vs silicon for a proposed mapping. Returns stats (mean, std, Cpk, yield, delta vs typical sim) and flags. Use at most one silicon source per spec.",
     "input_schema": {"type": "object", "properties": {"mapping": {"type": "array", "items": {
         "type": "object", "properties": {
             "spec_id": {"type": "string"}, "source": {"type": "string", "enum": ["ATE", "bench"]},
             "name": {"type": "string"}}, "required": ["spec_id", "source", "name"]}}},
         "required": ["mapping"]}},
    {"name": "submit_findings",
     "description": "Submit the final mapping and findings for the design team. Call exactly once, after run_correlation.",
     "input_schema": {"type": "object", "properties": {
         "mapping": {"type": "array", "items": {"type": "object", "properties": {
             "spec_id": {"type": "string"}, "source": {"type": "string"}, "name": {"type": "string"},
             "rationale": {"type": "string"}}, "required": ["spec_id", "source", "name", "rationale"]}},
         "findings": {"type": "array", "items": {"type": "object", "properties": {
             "spec_id": {"type": "string"}, "severity": {"type": "string", "enum": ["RED", "AMBER", "INFO"]},
             "observation": {"type": "string"}, "likely_causes": {"type": "string"},
             "suggested_action": {"type": "string"}},
             "required": ["spec_id", "severity", "observation", "likely_causes", "suggested_action"]}},
         "summary": {"type": "string"}},
         "required": ["mapping", "findings", "summary"]}},
]

SYSTEM = """You are a spec-to-silicon correlation agent for an analog design team.
Goal: map every spec to the right silicon measurement, run the correlation, and report
discrepancies the designers should act on.
Rules:
- Match by meaning, symbol, unit dimension and test conditions, not by string similarity alone.
- Prefer the source named in the spec's verified_by field; mention secondary sources in rationale.
- Never compute pass/fail yourself; use run_correlation and trust its numbers.
- For each flagged spec, give concrete, physically plausible analog causes (e.g. layout parasitics,
  model accuracy, test setup/probe loading, temperature, bias) and a concrete next check.
- Also report silicon tests with no spec, and specs with no silicon data.
Keep findings short and specific."""


def run_agent(max_turns: int = 12) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": "Correlate block OPA2S_01: spec sheet vs simulation corners vs ATE and bench data."}]
    last_corr = None
    for _ in range(max_turns):
        resp = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM,
                                      tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_findings":
                if last_corr is None:
                    last_corr = core.correlate(block.input["mapping"])
                return {"mode": f"agent ({MODEL})", **block.input, "correlation": last_corr}
            try:
                if block.name == "get_spec_sheet":
                    out = core.load_specs()
                elif block.name == "list_silicon_sources":
                    out = core.list_sources()
                elif block.name == "run_correlation":
                    out = last_corr = core.correlate(block.input["mapping"])
                else:
                    out = {"error": f"unknown tool {block.name}"}
            except Exception as e:  # surface errors to the agent so it can fix its mapping
                out = {"error": str(e)}
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(out, default=str)})
        if not results:
            break
        messages.append({"role": "user", "content": results})
    raise RuntimeError("Agent did not submit findings")


# ---------------------------------------------------------------- offline mode
SYNONYMS = {"A0": ["AOL", "GAIN"], "GBW": ["GBW", "UGB", "BANDWIDTH"],
            "PM": ["PHASE MARGIN", "PM"], "IQ": ["IDDQ", "IQ", "SUPPLY CURRENT"]}


def offline_align() -> list[dict]:
    sources = core.list_sources()
    mapping = []
    for spec in core.load_specs()["specs"]:
        cands = []
        for s in sources:
            if not any(k in s["name"].upper() for k in SYNONYMS.get(spec["symbol"], [])):
                continue
            if (s["unit"], spec["unit"]) not in core.UNIT_FACTORS:
                continue
            score = 2 if s["source"].lower() == spec["verified_by"].lower() else 1
            cands.append((score, s))
        if cands:
            _, best = max(cands, key=lambda c: c[0])
            mapping.append({"spec_id": spec["id"], "source": best["source"], "name": best["name"],
                            "rationale": f"Keyword match on {spec['symbol']}, unit {best['unit']}->{spec['unit']}, "
                                         f"source matches verified_by={spec['verified_by']}"})
    return mapping


CAUSES = {
    "GBW": ("Unmodelled parasitic capacitance at the Miller/compensation node, or Cc/Rz process spread.",
            "Re-run with post-layout (RC-extracted) netlist; check Cc/Rz values on silicon; compare ss corner."),
    "PM": ("Probe/board capacitance adds to CL on the bench; non-dominant pole lower than simulated.",
           "Re-simulate with measured fixture load (CL + probe); verify on ATE-style load or with active probe."),
}


def run_offline() -> dict:
    mapping = offline_align()
    corr = core.correlate(mapping)
    sym = {s["id"]: s["symbol"] for s in core.load_specs()["specs"]}
    findings = []
    for r in corr["results"]:
        if r["status"] == "GREEN":
            continue
        cause, action = CAUSES.get(sym[r["spec_id"]], ("Needs designer review.", "Review test setup and models."))
        findings.append({"spec_id": r["spec_id"], "severity": r["status"],
                         "observation": f"{r['spec']}: silicon mean {r['si_mean']} {r['unit']} vs sim tt {r['sim_tt']} "
                                        f"({r['delta_vs_tt_pct']:+}%), Cpk {r['cpk']}, flags {', '.join(r['flags'])}",
                         "likely_causes": cause, "suggested_action": action})
    specs = core.load_specs()["specs"]
    by_id = {r["spec_id"]: r for r in corr["results"]}
    for s in corr["unmapped_silicon_tests"]:
        twin = next((sp for sp in specs if sp["id"] in by_id and (s["unit"], sp["unit"]) in core.UNIT_FACTORS
                     and any(k in s["name"].upper() for k in SYNONYMS.get(sp["symbol"], []))), None)
        if twin:
            vals = core.silicon_values(s["source"], s["name"], twin["unit"])
            findings.append({"spec_id": twin["id"], "severity": "INFO",
                             "observation": f"Secondary {s['source']} measurement '{s['name']}' (n={s['n']}): mean "
                                            f"{vals.mean():.2f} {twin['unit']} vs primary {by_id[twin['id']]['si_mean']}",
                             "likely_causes": "Cross-check between test platforms.",
                             "suggested_action": "Track ATE-vs-bench offset; agreement supports the ATE test setup."})
            continue
        findings.append({"spec_id": "-", "severity": "INFO", "observation": f"Silicon test '{s['name']}' ({s['source']}) has no spec",
                         "likely_causes": "Screening/secondary test or missing spec entry.",
                         "suggested_action": "Confirm whether a spec limit should exist."})
    return {"mode": "offline (rule-based)", "mapping": mapping, "findings": findings,
            "summary": f"{sum(r['status'] != 'GREEN' for r in corr['results'])} of {len(corr['results'])} specs flagged.",
            "correlation": corr}


def run(offline: bool = False) -> dict:
    if offline or not os.environ.get("ANTHROPIC_API_KEY"):
        return run_offline()
    return run_agent()
