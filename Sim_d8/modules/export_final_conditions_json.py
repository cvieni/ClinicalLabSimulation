import json
import pandas as pd
from pathlib import Path

def export_initial_conditions_from_run(
    df_pivot: pd.DataFrame, total_sim_minutes: float, output_path: Path
):
    """Extracts active specimens at t=total_sim_minutes and outputs initial conditions JSON."""
    seed_plating_queue = []
    seed_incubating_specimens = []

    if df_pivot is not None and not df_pivot.empty:
        df = df_pivot.copy()

        # 1. Resolve ID Column or Fallback to Index
        id_col = next(
            (
                c
                for c in df.columns
                if "id" in c.lower() or "specimen" in c.lower()
            ),
            None,
        )

        # 2. Resolve Specimen Type Column
        type_col = next(
            (
                c
                for c in df.columns
                if c.lower() in ["type", "specimen_type", "specimentype", "category"]
            ),
            None,
        )

        # 3. Resolve Timestamps
        arr_col = next(
            (
                c
                for c in df.columns
                if "arrival" in c.lower() or "accession" in c.lower()
            ),
            df.columns[0],
        )
        plat_start_col = next(
            (
                c
                for c in df.columns
                if "plating_start" in c.lower() or "plated" in c.lower()
            ),
            None,
        )

        # Ensure numeric conversion
        for col in [arr_col, plat_start_col]:
            if col and col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Detect Hour vs. Minute Scale
        max_ts = df.select_dtypes(include=["number"]).max().max()
        time_scale = (
            60.0 if max_ts and max_ts <= (total_sim_minutes / 60.0) * 1.5 else 1.0
        )
        sim_end_time = total_sim_minutes / time_scale

        # Filter active plating items
        if plat_start_col:
            active_plating = df[
                (df[arr_col] <= sim_end_time)
                & (
                    df[plat_start_col].isna()
                    | (df[plat_start_col] > sim_end_time)
                )
            ]
        else:
            active_plating = df[df[arr_col] <= sim_end_time]

        for idx, row in active_plating.iterrows():
            # Extract distinct ID or synthesize unique ID
            raw_id = row.get(id_col) if id_col else None
            spec_id = (
                str(raw_id)
                if pd.notna(raw_id) and str(raw_id).upper() != "UNKNOWN"
                else f"SEED_SPEC_{idx:04d}"
            )

            # Extract distinct Specimen Type
            raw_type = row.get(type_col) if type_col else "General"
            spec_type = (
                str(raw_type) if pd.notna(raw_type) else "General"
            )

            seed_plating_queue.append(
                {
                    "spec_id": spec_id,
                    "spec_type": spec_type,
                    "priority": int(row.get("priority", row.get("Priority", 1))),
                    "arrival_time": round(float(row[arr_col]) * time_scale, 2),
                }
            )

    output_data = {
        "seed_plating_queue": seed_plating_queue,
        "seed_incubating_specimens": seed_incubating_specimens,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)

    print(
        f"Exported initial conditions ({len(seed_plating_queue)} queued, {len(seed_incubating_specimens)} incubating) -> {output_path}"
    )