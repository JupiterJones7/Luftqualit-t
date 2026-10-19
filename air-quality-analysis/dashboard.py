

import pandas as pd
import plotly.express as px
import streamlit as st

from database import load_data_from_database


st.set_page_config(
    page_title="Luftqualitäts-Dashboard",
    page_icon="🌡️",
    layout="wide",
)

st.title("Luftqualitäts-Dashboard")
st.caption("Überblick über deine gespeicherten Raumluftmessungen")


# Messgrössen und ihre Darstellung im Dashboard.
MEASUREMENT_GROUPS = {
    "Partikel-Massenkonzentration": [
        ("pm1_mass", "PM1.0", "µg/m³"),
        ("pm25_mass", "PM2.5", "µg/m³"),
        ("pm4_mass", "PM4.0", "µg/m³"),
        ("pm10_mass", "PM10", "µg/m³"),
    ],
    "Partikel-Anzahlkonzentration": [
        ("pm05_number", "PM0.5 Partikelanzahl", "particles/cm³"),
        ("pm1_number", "PM1.0 Partikelanzahl", "particles/cm³"),
        ("pm25_number", "PM2.5 Partikelanzahl", "particles/cm³"),
        ("pm4_number", "PM4.0 Partikelanzahl", "particles/cm³"),
        ("pm10_number", "PM10 Partikelanzahl", "particles/cm³"),
    ],
    "Gase und Luftqualitätsindizes": [
        ("co2", "CO₂", "ppm"),
        ("formaldehyde", "Formaldehyd (HCHO)", "mg/m³"),
        ("voc_index", "VOC-Index", "Index"),
        ("nox_index", "NOx-Index", "Index"),
    ],
    "Raumklima": [
        ("temperature", "Temperatur", "°C"),
        ("humidity", "Relative Luftfeuchtigkeit", "%"),
    ],
}


@st.cache_data(ttl=60)
def load_measurements():
    return load_data_from_database()


# Datenbankverbindung
try:
    df = load_measurements()
except Exception as exc:
    st.error("Die Messdaten konnten nicht geladen werden.")
    st.info(
        "Prüfe die DATABASE_URL in deiner .env-Datei "
        "und die Verbindung zu air_quality_v2."
    )
    with st.expander("Technische Fehlermeldung"):
        st.code(str(exc))
    st.stop()


if df.empty:
    st.warning(
        "Noch keine Messdaten vorhanden. "
        "Die Datenbank ist erreichbar, enthält aber "
        "noch keine gespeicherten Messungen."
    )
    st.info(
        "Sobald dein ESP32 Messwerte sendet oder du "
        "Testdaten importierst, erscheinen diese hier."
    )
    st.caption(
        f"Registrierte Messgrössen werden in der Datenbank "
        "verwaltet. Dieses Dashboard zeigt Messwerte an, "
        "sobald sie tatsächlich gespeichert wurden."
    )
    if st.button("Datenbank erneut prüfen"):
        st.cache_data.clear()
        st.rerun()
    st.stop()


# Daten vorbereiten
df = df.copy()

if "timestamp" not in df.columns:
    st.error("Die geladenen Daten enthalten keine Zeitstempel.")
    st.stop()

df["timestamp"] = pd.to_datetime(
    df["timestamp"],
    errors="coerce",
    utc=True,
)

df = df.dropna(subset=["timestamp"])

measurement_definitions = [
    measurement
    for group in MEASUREMENT_GROUPS.values()
    for measurement in group
]

for code, _, _ in measurement_definitions:
    if code in df.columns:
        df[code] = pd.to_numeric(df[code], errors="coerce")

if df.empty:
    st.warning("Es sind keine gültigen Messzeitpunkte vorhanden.")
    st.stop()

df = df.sort_values("timestamp")


# Sensorfilter
st.subheader("Filter")

filter_col1, filter_col2 = st.columns(2)

if "sensor_name" in df.columns:
    sensor_options = sorted(
        df["sensor_name"].dropna().unique().tolist()
    )
    selected_sensors = filter_col1.multiselect(
        "Sensor auswählen",
        options=sensor_options,
        default=sensor_options,
    )
    df = df[df["sensor_name"].isin(selected_sensors)]
else:
    filter_col1.info("Keine Sensorinformationen verfügbar.")

if df.empty:
    st.warning("Für die ausgewählten Sensoren gibt es keine Daten.")
    st.stop()


# Zeitraumfilter
minimum_date = df["timestamp"].min().date()
maximum_date = df["timestamp"].max().date()

selected_dates = filter_col2.date_input(
    "Messzeitraum auswählen",
    value=(minimum_date, maximum_date),
    min_value=minimum_date,
    max_value=maximum_date,
)

