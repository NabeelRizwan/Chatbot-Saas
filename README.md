# Chatbot SaaS

A multi-tenant chatbot platform with a Next.js dashboard, FastAPI API, PostgreSQL/pgvector knowledge retrieval, and an embeddable website widget.

## What is included

- Bot creation, organization management, authentication, subscriptions, and analytics
- Document upload and URL crawling for grounded responses
- Streaming public chat API and a self-contained widget at `frontend/public/widget.js`
- Gemini, OpenAI, Claude, and Grok provider support (per-bot or platform-managed keys)
- PostgreSQL with the pgvector extension for semantic retrieval

## Architecture

| Service | Location | Default local URL |
| --- | --- | --- |
| Dashboard and widget asset | `frontend` | `http://localhost:3000` |
| API | `backend` | `http://localhost:8000` |
| PostgreSQL / pgvector | Docker service | `localhost:5432` |

The widget is served by the frontend application at `/widget.js`. It connects to the API URL provided in its embed snippet; it is not served by the backend.

## Local development

Prerequisites: Node.js 18+, Python 3.11+, PostgreSQL with pgvector (or Docker), and at least one supported model-provider API key.

1. Create the local environment files:

   ```bash
   copy backend\\.env.example backend\\.env
   copy frontend\\.env.example frontend\\.env
   ```

   On macOS/Linux, use `cp` instead of `copy`.

2. Set `DATABASE_URL`, `JWT_SECRET`, and the provider key(s) in `backend/.env`.

3. Install and run the API:

   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn main:app --reload --port 8000
   ```

4. In another terminal, install and run the dashboard:

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

Open `http://localhost:3000`. API documentation is available at `http://localhost:8000/docs`.

### Docker development stack

```bash
docker compose up --build
```

The compose file is intended for local development. Do not use its default database password for an internet-facing deployment.

## Production deployment

Build the frontend with its public URLs; `NEXT_PUBLIC_*` values are embedded at build time.

```bash
docker build -t chatbot-api ./backend
docker build -t chatbot-web \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  --build-arg NEXT_PUBLIC_APP_URL=https://app.example.com \
  ./frontend
```

Set these backend environment variables in your hosting provider:

```text
APP_ENV=production
DATABASE_URL=postgresql://...
JWT_SECRET=<long-random-secret>
PLATFORM_KEY_ENCRYPTION_KEY=<persistent-fernet-key>
GEMINI_API_KEY=<if used>
CORS_ALLOWED_ORIGINS=*
```

`APP_ENV=production` refuses to start if `JWT_SECRET` is missing or still set to the insecure development default. Keep `PLATFORM_KEY_ENCRYPTION_KEY` unchanged once platform-managed keys have been saved; changing it makes previously encrypted keys unreadable.

For widgets embedded on arbitrary customer sites, `CORS_ALLOWED_ORIGINS=*` is appropriate because the widget uses token/header-based requests rather than browser cookies. If widgets are only installed on known sites, use a comma-separated allowlist instead.

## Widget installation

Use the embed snippet generated in the dashboard. Its shape is:

```html
<script
  src="https://app.example.com/widget.js"
  data-api-base-url="https://api.example.com"
  data-bot-id="YOUR_BOT_ID"
></script>
```

The widget uses the public API endpoints:

- `GET /public/widget/{bot_id}` for configuration
- `POST /public/chat/{bot_id}` for non-streaming responses
- `POST /public/chat/{bot_id}/stream` for streaming responses

## Verification

Before release, run:

```bash
cd frontend
npm run lint
npm run typecheck
npm run build

cd ../backend
python -m py_compile main.py services/rag_service.py
```

Then verify `/health`, open the dashboard, and send a message through an installed widget using a bot that has a configured provider key and completed knowledge source.

## Secrets

Never commit `backend/.env` or `frontend/.env`. If a key is ever pasted into a terminal, chat, issue, or log, revoke and replace it in the relevant provider console.
