from datetime import datetime, timezone


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    print(f"{timestamp} {message}", flush=True)
