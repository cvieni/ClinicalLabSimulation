# modules/helpers.py
import simpy
import params_config.params_d3 as p
from params_config import event_name as EV

# ==========================================
# Helper to pick the right tech resource based on specimen type
# ==========================================
# Based on the Specific specimen route to a specific tech
def get_tech_bench(spec_type, resources):
    spec_upper = spec_type.upper()
    if spec_upper.startswith("BCX") or spec_upper.startswith("BODYFLUID"):
        return resources["tech_blood"]
    elif spec_type in ["Urine"]:
        return resources["tech_urine"]
    elif spec_type in ["Stool"]:
        return resources["tech_stool"]
    elif any(spec_upper.startswith(prefix) for prefix in ["TISSUE", "BONE_CX", "WOUND"]):
        return resources["tech_routine"]
    else:
        # return resources["tech_new"]
        # Fallback to tech_new or load-balanced general techs
        return get_least_busy_tech(resources, "tech_routine", "tech_new")


def get_least_busy_tech(resources, primary_key="tech_routine", fallback_key="tech_new"):
    """Load-balances tech requests across available benches based on queue/capacity."""
    r_tech = resources.get(primary_key, resources[fallback_key])
    g_tech = resources[fallback_key]
    r_ratio = len(r_tech.queue) / max(1, r_tech.capacity)
    g_ratio = len(g_tech.queue) / max(1, g_tech.capacity)
    return r_tech if r_ratio <= g_ratio else g_tech

def get_least_busy_tech_accession(resources, primary_key="tech_plating", fallback_key="tech_accession"):
    r_tech = resources[primary_key]
    g_tech = resources[fallback_key]
    r_ratio = len(r_tech.queue) / max(1, r_tech.capacity)
    g_ratio = len(g_tech.queue) / max(1, g_tech.capacity)
    return r_tech if r_ratio <= g_ratio else g_tech


def req_resource(resource, priority=None):
    """Safely request a standard or PriorityResource."""
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
