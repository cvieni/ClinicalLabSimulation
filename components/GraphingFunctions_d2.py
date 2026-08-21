# components/GraphingFunctions_d2.py

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# =====================================================================
# ======== Figure 1  - Workload Queue  ========
# ====================================================================
def Graphing_WorkloadQueues(df_state):
    """1. Workload & Plating Bottlenecks Scatter/Line Plot."""
    if df_state is None or df_state.empty:
        return {}

    df = df_state.copy()
    df["Day"] = df["Minute"] / (24.0 * 60.0) if "Minute" in df.columns else (
        df["minute"] / (24.0 * 60.0) if "minute" in df.columns else df.index / 48.0
    )
    max_days = df["Day"].max()

    # marker_col = "Plating_Queue_Length" if "Plating_Queue_Length" in df.columns else (
    #     "plating_queue" if "plating_queue" in df.columns else df.columns[1]
    # )
    # Priority order for color metric: Total Queue > Accession Queue > Plating Queue
    if "Total_Tech_Queue_Length" in df.columns:
        marker_col = "Total_Tech_Queue_Length"
        marker_label = "Total Backlog Queue"
    elif "Tech_Accession_Queue_Length" in df.columns:
        marker_col = "Tech_Accession_Queue_Length"
        marker_label = "Accession Queue"
    elif "Plating_Queue_Length" in df.columns:
        marker_col = "Plating_Queue_Length"
        marker_label = "Plating Queue"
    else:
        marker_col = df.columns[1]
        marker_label = marker_col

    active_col = "Active_Specimens_In_Lab" if "Active_Specimens_In_Lab" in df.columns else (
        "active_specimens" if "active_specimens" in df.columns else df.columns[0]
    )

    fig = px.scatter(
        df,
        x="Day",
        y=active_col,
        color=marker_col,
        labels={
            "Day": "Simulation Time (Days)", 
            active_col: "Active Specimens",
            marker_col: marker_label
        },
        title="Workload & Plating Bottlenecks Over Time",
    )
    fig.update_traces(mode="lines+markers")
    return add_weekend_shading(fig, max_days)

# =====================================================================
# ======== Figure X  - Sample Queue  ========
# ====================================================================
def Graphing_SampleQueue(df_state):
    fig = go.Figure()

    tech_columns_map = {
        "Tech_Accession_Queue_Length": "Accession Tech",
        "Tech_Plating_Queue_Length": "Plating Tech",
        "Tech_Blood_Queue_Length": "Blood Tech",
        "Tech_Routine_Queue_Length": "Routine Tech",
        "Tech_Urine_Queue_Length": "Urine Tech",
        "Tech_New_Queue_Length": "New Tech",
    }

    df_state = df_state.copy()
    
    # Force X-axis numeric conversion
    if "Day" in df_state.columns:
        x_data = pd.to_numeric(df_state["Day"], errors="coerce")
        x_title = "Simulation Time (Days)"
    else:
        x_data = pd.to_numeric(df_state["Minute"], errors="coerce") / 1440.0
        x_title = "Simulation Time (Days)"

    # Drop rows where X coordinate itself failed to parse
    valid_mask = x_data.notna()
    x_data = x_data[valid_mask]
    df_state = df_state[valid_mask]

    # Plot queue lengths for each technician group
    for col, display_name in tech_columns_map.items():
        if col in df_state.columns:
            y_data = pd.to_numeric(df_state[col], errors="coerce").fillna(0)

            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=y_data,
                    mode="lines",
                    name=display_name,
                    connectgaps=True,
                    line=dict(width=2)
                )
            )

    # Force X-axis range to strictly fit the actual min & max of x_data
    min_x = 0
    max_x = x_data.max() if not x_data.empty else 7

    fig.update_layout(
        title="Technician Queue Bottlenecks Over Time",
        xaxis_title=x_title,
        yaxis_title="Samples Waiting in Queue",
        hovermode="x unified",
        legend=dict(
            title="Tech Role",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        # Explicit range assignment prevents Plotly from zooming into an empty day window
        xaxis=dict(range=[min_x, max_x]),
        yaxis=dict(rangemode="tozero", zeroline=True),
    )

    return fig



def add_weekend_shading(fig, max_days):
    """Adds light grey background shapes for weekend days on timeline plots."""
    if not max_days or max_days <= 0:
        return fig

    current_day = 5
    shapes = []
    while current_day <= max_days + 2:
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=current_day,
                x1=min(current_day + 2, max_days),
                y0=0,
                y1=1,
                fillcolor="rgba(220, 220, 220, 0.3)",
                opacity=0.5,
                layer="below",
                line_width=0,
            )
        )
        current_day += 7

    fig.update_layout(shapes=shapes)
    return fig




def Graphing_TechUtilization(df_state):
    """2. Technician Staffing & Active Utilization Line Chart."""
    if df_state is None or df_state.empty:
        return {}

    df = df_state.copy()
    df["Day"] = df["Minute"] / (24.0 * 60.0) if "Minute" in df.columns else (
        df["minute"] / (24.0 * 60.0) if "minute" in df.columns else df.index / 48.0
    )
    max_days = df["Day"].max()

    tech_cols = [c for c in ["Busy_Techs", "Active_Techs", "busy_techs", "active_techs"] if c in df.columns]
    if not tech_cols:
        return {}

    fig = px.line(
        df,
        x="Day",
        y=tech_cols,
        labels={"Day": "Simulation Time (Days)", "value": "Technicians", "variable": "Metric"},
        title="Technician Staffing & Active Utilization Over Time",
    )
    return add_weekend_shading(fig, max_days)


