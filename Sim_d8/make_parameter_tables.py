#!/usr/bin/env python
"""Build the three parameter tables for the manuscript / code tracing.

    python make_parameter_tables.py --src <folder with your .py files> [--src <more folders>] --out <folder>

--src may be given several times and may be the project root (it is scanned recursively, __pycache__ skipped).
Files found first win when two have the same name, so list your own project folder first.

Writes
    table_S1_adjustable_parameters.csv   one row per adjustable value; LAST column = script(s) that use it
    table_S2_stages.csv                  every tracker stage/event name; LAST column = script(s) that log it
    table_S3_distributions.csv           the SHAPE of each random draw (lognormal / uniform / empirical ...); LAST column = script

"used_in_script" = scripts that reference the name in code (comments stripped), most references first.
"also_referenced_by" = dashboards, optimizer, scenario runners and plot scripts that read or override it.
A value of "NOT REFERENCED" means no other file mentions the name: candidate dead parameter.
"""
import argparse, ast, csv, importlib.util, os, re, sys
from collections import Counter, OrderedDict

TOOLING = re.compile(r"(^|_)(ml_pipeline|policy_config|run_scenarios|scenarios_def|callbacks|sim_callbacks|scenario_overrides|"
                     r"scenario_controls|layout|layouts|tab|monte_carlo|montecarlo|make_|plot_|MCvalidation|app|GraphingFunctions|"
                     r"graphing|run_ml|apply_v8|mc_runner|OpSim|Extract_real|e2e|test_|diagnostic)", re.I)
DEFINERS = {"params_d3.py", "config_d2.py", "media_config.py", "staffing_config.py", "specimen_config_d2.py",
            "policy_config.py", "stages.py", "event_name.py"}


# ------------------------------------------------------------------ source scanning
def collect(srcs):
    files = OrderedDict()
    for s in srcs:
        for root, dirs, names in os.walk(s):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "deprecated")]
            for n in names:
                if n.endswith(".py") and n not in files and not re.search(r"(_new|_old|_bak|_backup|e2e|^test|evaluate|stub)", n):
                    files[n] = os.path.join(root, n)
    return files


def strip_comments(text):
    out = []
    for line in text.splitlines():
        # remove a trailing comment unless the # is inside quotes (good enough for this code base)
        q, res = None, []
        for i, ch in enumerate(line):
            if q:
                if ch == q:
                    q = None
            elif ch in "'\"":
                q = ch
            elif ch == "#":
                break
            res.append(ch)
        out.append("".join(res))
    return "\n".join(out)


class Index:
    def __init__(self, files):
        self.code = {n: strip_comments(open(p, encoding="utf-8", errors="ignore").read()) for n, p in files.items()}

    def users(self, pattern, exclude=()):
        """-> (sim_scripts, tooling_scripts) ordered by hit count."""
        rx = re.compile(pattern)
        hits = Counter()
        for n, txt in self.code.items():
            if n in exclude:
                continue
            c = len(rx.findall(txt))
            if c:
                hits[n] += c
        sim = [n for n, _ in hits.most_common() if n not in DEFINERS and not TOOLING.search(n[:-3])]
        tool = [n for n, _ in hits.most_common() if n not in DEFINERS and TOOLING.search(n[:-3])]
        return sim, tool


def word(name):
    return r"\b%s\b" % re.escape(name)


def fmt(sim, tool, missing="NOT REFERENCED BY NAME"):
    s = "; ".join(sim) if sim else (missing if not tool else "(tooling only)")
    return s, "; ".join(tool)


# ------------------------------------------------------------------ helpers over ast
def lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def seg(src, node):
    return ast.get_source_segment(src, node) or ""


def top_assigns(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    section = ""
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            # section banner = nearest preceding comment line that looks like "# <Words> ..." framed by dashes/equals
            i = node.lineno - 2
            while i >= 0 and i > node.lineno - 12:
                l = lines[i].strip()
                if l.startswith("#") and re.search(r"[A-Za-z]{4,}", l) and not re.match(r"^#\s*[-=!]+\s*$", l):
                    section = re.sub(r"^#\s*[-=!]*\s*|\s*[-=!]*\s*$", "", l)
                    break
                i -= 1
            trail = ""
            m = re.search(r"#\s*(.*)$", lines[node.end_lineno - 1])
            if m and "(" not in lines[node.end_lineno - 1][:m.start()].rsplit(")", 1)[-1:][0:0]:
                trail = m.group(1).strip()
            for t in targets:
                names = [e for e in t.elts] if isinstance(t, ast.Tuple) else [t]
                vals = node.value.elts if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple) else [node.value] * len(names)
                for nm, v in zip(names, vals):
                    if isinstance(nm, ast.Name):
                        out.append(dict(name=nm.id, node=v, line=node.lineno, section=section, comment=trail, src=src))
    return out


