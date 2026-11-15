import re
import subprocess

from fastapi import HTTPException

from debug_log import log

RECEIPT_MARKERS = (
    "good receipt voucher",
    "good delivery voucher",
    "cold storage",
    "cold store",
)
OCR_TIMEOUT_SECONDS = 10
MAX_MARKER_EDITS = 2


def _normalize_ocr_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _best_marker_distance(text: str, marker: str) -> int:
    text = _normalize_ocr_text(text)
    marker = _normalize_ocr_text(marker)
    previous = list(range(len(marker) + 1))
    best = len(marker)
    for char in text:
        current = [0] * (len(marker) + 1)
        for i, expected in enumerate(marker, 1):
            current[i] = min(
                previous[i] + 1,
                current[i - 1] + 1,
                previous[i - 1] + (char != expected),
            )
        previous = current
        best = min(best, current[-1])
    return best


def is_receipt_image(image: bytes) -> bool:
    """Run local OCR and accept any one recognized receipt marker."""
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout"],
            input=image,
            capture_output=True,
            timeout=OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"[receipt-precheck] Tesseract unavailable: {exc}")
        raise HTTPException(503, "Receipt precheck unavailable") from exc

    if result.returncode:
        log(f"[receipt-precheck] Tesseract exited with code {result.returncode}")
        return False

    text = result.stdout.decode("utf-8", errors="replace")
    confirmed = False
    for marker in RECEIPT_MARKERS:
        distance = _best_marker_distance(text, marker)
        marker_length = len(_normalize_ocr_text(marker))
        score = 1 - distance / marker_length
        threshold = 1 - MAX_MARKER_EDITS / marker_length
        matched = distance <= MAX_MARKER_EDITS
        log(
            f"[receipt-precheck] marker={marker!r} score={max(0, score):.0%} "
            f"threshold={threshold:.0%} edits={distance} matched={matched}"
        )
        confirmed = confirmed or matched
    log(f"[receipt-precheck] {'confirmed' if confirmed else 'not confirmed'}")
    return confirmed