def Graphing_SampleVolumes(df_pivot):
    """4. Sample Volume Trends Line Chart."""
    if df_pivot is None or df_pivot.empty:
        return {}

    col_arrived = next((c for c in df_pivot.columns if any(k in c.lower() for k in ["arrived", "arrival", "1."])), None)
    col_type = next((c for c in df_pivot.columns if any(k in c.lower() for k in ["type", "specimen_type", "category"])), None)

    if not col_arrived:
        return {}

    df_vol = df_pivot.copy()
    df_vol["Arrival_Day"] = (df_vol[col_arrived] / (24.0 * 60.0)).round(1)

    group_cols = ["Arrival_Day"]
    if col_type:
        group_cols.append(col_type)

    vol_summary = df_vol.groupby(group_cols).size().reset_index(name="Specimen_Count")

    fig = px.line(
        vol_summary,
        x="Arrival_Day",
        y="Specimen_Count",
        color=col_type if col_type else None,
        title="Sample Volume Trends Over Time",
        labels={"Arrival_Day": "Simulation Time (Days)", "Specimen_Count": "Arrival Volume"},
    )

    # Compute and overlay Total Daily Volume
    if col_type:
        total_vol = df_vol.groupby("Arrival_Day").size().reset_index(name="Total_Specimen_Count")
        
        fig.add_trace(
            go.Scatter(
                x=total_vol["Arrival_Day"],
                y=total_vol["Total_Specimen_Count"],
                mode="lines+markers",
                name="Total Volume",
                line=dict(color="black", width=3, dash="dash"),
                marker=dict(size=6, symbol="circle")
            )
        )

    max_days = df_vol["Arrival_Day"].max()
    return add_weekend_shading(fig, max_days)


def Graphing_TAT(completed_df):
    """5. Turnaround Time Boxplot."""
    if completed_df is None or completed_df.empty or "Total_TAT_Hours" not in completed_df.columns:
        return {}

    type_col = "Type" if "Type" in completed_df.columns else completed_df.columns[0]
    return px.box(
        completed_df,
        x=type_col,
        y="Total_TAT_Hours",
        color=type_col,
        points="all",
        title="Turnaround Time (TAT) Distribution",
    )


def Graphing_WaitTime(completed_df):
    """6. Plating Queue Waiting Time Histogram."""
    if completed_df is None or completed_df.empty or "Wait_For_Plating_Mins" not in completed_df.columns:
        return {}

    type_col = "Type" if "Type" in completed_df.columns else None
    return px.histogram(
        completed_df,
        x="Wait_For_Plating_Mins",
        color=type_col,
        nbins=30,
        title="Plating Queue Waiting Time Distribution",
    )


def Graphing_MediaUsage(media_usage):
    """7. Consumables Usage Bar Chart."""
    if not media_usage:
        return {}

    df_media = pd.DataFrame(list(media_usage.items()), columns=["Media Type", "Plates Consumed"])
    return px.bar(
        df_media,
        x="Media Type",
        y="Plates Consumed",
        color="Media Type",
        title="Consumables Usage Summary",
    )


def Graphing_review_milestones_scatter(sim_data):
    """8. Review Milestones Lifecycle Scatter Plot."""
    if not sim_data or "df_pivot" not in sim_data:
        return px.scatter(title="No simulation data available.")
        
    df = pd.DataFrame(sim_data["df_pivot"])
    records = []
    
    for _, row in df.iterrows():
        spec_id = row.get("Specimen_ID", "Unknown")
        spec_type = row.get("Type", "General")
        
        for col in df.columns:
            if col in ["Specimen_ID", "Type", "Total_TAT_Hours", "Wait_For_Plating_Mins"]:
                continue
                
            val = row[col]
            if pd.isnull(val):
                continue
                
            score = None
            stage_group = None
            
            if col == "1. Arrived":
                score = 0
                stage_group = "0 (Arrival)"
            elif col in ["3A. Plate Culture from BCx or Body Fluid Bottle", "3B-1. Plating from PrimarySpecimen Started"]:
                score = 1
                stage_group = "1 (Primary Plating)"
            elif col in ["4. Tech Review Started (Plate - Day 2)"] or "Sub Pure Colony #1" in col:
                score = 2
                stage_group = "2 (Day 2 Review / Sub #1)"
            elif "5a. Sub Pure Colony" in col or "Sub Pure Colony #2" in col:
                score = 3
                stage_group = "3 (Subculture #2)"
            elif col in ["Sub Pure Colony #3"]:
                score = 4
                stage_group = "Subculture #3"
            elif col == "10. Completed":
                score = 5
                stage_group = "5 (Finalized)"

            if score is not None:
                records.append({
                    "Specimen_ID": spec_id,
                    "Type": spec_type,
                    "Time_Minutes": val,
                    "Review_Score": score,
                    "Milestone": col,
                    "Stage_Group": stage_group
                })
                
    df_long = pd.DataFrame(records)
    
    if df_long.empty:
        return px.scatter(title="Milestone timestamps not found in current run data.")

    fig = px.scatter(
        df_long,
        x="Time_Minutes",
        y="Review_Score",
        color="Type",
        hover_data=["Specimen_ID", "Milestone"],
        title="Specimen Lifecycle: Arrival, Reviews, Subcultures & Finalization",
        labels={"Time_Minutes": "Simulation Time (Minutes)", "Review_Score": "Lifecycle Stage"},
        opacity=0.75
    )

    fig.update_layout(
        yaxis=dict(
            tickmode="array",
            tickvals=[0, 1, 2, 3, 4, 5],
            ticktext=[
                "0 (Arrival)", 
                "1 (Primary Plating)", 
                "2 (Day 2 Review / Sub #1)", 
                "3 (Subculture #2)", 
                "4 (ID/AST Prep)", 
                "5 (Completed)"
            ],
            range=[-0.5, 5.5]
        ),
        template="plotly_white"
    )

    return fig