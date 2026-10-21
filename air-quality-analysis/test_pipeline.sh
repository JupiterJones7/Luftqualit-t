

#!/usr/bin/env bash
set -Eeuo pipefail

cd /project/air-quality-analysis/air-quality-analysis

# Konfiguration laden, ohne Geheimnisse auszugeben
set -a
source .env
set +a

: "${INGEST_API_KEY:?INGEST_API_KEY fehlt in .env}"
: "${DATABASE_URL:?DATABASE_URL fehlt in .env}"
export MESSAGE_ID
export MEASURED_AT
URL="https://jupiterserver.taildefdec.ts.net/api/v1/measurements"
MESSAGE_ID="pipeline-test-$(date -u +%Y%m%dT%H%M%SZ)-$$"
MEASURED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "1/3: Sende simulierte SEN69C-Messdaten ..."

HTTP_CODE=$(curl -sS --connect-timeout 10 \
  --output /tmp/pipeline-test-response.json \
  --write-out '%{http_code}' \
  --resolve jupiterserver.taildefdec.ts.net:443:185.40.234.37 \
  -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${INGEST_API_KEY}" \
  -d "$(python -c '
import json, os
print(json.dumps({
 "device_uid":"SIM-SEN69C-001",
 "sensor_model":"SEN69C",
 "measured_at":os.environ["MEASURED_AT"],
 "message_id":os.environ["MESSAGE_ID"],
 "measurements":{
  "pm1_mass":4.2, "pm25_mass":7.8, "pm4_mass":9.1,
  "pm10_mass":10.5, "pm05_number":1200.0,
  "pm1_number":1500.0, "pm25_number":1800.0,
  "pm4_number":2000.0, "pm10_number":2200.0,
  "co2":650.0, "formaldehyde":0.015,
  "temperature":22.5, "humidity":45.0,
  "voc_index":100.0, "nox_index":2.0
 }
}))
')" )

export MESSAGE_ID MEASURED_AT

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FEHLER: HTTP $HTTP_CODE"
  cat /tmp/pipeline-test-response.json
  exit 1
fi

cat /tmp/pipeline-test-response.json
echo
echo "2/3: Prüfe die Speicherung in PostgreSQL ..."

python - <<'PY'
import os
import sys
import time
import psycopg
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(".env").resolve())

message_id = os.environ["MESSAGE_ID"]
expected_time = datetime.fromisoformat(
    os.environ["MEASURED_AT"].replace("Z", "+00:00")
)

# Kurz warten, falls die Übertragung noch läuft.
for attempt in range(10):
    try:
        with psycopg.connect(
            os.environ["DATABASE_URL"], connect_timeout=5
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM measurements
                    WHERE source_message_id LIKE %s
                      AND measured_at = %s
                """, (message_id + ":%", expected_time))
                count = cur.fetchone()[0]
        if count == 15:
            break
    except Exception as exc:
        print("Datenbankprüfung fehlgeschlagen:", type(exc).__name__)
        sys.exit(1)
    time.sleep(1)

if count != 15:
    print(f"FEHLER: {count}/15 Messwerte gefunden.")
    print("Prüfe die Receiver-Logs und die lokale Queue.")
    sys.exit(1)

print(f"OK: {count}/15 Messwerte in PostgreSQL gefunden.")
PY

echo "3/3: Prüfe die lokale Warteschlange ..."

python - <<'PY'
import sqlite3
from pathlib import Path

db = Path("data/collector_queue.sqlite3")
with sqlite3.connect(db) as conn:
    count = conn.execute(
        "SELECT COUNT(*) FROM pending_measurements"
    ).fetchone()[0]

print(f"Lokale Queue: {count} wartende Messungen.")
if count != 0:
    print("HINWEIS: Es sind noch Messungen in der Queue.")
    raise SystemExit(1)
PY

echo "ERFOLG: End-to-End-Test bestanden."
