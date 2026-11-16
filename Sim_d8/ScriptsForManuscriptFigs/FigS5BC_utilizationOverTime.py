
# =============================================================================
# FIGURE: MEDIA CONSUMPTION OVER THE COURSE OF THE SIMULATION
# =============================================================================

def fig_media_consumption(
    inv,
    days=None,
    filename="Fig_media_consumption",
):
    """
    Plot daily media consumption over the simulation.

    Panel A: Plates consumed per day, by media type.
    Panel B: Cumulative plates consumed, by media type.
    Panel C: Plates expired per day, by media type.

    Vertical dashed lines indicate media order events.

    Parameters
    ----------
    inv:
        Inventory object containing:
            inv.daily_used
            inv.daily_expired
            inv.order_events

    days:
        Number of simulation days to display.
        If None, inferred from the inventory records.
    """

    # -------------------------------------------------------------------------
    # Identify media types and simulation duration
    # -------------------------------------------------------------------------

    media_types = list(MEDIA_TYPES)

    if not media_types:
        raise ValueError("MEDIA_TYPES is empty.")

    if days is None:
        days = min(
            len(inv.daily_used),
            len(inv.daily_expired),
        )

    if days <= 0:
        raise ValueError("No daily inventory records were found.")

    day = np.arange(days)

    # -------------------------------------------------------------------------
    # Extract daily usage and expiration
    # -------------------------------------------------------------------------

    used = pd.DataFrame({
        media: [
            inv.daily_used[d].get(media, 0)
            for d in day
        ]
        for media in media_types
    })

    expired = pd.DataFrame({
        media: [
            inv.daily_expired[d].get(media, 0)
            for d in day
        ]
        for media in media_types
    })

    used = used.fillna(0)
    expired = expired.fillna(0)

    cumulative = used.cumsum()

    used.insert(0, "Day", day)
    expired.insert(0, "Day", day)
    cumulative.insert(0, "Day", day)

    # -------------------------------------------------------------------------
    # Save underlying data
    # -------------------------------------------------------------------------

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    used.to_csv(
        OUTPUT_DIR / "table_media_used_daily.csv",
        index=False,
    )

    expired.to_csv(
        OUTPUT_DIR / "table_media_expired_daily.csv",
        index=False,
    )

    cumulative.to_csv(
        OUTPUT_DIR / "table_media_used_cumulative.csv",
        index=False,
    )

    # -------------------------------------------------------------------------
    # Order events
    # -------------------------------------------------------------------------

    order_days = sorted({
        int(event[0])
        for event in getattr(inv, "order_events", [])
        if 0 <= int(event[0]) < days
    })

    # -------------------------------------------------------------------------
    # Figure
    # -------------------------------------------------------------------------

    n_panels = 3

    height = (
        PNG_HEIGHT
        if PNG_HEIGHT is not None
        else 5.8
    )

    fig, axes = plt.subplots(
        n_panels,
        1,
        figsize=(PNG_WIDTH + 1.0, height),
        sharex=True,
    )

    fig.subplots_adjust(
        left=0.17,
        right=0.97,
        bottom=0.12,
        top=0.88,
        hspace=0.38,
    )

    colors = {
        media: fc.FALLBACK_PALETTE[i % len(fc.FALLBACK_PALETTE)]
        for i, media in enumerate(media_types)
    }

    # -------------------------------------------------------------------------
    # Panel A: Daily consumption
    # -------------------------------------------------------------------------

    ax = axes[0]

    for media in media_types:
        ax.plot(
            day,
            used[media],
            color=colors[media],
            linewidth=1.2,
            label=media,
        )

    for order_day in order_days:
        ax.axvline(
            order_day,
            color=fc.OBS24_C,
            linestyle="--",
            alpha=0.25,
            linewidth=0.8,
        )

    ax.set_ylabel("Plates used / day")
    ax.set_title("A. Daily media consumption", loc="left", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.6)

    # -------------------------------------------------------------------------
    # Panel B: Cumulative consumption
    # -------------------------------------------------------------------------

    ax = axes[1]

    for media in media_types:
        ax.plot(
            day,
            cumulative[media],
            color=colors[media],
            linewidth=1.4,
            label=media,
        )

    for order_day in order_days:
        ax.axvline(
            order_day,
            color=fc.OBS24_C,
            linestyle="--",
            alpha=0.25,
            linewidth=0.8,
        )

    ax.set_ylabel("Cumulative plates used")
    ax.set_title("B. Cumulative media consumption", loc="left", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.6)

    # -------------------------------------------------------------------------
    # Panel C: Daily expiration
    # -------------------------------------------------------------------------

    ax = axes[2]

    for media in media_types:
        ax.plot(
            day,
            expired[media],
            color=colors[media],
            linewidth=1.2,
            linestyle="--",
            label=media,
        )

    for order_day in order_days:
        ax.axvline(
            order_day,
            color=fc.OBS24_C,
            linestyle="--",
            alpha=0.25,
            linewidth=0.8,
        )

    ax.set_ylabel("Plates expired / day")
    ax.set_xlabel("Simulation day")
    ax.set_title("C. Daily media expiration", loc="left", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.6)

    # -------------------------------------------------------------------------
    # Shared legend
    # -------------------------------------------------------------------------

    handles = [
        Line2D(
            [0], [0],
            color=colors[media],
            linewidth=1.5,
            label=media,
        )
        for media in media_types
    ]

    handles.append(
        Line2D(
            [0], [0],
            color=fc.OBS24_C,
            linestyle="--",
            linewidth=1,
            label="Media order placed",
        )
    )

    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.55, 0.99),
        ncol=LEGEND_COLUMNS,
        frameon=False,
    )

    # -------------------------------------------------------------------------
    # Save figure
    # -------------------------------------------------------------------------

    fc.save_both(
        fig,
        filename,
        OUTPUT_DIR,
        dpi=DPI,
        bare=BARE,
    )

    print(
        f"Media consumption figure saved to {OUTPUT_DIR}"
    )
