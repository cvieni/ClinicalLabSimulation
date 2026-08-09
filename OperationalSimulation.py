
import simpy
import random
import statistics

# ---------------------------
# Configuration
# ---------------------------

RANDOM_SEED = 42
# SIM_TIME = 24 * 60  # minutes (24 hours)
SIM_TIME = 24 # minutes (24 hours)

# Arrival rate
MEAN_INTERARRIVAL = 3  # minutes

# Test mix
CHEMISTRY_PROB = 0.60
HEMATOLOGY_PROB = 0.40

# Process times (minutes)
ACCESSIONING_TIME = (1, 3)
CHEMISTRY_TEST_TIME = (15, 25)
HEMATOLOGY_TEST_TIME = (8, 15)

# Resources
NUM_ACCESSIONERS = 2
NUM_CHEM_ANALYZERS = 2
NUM_HEM_ANALYZERS = 1
NUM_TECHNOLOGISTS = 3


# ---------------------------
# Clinical Lab Model
# ---------------------------

class ClinicalLab:
    def __init__(self, env):
        self.env = env

        self.accessioners = simpy.Resource(env, capacity=NUM_ACCESSIONERS)
        self.chem_analyzers = simpy.Resource(env, capacity=NUM_CHEM_ANALYZERS)
        self.hem_analyzers = simpy.Resource(env, capacity=NUM_HEM_ANALYZERS)
        self.technologists = simpy.Resource(env, capacity=NUM_TECHNOLOGISTS)

        self.turnaround_times = []
        self.chem_tats = []
        self.hem_tats = []

        self.specimens_processed = 0

    def accession_specimen(self):
        process_time = random.uniform(*ACCESSIONING_TIME)
        yield self.env.timeout(process_time)

    def run_chemistry(self):
        process_time = random.uniform(*CHEMISTRY_TEST_TIME)
        yield self.env.timeout(process_time)

    def run_hematology(self):
        process_time = random.uniform(*HEMATOLOGY_TEST_TIME)
        yield self.env.timeout(process_time)


# ---------------------------
# Specimen Workflow
# ---------------------------

def specimen(env, specimen_id, lab):
    arrival_time = env.now

    test_type = (
        "Chemistry"
        if random.random() < CHEMISTRY_PROB
        else "Hematology"
    )

    # Accessioning
    with lab.accessioners.request() as req:
        yield req
        yield env.process(lab.accession_specimen())

    # Analytical phase
    with lab.technologists.request() as tech_req:
        yield tech_req

        if test_type == "Chemistry":
            with lab.chem_analyzers.request() as analyzer_req:
                yield analyzer_req
                yield env.process(lab.run_chemistry())

        else:
            with lab.hem_analyzers.request() as analyzer_req:
                yield analyzer_req
                yield env.process(lab.run_hematology())

    tat = env.now - arrival_time

    lab.turnaround_times.append(tat)

    if test_type == "Chemistry":
        lab.chem_tats.append(tat)
    else:
        lab.hem_tats.append(tat)

    lab.specimens_processed += 1


# ---------------------------
# Arrival Generator
# ---------------------------

def specimen_generator(env, lab):
    specimen_id = 0

    while True:
        interarrival = random.expovariate(1.0 / MEAN_INTERARRIVAL)

        yield env.timeout(interarrival)

        specimen_id += 1

        env.process(specimen(env, specimen_id, lab))


# ---------------------------
# Reporting
# ---------------------------

def print_results(lab):
    print("\n=== Clinical Laboratory Results ===")

    print(f"Specimens processed: {lab.specimens_processed}")

    if lab.turnaround_times:
        print(
            f"Average TAT: "
            f"{statistics.mean(lab.turnaround_times):.2f} min"
        )
        print(
            f"Median TAT: "
            f"{statistics.median(lab.turnaround_times):.2f} min"
        )
        print(
            f"95th Percentile TAT: "
            f"{sorted(lab.turnaround_times)[int(0.95 * len(lab.turnaround_times))]:.2f} min"
        )

    if lab.chem_tats:
        print(
            f"Chemistry Average TAT: "
            f"{statistics.mean(lab.chem_tats):.2f} min"
        )

    if lab.hem_tats:
        print(
            f"Hematology Average TAT: "
            f"{statistics.mean(lab.hem_tats):.2f} min"
        )


# ---------------------------
# Main
# ---------------------------

def main():
    random.seed(RANDOM_SEED)

    env = simpy.Environment()

    lab = ClinicalLab(env)

    env.process(specimen_generator(env, lab))

    env.run(until=SIM_TIME)

    print_results(lab)


if __name__ == "__main__":
    main()
