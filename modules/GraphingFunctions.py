import graphviz
import matplotlib.pyplot as plt
from pathlib import Path
import numpy as np
import pandas as pd
from Media_dictionary import MEDIA_TYPES

def _ensure_dir(output_dir: str) -> Path:
  """Helper function to create the directory if it doesn't exist."""
  folder_path = Path(output_dir)
  folder_path.mkdir(parents=True, exist_ok=True)
  return folder_path

def plot_workflow(filename="microbiology_lab_workflow", output_dir="plots"):
    """Generates a Graphviz flow diagram showing the lab workflow from arrival to media tracking."""

    out_folder = _ensure_dir(output_dir)
    file_path = out_folder / filename

    dot = graphviz.Digraph(comment="Microbiology Lab Workflow", format="png")
    dot.attr(rankdir="LR", size="12,6", dpi="300")

    # Nodes
    dot.node("A", "Specimen Arrival\n(BCx, UCx, TissCx)", shape="ellipse", style="filled", fillcolor="#E1F5FE")
    dot.node("B", "Triage & Primary Setup", shape="box")
    dot.node("C1", "Blood Culture (BCx)\n[Bottles Incubated]", shape="box")
    dot.node("C2", "Urine Culture (UCx)\n[Primary Plating]", shape="box")
    dot.node("C3", "Tissue/Wound (TissCx)\n[Primary Plating]", shape="box")

    dot.node("D1", "Positivity Check\n(~10% Alert)", shape="diamond")
    dot.node("D2", "Subculture Check\n(~15% Growth)", shape="diamond")
    dot.node("D3", "Subculture Check\n(~50% Growth)", shape="diamond")

    dot.node("E", "Media Consumption\n(BAP, MacConkey, CNA, Choc, Anaerobic)", shape="box", style="filled", fillcolor="#FFF3E0")
    dot.node("F", "Expiration & Inventory Check", shape="box", style="filled", fillcolor="#FFEBEE")
    dot.node("G", "Reorder Evaluation\n(Lead Time = 3 Days)", shape="box", style="filled", fillcolor="#E8F5E9")

    # Edges
    dot.edge("A", "B")
    dot.edge("B", "C1")
    dot.edge("B", "C2")
    dot.edge("B", "C3")

    dot.edge("C1", "D1")
    dot.edge("C2", "D2")
    dot.edge("C3", "D3")

    dot.edge("D1", "E", label="Positives")
    dot.edge("D2", "E", label="Primary + Sub")
    dot.edge("D3", "E", label="Primary + Sub")

    dot.edge("E", "F")
    dot.edge("F", "G")

    try:
        dot.render(str(file_path), cleanup=True)
        print(f"Workflow diagram saved to '{file_path}.png'")
    except graphviz.backend.ExecutableNotFound:
        dot.save(str(file_path.with_suffix(".dot")))
        print(
            f"Warning: Graphviz executable not found. Saved raw graph source to"
            f" '{file_path.with_suffix('.dot')}'"
        )


def plot_media_and_orders(inv, days=365,
                          filename="media_consumption_and_orders.png", output_dir="plots"):
    """Plots 2 subplots: Media Consumed per Day and Media Expired per Day,

    overlaying vertical red lines for order placement dates.
    """
    out_folder = _ensure_dir(output_dir)
    save_path = out_folder / filename

    days_array = np.arange(days)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # 1. Media Consumed per day
    for media in MEDIA_TYPES:
        daily_use = [inv.daily_used[d][media] for d in days_array]
        ax1.plot(days_array, daily_use, label=media, alpha=0.8)

    ax1.set_ylabel("Plates Consumed / Day")
    ax1.set_title("Daily Media Consumption & Order Reorder Events")
    ax1.grid(True, linestyle=":", alpha=0.6)

    # 2. Media Expired per day
    for media in MEDIA_TYPES:
        daily_exp = [inv.daily_expired[d][media] for d in days_array]
        ax2.plot(days_array, daily_exp, label=media, linestyle="--", alpha=0.8)

    ax2.set_xlabel("Simulation Day")
    ax2.set_ylabel("Plates Expired / Day")
    ax2.set_title("Daily Media Expirations")
    ax2.grid(True, linestyle=":", alpha=0.6)

    # Vertical red lines for order dates
    order_days = sorted(list(set([event[0] for event in inv.order_events])))
    for day in order_days:
        ax1.axvline(x=day, color="red", linestyle="--", alpha=0.2, linewidth=1)
        ax2.axvline(x=day, color="red", linestyle="--", alpha=0.2, linewidth=1)

    # Custom legend entry for the vertical lines
    ax1.plot([], [], color="red", linestyle="--", label="Order Placed")
    ax1.legend(loc="upper right", fontsize=8, ncol=2)
    ax2.legend(loc="upper right", fontsize=8, ncol=2)

    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close(fig)  # Close memory buffer
    print(f"Media plot saved to '{save_path}'")


def plot_culture_volumes(metrics_log,
                        filename="culture_volumes_and_positivity.png",
                        output_dir="plots",):
    """Plots daily volumes and % positives for BCx, UCx, and TissCx."""
    out_folder = _ensure_dir(output_dir)
    save_path = out_folder / filename

    df = pd.DataFrame(metrics_log)
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True)

    # BCx
    axes[0, 0].plot(df["Day"], df["BCx_Vol"], color="#1f77b4")
    axes[0, 0].set_ylabel("BCx Volume")
    axes[0, 0].set_title("Blood Culture (BCx) Daily Volume")
    axes[0, 0].grid(True, linestyle=":", alpha=0.6)

    axes[0, 1].plot(df["Day"], df["BCx_Pos_Pct"], color="#ff7f0e")
    axes[0, 1].set_ylabel("% Positive")
    axes[0, 1].set_title("Blood Culture Positivity Rate (%)")
    axes[0, 1].grid(True, linestyle=":", alpha=0.6)

    # UCx
    axes[1, 0].plot(df["Day"], df["UCx_Vol"], color="#2ca02c")
    axes[1, 0].set_ylabel("UCx Volume")
    axes[1, 0].set_title("Urine Culture (UCx) Daily Volume")
    axes[1, 0].grid(True, linestyle=":", alpha=0.6)

    axes[1, 1].plot(df["Day"], df["UCx_Pos_Pct"], color="#d62728")
    axes[1, 1].set_ylabel("% Positive")
    axes[1, 1].set_title("Urine Culture Positivity Rate (%)")
    axes[1, 1].grid(True, linestyle=":", alpha=0.6)

    # TissCx
    axes[2, 0].plot(df["Day"], df["TissCx_Vol"], color="#9467bd")
    axes[2, 0].set_ylabel("Tissue Volume")
    axes[2, 0].set_xlabel("Simulation Day")
    axes[2, 0].set_title("Tissue/Wound Culture Daily Volume")
    axes[2, 0].grid(True, linestyle=":", alpha=0.6)

    axes[2, 1].plot(df["Day"], df["TissCx_Pos_Pct"], color="#8c564b")
    axes[2, 1].set_ylabel("% Positive")
    axes[2, 1].set_xlabel("Simulation Day")
    axes[2, 1].set_title("Tissue/Wound Culture Positivity Rate (%)")
    axes[2, 1].grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close(fig)  # Close memory buffer
    print(f"Culture volumes plot saved to '{save_path}'")