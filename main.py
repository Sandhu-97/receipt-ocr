"""Receipt extraction for the cold store app, over the DeepSeek vision API."""

import base64
import binascii
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from debug_log import log
from receipt_precheck import is_receipt_image

BASE_URL = "https://api.deepseek.com"
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
SUPPORTED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_BASE64_CHARS = 12_000_000  # ~9 MB of image
LOOKUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"

SYSTEM_PROMPT = "You summarise images. Describe only what is visible; do not invent details."

DEFAULT_PROMPT = """
Please extract the specific information from this cold storage receipt image.

Important Note 1 (Main Variety Matching): The only valid main varieties are: Pukhraj/Kufri Pukhraj, Jyoti/Kufri Jyoti, Cardinal, Diamant, 7008, Chandramukhi/KCM, Badshah, Himalini, Karoda, Super6. Compare the handwritten text on the "Variety" line against this list. If it matches one of these (or a clear phonetic/handwriting variation of it), use that name. If it does not match any of them, classify the Main Variety as "Others".

Important Note 2 (Sub-Varieties): In the main table, the columns labeled Ration, Seed Size(use Seed), 12 No.(use Seed12), Goli, and Cut are the sub-variety names. You must map the numerical quantity written in the row below each of these specific headers to its corresponding sub-variety. If a sub-variety column is blank or has a dash, skip it.

Important Note 3 (Address/Truck Field Matching): The "Tractor/Truck No." line often contains a location/address rather than a vehicle number. The majority of these addresses will be one of the following: Tahli Sahib, Sarai Khas, Khusropur, Fateh Jalal, Bakhu Nangal, Kartarpur, Basrampur, Ali khela, Momanpur. Please carefully read the handwriting and match it to the closest item on this list. If it clearly does not match any, extract it exactly as written.

Please extract the following details and return the final output STRICTLY in valid JSON format. Do not include any markdown formatting (like ```json), conversational text, or extra explanations outside of the JSON object.

Use this exact JSON structure:

{
"receipt_number": "Extract the red number near the top",
"date": "Extract the date near the top right",
"farmer_name": "Extract text from the 'Received From' line (DROP S/O)",
"address": "Extract and apply matching rules from Note 3",
"quantities": [
"Format exactly as: variety||subvariety: quantity (e.g., 'Badshah||Seed12: 610'). Include only sub-varieties that have a quantity."
]
}
"""

app = FastAPI(
    title="Cold store receipt extractor",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    # The Firebase ID token is the guard; CORS is not a security boundary here.
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    imageBase64: str
    mediaType: str


async def require_user(authorization: str | None = Header(default=None)) -> str:
    """Reject callers without a valid Firebase session."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")

    token = authorization.removeprefix("Bearer ")
    # Firebase ID tokens are JWTs; reject junk before spending a Google lookup.
    if token.count(".") != 2:
        raise HTTPException(401, "Invalid session")

    api_key = os.environ.get("FIREBASE_API_KEY", "")
    if not api_key:
        raise HTTPException(500, "FIREBASE_API_KEY is not set")

    async with httpx.AsyncClient(timeout=10) as client:
        lookup = await client.post(
            LOOKUP_URL,
            params={"key": api_key},
            json={"idToken": token},
        )

    try:
        users = lookup.json().get("users") if lookup.status_code == 200 else None
    except ValueError:
        users = None
    if not users:
        raise HTTPException(401, "Invalid session")
    return users[0]["localId"]


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "version": "1.1"}


@app.post("/extract")
def extract(payload: ExtractRequest, _uid: str = Depends(require_user)) -> dict[str, str]:
    media_type = payload.mediaType.lower()
    log(
        f"[extract] received image: media_type={media_type}, "
        f"base64_chars={len(payload.imageBase64)}"
    )
    if media_type not in SUPPORTED_TYPES:
        raise HTTPException(415, "Use a JPEG, PNG, GIF or WebP photo")
    if len(payload.imageBase64) > MAX_BASE64_CHARS:
        raise HTTPException(413, "Image is larger than 9 MB")

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(500, "DEEPSEEK_API_KEY is not set")

    try:
        image = base64.b64decode(payload.imageBase64, validate=True)
    except (binascii.Error, ValueError) as exc:
        log("[extract] invalid base64 image data")
        raise HTTPException(422, "Invalid image data") from exc
    if not is_receipt_image(image):
        log("[extract] rejected by receipt precheck")
        raise HTTPException(422, "Image is not a confirmed cold-store receipt")

    data_url = f"data:{media_type};base64,{payload.imageBase64}"
    log("[extract] receipt confirmed; sending to DeepSeek")
    try:
        response = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=90).chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DEFAULT_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
    except OpenAIError as exc:
        log(f"[extract] DeepSeek request failed: {type(exc).__name__}")
        raise HTTPException(502, f"DeepSeek request failed: {exc}") from exc

    log("[extract] DeepSeek response received")
    return {"summary": response.choices[0].message.content or ""}
