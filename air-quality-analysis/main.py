
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from database import load_data_from_database


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


IDENTIFIER_COLUMNS = [
    "timestamp",
    "sensor_id",
    "sensor_name",
    "sensor_model",
]


def clean_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prüft Messdaten und trennt gültige von ungültigen Zeilen."""

    if df.empty:
        raise ValueError(
            "Die Datenbank enthält noch keine Messdaten."
        )

    required_columns = set(IDENTIFIER_COLUMNS)
    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Fehlende Metadatenspalten: {sorted(missing)}"
        )

    df = df.copy()
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], errors="coerce", utc=True
    )

    measurement_columns = [
        column
        for column in df.columns
        if column not in IDENTIFIER_COLUMNS
    ]

    if not measurement_columns:
        raise ValueError(
            "Es wurden keine Messgrössen gefunden."
        )

    errors = pd.Series("", index=df.index, dtype="string")

    invalid_timestamp = df["timestamp"].isna()
    errors.loc[invalid_timestamp] += (
        "Ungültiger Zeitstempel; "
    )

    for column in measurement_columns:
        df[column] = pd.to_numeric(
            df[column], errors="coerce"
        )

        infinite_value = df[column].isin(
            [float("inf"), float("-inf")]
        )

        errors.loc[infinite_value] += (
            f"Unendlicher Wert in {column}; "
        )

        # Fehlende Werte sind erlaubt, wenn ein Sensor
        # diese Messgrösse nicht bei jedem Zeitpunkt liefert.
        # Unendliche Werte werden jedoch als ungültig markiert.
        infinite_value = df[column].map(
            lambda value: (
                pd.notna(value)
                and not pd.Series([value]).map(
                    lambda item: abs(item) != float("inf")
                ).iloc[0]
            )
        )

        errors.loc[infinite_value] += (
            f"Unendlicher Wert in {column}; "
        )

    # Nur vollständig identische Sensor-Zeitpunkte
    # werden als Duplikate betrachtet.
    duplicate_mask = df.duplicated(
        subset=["timestamp", "sensor_id"],
        keep="first",
    )

    errors.loc[duplicate_mask] += (
        "Doppelter Zeitstempel für Sensor; "
    )

    rejected_mask = errors.ne("")
    rejected = df.loc[rejected_mask].copy()
    rejected["error_reason"] = errors.loc[rejected_mask]

    clean = df.loc[~rejected_mask].copy()
    clean = clean.sort_values(
        ["sensor_id", "timestamp"]
    ).reset_index(drop=True)

    return clean, rejected


def analyze_data(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet Zeit seit der ersten Messung und CO₂-Änderungsraten."""

    df = df.copy()

    if "co2" not in df.columns:
        return df

    df = df.sort_values(["sensor_id", "timestamp"])
    grouped = df.groupby("sensor_id", sort=False)

    first_timestamp = grouped["timestamp"].transform("first")
    df["minutes_elapsed"] = (
        df["timestamp"] - first_timestamp
    ).dt.total_seconds() / 60

    time_difference = (
        grouped["timestamp"].diff().dt.total_seconds() / 60
    )
    co2_difference = grouped["co2"].diff()

    df["co2_rate_ppm_min"] = (
        co2_difference / time_difference.where(time_difference > 0)
    )

    return df



def print_statistics(df: pd.DataFrame) -> None:
    """Gibt Statistiken zu den verfügbaren Messwerten aus."""

    print("\n--- Datenqualitätsbericht ---")
    print(f"Gültige Zeilen: {len(df)}")

    measurement_columns = [
        column for column in df.columns
        if column not in IDENTIFIER_COLUMNS
        and column not in ["minutes_elapsed", "co2_rate_ppm_min"]
    ]

    print(f"Verfügbare Messgrössen: {len(measurement_columns)}")

    for column in measurement_columns:
        values = pd.to_numeric(df[column], errors="coerce").dropna()

        if values.empty:
            continue

        print(f"\n--- {column} ---")
        print(f"Anzahl Werte: {len(values)}")
        print(f"Mittelwert: {values.mean():.2f}")
        print(f"Minimum: {values.min():.2f}")
        print(f"Maximum: {values.max():.2f}")

    if "timestamp" in df.columns:
        times = df["timestamp"].dropna()
        if len(times) >= 2:
            duration = (
                times.max() - times.min()
            ).total_seconds() / 60
            print(f"\nMessdauer: {duration:.1f} Minuten")

    if "co2_rate_ppm_min" in df.columns:
        rate = df["co2_rate_ppm_min"].dropna()
        if not rate.empty:
            print(
                "Mittlere CO₂-Änderungsrate: "
                f"{rate.mean():.2f} ppm/min"
            )



def export_data(
    clean: pd.DataFrame,
    rejected: pd.DataFrame,
) -> None:
    """Speichert bereinigte und abgelehnte Messdaten."""

    clean.to_csv(
        OUTPUT_DIR / "cleaned_measurements.csv",
        index=False,
    )

    rejected.to_csv(
        OUTPUT_DIR / "rejected_measurements.csv",
        index=False,
    )

    print(f"\nAusgabedateien gespeichert in: {OUTPUT_DIR}")



def create_plot(df: pd.DataFrame) -> None:
    """Erstellt ein Diagramm des CO₂-Verlaufs."""

    if "co2" not in df.columns:
        print("Keine CO₂-Spalte vorhanden; Diagramm übersprungen.")
        return

    plot_data = df.dropna(subset=["timestamp", "co2"])

    if plot_data.empty:
        print("Keine CO₂-Daten zum Zeichnen vorhanden.")
        return

    plt.figure(figsize=(10, 5))

    for sensor_name, sensor_df in plot_data.groupby("sensor_name"):
        plt.plot(
            sensor_df["timestamp"],
            sensor_df["co2"],
            marker="o",
            label=str(sensor_name),
        )

    plt.title("CO₂-Verlauf")
    plt.xlabel("Zeit")
    plt.ylabel("CO₂-Konzentration (ppm)")
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_file = OUTPUT_DIR / "co2_plot.png"
    plt.savefig(output_file, dpi=150)
    plt.close()

    print(f"Diagramm gespeichert: {output_file}")



def main() -> None:
    df = load_data_from_database()

    clean, rejected = clean_data(df)

    print(f"Ursprüngliche Zeilen: {len(df)}")
    print(f"Gültige Zeilen: {len(clean)}")
    print(f"Abgelehnte Zeilen: {len(rejected)}")

    if clean.empty:
        export_data(clean, rejected)
        raise ValueError(
            "Keine gültigen Messdaten für die Analyse vorhanden."
        )

    clean = analyze_data(clean)
    print_statistics(clean)
    export_data(clean, rejected)
    create_plot(clean)


if __name__ == "__main__":
    main()
