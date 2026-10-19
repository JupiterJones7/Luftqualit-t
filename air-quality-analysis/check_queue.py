
import sqlite3
from pathlib import Path

queue_file = (
    Path(__file__).resolve().parent
    / "data"
    / "collector_queue.sqlite3"
)

with sqlite3.connect(queue_file) as connection:
    count = connection.execute(
        "SELECT COUNT(*) FROM pending_measurements"
    ).fetchone()[0]

print(f"Ausstehende Messzyklen: {count}")
