"""Render the correlation result as a single self-contained HTML dashboard."""
import html
import json
from datetime import date
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from flow import core

ROOT = Path(__file__).resolve().parents[1]
COLORS = {"GREEN": "#1a7f37", "AMBER": "#b26a00", "RED": "#c62828", "INFO": "#4a5568"}


def spec_figure(r: dict) -> str:
    vals = core.silicon_values(r["silicon_source"], r["silicon_name"], r["unit"])
    fig = go.Figure()
    fig.add_histogram(x=vals, name=f"Silicon ({r['silicon_source']}, n={r['n']})",
                      marker_color="#5b8def", opacity=0.75, nbinsx=30)
    fig.add_vrect(x0=r["sim_ss"], x1=r["sim_ff"], fillcolor="#9ad0a8", opacity=0.35,
                  line_width=0)
    fig.add_vline(x=r["sim_tt"], line_color="#1a7f37", line_width=2)
    for lim, label in ((r["limit_min"], "min"), (r["limit_max"], "max")):
        if lim is not None:
            fig.add_vline(x=lim, line_color="#c62828", line_dash="dash",
                          annotation_text=f"spec {label}", annotation_position="top left")
    pts = [float(vals.min()), float(vals.max()), r["sim_ss"], r["sim_ff"]] + \
          [x for x in (r["limit_min"], r["limit_max"]) if x is not None]
    pad = (max(pts) - min(pts)) * 0.08
    fig.update_xaxes(range=[min(pts) - pad, max(pts) + pad])
    fig.update_layout(autosize=True, height=260, margin=dict(l=40, r=20, t=30, b=40), showlegend=False,
                      xaxis_title=f"{r['spec']} [{r['unit']}]", yaxis_title="count",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig.to_html(full_html=False, include_plotlyjs=False, default_width="100%",
                       config={"responsive": True, "displaylogo": False})


def limits(r: dict) -> str:
    lo, hi, u = r["limit_min"], r["limit_max"], html.escape(r["unit"])
    if lo is not None and hi is not None:
        return f"{lo} – {hi} {u}"
    return f"≥ {lo} {u}" if lo is not None else f"≤ {hi} {u}"


def render(run: dict, out: Path) -> Path:
    corr = run["correlation"]
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(r['spec_id'])}</td><td>{e(r['spec'])}</td>"
        f"<td>{limits(r)}</td>"
        f"<td>{r['sim_ss']} / {r['sim_tt']} / {r['sim_ff']}</td>"
        f"<td>{r['si_mean']} ± {r['si_std']}</td><td>{r['delta_vs_tt_pct']:+}%</td>"
        f"<td>{r['cpk']}</td><td>{r['yield_pct']}%</td>"
        f"<td><span class='pill' style='background:{COLORS[r['status']]}'>{r['status']}</span></td>"
        f"<td class='small' style='white-space:normal'>{e(r['silicon_source'])}: {e(r['silicon_name'])}</td></tr>"
        for r in corr["results"])
    mapping = "".join(f"<li><b>{e(m['spec_id'])}</b> → {e(m['source'])}: <code>{e(m['name'])}</code> — "
                      f"<span class='small'>{e(m.get('rationale', ''))}</span></li>" for m in run["mapping"])
    findings = "".join(
        f"<div class='finding' style='border-left-color:{COLORS.get(f['severity'], '#4a5568')}'>"
        f"<b>{e(f['severity'])} · {e(f['spec_id'])}</b> — {e(f['observation'])}"
        f"<div class='small'><b>Likely causes:</b> {e(f['likely_causes'])}<br><b>Next check:</b> {e(f['suggested_action'])}</div></div>"
        for f in run["findings"])
    charts = "".join(f"<div class='card'><h3>{e(r['spec_id'])} · {e(r['spec'])} "
                     f"<span class='pill' style='background:{COLORS[r['status']]}'>{r['status']}</span></h3>"
                     f"{spec_figure(r)}</div>" for r in corr["results"])
    c = corr["conditions"]
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Spec-to-Silicon Correlation</title>
<script>{get_plotlyjs()}</script>
<style>
:root{{--bg:#f7f8fa;--fg:#1d2330;--card:#fff;--muted:#5b6475;--line:#e3e6ec}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#12151b;--fg:#e6e9ef;--card:#1b2029;--muted:#9aa3b2;--line:#2c3340}}}}
:root[data-theme="dark"]{{--bg:#12151b;--fg:#e6e9ef;--card:#1b2029;--muted:#9aa3b2;--line:#2c3340}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:1100px;margin:auto}} h1{{margin:0 0 4px}} .small{{color:var(--muted);font-size:13px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
.pill{{color:#fff;border-radius:99px;padding:2px 9px;font-size:12px;font-weight:600}}
.finding{{border-left:4px solid;padding:8px 12px;margin:8px 0;background:var(--bg);border-radius:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:0 14px}}
h3{{margin:0 0 6px;font-size:15px}} .grid .card{{overflow:hidden;min-width:0}} code{{font-size:13px}}
</style></head><body><main>
<h1>Spec-to-Silicon Correlation · OPA2S_01</h1>
<div class="small">Conditions {c['temp_c']} °C, VDD {c['vdd']} V · sim corners ss/tt/ff from ngspice · alignment mode: {e(run['mode'])} · generated {date.today()}<br>
Silicon data in this demo is synthetic (see README).</div>
<div class="card"><b>Summary.</b> {e(run['summary'])}</div>
<div class="card"><table><tr><th>ID</th><th>Spec</th><th>Limits</th><th>Sim ss / tt / ff</th><th>Silicon mean ± σ</th>
<th>Δ vs tt</th><th>Cpk</th><th>Yield</th><th>Status</th><th>Silicon source</th></tr>{rows}</table></div>
<div class="small">Charts: blue = silicon distribution · green band = simulated ss–ff corners · green line = sim tt · red dashed = spec limits</div>
<div class="grid">{charts}</div>
<div class="card"><h3>Findings for the design team</h3>{findings}</div>
<div class="card"><h3>Spec ↔ silicon alignment</h3><ul>{mapping}</ul>
<div class="small">Unmapped silicon tests: {e(', '.join(s['name'] for s in corr['unmapped_silicon_tests']) or 'none')} ·
Specs without silicon data: {e(', '.join(corr['specs_without_silicon_data']) or 'none')}</div></div>
</main><script>window.addEventListener('load',()=>document.querySelectorAll('.plotly-graph-div').forEach(d=>Plotly.Plots.resize(d)));</script></body></html>"""
    out.write_text(doc)
    (out.with_suffix(".json")).write_text(json.dumps(run, indent=2, default=str))
    return out