# ------------------------------------------------------------------ Table S1
UNIT_HINT = [("_hours", "hours"), ("_hrs", "hours"), ("_days", "days"), ("_minutes", "minutes"), ("_min", "minutes"),
              ("_time", "minutes"), ("percent", "fraction"), ("rate", "fraction"), ("probability", "fraction"),
              ("capacity", "count"), ("_size", "count"), ("_count", "count")]


def unit_of(name, comment):
    m = re.search(r"\b(minutes?|hours?|days?|fraction|plates|seconds)\b", comment or "", re.I)
    if m:
        return m.group(1).lower()
    for k, u in UNIT_HINT:
        if k in name.lower():
            return u
    return ""


GROUPS = [
    ("Literature (Gerada 2024)", r"(task_time|_distrib$|_meta$|_process_time$|unload_from_analyzer_batch_size|use_literature)"),
    ("Run control / measurement window", r"^(sim_max_time|seed_input|warmup_days|cooldown_days|sim_start_weekday|json_year|ALLOW_DEFAULT_TTP)$"),
    ("Scenario hooks", r"^(scenario_|stool_biochem_time_multiplier)"),
    ("Media / inventory", r"(lead_time|stockout_recheck)"),
    ("Shifts and staffing", r"^(shift_|break1|handoff|float_accession)"),
    ("Arrival and priority", r"^(stat_skip_hold|accession_hold_mode|rejection_percent|accession_batch)"),
    ("Positivity and organisms", r"(positivity|positive_specimen|multiple_organism|colony|isolate|time2pos|DEFAULT_.*TTP)"),
    ("Work-up and subculture", r"(workup|subcult|reincub|tech_review|repeat_read|max_subculture|incubation_1|incubation_2)"),
    ("Incubation and plate reads", r"(incubation|plate_read|read_min|scheduled_reads)"),
    ("Plating and WASP", r"(plating|wasp)"),
    ("MALDI / Phoenix / Gram", r"(maldi|MALDI|phoenix|PHENIX|gram_stain|BioFire|biochem_screen)"),
    ("Final read", r"^(final_read|min_final_read|max_final_read)"),
    ("Bench tests (stool/biochem)", r"(oxidase|indole|catalase|latex|tsi_|pbp|biochem_)"),
    ("Batching", r"^(batch_size|max_wait)$"),
]


def group_of(n):
    for g, rx in GROUPS:
        if re.search(rx, n):
            return g
    return "Other (params_d3)"


GUI_OVERRIDE = {  # how the value can be changed without editing the file
    "scenario_staffing_json": "scenario tweak (staffing ops)", "scenario_media_json": "scenario tweak (media)",
    "scenario_volume_json": "scenario tweak (volume)", "scenario_instrument_json": "scenario tweak (instrument)",
}


