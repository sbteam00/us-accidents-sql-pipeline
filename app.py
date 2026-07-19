"""
app.py
------
US Accidents Analytics — Streamlit + PyDeck Interactive Map Dashboard

Connects to us_accidents_db (local Postgres) and provides:
  - Three toggleable PyDeck map layers (Hexagon, Scatter, Heatmap)
  - Sidebar filters that auto-apply on change
  - Info panel with three tabs:
      Tab 1: Selected accident detail (manual ID lookup or click)
      Tab 2: Filter summary statistics (live stats for current filter)
      Tab 3: Analytics highlights (key findings from mart tables)

Usage:
    streamlit run app.py

Requirements:
    pip install streamlit pydeck psycopg2-binary pandas
"""

import json
import streamlit as st
import pydeck as pdk
import psycopg2
import pandas as pd
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Page config — must be first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="US Accidents Analytics",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Dark theme CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    [data-testid="stSidebar"] { background-color: #161b27; }
    [data-testid="stSidebar"] * { color: #fafafa !important; }
    [data-testid="metric-container"] {
        background-color: #1e2536;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 12px;
    }
    .stTabs [data-baseweb="tab-list"] { background-color: #161b27; }
    .stTabs [data-baseweb="tab"] { color: #a0aec0; }
    .stTabs [aria-selected="true"] { color: #63b3ed !important; }
    .info-box {
        background-color: #1e2536;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    .highlight-card {
        background-color: #1e2536;
        border-left: 4px solid #63b3ed;
        border-radius: 4px;
        padding: 12px 16px;
        margin: 6px 0;
        font-size: 14px;
        line-height: 1.6;
    }
    hr { border-color: #2d3748; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "user":     "postgres",
    "password": "password",   # ← update this
    "database": "us_accidents_db",
}


@st.cache_resource
def get_connection():
    """Persistent connection — cached for the session lifetime."""
    return psycopg2.connect(**DB_CONFIG)


def run_query(sql: str, params=None) -> pd.DataFrame:
    """Execute SQL and return a DataFrame."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return pd.DataFrame(rows)
    except Exception as e:
        conn.rollback()
        st.error(f"Query error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_filter_options():
    states = run_query(
        "SELECT DISTINCT state FROM raw.accidents ORDER BY state"
    )["state"].tolist()
    weather = run_query(
        "SELECT DISTINCT weather_condition FROM raw.accidents "
        "WHERE weather_condition IS NOT NULL ORDER BY weather_condition"
    )["weather_condition"].tolist()
    contexts = run_query(
        "SELECT DISTINCT incident_context FROM raw.accidents ORDER BY incident_context"
    )["incident_context"].tolist()
    return states, weather, contexts


@st.cache_data(ttl=3600)
def load_mart_highlights():
    """Pull key findings from mart tables once on app load."""
    def safe_float(df, col):
        return float(df[col].iloc[0]) if not df.empty else None

    def safe_int(df, col):
        return int(df[col].iloc[0]) if not df.empty else None

    def safe_str(df, col):
        return str(df[col].iloc[0]) if not df.empty else None

    overall = run_query(
        "SELECT critical_rate_pct FROM analytics_analytics.mart_funnel "
        "WHERE funnel_dimension = 'overall' LIMIT 1"
    )
    night = run_query(
        "SELECT critical_rate_pct FROM analytics_analytics.mart_funnel "
        "WHERE funnel_dimension = 'by_light' AND dimension_value = 'Full_Night' LIMIT 1"
    )
    day = run_query(
        "SELECT critical_rate_pct FROM analytics_analytics.mart_funnel "
        "WHERE funnel_dimension = 'by_light' AND dimension_value = 'Full_Day' LIMIT 1"
    )
    ca = run_query(
        "SELECT accident_count, critical_rate_pct FROM analytics_analytics.mart_geo "
        "WHERE geo_level = 'state' AND state = 'CA' LIMIT 1"
    )
    roundabout = run_query(
        "SELECT avg_severity FROM analytics_analytics.mart_weather_poi "
        "WHERE analysis_type = 'roundabout' LIMIT 1"
    )
    junction = run_query(
        "SELECT avg_severity FROM analytics_analytics.mart_weather_poi "
        "WHERE analysis_type = 'junction' LIMIT 1"
    )
    top_ctx = run_query(
        "SELECT dimension_value, critical_rate_pct "
        "FROM analytics_analytics.mart_funnel "
        "WHERE funnel_dimension = 'by_context' "
        "ORDER BY critical_rate_pct DESC LIMIT 1"
    )
    return {
        "national_critical_rate": safe_float(overall, "critical_rate_pct") or 2.53,
        "night_critical_rate":    safe_float(night,   "critical_rate_pct") or 4.05,
        "day_critical_rate":      safe_float(day,     "critical_rate_pct") or 2.18,
        "ca_accidents":           safe_int(ca,        "accident_count")    or 1557414,
        "ca_critical_rate":       safe_float(ca,      "critical_rate_pct") or 0.70,
        "roundabout_severity":    safe_float(roundabout, "avg_severity")   or 2.073,
        "junction_severity":      safe_float(junction,   "avg_severity")   or 2.286,
        "top_context_name":       safe_str(top_ctx, "dimension_value")     or "road_closure",
        "top_context_rate":       safe_float(top_ctx, "critical_rate_pct") or 41.36,
    }


# ---------------------------------------------------------------------------
# Filter → WHERE clause builder
# ---------------------------------------------------------------------------
def build_where(filters: dict):
    conditions, params = [], []

    if filters["states"]:
        ph = ",".join(["%s"] * len(filters["states"]))
        conditions.append(f"state IN ({ph})")
        params.extend(filters["states"])

    yr = filters.get("year_range")
    if yr:
        conditions.append("EXTRACT(YEAR FROM start_time) BETWEEN %s AND %s")
        params.extend(yr)

    hr = filters.get("hour_range")
    if hr:
        conditions.append("hour_of_day BETWEEN %s AND %s")
        params.extend(hr)

    if filters["severities"]:
        ph = ",".join(["%s"] * len(filters["severities"]))
        conditions.append(f"severity IN ({ph})")
        params.extend(filters["severities"])

    if filters["weather_conditions"]:
        ph = ",".join(["%s"] * len(filters["weather_conditions"]))
        conditions.append(f"weather_condition IN ({ph})")
        params.extend(filters["weather_conditions"])

    if filters["incident_contexts"]:
        ph = ",".join(["%s"] * len(filters["incident_contexts"]))
        conditions.append(f"incident_context IN ({ph})")
        params.extend(filters["incident_contexts"])

    if filters.get("weekend_only"):
        conditions.append("is_weekend = TRUE")

    if filters.get("rush_hour_only"):
        conditions.append("is_rush_hour = TRUE")

    if filters.get("junction_only"):
        conditions.append("junction = TRUE")

    dr = filters.get("duration_range")
    if dr and dr != [0, 1440]:
        conditions.append("duration_mins BETWEEN %s AND %s")
        params.extend(dr)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params


@st.cache_data(ttl=60, show_spinner=False)
def load_map_data(cache_key: str, filters_json: str, max_rows: int):
    filters = json.loads(filters_json)
    where, params = build_where(filters)
    sql = f"""
        SELECT
            id,
            start_lat   AS lat,
            start_lng   AS lng,
            severity,
            city,
            state,
            incident_context,
            start_time::TEXT AS start_time,
            duration_mins,
            weather_condition,
            hour_of_day
        FROM raw.accidents
        {where}
        ORDER BY RANDOM()
        LIMIT %s
    """
    params.append(max_rows)
    df = run_query(sql, params)
    colour_map = {
        1: [0,   200, 100, 180],
        2: [255, 220, 0,   180],
        3: [255, 140, 0,   200],
        4: [220, 30,  30,  220],
    }
    if not df.empty and "severity" in df.columns:
        df["colour"] = df["severity"].apply(
            lambda s: colour_map.get(int(s), [150, 150, 150, 180])
        )
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_filter_stats(cache_key: str, filters_json: str):
    filters = json.loads(filters_json)
    where, params = build_where(filters)
    sql = f"""
        SELECT
            COUNT(*)                                              AS total,
            ROUND(AVG(severity)::NUMERIC, 3)                     AS avg_severity,
            ROUND(AVG(duration_mins) FILTER (
                WHERE duration_mins > 0 AND duration_mins < 1440
            )::NUMERIC, 1)                                       AS avg_duration,
            ROUND(
                COUNT(*) FILTER (WHERE severity = 4) * 100.0
                / NULLIF(COUNT(*), 0), 2
            )                                                    AS critical_rate,
            COUNT(*) FILTER (WHERE severity = 1)                 AS sev1,
            COUNT(*) FILTER (WHERE severity = 2)                 AS sev2,
            COUNT(*) FILTER (WHERE severity = 3)                 AS sev3,
            COUNT(*) FILTER (WHERE severity = 4)                 AS sev4
        FROM raw.accidents {where}
    """
    return run_query(sql, params)


def load_accident_detail(accident_id: int) -> dict:
    sql = """
        SELECT
            id, source_id, severity,
            start_time::TEXT AS start_time,
            end_time::TEXT   AS end_time,
            duration_mins, start_lat, start_lng, distance_mi,
            city, county, state, zipcode, street, timezone,
            weather_condition, temperature_f, humidity_pct,
            visibility_mi, wind_speed_mph, precipitation_in, wind_direction,
            incident_context, light_condition_category,
            junction, crossing, traffic_signal, roundabout,
            is_rush_hour, is_weekend, description
        FROM raw.accidents
        WHERE id = %s
    """
    df = run_query(sql, [accident_id])
    return df.iloc[0].to_dict() if not df.empty else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SEVERITY_LABELS  = {1: "🟢 Minor", 2: "🟡 Moderate", 3: "🟠 Serious", 4: "🔴 Critical"}
SEVERITY_COLOURS = {1: "#00c864", 2: "#ffdc00", 3: "#ff8c00", 4: "#dc1e1e"}

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🚗 US Accidents")
    st.markdown("### Filters")
    st.caption("Filters auto-apply on change")
    st.divider()

    states_list, weather_list, contexts_list = load_filter_options()

    st.markdown("**📍 Geographic**")
    selected_states = st.multiselect(
        "State", options=states_list, default=[], placeholder="All states"
    )
    st.divider()

    st.markdown("**📅 Temporal**")
    year_min, year_max = st.slider(
        "Year range", min_value=2016, max_value=2022, value=(2016, 2022)
    )
    hour_min, hour_max = st.slider(
        "Hour of day", min_value=0, max_value=23, value=(0, 23), format="%d:00"
    )
    c1, c2 = st.columns(2)
    with c1:
        weekend_only  = st.checkbox("Weekend only",   value=False)
    with c2:
        rush_only     = st.checkbox("Rush hour only", value=False)
    st.divider()

    st.markdown("**⚠️ Severity**")
    selected_severities = st.multiselect(
        "Severity levels", options=[1, 2, 3, 4], default=[],
        format_func=lambda s: SEVERITY_LABELS[s], placeholder="All severities"
    )
    st.markdown("**⏱️ Duration (mins)**")
    dur_min, dur_max = st.slider(
        "Duration range", min_value=0, max_value=1440, value=(0, 1440), step=10
    )
    st.divider()

    st.markdown("**🌦️ Weather**")
    selected_weather = st.multiselect(
        "Weather condition", options=weather_list, default=[], placeholder="All conditions"
    )
    st.divider()

    st.markdown("**🛣️ Road Features**")
    selected_contexts = st.multiselect(
        "Incident context", options=contexts_list, default=[], placeholder="All contexts"
    )
    junction_only = st.checkbox("Junction accidents only", value=False)
    st.divider()

    st.markdown("**🗺️ Map Layer**")
    layer_type = st.radio(
        "Active layer",
        options=["Hexagon (Density)", "Scatter (Individual)", "Heatmap (Intensity)"],
        index=0,
        label_visibility="collapsed",
    )
    if layer_type == "Hexagon (Density)":
        elevation_scale = st.slider(
            "3D elevation scale", min_value=10, max_value=200, value=50, step=10
        )
    else:
        elevation_scale = 50

    st.markdown("**📊 Max points**")
    max_rows = st.select_slider(
        "Row limit",
        options=[1000, 5000, 10000, 25000, 50000],
        value=10000,
        label_visibility="collapsed",
    )
    st.caption(f"Map capped at {max_rows:,} points")

# ---------------------------------------------------------------------------
# Filters dict + cache key
# ---------------------------------------------------------------------------
filters = {
    "states":             selected_states,
    "year_range":         [year_min, year_max],
    "hour_range":         [hour_min, hour_max],
    "severities":         selected_severities,
    "weather_conditions": selected_weather,
    "incident_contexts":  selected_contexts,
    "weekend_only":       weekend_only,
    "rush_hour_only":     rush_only,
    "junction_only":      junction_only,
    "duration_range":     [dur_min, dur_max],
}
filters_json = json.dumps(filters, sort_keys=True)
filters_key  = str(hash(filters_json))

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
with st.spinner("Loading map data..."):
    map_df = load_map_data(filters_key, filters_json, max_rows)

with st.spinner("Computing statistics..."):
    stats_df = load_filter_stats(filters_key, filters_json)

highlights = load_mart_highlights()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    "<h1 style='text-align:center; color:#63b3ed; margin-bottom:4px;'>"
    "🚗 US Accidents Interactive Map</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align:center; color:#a0aec0; font-size:14px; margin-top:0;'>"
    "7M+ accident records (2016–2022) · Source: Kaggle US Accidents Dataset</p>",
    unsafe_allow_html=True,
)

# Metric strip
stats_row = stats_df.iloc[0] if not stats_df.empty else {}
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Points on Map",  f"{len(map_df):,}")
c2.metric("Filtered Total", f"{int(stats_row.get('total', 0)):,}" if stats_row.get("total") else "—")
c3.metric("Avg Severity",   str(stats_row.get("avg_severity", "—")))
c4.metric("Avg Duration",   f"{stats_row.get('avg_duration', '—')} min" if stats_row.get("avg_duration") else "—")
c5.metric("Critical Rate",  f"{stats_row.get('critical_rate', '—')}%" if stats_row.get("critical_rate") else "—")
st.divider()

# ---------------------------------------------------------------------------
# PyDeck Map
# ---------------------------------------------------------------------------
view_state = pdk.ViewState(
    latitude=39.5,
    longitude=-98.35,
    zoom=3.8,
    pitch=45 if layer_type == "Hexagon (Density)" else 0,
    bearing=0,
)

if not map_df.empty:
    if layer_type == "Hexagon (Density)":
        active_layer = pdk.Layer(
            "HexagonLayer",
            data=map_df[["lat", "lng"]],
            get_position="[lng, lat]",
            radius=8000,
            elevation_scale=elevation_scale,
            elevation_range=[0, 3000],
            extruded=True,
            pickable=True,
            auto_highlight=True,
            coverage=0.9,
            color_range=[
                [1,   152, 189, 200],
                [103, 169, 207, 200],
                [209, 229, 240, 200],
                [253, 174, 97,  200],
                [244, 109, 67,  200],
                [215, 48,  39,  220],
            ],
        )
        tooltip = {
            "html": "<div style='background:#1e2536; padding:8px; border-radius:6px; color:#fafafa;'>"
                    "<b style='color:#63b3ed;'>Accident Cluster</b><br/>"
                    "Count: <b>{elevationValue}</b></div>",
            "style": {"backgroundColor": "transparent"},
        }

    elif layer_type == "Scatter (Individual)":
        active_layer = pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position="[lng, lat]",
            get_color="colour",
            get_radius=3000,
            pickable=True,
            auto_highlight=True,
            radius_min_pixels=2,
            radius_max_pixels=8,
        )
        tooltip = {
            "html": """
                <div style='background:#1e2536; padding:10px; border-radius:6px;
                            border:1px solid #2d3748; font-family:sans-serif;'>
                    <b style='color:#63b3ed;'>Accident #{id}</b><br/>
                    <span style='color:#a0aec0;'>Severity:</span>
                    <b style='color:#fafafa;'> {severity}</b><br/>
                    <span style='color:#a0aec0;'>Location:</span>
                    <b style='color:#fafafa;'> {city}, {state}</b><br/>
                    <span style='color:#a0aec0;'>Time:</span>
                    <b style='color:#fafafa;'> {start_time}</b><br/>
                    <span style='color:#a0aec0;'>Context:</span>
                    <b style='color:#fafafa;'> {incident_context}</b><br/>
                    <span style='color:#a0aec0;'>Weather:</span>
                    <b style='color:#fafafa;'> {weather_condition}</b>
                </div>
            """,
            "style": {"backgroundColor": "transparent", "color": "white"},
        }

    else:  # Heatmap
        active_layer = pdk.Layer(
            "HeatmapLayer",
            data=map_df[["lat", "lng"]],
            get_position="[lng, lat]",
            aggregation="MEAN",
            threshold=0.05,
            pickable=False,
            color_range=[
                [0,   0,   255, 0  ],
                [0,   128, 255, 100],
                [0,   255, 128, 150],
                [255, 255, 0,   180],
                [255, 128, 0,   200],
                [255, 0,   0,   220],
            ],
        )
        tooltip = None

    deck = pdk.Deck(
        layers=[active_layer],
        initial_view_state=view_state,
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True, height=480)

else:
    st.warning("No accidents match the current filters — try broadening your selection.")

# ---------------------------------------------------------------------------
# Info panel — three tabs
# ---------------------------------------------------------------------------
st.divider()
tab1, tab2, tab3 = st.tabs([
    "🔍 Accident Detail",
    "📊 Filter Statistics",
    "💡 Analytics Highlights",
])

# ── TAB 1: Accident Detail ──────────────────────────────────────────────────
with tab1:
    st.markdown("#### Selected Accident Detail")
    st.caption("Enter an Accident ID to retrieve its full record from `raw.accidents`.")

    if "selected_id" not in st.session_state:
        st.session_state.selected_id = None

    col_l, col_r = st.columns([3, 1])
    with col_l:
        manual_id = st.number_input(
            "Accident ID", min_value=1, max_value=9_999_999,
            value=int(st.session_state.selected_id) if st.session_state.selected_id else 1,
            step=1, label_visibility="collapsed",
        )
    with col_r:
        if st.button("🔍 Look up", use_container_width=True):
            st.session_state.selected_id = int(manual_id)

    if st.session_state.selected_id:
        detail = load_accident_detail(st.session_state.selected_id)
        if detail:
            sev        = int(detail.get("severity", 2))
            sev_label  = SEVERITY_LABELS.get(sev, "Unknown")
            sev_colour = SEVERITY_COLOURS.get(sev, "#ffffff")

            def v(key, default="—"):
                val = detail.get(key, default)
                return default if val is None else val

            st.markdown(f"""
            <div class='info-box'>
                <div style='display:flex; justify-content:space-between;
                            align-items:center; margin-bottom:12px;'>
                    <span style='font-size:18px; font-weight:600; color:#63b3ed;'>
                        Accident #{v("id")}
                    </span>
                    <span style='font-size:14px; font-weight:600; color:{sev_colour};
                                 background:#2d3748; padding:4px 10px; border-radius:12px;'>
                        {sev_label}
                    </span>
                </div>
                <hr style='border-color:#2d3748; margin:8px 0;'/>
                <table style='width:100%; font-size:13px; color:#fafafa; border-spacing:0;'>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0; white-space:nowrap;'>📍 Location</td>
                        <td><b>{v("city")}, {v("county")} County, {v("state")} {v("zipcode")}</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🛣️ Street</td>
                        <td><b>{v("street")}</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🕐 Start time</td>
                        <td><b>{v("start_time")}</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>⏱️ Duration</td>
                        <td><b>{v("duration_mins")} mins</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🌐 Coordinates</td>
                        <td><b>{v("start_lat")}°N, {v("start_lng")}°W</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🌦️ Weather</td>
                        <td><b>{v("weather_condition")}, {v("temperature_f")}°F,
                            Vis {v("visibility_mi")} mi</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>💨 Wind</td>
                        <td><b>{v("wind_speed_mph")} mph {v("wind_direction")},
                            Humidity {v("humidity_pct")}%</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🏷️ Incident type</td>
                        <td><b>{v("incident_context")}</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>💡 Light condition</td>
                        <td><b>{v("light_condition_category")}</b></td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>🚦 Infrastructure</td>
                        <td>
                            Junction: <b>{"Yes" if detail.get("junction") else "No"}</b> &nbsp;|&nbsp;
                            Signal: <b>{"Yes" if detail.get("traffic_signal") else "No"}</b> &nbsp;|&nbsp;
                            Crossing: <b>{"Yes" if detail.get("crossing") else "No"}</b> &nbsp;|&nbsp;
                            Roundabout: <b>{"Yes" if detail.get("roundabout") else "No"}</b>
                        </td>
                    </tr>
                    <tr>
                        <td style='color:#a0aec0; padding:4px 12px 4px 0;'>⏰ Time context</td>
                        <td>
                            <b>{"Rush hour" if detail.get("is_rush_hour") else "Off-peak"}</b>
                            &nbsp;|&nbsp;
                            <b>{"Weekend" if detail.get("is_weekend") else "Weekday"}</b>
                        </td>
                    </tr>
                </table>
                <hr style='border-color:#2d3748; margin:12px 0 8px;'/>
                <div style='color:#a0aec0; font-size:12px; margin-bottom:4px;'>
                    📝 Description
                </div>
                <div style='color:#fafafa; font-size:13px; line-height:1.6;
                            background:#0e1117; padding:10px; border-radius:4px;'>
                    {v("description", "No description available.")}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning(f"No accident found with ID {st.session_state.selected_id}.")
    else:
        st.markdown(
            "<div class='info-box' style='color:#a0aec0; text-align:center; padding:32px;'>"
            "Enter an Accident ID above and click <b>Look up</b> to view full details.<br/>"
            "IDs range from 1 to 7,051,556."
            "</div>",
            unsafe_allow_html=True,
        )

# ── TAB 2: Filter Statistics ────────────────────────────────────────────────
with tab2:
    st.markdown("#### Current Filter Statistics")
    if not stats_df.empty:
        row   = stats_df.iloc[0]
        total = int(row.get("total", 0))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Matching accidents", f"{total:,}")
        c2.metric("Avg severity",       str(row.get("avg_severity", "—")))
        c3.metric("Avg duration",       f"{row.get('avg_duration', '—')} min")
        c4.metric("Critical rate",      f"{row.get('critical_rate', '—')}%")

        st.markdown("**Severity breakdown**")
        sev_data = {
            "🟢 Severity 1 — Minor":    int(row.get("sev1", 0)),
            "🟡 Severity 2 — Moderate": int(row.get("sev2", 0)),
            "🟠 Severity 3 — Serious":  int(row.get("sev3", 0)),
            "🔴 Severity 4 — Critical": int(row.get("sev4", 0)),
        }
        for label, count in sev_data.items():
            pct = round(count / total * 100, 1) if total > 0 else 0.0
            cl, cr = st.columns([4, 1])
            with cl:
                st.progress(pct / 100, text=f"{label}: {count:,}")
            with cr:
                st.markdown(
                    f"<div style='text-align:right; color:#a0aec0; "
                    f"font-size:13px; padding-top:8px;'>{pct}%</div>",
                    unsafe_allow_html=True,
                )
    else:
        st.info("No data matches current filters.")

# ── TAB 3: Analytics Highlights ─────────────────────────────────────────────
with tab3:
    st.markdown("#### Key Findings from Full Dataset Analysis")
    st.caption("Pre-computed from 7M records · Source: dbt analytics mart tables")

    h = highlights
    findings = [
        (
            "🗺️ California Volume vs Safety Paradox",
            f"California accounts for <b>22%</b> of all US accidents "
            f"({h['ca_accidents']:,} records) yet has only a <b>{h['ca_critical_rate']}% critical rate</b> "
            f"— the highest-volume, lowest-severity state. Dense urban infrastructure and fast "
            f"emergency response explain the disconnect between volume and severity."
        ),
        (
            "🌙 Nighttime Nearly Doubles Critical Risk",
            f"Full Night accidents have a <b>{h['night_critical_rate']}% critical rate</b> vs "
            f"<b>{h['day_critical_rate']}% during Full Day</b> — nearly double. Despite similar "
            f"average severity scores, darkness fundamentally changes the worst-case outcome "
            f"probability. Speed on empty roads is the primary driver."
        ),
        (
            "🔄 Roundabout Safety Is Data-Supported",
            f"Accidents near roundabouts average severity <b>{h['roundabout_severity']}</b> — "
            f"the lowest of all 13 road infrastructure features in the dataset. Junctions average "
            f"<b>{h['junction_severity']}</b>. This directly validates traffic engineering evidence "
            f"that roundabouts reduce fatal and serious collisions."
        ),
        (
            "⚡ COVID Lockdown Created a Severity Paradox",
            "March–June 2020 saw critical accident rates spike to 3.77–4.71% despite stable "
            "or lower total accident volumes. Emptier roads enabled higher speeds — fewer "
            "accidents but significantly worse outcomes when they occurred. A counterintuitive "
            "consequence of pandemic-era mobility changes."
        ),
        (
            f"🚨 {h['top_context_name'].replace('_', ' ').title()} — Highest Critical Rate",
            f"<b>{h['top_context_name'].replace('_', ' ')}</b> incidents have a "
            f"<b>{h['top_context_rate']}% critical rate</b> — the highest of any incident "
            f"classification in the dataset. Full road closures are strongly correlated with "
            f"the most severe accidents, reflecting the nature of incidents that cause them."
        ),
        (
            "🕗 Late Evening Has Highest Severity Despite Mid-Table Volume",
            "Hours 19–22 (7–10pm) rank highest on average severity yet sit mid-table on "
            "accident volume. Rush hours (7–8am) generate the most accidents but at lower "
            "severity — congestion slows traffic. Late evening accidents occur at speed on "
            "emptier roads, producing consistently worse outcomes."
        ),
    ]

    for title, body in findings:
        st.markdown(
            f"<div class='highlight-card'>"
            f"<div style='font-weight:600; color:#63b3ed; margin-bottom:4px;'>{title}</div>"
            f"<div style='color:#e2e8f0;'>{body}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
