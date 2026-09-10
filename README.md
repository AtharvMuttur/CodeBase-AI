# CodeBase AI

CodeBase AI is a repository question-answering assistant. It clones GitHub repositories, indexes source files with embeddings, searches the indexed code with PostgreSQL/pgvector, and answers questions with file and line citations.

The project contains:

- A React + TypeScript frontend for repository management and chat.
- A FastAPI backend for cloning, indexing, retrieval, and answers.
- PostgreSQL 16 with the pgvector extension for repository metadata and vector search.
- Gemini-native or OpenAI-compatible embedding and LLM integrations, plus local fallback modes.
- Email/password authentication with JWT sessions and private repository ownership.

## How It Works

```text
GitHub URL
    |
    v
Validate URL -> discover default branch -> shallow clone
    |
    v
Discover source files -> split into overlapping line chunks
    |
    v
Generate embeddings -> store files, chunks, and vectors in PostgreSQL
    |
    v
Embed question -> retrieve similar chunks -> generate cited answer
```

The default chunker uses windows of approximately 60 lines with a 15-line overlap. Repository cards show cloning and indexing progress, errors, file counts, and chunk counts. Citation panels are collapsed initially and can be opened individually.

## Requirements

- Docker Desktop with Docker Compose v2.
- At least 4 GB of available memory for the containers.
- A GitHub token for private repositories or repositories that require authentication.
- An authentication secret with at least 32 characters for non-development deployments.
- Optional Gemini or OpenAI-compatible API credentials for higher-quality embeddings and generated answers.

The application can run without model credentials. In that mode, embeddings use a deterministic local hash and answers use an extractive fallback. Retrieval works, but semantic quality is limited.

## Quick Start

From the repository root:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

### Linux or macOS

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Open these URLs after the containers start:

- Frontend: http://localhost:5173
- Backend API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

Check health with PowerShell:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

Expected health output includes `"status":"ok"` and `"database":true`.

## Configuration

Copy `.env.example` to `.env` and update the values before starting Docker. Compose passes these variables into the backend and uses `VITE_API_BASE` when building the frontend.

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER` | PostgreSQL username. |
| `POSTGRES_PASSWORD` | PostgreSQL password. Change this outside local development. |
| `POSTGRES_DB` | PostgreSQL database name. |
| `DATABASE_URL` | SQLAlchemy connection URL. Use `db` as the hostname inside Compose. |
| `FRONTEND_URL` | Frontend origin allowed by backend CORS. |
| `VITE_API_BASE` | Public backend URL embedded into the frontend build. |
| `AUTH_SECRET_KEY` | Secret used to sign JWT access tokens. Use a random value in deployment. |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime. Default is 1440 minutes. |
| `GITHUB_TOKEN` | Optional GitHub token for authenticated repository access and higher API limits. |
| `LLM_PROVIDER` | `gemini` for the native Gemini client or another provider using the compatible client. |
| `LLM_API_KEY` | LLM credential. Empty values use the extractive fallback. |
| `LLM_MODEL` | Model name used for answer generation. |
| `LLM_BASE_URL` | Provider base URL. Gemini defaults to its `v1beta` endpoint. |
| `EMBEDDING_PROVIDER` | `gemini` for Gemini-native embeddings; other values use the OpenAI-compatible client. |
| `EMBEDDING_API_KEY` | Embedding credential. Empty values use local deterministic embeddings. |
| `EMBEDDING_MODEL` | Embedding model name. |
| `EMBEDDING_BASE_URL` | Optional embedding provider base URL. |
| `EMBEDDING_DIMENSIONS` | Vector size. The checked-in schema and ORM currently use `768`. |
| `MAX_FILE_SIZE_KB` | Maximum file size considered during indexing. |
| `MAX_FILES_PER_REPO` | Maximum number of discovered files per repository. |
| `MAX_REPO_SIZE_MB` | Configured repository size limit; cloning enforcement is not currently implemented. |
| `LOG_LEVEL` | Backend log level. |

### Embedding dimension warning

The current database schema uses `vector(768)`. Keep this setting at `768` for the supplied Compose/database setup. Changing the embedding model or dimension requires a coordinated schema migration and re-indexing; changing only `.env` is not sufficient.

### API keys

Do not commit `.env` or paste credentials into source control, chat, issue trackers, or logs. If a key has been exposed, revoke it and create a replacement.

## Authentication and Privacy

The application requires an account before repository or query endpoints can be used. The frontend provides registration and sign-in screens. Successful authentication stores a JWT session in the browser and sends it as a Bearer token on API requests.

Each repository created after authentication is assigned to the current user. Repository listing, details, files, deletion, ingestion, and querying are scoped to that owner. The health endpoint remains public.

Authentication endpoints:

```http
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
```

Registration and login bodies use:

```json
{
  "email": "you@example.com",
  "password": "at-least-8-characters"
}
```

For an existing PostgreSQL volume, run the migration once before using authentication:

```powershell
Get-Content backend/scripts/migrate_auth.sql | docker compose exec -T db psql -U codebase -d codebase_ai
```

Existing pre-auth repositories have no owner and are intentionally not visible to authenticated users. Assign them manually to a user or recreate them after signing in. A fresh database receives the users table automatically.

## Using the Application

1. Open the frontend.
2. Expand **Clone from GitHub** if needed.
3. Enter a repository URL such as `https://github.com/owner/repository`.
4. Select **Clone & Index**.
5. Wait for the repository card to reach `ready` or display a failure message.
6. Select the repository and ask a question in the chat composer.
7. Open individual citation headers when you want to inspect retrieved source code.

