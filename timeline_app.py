# timeline_app.py
# Streamlit app: Integrated Sampling + Spreading (rolling, coupled by "ready area")
# - Sampling converts points/day -> ha/day using points/ha
# - Spreading converts tonnes/day -> ha/day using t/ha
# - Spreading can only occur on area already sampled (after optional lag)
# - Visualizes cumulative sampled vs spread over time + backlog

import math
from datetime import date, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Sampling + Spreading Integrated Timeline", layout="centered")

st.title("Sampling + Spreading Integrated Timeline")
st.caption("Coupled rolling model: sampling creates 'ready' hectares; spreading consumes them.")

# ----------------------------
# INPUTS
# ----------------------------
st.header("1) Scope")

total_area_ha = st.number_input("Total area to cover (ha)", min_value=0.0, value=100.22, step=0.01)
total_points = st.number_input("Total sampling points", min_value=0, value=13545, step=1)

st.header("2) Sampling (points → ha)")

sampling_people = st.number_input("Sampling crew size (people)", min_value=1, value=5, step=1)
points_per_person_per_week = st.number_input(
    "Sampling throughput (points / person / week)",
    min_value=1.0,
    value=519.0,
    step=1.0,
)
workdays_per_week = st.selectbox("Workdays per week", [5, 6, 7], index=0)

sampling_contingency_pct = st.number_input(
    "Sampling contingency (%)",
    min_value=0.0,
    value=10.0,
    step=1.0,
    help="Planning buffer applied to sampling capacity (reduces effective sampling rate).",
)

st.header("3) Spreading (tonnes → ha)")

t_per_ha = st.number_input("Application rate (t/ha)", min_value=0.1, value=40.0, step=1.0)
tonnes_per_day = st.number_input("Spreading capacity (t/day)", min_value=0.0, value=80.0, step=5.0)

spreading_lag_days = st.number_input(
    "Lag (days) before spreading can start",
    min_value=0,
    value=1,
    step=1,
    help="0 = spreading can start immediately; 1 = starts the next day; etc.",
)

st.header("4) Dates & simulation")

start_date = st.date_input("Start date", value=date.today())
max_sim_days = st.number_input(
    "Max simulation days (safety cap)", min_value=30, value=365, step=30
)

st.subheader("Derived density")
points_per_ha = (total_points / total_area_ha) if total_area_ha > 0 else 0.0
st.write(f"**Points per hectare:** {points_per_ha:.2f} points/ha")

# ----------------------------
# DERIVED RATES
# ----------------------------
# Sampling points/day (working day)
points_per_week_team = sampling_people * points_per_person_per_week
points_per_workday_team = points_per_week_team / float(workdays_per_week)

# Apply contingency as "friction" reducing effective sampling output
# (i.e., 10% contingency -> divide by 1.10)
sampling_friction = 1.0 + sampling_contingency_pct / 100.0
effective_points_per_workday = points_per_workday_team / sampling_friction

# Convert to ha/day sampled (working day)
effective_sampling_ha_per_workday = (
    effective_points_per_workday / points_per_ha if points_per_ha > 0 else 0.0
)

# Spreading ha/day (calendar day, but we’ll apply the same workdays/week schedule)
spreading_ha_per_workday = (tonnes_per_day / t_per_ha) if t_per_ha > 0 else 0.0

st.divider()
st.header("Key rates (as modeled)")

c1, c2, c3 = st.columns(3)
c1.metric("Sampling (ha / workday)", f"{effective_sampling_ha_per_workday:.2f}")
c2.metric("Spreading (ha / workday)", f"{spreading_ha_per_workday:.2f}")
c3.metric("Spreading cap (t/day)", f"{tonnes_per_day:.0f}")

# ----------------------------
# SIMULATION (rolling)
# ----------------------------
def is_workday(day_index: int, workdays_per_week_: int) -> bool:
    """
    A simple repeating workweek:
    - day_index=0 is a workday
    - first 'workdays_per_week' days are workdays, remaining are off days
    """
    return (day_index % 7) < workdays_per_week_


rows = []
sampled_cum = 0.0
spread_cum = 0.0

for d in range(int(max_sim_days)):
    current_date = start_date + timedelta(days=d)
    workday = is_workday(d, workdays_per_week)

    # Sampling happens on workdays only
    sampled_today = 0.0
    if workday and sampled_cum < total_area_ha:
        sampled_today = min(effective_sampling_ha_per_workday, total_area_ha - sampled_cum)
        sampled_cum += sampled_today

    # Spreading happens on workdays only, and only after lag days have passed
    spread_today = 0.0
    if workday and d >= spreading_lag_days:
        ready_backlog = max(sampled_cum - spread_cum, 0.0)
        if ready_backlog > 0 and spread_cum < total_area_ha:
            spread_today = min(spreading_ha_per_workday, ready_backlog, total_area_ha - spread_cum)
            spread_cum += spread_today

    backlog = max(sampled_cum - spread_cum, 0.0)

    rows.append(
        {
            "day": d,
            "date": current_date,
            "workday": workday,
            "sampled_today_ha": sampled_today,
            "spread_today_ha": spread_today,
            "sampled_cum_ha": sampled_cum,
            "spread_cum_ha": spread_cum,
            "backlog_ha": backlog,
        }
    )

    # Stop early if fully spread
    if spread_cum >= total_area_ha - 1e-9:
        break

df = pd.DataFrame(rows)

# ----------------------------
# OUTPUTS
# ----------------------------
st.divider()
st.header("Results")

sampling_finish_date = None
spreading_finish_date = None

if (df["sampled_cum_ha"] >= total_area_ha - 1e-9).any():
    sampling_finish_date = df.loc[df["sampled_cum_ha"] >= total_area_ha - 1e-9, "date"].iloc[0]

if (df["spread_cum_ha"] >= total_area_ha - 1e-9).any():
    spreading_finish_date = df.loc[df["spread_cum_ha"] >= total_area_ha - 1e-9, "date"].iloc[0]

colA, colB, colC = st.columns(3)
colA.metric("Days simulated", f"{len(df)}")
colB.metric("Sampling finish", sampling_finish_date.strftime("%Y-%m-%d") if sampling_finish_date else "Not reached")
colC.metric("Spreading finish", spreading_finish_date.strftime("%Y-%m-%d") if spreading_finish_date else "Not reached")

final_backlog = float(df["backlog_ha"].iloc[-1]) if len(df) else 0.0
st.metric("Backlog at end (ha sampled, not yet spread)", f"{final_backlog:.2f}")

# ----------------------------
# VISUALIZATION
# ----------------------------
st.subheader("Cumulative sampled vs spread (ha)")
chart_df = df[["date", "sampled_cum_ha", "spread_cum_ha"]].set_index("date")
st.line_chart(chart_df)

st.subheader("Backlog over time (ha)")
backlog_df = df[["date", "backlog_ha"]].set_index("date")
st.line_chart(backlog_df)

with st.expander("Show daily table"):
    st.dataframe(df, use_container_width=True)

st.caption(
    "Interpretation: if sampled rises faster than spread, backlog grows (spreading bottleneck). "
    "Spreading is capped by tonnes/day and can only consume already-sampled area (after lag)."
)
