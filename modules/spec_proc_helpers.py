# modules/helpers.py
import simpy
import params_config.params_d2 as p

# ==========================================
# Helper to pick the right tech resource based on specimen type
# ==========================================
# Based on the Specific specimen route to a specific tech
def get_tech_bench(spec_type, resources):
    if spec_type in ["BCx", "BodyFluid"]:
        return resources["tech_blood"]
    elif spec_type in ["Urine"]:
        return resources["tech_urine"]
    elif spec_type in ["Tissue", "Tissue_FNA", "Tissue_genital", "Bone_Cx"]:
        return resources["tech_routine"]
    else:
        return resources["tech_new"]


def get_least_busy_tech(resources, primary_key="tech_routine", fallback_key="tech_new"):
    """Load-balances tech requests across available benches based on queue/capacity."""
    r_tech = resources.get(primary_key, resources[fallback_key])
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
    # Initialize variables
    # media_allocated = False
    stockout_start = None
    attempts = 0
    max_attempts = 5

    while attempts < max_attempts:
        can_fulfill = all(
            inventory.total_inventory(media) >= qty 
            for media, qty in media_req.items()
        )
        
        if can_fulfill:
            for media, qty in media_req.items():
                inventory.try_consume_media(media, qty)
                # Safely log media usage to tracker
                if hasattr(tracker, 'log_media_usage'):
                    tracker.log_media_usage(media, qty)
                else:
                    tracker.media_usage[media] = tracker.media_usage.get(media, 0) + qty

            if stockout_start is not None:
                delay_duration = env.now - stockout_start
                tracker.log_stockout_delay(spec_id, delay_duration)

            return True  # Successfully allocated
        else:
            attempts += 1
            if stockout_start is None:
                stockout_start = env.now
                tracker.log_event(spec_id, spec_type, "Stockout Delay Started", env.now)

            # Re-check inventory every N minutes during a stockout
            recheck_interval = p.inventory_stockout_recheck
            yield env.timeout(recheck_interval)

    # Max attempts reached; log failure and return False without forcing consumption
    tracker.log_event(spec_id, spec_type, "Media Allocation Failed - Aborted", env.now)
    return False