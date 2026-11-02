"""Where does each bench's time go?  Records, for every request on a simpy Resource, WHO asked (the calling function)
and how long the slot was held, then prints tech-minutes per day by bench x activity.

    from modules.tech_audit import install, report
    install()                      # before run_simulation(); tags resources made by simulation_d4._initialize_resources
    ... run_simulation(...)
    report(sim_days)

Used by `python diagnostic_plots.py --audit`. Breaks show as `single_shift_breaks`, huddles as `shift_handoff_process`;
a bench that is 'busy' but whose time is mostly breaks/huddles/workups explains a queue that nominal rho misses.
Zero effect on the simulation's random numbers; a few percent slower while installed.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import simpy
from simpy.resources.resource import Release, Request

_SKIP_FUNCS = {"req_resource", "__init__", "request", "__get__", "_get_request"}
busy = defaultdict(float)      # (bench, caller) -> slot-minutes
count = defaultdict(int)
_installed = False


def _caller():
    f = sys._getframe(2)
    while f is not None:
        fn = f.f_code.co_filename.replace("\\", "/")
        if "/simpy/" not in fn and f.f_code.co_name not in _SKIP_FUNCS:
            return f.f_code.co_name
        f = f.f_back
    return "?"


def install():
    global _installed
    if _installed:
        return
    _installed = True
    busy.clear()
    count.clear()

    orig_init = Request.__init__
    orig_rel_init = Release.__init__

    def init(self, resource):
        orig_init(self, resource)
        self._audit_caller = _caller()

    def rel_init(self, resource, request):
        t0 = getattr(request, "usage_since", None)
        label = getattr(resource, "_label", None)
        if t0 is not None and label:
            key = (label, getattr(request, "_audit_caller", "?"))
            busy[key] += resource._env.now - t0
            count[key] += 1
        orig_rel_init(self, resource, request)

    Request.__init__ = init
    Release.__init__ = rel_init

    import modules.simulation_d4 as sim
    orig_res = sim._initialize_resources

    def tagged(*a, **k):
        res = orig_res(*a, **k)
        for name, r in res.items():
            r._label = name
        return res

    sim._initialize_resources = tagged


def report(sim_days: float, state=None, benches=("tech_new", "tech_urine", "tech_routine", "tech_stool", "tech_blood",
                                                  "tech_plating", "tech_accession", "tech_supervisor")):
    """tech-minutes per day by bench x activity. If df_state is given, also the share of that bench's mean capacity."""
    import pandas as pd
    rows = []
    for (bench, who), mins in busy.items():
        rows.append(dict(bench=bench, activity=who, slot_min_per_day=mins / sim_days, requests_per_day=count[(bench, who)] / sim_days,
                         mean_min_each=mins / max(count[(bench, who)], 1)))
    df = pd.DataFrame(rows)
    if df.empty:
        print("tech_audit: nothing recorded (was install() called before the run?)")
        return df
    if state is not None:
        cap = {b: float(state[f"Res_{b}_capacity"].mean()) * 1440.0 for b in benches if f"Res_{b}_capacity" in state}
        df["pct_of_bench_capacity"] = [100 * r.slot_min_per_day / cap[r.bench] if r.bench in cap else float("nan")
                                       for r in df.itertuples()]
    print("\n=== Bench time by activity (slot-minutes per day; breaks and huddles count as 'in use') ===")
    for b in benches:
        g = df[df["bench"] == b].sort_values("slot_min_per_day", ascending=False)
        if g.empty:
            continue
        print(f"\n  {b}   total {g['slot_min_per_day'].sum():,.0f} slot-min/day")
        print(g.drop(columns="bench").round(1).to_string(index=False))
    return df