if not isinstance(selected_dates, (tuple, list)) or len(selected_dates) != 2:
    st.info("Bitte wähle einen Start- und Endzeitpunkt aus.")
    st.stop()

start_date, end_date = selected_dates

if start_date > end_date:
    st.error("Das Startdatum darf nicht nach dem Enddatum liegen.")
    st.stop()

start = pd.Timestamp(start_date, tz="UTC")
end = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)

filtered = df[
    (df["timestamp"] >= start)
    & (df["timestamp"] < end)
].copy()

if filtered.empty:
    st.warning("Im ausgewählten Zeitraum gibt es keine Messwerte.")
    st.stop()


# Allgemeine Informationen
st.subheader("Übersicht")

info1, info2, info3 = st.columns(3)

info1.metric("Messzeitpunkte", len(filtered))
info2.metric(
    "Sensoren",
    filtered["sensor_id"].nunique()
    if "sensor_id" in filtered.columns
    else "Unbekannt",
)
info3.metric(
    "Letzte gespeicherte Messung",
    filtered["timestamp"].max().strftime("%d.%m.%Y %H:%M UTC"),
)

st.divider()


# Aktuelle Messwerte
st.subheader("Aktuelle Messwerte")

available_groups = {}

for group_name, measurements in MEASUREMENT_GROUPS.items():
    available = [
        (code, label, unit)
        for code, label, unit in measurements
        if code in filtered.columns
    ]
    if available:
        available_groups[group_name] = available

if not available_groups:
    st.warning(
        "Die Daten enthalten keine der erwarteten Messgrössen. "
        "Prüfe die Spaltennamen in database.py."
    )
else:
    for group_name, measurements in available_groups.items():
        st.markdown(f"**{group_name}**")
        metric_columns = st.columns(min(4, len(measurements)))

        for index, (code, label, unit) in enumerate(measurements):
            valid_values = filtered[["timestamp", code]].dropna()
            column = metric_columns[index % len(metric_columns)]

            if valid_values.empty:
                column.metric(label, "Keine Daten")
                continue

            latest_row = valid_values.loc[
                valid_values["timestamp"].idxmax()
            ]
            value = latest_row[code]

            if unit == "°C":
                display_value = f"{value:.1f} °C"
            elif unit == "%":
                display_value = f"{value:.1f} %"
            elif unit == "ppm":
                display_value = f"{value:.0f} ppm"
            elif unit == "µg/m³":
                display_value = f"{value:.2f} µg/m³"
            elif unit == "mg/m³":
                display_value = f"{value:.4f} mg/m³"
            else:
                display_value = f"{value:.2f} {unit}"

            column.metric(label, display_value)

        st.caption(
            "Angezeigte Werte stammen jeweils aus dem letzten "
            "Zeitpunkt mit einem gültigen Wert für die betreffende Messgrösse."
        )

st.divider()


# Interaktive Diagramme
st.subheader("Messwertverlauf")

for group_name, measurements in available_groups.items():
    with st.expander(group_name, expanded=True):
        for code, label, unit in measurements:
            if code not in filtered.columns:
                continue

            chart_df = filtered.dropna(subset=[code]).copy()

            if chart_df.empty:
                st.info(f"Noch keine Messwerte für {label} vorhanden.")
                continue

            st.markdown(f"**{label}**")

            fig = px.line(
                chart_df,
                x="timestamp",
                y=code,
                color=(
                    "sensor_name"
                    if "sensor_name" in chart_df.columns
                    and chart_df["sensor_name"].nunique() > 1
                    else None
                ),
                labels={
                    "timestamp": "Zeitpunkt",
                    code: f"{label} ({unit})",
                    "sensor_name": "Sensor",
                },
            )

            fig.update_layout(
                hovermode="x unified",
                xaxis_title="Zeitpunkt",
                yaxis_title=f"{label} ({unit})",
                margin=dict(l=20, r=20, t=20, b=20),
            )

            st.plotly_chart(fig, use_container_width=True)


# Messhistorie
st.divider()
st.subheader("Messhistorie")

history_columns = [
    column
    for column in [
        "timestamp",
        "sensor_name",
        "sensor_model",
    ]
    + [
        code
        for code, _, _ in measurement_definitions
        if code in filtered.columns
    ]
    if column in filtered.columns
]

history = filtered[history_columns].sort_values(
    "timestamp",
    ascending=False,
)

st.dataframe(
    history,
    use_container_width=True,
    hide_index=True,
)

# Manuelles Aktualisieren
if st.button("Messdaten aktualisieren"):
    st.cache_data.clear()
    st.rerun()
