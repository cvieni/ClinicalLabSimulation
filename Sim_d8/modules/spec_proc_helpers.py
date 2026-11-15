# modules/helpers.py
import simpy
import params_config.params_d3 as p
from params_config import event_name as EV


# ==========================================
# Shared tech pools (tech_new / tech_float_newroutine / tech_routine, tech_plating / tech_float_accession / ...)
# ==========================================
class PoolRequest(simpy.Event):
    """One request that races several resources and is served by whichever has a free tech first.

    Members are tried in PREFERENCE ORDER: if more than one is free at the moment of the request the first listed wins;
    if none is free the request waits in every member's queue and the first slot to open serves it (the other queued
    copies are cancelled).  Works exactly like a normal request: `with pool.request(priority=p) as req: yield req`.
    """

    def __init__(self, members, priority=None):
        super().__init__(members[0]._env if hasattr(members[0], "_env") else members[0].env)
        self.granted = None
        self._pairs = []
        for idx, r in enumerate(members):
            if isinstance(r, simpy.PriorityResource) and priority is not None:
                q = r.request(priority=priority)
            else:
                q = r.request()
            q._pool_dup = idx > 0          # only the preferred member's copy is counted in queue-length statistics
            self._pairs.append((r, q))
        for r, q in self._pairs:                       # already-free member, in preference order
            if q.triggered:
                self._choose(r, q)
                break
        else:
            for r, q in self._pairs:
                q.callbacks.append(lambda ev, r=r, q=q: self._on_grant(r, q))

    def _choose(self, r, q):
        self.granted = (r, q)
        for r2, q2 in self._pairs:
            if q2 is q:
                continue
            if q2.triggered:
                r2.release(q2)
            else:
                q2.cancel()
        self.succeed()

    def _on_grant(self, r, q):
        if self.granted is None and not self.triggered:
            self._choose(r, q)

    def release(self):
        if self.granted is not None:
            r, q = self.granted
            self.granted = None
            r.release(q)
        elif not self.triggered:
            for r2, q2 in self._pairs:
                q2.cancel()
            self._pairs = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class TechPool:
    """Looks like a resource to callers (request / queue / capacity / count) but is served by several resources."""

    def __init__(self, members):
        self.members = list(members)

    def request(self, priority=None):
        return PoolRequest(self.members, priority)

    @property
    def queue(self):
        return [q for r in self.members for q in r.queue]

    @property
    def capacity(self):
        return sum(r.capacity for r in self.members)

    @property
    def count(self):
        return sum(r.count for r in self.members)


def make_pool(resources, keys):
    """TechPool over the listed resource keys that exist (returns the plain resource when only one exists)."""
    members = [resources[k] for k in keys if k in resources]
    return members[0] if len(members) == 1 else TechPool(members)


# ==========================================
# Helper to pick the right tech resource based on specimen type
# ==========================================
# Based on the Specific specimen route to a specific tech
def get_tech_bench(spec_type, resources):
    """Bench that does the FIRST plate read (day-2 tech review) for this specimen type.

    Real workflow: blood/body-fluid bottles -> tech_blood; urine -> tech_urine; EVERYTHING else is read first by
    tech_new on day 1. Only specimens that are subbed / go on to a second day get the comprehensive workup, and
    that (subculture, biochem, repeat reads) is requested on tech_routine in specimen_process_d5, not here.
    p.stool_review_bench (default "tech_new"): set to "tech_stool" if stool has its own first reader.
    If the chosen bench has no staff on the current shift the request goes to the least busy of routine/new
    instead of waiting for the next shift.
    """
    spec_upper = spec_type.upper()
    if spec_upper.startswith("BCX") or spec_upper.startswith("BODYFLUID"):
        return resources["tech_blood"]
    if spec_upper.startswith("URINE"):
        key = "tech_urine"
    elif spec_upper.startswith("STOOL"):
        key = getattr(p, "stool_review_bench", "tech_new")
    else:
        key = "tech_new"
    if key == "tech_new":
        # new-plate reads: tech_new first, then the float tech between new and routine, then tech_routine
        return make_pool(resources, ["tech_new", "tech_float_newroutine", "tech_routine"])
    if resources[key].capacity > 0:
        return resources[key]
    return get_least_busy_tech(resources, "tech_routine", "tech_new")


def get_least_busy_tech(resources, primary_key="tech_routine", fallback_key="tech_new"):
    """Tech for routine-side work (workup, MALDI spotting, AST prep): primary bench, then the float tech that
    covers new/routine, then the fallback bench -- whichever has a free tech first (see PoolRequest)."""
    keys = [primary_key]
    if {primary_key, fallback_key} == {"tech_routine", "tech_new"}:
        keys.append("tech_float_newroutine")
    keys.append(fallback_key)
    return make_pool(resources, [k for k in keys if k in resources] or [fallback_key])


def get_least_busy_tech_accession(resources, primary_key="tech_plating", fallback_key="tech_accession"):
    """Plating tech: tech_plating, then the float tech that helps accession/plating, then tech_accession."""
    return make_pool(resources, [primary_key, "tech_float_accession", fallback_key])


def req_resource(resource, priority=None):
    """Safely request a standard or PriorityResource."""
    if isinstance(resource, TechPool):
        return resource.request(priority)
    if isinstance(resource, simpy.PriorityResource) and priority is not None:
        return resource.request(priority=priority)
    return resource.request()


# ==========================================
# 1. Check and Consume Inventory Helper Function
# ==========================================
def consume_media_inventory(env, inventory, tracker, spec_id, spec_type, media_req):
    """Take media for one specimen. If stock is short, wait (re-checking every p.inventory_stockout_recheck minutes)
    for up to p.inventory_stockout_max_wait_minutes, then give up and abort the specimen.

    The old version gave up after 5 re-checks, i.e. 5 x inventory_stockout_recheck minutes (40 h with the 480-minute
    setting), which was shorter than a 2-3 day resupply, so every stockout turned into dropped specimens. The poll
    interval and the longest tolerable wait are now separate settings."""
    stockout_start = None
    recheck = float(getattr(p, "inventory_stockout_recheck", 60.0))
    max_wait = float(getattr(p, "inventory_stockout_max_wait_minutes", 7 * 1440.0))

    while True:
        can_fulfill = all(inventory.total_inventory(media) >= qty for media, qty in media_req.items())

        if can_fulfill:
            for media, qty in media_req.items():
                inventory.try_consume_media(media, qty)
                if hasattr(tracker, 'log_media_usage'):
                    tracker.log_media_usage(media, qty)
                else:
                    tracker.media_usage[media] = tracker.media_usage.get(media, 0) + qty

            if stockout_start is not None:
                tracker.log_stockout_delay(spec_id, env.now - stockout_start)
            return True

        if stockout_start is None:
            stockout_start = env.now
            tracker.log_event(spec_id, spec_type, EV.STOCKOUT_DELAY_START, env.now)
        if env.now - stockout_start >= max_wait:
            break
        yield env.timeout(recheck)

    tracker.log_event(spec_id, spec_type, EV.MEDIA_ALLOCATION_FAILED, env.now)
    return False
