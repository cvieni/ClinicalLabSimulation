# modules/sim_classes.py
import simpy

# Centralized parameters file which has the adjustable variables
import params_config.params_d3 as p

# -------------------------------
# ----- Buffer Incoming Requests -----------
# -------------------------------
class BatchAccumulator:
    """Buffers incoming requests until a batch size or timeout condition is met."""
    def __init__(self, env, batch_size=p.batch_size, max_wait=p.max_wait):
        self.env = env
        self.batch_size = batch_size
        self.max_wait = max_wait
        self.queue = []
        self.timer_proc = None

    def wait_for_batch(self):
        """Processes call this to pause until released in a batch."""
        event = self.env.event()
        self.queue.append(event)

        if len(self.queue) >= self.batch_size:
            self._flush_batch()
        elif self.timer_proc is None or not self.timer_proc.is_alive:
            self.timer_proc = self.env.process(self._batch_timer())

        return event

    def _batch_timer(self):
        try:
            yield self.env.timeout(self.max_wait)
            self._flush_batch()
        except simpy.Interrupt:
            pass # Batch filled before timeout
        
    def _flush_batch(self):
        # if self.timer_proc and self.timer_proc.is_alive:
        #     self.timer_proc.defused = True
        if self.timer_proc and self.timer_proc.is_alive:
            try:
                self.timer_proc.interrupt()
            except RuntimeError:
                pass # Already finished
            
        to_release = self.queue[:self.batch_size]
        self.queue = self.queue[self.batch_size:]
        
        for event in to_release:
            if not event.triggered:
                event.succeed()


# ==================================================================================
# EVENT & TIMEOUT MONITORING HELPER
# ==================================================================================
class MonitoredRequest:
    """Wraps a SimPy resource request and logs warnings if waiting exceeds threshold."""
    def __init__(self, env, resource, resource_name, spec_id, timeout_warn=60):
        self.env = env
        self.resource = resource
        self.resource_name = resource_name
        self.spec_id = spec_id
        self.timeout_warn = timeout_warn
        self.req = None

    def __enter__(self):
        self.req = self.resource.request()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.req:
            self.resource.release(self.req)

    def wait(self):
        start_time = self.env.now
        # Wait for either resource acquisition OR warning timeout
        yield self.req
        wait_duration = self.env.now - start_time
        if wait_duration >= self.timeout_warn:
            print(f"⚠️ [DELAY WARNING] t={self.env.now:.1f}m | {self.spec_id} waited {wait_duration:.1f}m for {self.resource_name}!")