The frontend currently exposes GitHub ingestion. The backend also retains a local-folder ingestion endpoint for API and development use; it requires a path visible inside the backend container when Docker is used.

## API

Interactive documentation is available at http://localhost:8000/docs.

### Health

```http
GET /api/health
```

### List repositories

```http
GET /api/repositories
```

### Queue a GitHub repository

```powershell
$body = @{ url = "https://github.com/owner/repository" } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/repositories `
  -ContentType "application/json" `
  -Body $body
```

The endpoint returns immediately with a repository id. Poll the detail endpoint to observe progress:

```http
GET /api/repositories/{repository_id}
```

Possible indexing states include `queued`, `cloning`, `scanning`, `chunking`, `embedding`, `ready`, and `failed`.

### Ask a question

```powershell
$body = @{
  question = "How does the indexing pipeline work?"
  repository_id = 1
  top_k = 5
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/api/query `
  -ContentType "application/json" `
  -Body $body
```

The response includes the answer, model name, repository id, and retrieved citations with file paths, line ranges, content, and similarity scores.

### Delete a repository

```http
DELETE /api/repositories/{repository_id}
```

Deletion cascades to the repository's files and code chunks.

## Project Structure

```text
backend/
  app/
    main.py                 FastAPI application factory
    config.py               Environment settings
    database.py             SQLAlchemy engine and sessions
    routers/                HTTP endpoints
    services/               GitHub, indexing, embeddings, retrieval, and LLM logic
    models/                 Repository, file, and chunk ORM models
    schemas/                Request and response schemas
  scripts/init_db.sql       PostgreSQL and pgvector schema
  tests/                    Backend tests

frontend/
  src/
    App.tsx                 Application shell and global state
    components/             Sidebar, chat, modal, toast, and icons
    lib/                    API client, markdown, highlighting, storage, and theme
    styles.css              UI design system and responsive layout

docker-compose.yml          Database, backend, and frontend services
.env.example                Environment variable template
```

## Development Without Docker

### Backend

The backend still requires PostgreSQL with pgvector.

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DATABASE_URL = "postgresql+psycopg://codebase:codebase_dev_password@localhost:5432/codebase_ai"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start only the database with Docker when needed:

```powershell
docker compose up -d db
```

### Frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite development server runs at http://localhost:5173 and proxies `/api` requests to the backend.

## Tests and Validation

Run backend tests from the `backend` directory:

```powershell
Set-Location backend
python -m pytest -v
```

Build the frontend:

```powershell
Set-Location frontend
npm run build
```

The backend test suite covers authentication, URL parsing, ingestion, embeddings, API schemas, health checks, and fallback answers. It does not replace a full PostgreSQL integration test or external-provider test.

## Data and Docker Volumes

PostgreSQL data is stored in the named `codebase_pgdata` volume. Cloned repositories are stored temporarily in the named `codebase_workspace` volume and are removed after indexing completes.

The database initialization script runs only when PostgreSQL creates a new data volume. Existing volumes do not automatically receive schema changes. Back up the database before migrations or volume operations.

To intentionally remove all local database data and start over:

```powershell
docker compose down -v
docker compose up --build -d
```

This permanently deletes indexed repositories and vectors.

## Deployment Notes

For a remote deployment:

1. Copy `.env.example` to `.env` on the server.
2. Set production database credentials, `FRONTEND_URL`, and `VITE_API_BASE`.
3. Configure `GITHUB_TOKEN` and model credentials as required.
4. Remove or replace the Windows-specific `/mnt/codebase-ai` bind mount in `docker-compose.yml`.
5. Run `docker compose up --build -d`.
6. Put HTTPS and authentication in front of the services before exposing them publicly.

The supplied Compose file is suitable for local development and small private deployments. Before public production use, add authentication, rate limiting, persistent background jobs, resource quotas, database backups, and a production process configuration without Uvicorn `--reload`.

## Troubleshooting

### Repository remains in `cloning`

Check backend logs:

```powershell
docker compose logs --tail=200 backend
```

GitHub authentication failures are reported when a repository requires credentials. Set `GITHUB_TOKEN` in `.env` and rebuild the backend:

```powershell
docker compose up --build -d backend
```

Git prompts are disabled so an invalid or missing credential fails the job instead of blocking the worker.

### Repository remains in `embedding`

Look for provider errors such as `429 Too Many Requests`, invalid credentials, or network failures. Gemini requests are limited to four concurrent calls, but provider quota can still be exhausted. The repository card will show the resulting failure message.

### Database reports unhealthy

```powershell
docker compose ps
docker compose logs --tail=100 db
```

Wait for the database health check to pass, then retry `/api/health`.

### Frontend cannot reach the backend

For Docker on the same machine, use `VITE_API_BASE=http://localhost:8000`. For a remote deployment, use the public backend URL and rebuild the frontend because Vite embeds this value at build time.

## License

No license file is currently included in this repository.
