# Receipt OCR

A small FastAPI service that extracts structured information from receipt
images. It authenticates requests with Firebase and uses DeepSeek for image
processing. Images are not stored.

## API

- `POST /extract` — requires `Authorization: Bearer <Firebase ID token>`.
- `GET /health` — basic service health check.

Example request:

```json
{
  "imageBase64": "<base64-encoded image>",
  "mediaType": "image/jpeg"
}
```

The extraction response contains a `summary` field with the result.

## Run locally

Install Tesseract, then install the Python dependencies and start the service:

```bash
sudo apt install tesseract-ocr
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
DEEPSEEK_API_KEY=... FIREBASE_API_KEY=... .venv/bin/uvicorn main:app --reload
```

Run the tests with:

```bash
.venv/bin/pytest
```

## Deploy

The service runs behind Caddy and listens only on localhost. Keep the
environment file outside the project directory and restrict its permissions:

```bash
sudo chmod 600 /etc/receipt-ocr.env
sudo cp receipt-ocr.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now receipt-ocr
```


Validate and reload Caddy after changing its configuration:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Configuration and security

- Set `DEEPSEEK_API_KEY` and `FIREBASE_API_KEY`
- Browser CORS is limited to the production web app origins. CORS is not
  authentication; `/extract` still requires a valid Firebase ID token.
- `/extract` allows 10 requests per authenticated user per minute
