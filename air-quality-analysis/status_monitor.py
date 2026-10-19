
import os
import time
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
OFFLINE_AFTER_MINUTES = 1
CHECK_INTERVAL_SECONDS = 60


def check_device_status():
    if not DATABASE_URL:
        print("Fehler: DATABASE_URL fehlt in der .env-Datei.")
        return

    try:
        with psycopg.connect(
            DATABASE_URL,
            connect_timeout=5
        ) as connection:

            with connection.cursor() as cursor:
                # Veraltete Geräte auf offline setzen
                cursor.execute("""
                    UPDATE device_status
                    SET status = 'offline',
                        last_error = 'Keine aktuellen Messdaten',
                        updated_at = NOW()
                    WHERE (
                        last_seen IS NULL
                        OR last_seen < NOW()
                            - (%s * INTERVAL '1 minute')
                    )
                    AND status IS DISTINCT FROM 'offline'
                """, (OFFLINE_AFTER_MINUTES,))

                offline_count = cursor.rowcount

                # Aktuelle Geräte wieder online setzen
                cursor.execute("""
                    UPDATE device_status
                    SET status = 'online',
                        last_error = NULL,
                        updated_at = NOW()
                    WHERE status = 'offline'
                      AND last_seen IS NOT NULL
                      AND last_seen >= NOW()
                          - (%s * INTERVAL '1 minute')
                """, (OFFLINE_AFTER_MINUTES,))

                online_count = cursor.rowcount

                # Aktuellen Status aller aktiven Geräte laden
                cursor.execute("""
                    SELECT
                        d.name,
                        d.device_uid,
                        ds.status,
                        ds.last_seen,
                        ds.last_error
                    FROM devices AS d
                    LEFT JOIN device_status AS ds
                        ON d.id = ds.device_id
                    WHERE d.active = TRUE
                    ORDER BY d.name;
                """)

                devices = cursor.fetchall()

        if offline_count:
            print(f"{offline_count} Gerät(e) auf offline gesetzt.")

        if online_count:
            print(f"{online_count} Gerät(e) auf online gesetzt.")

        # Status immer im Terminal anzeigen
        print("\n--- Gerätestatus ---")

        for name, uid, status, last_seen, last_error in devices:
            print(f"Gerät: {name} ({uid})")
            print(f"Status: {status or 'unbekannt'}")
            print(f"Letzter Kontakt: {last_seen}")
            if last_error:
                print(f"Fehler: {last_error}")
            print()

    except psycopg.Error as error:
        print(f"Datenbankfehler: {error}")


def main():
    print("Gerätestatus-Monitor gestartet.")
    print(
        f"Offline nach {OFFLINE_AFTER_MINUTES} Minuten "
        "ohne aktuelle Messdaten."
    )
    print(f"Prüfintervall: {CHECK_INTERVAL_SECONDS} Sekunden\n")

    while True:
        check_device_status()
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStatusmonitor beendet.")
