# receipt-ocr

FastAPI service that reads a cold-store receipt photo with the DeepSeek vision
API and returns the structured JSON the Flutter app parses. Images are not
stored.

## Contract

```
POST /extract
Authorization: Bearer <Firebase ID token>
{ "imageBase64": "...", "mediaType": "image/jpeg" }

200 { "summary": "<JSON string>" }
401 missing or invalid session
413 image larger than 9 MB
415 media type not JPEG/PNG/GIF/WebP
422 image is invalid or not confirmed as a cold-store receipt
503 local receipt precheck unavailable
502 DeepSeek request failed
```

`GET /health` returns `{"ok": true, "version": "1.1"}`.
Before contacting DeepSeek, `/extract` runs local Tesseract OCR. The image passes
if OCR finds any one of “GOOD RECEIPT VOUCHER”, “GOOD DELIVERY VOUCHER”, “cold
storage” or “cold store” (case/punctuation-insensitive, allowing up to two
character edits).

## Environment

| Variable | Required | Notes |
|---|---|---|
| `DEEPSEEK_API_KEY` | yes | server-only, never shipped to the browser |
| `FIREBASE_API_KEY` | yes | the public web key from the app's `firebase_options.dart` |
| `DEEPSEEK_MODEL` | no | defaults to `deepseek-flash` |

## Run locally

Install Tesseract first (Ubuntu: `sudo apt install tesseract-ocr`), then:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
DEEPSEEK_API_KEY=... FIREBASE_API_KEY=... .venv/bin/uvicorn main:app --reload
.venv/bin/pytest
```

For a manual check, run `python3 -m http.server 8080` in another terminal and
open <http://127.0.0.1:8080/dev-test.html>. Enter a Firebase ID token and choose
a receipt photo (the local `whi.jpg` or `yel.jpg` samples are handy). Confirmed
receipts continue to DeepSeek and use the configured API key.

## Deploy on the Oracle VM

1. Clone to `/home/ubuntu/receipt-ocr`, create the venv and install
   `requirements.txt`. Install Tesseract as well:
   ```bash
   sudo apt install tesseract-ocr
   ```
2. Write `/etc/receipt-ocr.env` with the two keys, then `sudo chmod 600` it.
3. Install the unit:
   ```bash
   sudo cp receipt-ocr.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now receipt-ocr
   ```
   Change `User`/`WorkingDirectory` if the VM image uses `opc` instead of
   `ubuntu`.
4. Add an `A` record `ocr` pointing at the VM's public IP.
5. Add to the Caddyfile and reload Caddy:
   ```
   ocr.daanveersingh.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
6. Check `curl https://ocr.daanveersingh.com/health`.

The service listens on `127.0.0.1:8000` only; Caddy is the public listener and
handles TLS.

## Security

- The DeepSeek key lives only in `/etc/receipt-ocr.env` (and local `.env` files).
- Every `/extract` call needs a Firebase ID token, checked against Google's
  Identity Toolkit. A leaked endpoint URL is not enough to use the API.
- Use a dedicated DeepSeek key with a small balance and rotate it if the VM is
  compromised.