def table_params(files, idx, out_rows):
    # ---- params_d3.py
    p = files.get("params_d3.py")
    if p:
        skip = {"file_dir", "PROJECT_ROOT", "PARENT_DIR", "json_dir", "loaded_data", "TTP_SOURCE", "TTP_CONFIGS",
                "_warned_ttp_keys", "configs_to_load"}
        for a in top_assigns(p):
            n = a["name"]
            if n in skip or n.startswith("_"):
                continue
            v = lit(a["node"])
            if v is None and not isinstance(a["node"], (ast.Call, ast.BinOp, ast.Attribute)):
                continue
            if v is None:
                v = seg(a["src"], a["node"])
            sim, tool = idx.users(r"(?<![\w.])(?:p|params|params_d3)\.%s\b|getattr\(\s*\w+\s*,\s*[\"']%s[\"']|[\"']%s[\"']|^\s*%s\b" % (n, n, n, n),
                                  exclude=("params_d3.py",))
            s, t = fmt(sim, tool)
            grp = group_of(n)
            out_rows.append(dict(group=grp, parameter=n, value=v, units=unit_of(n, a["comment"]), description=a["comment"],
                                 defined_in="params_d3.py:%d" % a["line"],
                                 how_to_change=GUI_OVERRIDE.get(n, "edit file / --overrides / dashboard Scenario Tweaks"),
                                 also_referenced_by=t, used_in_script=s))
    # ---- config_d2.py (instruments)
    p = files.get("config_d2.py")
    if p:
        for a in top_assigns(p):
            n = a["name"]
            if n == "Instrument_resources":
                continue
            v = lit(a["node"]) if lit(a["node"]) is not None else seg(a["src"], a["node"])
            sim, tool = idx.users(word(n), exclude=("config_d2.py",))
            if not sim and n in ("bc_instrument_capacity", "num_BACTEC_virtuo", "incubator_capacity", "temp_slots_phenix",
                                 "phoenix_capacity_permach", "numphenix", "maldi_cap"):
                sim, tool = idx.users(word("Instrument_resources"), exclude=("config_d2.py",))
            s, t = fmt(sim, tool)
            out_rows.append(dict(group="Instruments", parameter=n, value=v, units=unit_of(n, a["comment"]), description=a["comment"],
                                 defined_in="config_d2.py:%d" % a["line"],
                                 how_to_change="edit file / scenario_instrument_json / dashboard capacities",
                                 also_referenced_by=t, used_in_script=s))
    # ---- staffing_config.py
    p = files.get("staffing_config.py")
    if p:
        ns = {}
        exec(compile(open(p, encoding="utf-8").read(), p, "exec"), ns)
        prof = ns["SHIFT_STAFFING_PROFILE"]
        base_sim, base_tool = idx.users(word("SHIFT_STAFFING_PROFILE"), exclude=("staffing_config.py",))
        for dt, shifts in prof.items():
            for sh, cfg in shifts.items():
                for k, v in cfg.items():
                    sim, tool = idx.users(r"[\"']%s[\"']" % k, exclude=("staffing_config.py",))
                    sim = list(base_sim) + [s for s in sim if s not in base_sim and re.search(r"media|inventory", idx.code[s], re.I)]
                    s, t = fmt(sim, tool)
                    out_rows.append(dict(group="Staffing (%s)" % dt, parameter="SHIFT_STAFFING_PROFILE[%s][%s][%s]" % (dt, sh, k),
                                         value=str(v), units="hours (start, end)" if k == "hours" else "techs" if k.startswith("tech_") else "plates in parallel",
                                         description="", defined_in="staffing_config.py",
                                         how_to_change="edit file / scenario_staffing_json / dashboard staffing grid",
                                         also_referenced_by=t, used_in_script=s))
    # ---- media_config.py
    p = files.get("media_config.py")
    if p:
        spec = importlib.util.spec_from_file_location("media_config_tmp", p)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        base_sim, base_tool = idx.users(r"\bMEDIA_CONFIG\b|\bbase_media_config\b", exclude=("media_config.py",))
        for media, d in m.MEDIA_CONFIG.items():
            for k in ("cost", "shelf_life", "reorder_point", "order_qty", "initial", "order_frequency", "standing_order_qty"):
                sim, tool = idx.users(r"[\"']%s[\"']" % k, exclude=("media_config.py",))
                sim = list(base_sim) + [s for s in sim if s not in base_sim and re.search(r"media|inventory", idx.code[s], re.I)]
                s, t = fmt(sim, tool)
                src_note = "derived from real_world_media_orders (units x plates_per_order)" if k in ("order_qty", "standing_order_qty", "order_frequency") else ""
                out_rows.append(dict(group="Media inventory", parameter="MEDIA_CONFIG[%s][%s]" % (media, k), value=d.get(k),
                                     units={"cost": "$ per plate", "shelf_life": "days", "order_frequency": "days"}.get(k, "plates"),
                                     description=src_note, defined_in="media_config.py",
                                     how_to_change="edit file / scenario_media_json / dashboard media policy",
                                     also_referenced_by=t, used_in_script=s))
        for media, d in m.real_world_media_orders.items():
            for k, v in d.items():
                s, t = fmt(base_sim, base_tool)
                out_rows.append(dict(group="Media ordering (lab table)", parameter="real_world_media_orders[%s][%s]" % (media, k), value=v,
                                     units="units/order" if k == "minimum_order_qnty" else "plates/unit" if k == "plates_per_order" else "days",
                                     description="", defined_in="media_config.py", how_to_change="edit file",
                                     also_referenced_by=t, used_in_script=s))
    # ---- policy_config.py (optimizer)
    p = files.get("policy_config.py")
    if p:
        for a in top_assigns(p):
            n = a["name"]
            v = lit(a["node"])
            if v is None:
                continue
            if n == "LEVERS":
                for lv in v:
                    nm = lv.get("name") or "%s/%s" % (lv.get("bench"), lv.get("shift"))
                    rng = "[%s, %s]" % (lv["lo"], lv["hi"])
                    s, t = fmt(*idx.users(r"\bLEVERS\b", exclude=("policy_config.py",)), missing="optimizer script (reads policy_config.py) not among scanned files")
                    out_rows.append(dict(group="Optimizer levers", parameter="LEVERS[%s:%s]" % (lv["kind"], nm), value=rng,
                                         units={"staff": "delta techs", "media": "x multiplier", "instrument": "x multiplier"}.get(lv["kind"], ""),
                                         description="", defined_in="policy_config.py:%d" % a["line"], how_to_change="edit file",
                                         also_referenced_by=t, used_in_script=s))
                continue
            s, t = fmt(*idx.users(word(n), exclude=("policy_config.py",)), missing="optimizer script (reads policy_config.py) not among scanned files")
            out_rows.append(dict(group="Optimizer cost/constraints", parameter=n, value=v, units=unit_of(n, a["comment"]),
                                 description=a["comment"], defined_in="policy_config.py:%d" % a["line"], how_to_change="edit file",
                                 also_referenced_by=t, used_in_script=s))
    # ---- specimen_config_d2.py scalars (not the distributions: see S3)
    p = files.get("specimen_config_d2.py")
    if p:
        src = open(p, encoding="utf-8").read(); tree = ast.parse(src)
        sc = next((n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SPECIMEN_TYPES"), None)
        for kn, vn in zip(sc.value.keys, sc.value.values):
            t_name = lit(kn)
            seen = {}
            for k2, v2 in zip(vn.keys, vn.values):
                seen[lit(k2)] = v2
            for key, v2 in seen.items():
                if key in ("media_req", "plating_time_range", "tech_review_range", "initial_vol", "accession_touch_time_min",
                           "accession_touch_time_max", "cancel_rate_percent", "daily_volume_mean"):
                    val = lit(v2)
                    if val is None:
                        val = "JSON: " + re.sub(r"\s+", " ", seg(src, v2))
                    sim, tool = idx.users(r"[\"']%s[\"']" % key, exclude=("specimen_config_d2.py",))
                    s, t = fmt(sim, tool)
                    out_rows.append(dict(group="Specimen config", parameter="SPECIMEN_TYPES[%s][%s]" % (t_name, key), value=val,
                                         units={"media_req": "plates per specimen", "daily_volume_mean": "specimens/day",
                                                "cancel_rate_percent": "percent"}.get(key, "minutes" if "time" in key or "range" in key else ""),
                                         description="", defined_in="specimen_config_d2.py", how_to_change="edit file / scenario_volume_json for volume",
                                         also_referenced_by=t, used_in_script=s))
        for a in top_assigns(p):
            n = a["name"]
            if n in ("typical_max_plating_time", "stat_priority_cutoff", "accession_aging_minutes_per_rank", "stat_skip_hold") and lit(a["node"]) is not None:
                s, t = fmt(*idx.users(word(n), exclude=("specimen_config_d2.py",)))
                out_rows.append(dict(group="Specimen config", parameter=n, value=lit(a["node"]), units=unit_of(n, a["comment"]),
                                     description=a["comment"], defined_in="specimen_config_d2.py:%d" % a["line"], how_to_change="edit file",
                                     also_referenced_by=t, used_in_script=s))
        for dname in ("SPEC_PRIORITY_MAP", "STAT_FRACTION_BY_TYPE"):
            a = next((x for x in top_assigns(p) if x["name"] == dname), None)
            if a is not None and lit(a["node"]) is not None:
                s, t = fmt(*idx.users(word(dname), exclude=("specimen_config_d2.py",)))
                for k, v in lit(a["node"]).items():
                    out_rows.append(dict(group="Specimen priority", parameter="%s[%s]" % (dname, k), value=v, units="rank" if dname == "SPEC_PRIORITY_MAP" else "fraction",
                                         description="", defined_in="specimen_config_d2.py:%d" % a["line"], how_to_change="edit file",
                                         also_referenced_by=t, used_in_script=s))


# ------------------------------------------------------------------ Table S2 (stages)
def table_stages(files, idx, rows):
    ev = files.get("event_name.py")
    if not ev:
        return
    src = open(ev, encoding="utf-8").read()
    spec = importlib.util.spec_from_file_location("event_name_tmp", ev)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    section = ""
    lines = src.splitlines()
    sec_of = {}
    for i, l in enumerate(lines):
        mm = re.match(r"^#\s*(\d+[a-z]?\.\s+.+)$", l.strip())
        if mm and i > 0 and lines[i - 1].strip().startswith("# ---"):
            section = mm.group(1)
        mc = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*", l)
        if mc:
            sec_of[mc.group(1)] = (section, (re.search(r"#\s*(.*)$", l) or [None, ""])[1])
    stage_alias = {}
    st = files.get("stages.py")
    if st:
        for a in top_assigns(st):
            r = re.search(r"_EV\.(\w+)", seg(a["src"], a["node"]))
            if r:
                stage_alias.setdefault(r.group(1), []).append(a["name"])
    for name in [k for k in vars(m) if k.isupper() and isinstance(getattr(m, k), str)]:
        val = getattr(m, name)
        pat = r"\b(?:EV|_EV|event_name)\.%s\b" % name
        users, tool = idx.users(pat, exclude=("event_name.py", "stages.py"))
        alias = stage_alias.get(name, [])
        for al in alias:
            u2, t2 = idx.users(word(al), exclude=("event_name.py", "stages.py"))
            users += [x for x in u2 if x not in users]; tool += [x for x in t2 if x not in tool]
        s, t = fmt(users, tool)
        m_sec = sec_of.get(name, ("", ""))
        rows.append(dict(section=m_sec[0], constant=name, stage_string=val, note=m_sec[1],
                         analysis_alias=", ".join(alias), also_referenced_by=t, used_in_script=s))
    # parameterised events (functions in event_name) listed for completeness
    for fn in [k for k in vars(m) if callable(getattr(m, k)) and not k.startswith("_") and k.islower()]:
        pass


# ------------------------------------------------------------------ Table S3 (distribution shapes)
JSON_OF = {}


def table_dists(files, idx, rows):
    p = files.get("specimen_config_d2.py")
    if not p:
        return
    src = open(p, encoding="utf-8").read(); tree = ast.parse(src)
    ass = {a["name"]: a for a in top_assigns(p)}
    cfgload = lit(ass["configs_to_load"]["node"]) if "configs_to_load" in ass and lit(ass["configs_to_load"]["node"]) else None
    if cfgload is None and "configs_to_load" in ass:
        d = ass["configs_to_load"]["node"]
        cfgload = {lit(k): re.sub(r"[{}]", "", lit(v) if lit(v) else seg(src, v)).strip("f\"'") for k, v in zip(d.keys, d.values)}
    final = lit(ass["FINAL_READ_BY_TYPE"]["node"]) if "FINAL_READ_BY_TYPE" in ass else {}
    prio = lit(ass["PRIORITY_CATEGORY_BY_TYPE"]["node"]) if "PRIORITY_CATEGORY_BY_TYPE" in ass else {}
    tune = lit(ass["SPECIMEN_TUNING_MATRIX"]["node"]) if "SPECIMEN_TUNING_MATRIX" in ass else {}
    stool = lit(ass["_STOOL_PATHWAY_CFG"]["node"]) if "_STOOL_PATHWAY_CFG" in ass else {}
    pos = lit(ass["_STOOL_POSITIVITY"]["node"]) if "_STOOL_POSITIVITY" in ass else {}
    TUNE_KEY = {"Tissue": "Tissue", "Bone_Cx": "Bone_Cx", "BodyFluid": "BodyFluid", "Wound": "Wound", "Tissue_FNA": "FNA_Tissue"}

    def S(pat, ex=("specimen_config_d2.py",)):
        return fmt(*idx.users(pat, exclude=ex))

    sc = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SPECIMEN_TYPES")
    for kn, vn in zip(sc.value.keys, sc.value.values):
        t = lit(kn)
        e = {lit(k): v for k, v in zip(vn.keys, vn.values)}
        def jsonref(key):
            seg_ = seg(src, e[key]) if key in e else ""
            m_ = re.search(r"[\"'](\w+)[\"']", seg_)
            return (cfgload or {}).get(m_.group(1), "?") if m_ else ""
        jk = re.search(r"[\"'](\w+)[\"']", seg(src, e["daily_volume_mean"])).group(1) if "daily_volume_mean" in e else ""
        jf = (cfgload or {}).get(jk, "")
        def add(step, dist, params, units, source, pattern, ex=("specimen_config_d2.py",)):
            s, tl = S(pattern, ex)
            rows.append(dict(specimen_type=t, process_step=step, distribution=dist, parameters=params, units=units,
                             parameter_source=source, also_referenced_by=tl, used_in_script=s))
        # 1 arrival
        vol = lit(e["daily_volume_mean"]) if "daily_volume_mean" in e and lit(e["daily_volume_mean"]) is not None else "JSON daily_volume_mean"
        add("Arrival process", "Non-homogeneous Poisson (thinning): exponential gaps, rate = daily_volume_mean x hourly weight",
            "daily_volume_mean=%s ; 24 hourly weights (weekday) ; 24 hourly weights (weekend)" % vol, "specimens/day; weights relative",
            "JSON %s (%s)%s" % (jk, jf, " + UofU rows/365 added for urine" if t.startswith("Urine") else ""), r"nhpp_next_arrival_delta|get_current_hourly_weights")
        # 2 hold
        if "accession_time_config" in e:
            mult = {sh: v["pre_accession_hold_multiplier"] for sh, v in tune.get(TUNE_KEY.get(t, ""), {}).items() if "pre_accession_hold_multiplier" in v}
            add("Pre-accession hold (receipt -> joins accession queue)", "Empirical histogram: pick bin ~ bin_probabilities, then Uniform(bin edges)",
                "bin_probabilities, bin_edges from JSON; multiplier by shift=%s; mode=p.accession_hold_mode; STAT skips if stat_skip_hold" % (mult or "none"),
                "minutes", "JSON %s accession_time_config" % jf, r"sample_pre_accession_hold|_hist_sample")
        # 3 touch
        if "accession_touch_time_min" in e:
            add("Accession tech touch time", "Uniform(min, max)", "min=%s, max=%s" % (lit(e["accession_touch_time_min"]), lit(e["accession_touch_time_max"])),
                "minutes", "specimen_config_d2.py literal", r"_sample_accession_touch_time")
        # 4 plating
        if t in ("BCx", "BodyFluid"):
            add("Instrument load hand-off", "Uniform(0.1, 0.5) hard-coded", "0.1, 0.5", "minutes", "hard-coded in accession_d2.py", r"BC_INSTRUMENT_LOAD_PENDING")
        else:
            add("Manual plating time", "Triangular(min_plating_time, max_plating_time, mode=avg_plating_time)",
                "from params_d3: min_plating_time, max_plating_time, avg_plating_time (SPECIMEN_TYPES plating_time_range=%s is defined but %s)" % (
                    lit(e.get("plating_time_range")) if "plating_time_range" in e else "n/a",
                    "NOT read by any script" if not idx.users(r"[\"']plating_time_range[\"']", exclude=("specimen_config_d2.py",))[0] else "read"),
                "minutes", "params_d3.py", r"\bmin_plating_time\b|\bavg_plating_time\b")
            if t.startswith(("Urine", "Stool")):
                add("Automated (WASP) plating time", "Uniform(automatic_plating_time_min, automatic_plating_time_max); chosen with P=auto_plating_probability",
                    "automatic_plating_time_min/max, auto_plating_probability", "minutes / fraction", "params_d3.py", r"\bautomatic_plating_time_min\b|\bauto_plating_probability\b")
        # 5 TTP
        if t == "BCx":
            add("Time to positivity (positive bottles)", "Lognormal: exp(Normal(mu=ln(scale), sigma=shape)); params loc and min/max hours are in the config",
                "mu=ln(scale), sigma=shape from JSON BCx ttp_config; loc, min_hours, max_hours also written to the config", "hours", "JSON %s ttp_config" % jf,
                r"lognormvariate|lognormal_mu", ("specimen_config_d2.py", "specimen_config_helperfunctions.py"))
        if t == "BodyFluid":
            add("Time to positivity (positive bottles)", "Empirical histogram: bin ~ bin_probabilities, then Uniform within bin", "bin_probabilities, bin_edges from JSON",
                "hours", "JSON %s ttp_config" % jf, r"bin_probabilities", ("specimen_config_d2.py",))
        if t in ("BCx", "BodyFluid"):
            add("Negative bottle hold", "Constant", "120", "hours", "hard-coded (5-day protocol) in subpathways.py", r"120 \* 60")
            pr = lit(e.get("tech_review_range")) if "tech_review_range" in e else None
        # 6 positivity
        pr = {"BCx": "BCx_positivity", "BodyFluid": "BdyFlid_positivity"}.get(t)
        add("Culture positivity", "Bernoulli(p)", "p=%s" % (pos.get(t) if t in pos else ("params_d3 " + pr if pr else "params_d3 positive_specimen_rate (0.12) unless per-type override")),
            "probability", "params_d3.py / specimen_config_d2.py", r"\bpositive_specimen_rate\b|\bBCx_positivity\b|\bBdyFlid_positivity\b")
        # 7 incubation
        if t not in ("BCx",):
            tkey = TUNE_KEY.get(t)
            ov = {sh: {k: v for k, v in d.items() if "incubation" in k} for sh, d in tune.get(tkey, {}).items()} if tkey else {}
            prim = stool.get(t, {}).get("primary_incubation")
            if prim:
                add("Primary incubation", "Constant", "hours=%s, uses incubator slot=%s" % (prim["hours"], prim["incubator"]), "hours", "specimen_config_d2.py _STOOL_PATHWAY_CFG",
                    r"primary_incubation", ("specimen_config_d2.py",))
            add("Plate incubation / read", "Default (scheduled_reads_enabled=True): deterministic - next scheduled read slot after read_min_incubation_*_hours. "
                "Fallback model: truncated Lognormal(mean=avg, sd), resampled into [min, incubation_max_hours]",
                "read slots weekday/weekend, read_min_incubation_*_hours; fallback avg/sd/min=avg_incubation_time_Other/std_incubation_time_Other/min_incubation_time_Other; per-shift overrides=%s" % (ov or "none"),
                "hours", "params_d3.py + SPECIMEN_TUNING_MATRIX", r"_sample_incubation_minutes|_next_read_time|scheduled_reads_enabled")
        # 8 review
        if "tech_review_range" in e:
            add("Tech review (day-2 read)", "Uniform(min, max)", "min,max=%s ; per-shift overrides=%s" % (lit(e["tech_review_range"]),
                {sh: d["tech_review_range"] for sh, d in tune.get(TUNE_KEY.get(t, ""), {}).items() if "tech_review_range" in d} or "none"),
                "minutes", "specimen_config_d2.py", r"tech_review_range")
        # 9 final read
        fr = final.get(t)
        if fr:
            add("Final report timing (hold after arrival)", "Uniform(hold_hours) ; with P=extended_fraction use Uniform(extended_hours) instead (Bernoulli mixture)",
                "hold_hours=%s, extended_fraction=%s, extended_hours=%s" % (fr["hold_hours"], fr["extended_fraction"], fr["extended_hours"]), "hours after arrival",
                "specimen_config_d2.py FINAL_READ_BY_TYPE", r"process_final_read|hold_hours")
            if "positive_delay_hours" in fr:
                add("Delay for positive cultures before final", "Uniform(lo, hi)", "positive_delay_hours=%s" % (fr["positive_delay_hours"],), "hours",
                    "specimen_config_d2.py FINAL_READ_BY_TYPE", r"positive_delay_hours")
        elif t == "BCx":
            add("Final report timing", "Fixed by instrument protocol (negative bottles held 120 h); no FINAL_READ entry", "none", "hours", "n/a", r"final_read")
        # 10 cancel
        if "cancel_rate_percent" in e:
            add("Lab cancellation", "Bernoulli(p)", "p from JSON cancellation_metrics.lab_cancel_rate_pct (stool: literal 0.02 is overwritten by JSON)", "percent",
                "JSON %s" % jf, r"cancel_rate_percent")
        # 11 priority
        pm = prio.get(t)
        if pm:
            add("Priority category", "Categorical", ", ".join("%s=%s" % kv for kv in pm.items()), "probability", "specimen_config_d2.py PRIORITY_CATEGORY_BY_TYPE",
                r"priority_mix|classify_priority")
        add("STAT flag", "Bernoulli(stat_fraction)", "stat_fraction=0.0 (placeholder until estimated from LIS)", "probability", "STAT_FRACTION_BY_TYPE", r"stat_fraction")

    # ---------- global (type independent) draws from params_d3
    G = [
        ("Pre-analytical rejection", "Bernoulli(p)", "rejection_percent", r"\brejection_percent\b", "probability"),
        ("Re-incubation", "Bernoulli(p); duration Uniform(min_reincubate_time, max_reincubate_time) h", "reincubation_percent, min/max_reincubate_time", r"\breincubation_percent\b", ""),
        ("Number of organisms in a positive", "Categorical (1,2,3,4+) set by multiple_organism_rate and second/third/four_colony_(blood_)percent", "multiple_organism_rate, second_colony_percent, third_colony_percent, four_colony_percent", r"\bmultiple_organism_rate\b", "probability"),
        ("Colony work-up time", "Base time x (1 + (n-1) x colony_workup_time_factor)", "colony_workup_time_factor", r"\bcolony_workup_time_factor\b", "multiplier"),
        ("Repeat work-up (day 2/3)", "Bernoulli(p) per stage", "second_workup_percent, third_workup_percent, additional_workup_percent", r"\bsecond_workup_percent\b", "probability"),
        ("Subculture time", "Uniform(min_subculture_time, max_subculture_time) x colony factor", "min/max_subculture_time", r"\bmin_subculture_time\b", "minutes"),
        ("Subculture evaluation", "Uniform(min_subcultEval_time, max_subcultEval_time)", "min/max_subcultEval_time", r"\bmin_subcultEval_time\b", "minutes"),
        ("Repeat-plate read", "Uniform(min_repeat_read_time, max_repeat_read_time) x colony factor", "min/max_repeat_read_time", r"\bmin_repeat_read_time\b", "minutes"),
        ("Rapid biochemical screen", "Uniform(min_biochem_screen_time, max_biochem_screen_time) x batch", "min/max_biochem_screen_time", r"\bmin_biochem_screen_time\b", "minutes"),
        ("MALDI selection", "Bernoulli(maldi_testing_percent)", "maldi_testing_percent", r"\bmaldi_testing_percent\b", "probability"),
        ("MALDI target prep", "Uniform(min_MALDI_prep_time, max_MALDI_prep_time) x isolates", "min/max_MALDI_prep_time", r"\bmin_MALDI_prep_time\b", "minutes"),
        ("MALDI cartridge size", "Uniform integer over maldi_batch_isolates_range; runs part-full after maldi_batch_max_wait_minutes", "maldi_batch_isolates_range, maldi_run_min_per_isolate", r"\bmaldi_batch_isolates_range\b", "isolates"),
        ("Phoenix AST selection", "Bernoulli(Phoenix_test_percent)", "Phoenix_test_percent", r"\bPhoenix_test_percent\b", "probability"),
        ("Phoenix prep", "Uniform(min_PHENIXprep_time, max_PHENIXprep_time)", "min/max_PHENIXprep_time", r"\bmin_PHENIXprep_time\b", "minutes"),
        ("Phoenix run", "Constant phoenix_run_time_hours; times out at phoenix_max_wait", "phoenix_run_time_hours, phoenix_max_wait", r"\bphoenix_run_time_hours\b", "hours / minutes"),
        ("Final-read verify", "Uniform(min_final_read_time, max_final_read_time)", "min/max_final_read_time", r"\bmin_final_read_time\b", "minutes"),
        ("Final-read delay after positive", "Uniform over the delay tuple (blood / AST / other)", "final_read_delay_blood_hours, final_read_delay_ast_hours, final_read_delay_other_hours", r"\bfinal_read_delay_blood_hours\b", "hours"),
        ("Bench tests (oxidase, indole, catalase, latex, TSI, PBP)", "Uniform(min, max) hands-on; TSI incubation Uniform(18, 24) h; PBP wait Uniform(10, 15) min; positive rates Bernoulli", "min_/max_*_time, *_positive_rate", r"\bmin_oxidase_time\b|\bbiochem_tests_enabled\b", "minutes / hours"),
        ("Tech break start", "Uniform window break1_wind_min..break1_wind_max after shift start", "break1_wind_min, break1_wind_max", r"\bbreak1_wind_min\b", "minutes"),
        ("Accession batch wait / plating batch wait", "Deterministic timeout", "accession_batch_max_wait_minutes, batch_size, max_wait", r"\baccession_batch_max_wait_minutes\b|\bbatch_size\b", "minutes / count"),
        ("Media re-check when stocked out", "Constant", "inventory_stockout_recheck", r"\binventory_stockout_recheck\b", "minutes"),
        ("Media delivery lead time", "Constant", "order_lead_time_days", r"\border_lead_time_days\b", "days"),
    ]
    for step, dist, par, pat, units in G:
        s, tl = S(pat, ("params_d3.py", "specimen_config_d2.py"))
        rows.append(dict(specimen_type="(all types)", process_step=step, distribution=dist, parameters=par, units=units,
                         parameter_source="params_d3.py", also_referenced_by=tl, used_in_script=s))


# ------------------------------------------------------------------ main
def write(path, rows, order):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=order, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in order})
    print("wrote %s  (%d rows)" % (path, len(rows)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", action="append", required=True)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    files = collect(a.src)
    idx = Index(files)
    os.makedirs(a.out, exist_ok=True)
    r1, r2, r3 = [], [], []
    table_params(files, idx, r1); table_stages(files, idx, r2); table_dists(files, idx, r3)
    write(os.path.join(a.out, "table_S1_adjustable_parameters.csv"), r1,
          ["group", "parameter", "value", "units", "description", "defined_in", "how_to_change", "also_referenced_by", "used_in_script"])
    write(os.path.join(a.out, "table_S2_stages.csv"), r2,
          ["section", "constant", "stage_string", "note", "analysis_alias", "also_referenced_by", "used_in_script"])
    write(os.path.join(a.out, "table_S3_distributions.csv"), r3,
          ["specimen_type", "process_step", "distribution", "parameters", "units", "parameter_source", "also_referenced_by", "used_in_script"])


if __name__ == "__main__":
    main()
