"""Per-isolate bookkeeping for a positive specimen.

A positive specimen owns an IsolateSet (n isolates, drawn once from the specimen's organism-count model).  Every test that is
"per isolate" claims an isolate through the set, and an isolate can be claimed for a given test ONCE:

  gram     one Gram stain per isolate (blood / body fluid bottles)
  maldi    one MALDI spot per isolate (at most p.max_isolates_identified isolates per specimen are ever spotted)
  ast      one Phoenix AST per isolate, and only an isolate that was identified by MALDI
  <bench>  oxidase / tsi / indole / catalase / pbp / latex / biochem_panel   (see modules/biochem_tests.py)

p.isolate_strict = True (default): asking for a second MALDI/AST/Gram/bench test on the same isolate, or AST before MALDI,
raises DuplicateIsolateTest, so a workflow bug stops the run instead of quietly doubling the workload.
A polymicrobial plate is allowed to send only some isolates to MALDI/AST: each isolate is an independent draw
(rate = the specimen type's maldi_testing_percent / Phoenix_test_percent, or multi_isolate_*_rate when n > 1).

Randomness: its own stream Random(f"{run_seed}:{type}:{id}:isolates"), so isolate logic never shifts the other draws.
Export: isolate_ledger_df(env) (one row per isolate) and audit_ledger(env) (scalars added to stochastic_stats).
"""
import random

import params_config.params_d3 as p


class DuplicateIsolateTest(RuntimeError):
    pass


class PyRng:                       # adapter: _sample_num_colonies(spec_cfg, rng, ...) only touches rng.py
    __slots__ = ("py",)

    def __init__(self, r):
        self.py = r


class Isolate:
    __slots__ = ("idx", "counts", "organism")

    def __init__(self, idx):
        self.idx, self.counts, self.organism = idx, {}, None

    def done(self, test):
        return self.counts.get(test, 0) > 0


class IsolateSet:
    def __init__(self, env, spec_id, spec_type, n):
        self.spec_id, self.spec_type = spec_id, spec_type
        self.rng = random.Random(f"{env.run_seed}:{spec_type}:{spec_id}:isolates:pick")
        self.isolates = [Isolate(i + 1) for i in range(max(1, int(n)))]
        self.violations = 0

    @property
    def n(self):
        return len(self.isolates)

    def pending(self, test, identified_only=False):
        return [i for i in self.isolates if not i.done(test) and (i.done("maldi") or not identified_only)]

    def mark(self, iso, test):
        if test == "ast" and not iso.done("maldi") and getattr(p, "isolate_strict", True):
            raise DuplicateIsolateTest(f"{self.spec_type}/{self.spec_id} isolate {iso.idx}: AST requested without MALDI ID")
        if iso.done(test):
            self.violations += 1
            if getattr(p, "isolate_strict", True):
                raise DuplicateIsolateTest(f"{self.spec_type}/{self.spec_id} isolate {iso.idx}: '{test}' already done")
        iso.counts[test] = iso.counts.get(test, 0) + 1

    def select(self, test, prob, among=None, limit=None):
        """Independent draw per candidate isolate; chosen isolates are marked (claimed) and returned."""
        cand = list(among) if among is not None else self.pending(test)
        cand = [i for i in cand if not i.done(test)]
        if limit is not None:
            cand = cand[:int(limit)]
        chosen = [i for i in cand if self.rng.random() < prob]
        for i in chosen:
            self.mark(i, test)
        return chosen


def get_isolates(env, spec_id, spec_type, sampler):
    """Get-or-create. sampler(random.Random) -> number of organisms; called once per specimen."""
    reg = env.__dict__.setdefault("isolate_sets", {})
    key = (spec_type, spec_id)
    s = reg.get(key)
    if s is None:
        draw = random.Random(f"{env.run_seed}:{spec_type}:{spec_id}:isolates:count")
        s = reg[key] = IsolateSet(env, spec_id, spec_type, sampler(draw))
    return s


def rate_for(isolates, spec_cfg, base, key):
    """Polymicrobial override: multi_isolate_maldi_rate / multi_isolate_ast_rate (None = same rate as a single isolate)."""
    if isolates.n > 1:
        v = spec_cfg.get(key, getattr(p, key, None))
        if v is not None:
            return float(v)
    return base


TESTS = ("gram", "maldi", "ast", "oxidase", "tsi", "indole", "catalase", "pbp", "latex", "biochem_panel")


def isolate_ledger_df(env):
    import pandas as pd
    rows = []
    for (stype, sid), s in getattr(env, "isolate_sets", {}).items():
        for i in s.isolates:
            rows.append({"Specimen_ID": sid, "Type": stype, "Isolate": i.idx, "N_Isolates": s.n,
                         **{t: i.counts.get(t, 0) for t in TESTS}})
    return pd.DataFrame(rows)


def audit_ledger(env):
    sets = list(getattr(env, "isolate_sets", {}).values())
    iso = [i for s in sets for i in s.isolates]
    n_iso = len(iso)
    out = {"isolate_n_specimens": len(sets), "isolate_n_isolates": n_iso,
           "isolate_mean_per_specimen": (n_iso / len(sets)) if sets else 0.0,
           "isolate_duplicate_tests": sum(s.violations for s in sets),
           "isolate_ast_without_maldi": sum(1 for i in iso if i.counts.get("ast", 0) and not i.counts.get("maldi", 0))}
    for t in ("gram", "maldi", "ast"):
        out[f"isolate_{t}_max_per_isolate"] = max((i.counts.get(t, 0) for i in iso), default=0)
        out[f"isolate_{t}_total"] = sum(i.counts.get(t, 0) for i in iso)
    return out


def export_ledger(env, path):
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    isolate_ledger_df(env).to_csv(path, index=False)
