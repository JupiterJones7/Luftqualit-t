
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# 1. Pfade definieren
BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "data" / "measurements.csv"
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 2. Daten einlesen
def load_data(path):
    if not path.exists():
        raise FileNotFoundError(
            f"CSV-Datei nicht gefunden: {path}"
        )

    df = pd.read_csv(path)

    required_columns = [
        "timestamp",
        "co2_ppm",
        "temperature_c",
        "humidity_pct",
    ]

    # Prüfen, ob alle benötigten Spalten existieren
    missing_columns = (
        set(required_columns) - set(df.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Fehlende Spalten: {sorted(missing_columns)}"
        )

    print(f"Eingelesene Zeilen: {len(df)}")

    return df


# 3. Datenqualität überprüfen
def clean_data(df):
    df = df.copy()

    original_count = len(df)

    # Ursprüngliche Zeilennummer dokumentieren
    df["source_row"] = range(2, len(df) + 2)

    # Fehlergründe sammeln
    df["error_reason"] = ""

    def add_error(mask, message):
        df.loc[mask, "error_reason"] = (
            df.loc[mask, "error_reason"]
            .apply(
                lambda current:
                f"{current}; {message}"
                if current else message
            )
        )

    # 1. Zeitstempel überprüfen
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], errors="coerce"
    )

    invalid_timestamp = df["timestamp"].isna()
    add_error(
        invalid_timestamp,
        "Fehlender oder ungültiger Zeitstempel"
    )

    # 2. Messwerte in Zahlen umwandeln
    numeric_columns = [
        "co2_ppm",
        "temperature_c",
        "humidity_pct",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column], errors="coerce"
        )

        invalid_value = df[column].isna()

        add_error(
            invalid_value,
            f"Fehlender oder ungültiger Wert: {column}"
        )

    # 3. Plausibilität prüfen
    co2_invalid = (
        df["co2_ppm"].notna()
        & ~df["co2_ppm"].between(0, 10000)
    )

    add_error(
        co2_invalid,
        "CO2 ausserhalb des Prüfbereichs"
    )

    temp_invalid = (
        df["temperature_c"].notna()
        & ~df["temperature_c"].between(-20, 60)
    )

    add_error(
        temp_invalid,
        "Temperatur ausserhalb des Prüfbereichs"
    )

    humidity_invalid = (
        df["humidity_pct"].notna()
        & ~df["humidity_pct"].between(0, 100)
    )

    add_error(
        humidity_invalid,
        "Luftfeuchtigkeit ausserhalb des Prüfbereichs"
    )

    # 4. Fehlerhafte Zeilen vorerst markieren
    rejected_mask = df["error_reason"] != ""

    # 5. Doppelte gültige Zeitstempel erkennen
    candidates = df.loc[~rejected_mask]

    duplicate_mask = candidates.duplicated(
        subset=["timestamp"], keep="first"
    )

    duplicate_indices = candidates.index[duplicate_mask]

    add_error(
        df.index.isin(duplicate_indices),
        "Doppelter Zeitstempel"
    )

    # 6. Gültige und fehlerhafte Daten trennen
    rejected_mask = df["error_reason"] != ""

    rejected = df.loc[rejected_mask].copy()
    clean = df.loc[~rejected_mask].copy()

    # 7. Chronologisch sortieren
    clean = clean.sort_values("timestamp")

    # 8. Fehlerhafte Daten separat exportieren
    rejected_file = OUTPUT_DIR / "rejected_measurements.csv"

    rejected.to_csv(
        rejected_file,
        index=False
    )

    # Interne Prüfspalten aus der Analyse entfernen
    clean = clean.drop(
        columns=["source_row", "error_reason"]
    )

    clean = clean.reset_index(drop=True)

    print("\n--- Datenqualitätsbericht ---")
    print(f"Ursprüngliche Zeilen: {original_count}")
    print(f"Gültige Zeilen: {len(clean)}")
    print(f"Ausgeschlossene Zeilen: {len(rejected)}")

    print(
        f"Fehlerhafte Messungen gespeichert: {rejected_file}"
    )

    if len(clean) < 2:
        raise ValueError(
            "Weniger als zwei gültige Messungen vorhanden."
        )

    return clean


# 4. Messwerte analysieren
def analyze_data(df):
    df = df.copy()

    df["minutes_elapsed"] = (
        df["timestamp"] - df["timestamp"].iloc[0]
    ).dt.total_seconds() / 60

    time_difference = (
        df["timestamp"].diff().dt.total_seconds() / 60
    )

    df["co2_rate_ppm_min"] = (
        df["co2_ppm"].diff() / time_difference
    )

    return df


# 5. Statistik anzeigen
def print_statistics(df):
    print("\n--- CO2-Statistik ---")

    print(df["co2_ppm"].describe())

    duration = (
        df["timestamp"].iloc[-1]
        - df["timestamp"].iloc[0]
    ).total_seconds() / 60

    print(f"\nMessdauer: {duration:.1f} Minuten")

    print(
        "Mittlere CO2-Anstiegsrate:",
        f"{df['co2_rate_ppm_min'].mean():.2f} ppm/min",
    )


# 6. Diagramm erstellen
def create_plot(df):
    plt.figure(figsize=(10, 5))

    plt.plot(
        df["timestamp"],
        df["co2_ppm"],
        marker="o",
        label="CO2",
    )

    plt.title("CO2-Verlauf im Schulzimmer")
    plt.xlabel("Zeit")
    plt.ylabel("CO2-Konzentration (ppm)")
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_file = OUTPUT_DIR / "co2_plot.png"

    plt.savefig(output_file, dpi=150)

    print(f"\nDiagramm gespeichert: {output_file}")

    plt.show()


# 7. Hauptprogramm
def main():
    df = load_data(DATA_FILE)

    df = clean_data(df)

    print("\n--- Kontrolle vor dem Diagramm ---")
    print(df[["timestamp", "co2_ppm"]].to_string(index=False))

    df = analyze_data(df)

    print_statistics(df)

    df.to_csv(
        OUTPUT_DIR / "cleaned_measurements.csv",
        index=False,
    )

    create_plot(df)





if __name__ == "__main__":
    main()
