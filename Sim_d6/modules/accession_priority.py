"""STAT / priority handling for the accession stage.

Why this module exists
----------------------
Your accession_d2.py already computed `IS_HIGH_PRIORITY_STAT = priority <= 4`, but the specimens were
put into a plain FIFO `simpy.Store`, so a STAT specimen waited behind every routine specimen that
arrived before it. The 'aging' line (`max(5.0, base - wait/15)`) ran BEFORE the wait, so it was always 0 min
of aging, and the result was never used either. Priority only had an effect at the downstream PriorityResources.

What this does
--------------
* classify_priority(spec_cfg)      -> (rank, is_stat). rank comes from get_specimen_priority (SPEC_PRIORITY_MAP),
                                      STAT = rank <= p.stat_priority_cutoff (default 4, your existing rule).
* PriorityAccessionStore           -> drop-in for simpy.Store. Tier 0 = STAT (ordered by rank, then arrival),
                                      tier 1 = routine, ordered by  rank + enqueue_time / aging_minutes_per_rank
                                      so a routine specimen gains 1 rank per `aging_minutes_per_rank` of waiting
                                      relative to later arrivals (no starvation, but STAT always goes first).
                                      `store.items` is still a list (len(store.items) works), sorted best-first.
* sample_pre_accession_hold(...)   -> the JSON-histogram delay, with an explicit mode (see below).

Aging detail: routine order is (rank + t_enqueue/aging), a static key, so no re-sorting is ever needed.
It is equivalent to 'effective rank = rank - wait/aging' except that the 'floor at cutoff+1' tie-break
between long-waiting items is by that key instead of pure FIFO. STAT is never overtaken by routine.
"""
from __future__ import annotations

import bisect
import itertools
import random

import simpy

import params_config.params_d3 as p
import params_config.specimen_config_d2 as scfg

from modules.specimen_priority import get_specimen_priority

def _setting(names, default, spec_cfg=None):
    """First hit wins: the specimen's own config dict -> params_config/specimen_config_d2.py (module-level
    constant) -> params_d3.py -> default. `names` lists accepted spellings, e.g. ("accession_aging_minutes",
    "accession_aging_minutes_per_rank")."""
    for src in (spec_cfg, scfg, p):
        if src is None:
            continue
        for n in names:
            v = src.get(n) if isinstance(src, dict) else getattr(src, n, None)
            if v is not None:
                return v
    return default
 
 
_CUTOFF_NAMES = ("stat_priority_cutoff",)
_AGING_NAMES = ("accession_aging_minutes", "accession_aging_minutes_per_rank")


# ----------------------------------------------------------------------------------------------
# classification
# ----------------------------------------------------------------------------------------------
def stat_cutoff(spec_cfg=None) -> float:
    return float(_setting(_CUTOFF_NAMES, 4, spec_cfg))
 
 
def classify_priority(spec_cfg) -> tuple[float, bool]:
    """(rank, is_stat). Lower rank = more urgent (SPEC_PRIORITY_MAP: 1 whole blood/BM, 2 stat, 3 csf,
    4 positive blood culture, 5 surgical/fna ... 16 studies)."""
    rank = float(get_specimen_priority(spec_cfg))
    return rank, rank <= stat_cutoff(spec_cfg)
 
 
# ----------------------------------------------------------------------------------------------
# priority store
# ----------------------------------------------------------------------------------------------
class PriorityAccessionStore(simpy.Store):
    """simpy.Store whose get() returns the most urgent item. Items are dicts with at least
    'priority' (rank) and 'is_stat'. Capacity/blocking semantics are those of simpy.Store."""
 
    def __init__(self, env, capacity=float("inf"), aging_minutes_per_rank: float | None = None):
        super().__init__(env, capacity)
        self._keys: list = []
        self._seq = itertools.count()
        self.aging = float(aging_minutes_per_rank if aging_minutes_per_rank is not None
                           else _setting(_AGING_NAMES, 15.0))
 
    def _sort_key(self, item):
        seq = next(self._seq)
        rank = float(item.get("priority", 99.0))
        if item.get("is_stat"):
            return (0, rank, seq)
        return (1, rank + self._env_now() / self.aging, seq)
 
    def _env_now(self) -> float:
        return float(self._env.now)
 
    def _do_put(self, event):
        if len(self.items) < self._capacity:
            key = self._sort_key(event.item)
            i = bisect.bisect_right(self._keys, key)
            self._keys.insert(i, key)
            self.items.insert(i, event.item)
            event.succeed()
 
    def _do_get(self, event):
        if self.items:
            self._keys.pop(0)
            event.succeed(self.items.pop(0))
 
    # ---- diagnostics ---------------------------------------------------------------------
    def counts(self) -> dict:
        n_stat = sum(1 for it in self.items if it.get("is_stat"))
        return {"stat": n_stat, "routine": len(self.items) - n_stat}
 
 
# ----------------------------------------------------------------------------------------------
# pre-accession hold (the JSON accession-time histogram)
# ----------------------------------------------------------------------------------------------
def _hist_sample(acc_cfg) -> float:
    probs, edges = acc_cfg["bin_probabilities"], acc_cfg["bin_edges"]
    i = random.choices(range(len(probs)), weights=probs, k=1)[0]
    return random.uniform(edges[i], edges[i + 1])
 
 
def mean_touch_minutes(spec_cfg) -> float:
    return (float(spec_cfg["accession_touch_time_min"]) + float(spec_cfg["accession_touch_time_max"])) / 2.0
 
 
def sample_pre_accession_hold(spec_cfg, is_stat: bool, hold_multiplier: float = 1.0) -> float:
    """Minutes a specimen waits before it joins the accession queue (no tech involved).
 
    p.accession_hold_mode
      "histogram"             hold = a draw from the JSON histogram (your current behaviour).
                              Correct ONLY if the LIS interval behind the histogram ends when a tech is
                              handed the specimen (e.g. collect->lab receipt). Otherwise queue + touch are counted twice.
      "histogram_minus_touch" hold = max(0, draw - mean touch time). Use when the histogram is
                              receipt->accessioned in the LIS (it already contains the touch); the sim adds queue + touch back.
      "none"                  no hold: the whole receipt->accessioned time is produced by queue + touch.
                              Use this to check what the queue ALONE gives vs the histogram (accession_time_check).
    STAT specimens skip the hold when p.stat_skip_hold (default True).
    """
    if is_stat and _setting(("stat_skip_hold",), True, spec_cfg):
        return 0.0
    mode = _setting(("accession_hold_mode",), "histogram", spec_cfg)
    if mode == "none":
        return 0.0
    hold = _hist_sample(spec_cfg["accession_time_config"])
    if mode == "histogram_minus_touch":
        hold = max(0.0, hold - mean_touch_minutes(spec_cfg))
    elif mode != "histogram":
        raise ValueError(f"p.accession_hold_mode must be 'histogram', 'histogram_minus_touch' or 'none', got {mode!r}")
    if isinstance(hold_multiplier, (int, float)) and hold_multiplier > 0:
        hold *= float(hold_multiplier)
    return hold