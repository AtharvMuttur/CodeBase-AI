# CodeBase AI

A RAG (Retrieval-Augmented Generation) assistant for understanding codebases. Point it at a local folder, ask natural-language questions, and get answers grounded in the actual source code with citations back to file paths and line ranges.

**Phase 1 — MVP.** Local-folder ingestion, line-window chunking, OpenAI-compatible embeddings and LLM (with a deterministic, dependency-free fallback when no API keys are configured), pgvector semantic search, and a React chat UI.

```
Local Repository
      ↓
File discovery (allow/deny by extension)
      ↓
Line-window chunking (~60 lines, 15-line overlap)
      ↓
Embeddings (OpenAI-compatible remote, or deterministic local hash)
      ↓
PostgreSQL + pgvector
      ↓
Cosine-distance similarity search
      ↓
LLM answer (or extractive fallback) with citations
```

## Architecture

```
┌────────────┐    ┌─────────────┐    ┌────────────┐
│  Frontend  │ →  │   Backend   │ →  │ PostgreSQL │
│  Vite/React│    │   FastAPI   │    │ + pgvector │
│  :5173     │    │   :8000     │    │   :5432    │
└────────────┘    └─────────────┘    └────────────┘
```

| Layer | Tech | Lives in |
|---|---|---|
| Frontend | Vite + React + TypeScript | `frontend/` |
| Backend | FastAPI + SQLAlchemy 2.x + psycopg | `backend/` |
| Database | PostgreSQL 16 + pgvector | `docker-compose.yml` |
| Embeddings | OpenAI-compatible HTTP (`/v1/embeddings`) | `backend/app/services/embeddings.py` |
| LLM | OpenAI-compatible HTTP (`/v1/chat/completions`) | `backend/app/services/llm.py` |
| Retrieval | pgvector `<=>` cosine distance | `backend/app/services/retrieval.py` |
| Chunking | line-window with overlap | `backend/app/services/ingestion.py` |

## Project structure

```
CodeBase AI/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI factory
│   │   ├── config.py            # pydantic-settings
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/              # ORM: Repository, File, CodeChunk
│   │   ├── schemas/             # pydantic request/response models
│   │   ├── routers/             # health, ingest, query, repositories
│   │   ├── services/            # ingestion, embeddings, retrieval, llm, pipeline
│   │   └── core/                # logging
│   ├── scripts/init_db.sql      # pgvector extension + schema
│   ├── tests/                   # pytest
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/          # Sidebar, Chat
│   │   ├── lib/api.ts           # typed API client
│   │   └── styles.css
│   ├── vite.config.ts
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Docker Desktop (or any Docker Engine with Compose v2)
- 4 GB RAM available for the containers
- (Optional) An OpenAI API key, or any OpenAI-compatible endpoint for embeddings + chat

## Quick start

```bash
# 1. Clone and enter the project
cd "D:/Atharv/ML Projects/CodeBase AI"

# 2. Create your .env (API keys are optional — see "Without API keys" below)
cp .env.example .env
cp backend/.env.example backend/.env
# Edit .env and add LLM_API_KEY / EMBEDDING_API_KEY if you have them.

# 3. Build and start all three services
docker compose up --build -d

# 4. Wait for the healthcheck to pass (first boot takes ~5-10 min while images are pulled)
docker compose ps

# 5. Open the UI
# Frontend: http://localhost:5173
# Backend:  http://localhost:8000/docs
# Health:   http://localhost:8000/api/health
```

After the first build, subsequent `docker compose up -d` runs take ~30 seconds because images are cached.

## Configuration

All configuration is environment-driven. The repo ships `.env.example` for both the root and the backend. The backend reads its `.env` automatically when run on the host; in Docker the values are passed through `docker-compose.yml`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://codebase:codebase_dev_password@db:5432/codebase_ai` | SQLAlchemy URL. Use `db` inside Docker, `localhost` on the host. |
| `FRONTEND_URL` | `http://localhost:5173` | CORS allowlist. |
| `LLM_API_KEY` | _(empty)_ | OpenAI-compatible `/v1/chat/completions`. Empty → extractive fallback. |
| `LLM_MODEL` | `gpt-4o-mini` | Used when `LLM_API_KEY` is set. |
| `LLM_BASE_URL` | `https://api.openai.com` | Override for Together / Ollama / vLLM / etc. |
| `EMBEDDING_API_KEY` | _(empty)_ | OpenAI-compatible `/v1/embeddings`. Empty → deterministic local hash. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Used when `EMBEDDING_API_KEY` is set. |
| `EMBEDDING_DIMENSIONS` | `1536` | Must match the `vector(N)` column in `init_db.sql`. |
| `LLM_PROVIDER` / `EMBEDDING_PROVIDER` | `openai` | Provider identifier (provider-agnostic). |
| `LOG_LEVEL` | `INFO` | Root logger level. |
| `MAX_FILE_SIZE_KB` | `512` | Skip files larger than this when indexing. |
| `MAX_FILES_PER_REPO` | `20000` | Hard cap per repository. |

## Without API keys

Phase 1 runs end-to-end **without** any external API keys:

- **Embeddings** fall back to a deterministic hashed backend (vectors are L2-normalized so the rest of the pipeline is exercised; the semantic quality is not comparable to a real model).
- **LLM** falls back to an extractive answer — the top retrieved chunks are returned verbatim with a notice that real generation is disabled.

You can flip on real models by setting `LLM_API_KEY` and `EMBEDDING_API_KEY` in `.env` and restarting `docker compose up -d backend`.

## Verify the stack

```bash
# Backend health (should report database: true)
curl http://localhost:8000/api/health

# List routes
curl -s http://localhost:8000/openapi.json | python -c "import json,sys; r=json.load(sys.stdin); print('\n'.join(p for p in r['paths']))"
```

## Index a repository and ask a question

The fastest path is via the UI at `http://localhost:5173`:

1. Type a name (e.g. `my-project`).
2. Type the absolute path to a local folder. **Inside Docker**, this is a path the backend container can see — `docker-compose.yml` mounts the named volume `codebase_workspace` at `/app/workspace`, so files in there are reachable as `/app/workspace/...`. On the host (no Docker), use a host path.
3. Click **Index**.
4. Switch to the chat panel and ask a question.

The same flow works via curl:

```bash
# Ingest
curl -s -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"name":"my-project","local_path":"/app/workspace/my-project"}'

# Query
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"How does the chunker work?","repository_id":1,"top_k":5}'
```

The query response includes:

```json
{
  "answer": "...",
  "chunks": [
    {
      "chunk_id": 7,
      "file_id": 3,
      "file_path": "src/ingestion.py",
      "language": "py",
      "start_line": 200,
      "end_line": 240,
      "content": "...",
      "score": 0.81
    }
  ],
  "model": "gpt-4o-mini",
  "repository_id": 1
}
```

## API surface (Phase 1)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | API + DB status. |
| `GET` | `/api/repositories` | List indexed repositories. |
| `GET` | `/api/repositories/{id}` | Single repository. |
| `GET` | `/api/repositories/{id}/files` | Files in a repository. |
| `POST` | `/api/ingest` | Index a local folder. Body: `{name, local_path}`. |
| `POST` | `/api/query` | Ask a question. Body: `{question, repository_id?, top_k?}`. |

Full schema at `http://localhost:8000/docs` (Swagger UI).

## Running the backend on the host (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# PostgreSQL with pgvector must be running somewhere reachable.
# The fastest path is `docker compose up -d db` and then point at `localhost`.
DATABASE_URL=postgresql+psycopg://codebase:codebase_dev_password@localhost:5432/codebase_ai \
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Running the frontend on the host (without Docker)

```bash
cd frontend
npm install
npm run dev    # http://localhost:5173 — proxies /api to VITE_API_BASE (default http://localhost:8000)
```

## Tests

```bash
cd backend
python -m pytest -v
```

24 tests cover: health endpoint, OpenAPI schema, chunking, file discovery, embedding determinism, the extractive fallback, and request validation.

## Verified end-to-end

The Phase 1 verification was performed against the running Docker stack:

| Check | Result |
|---|---|
| `GET /api/health` | `{"status":"ok","database":true,"version":"0.1.0"}` |
| `POST /api/ingest` (sample calculator) | `repository_id=1, file_count=2, chunk_count=2, 0.11s` |
| `POST /api/ingest` (backend self) | `repository_id=2, file_count=32, chunk_count=65, 0.43s` |
| pgvector: `SELECT COUNT(*), COUNT(embedding) FROM code_chunks` | `67  /  67` (every chunk has a 1536-d embedding) |
| `POST /api/query` | Returns ranked chunks + answer (extractive fallback when `LLM_API_KEY` unset) |
| `GET /api/repositories` | Lists both indexed repositories |
| `GET /api/repositories/{id}/files` | Lists files per repository |
| Frontend | `http://localhost:5173` returns the React shell |

## Phase 1 scope

**In scope (delivered):**

- React + Vite + TypeScript frontend with chat UI and ingest form
- FastAPI backend with health, ingest, query, and repository endpoints
- PostgreSQL + pgvector (vector(1536) column)
- Docker / Docker Compose for one-command stack bring-up
- File discovery (extension allowlist + size + excluded dirs)
- Line-window chunking with overlap
- OpenAI-compatible embedding + LLM clients with httpx + tenacity retries
- Deterministic fallback for both embeddings and LLM (no API key required)
- Cosine-distance semantic search via pgvector
- Per-chunk citations (file path, line range, language, score)
- CORS, structured JSON logging, Pydantic validation, error handling
- 24 passing pytest tests
- README with run / verify / configure instructions

**Out of scope (later phases):**

- GitHub ingestion (Phase 2)
- Tree-sitter AST chunking (Phase 3)
- Reranking (Cohere / cross-encoder) (Phase 3)
- Conversation history, multi-hop questions, eval harness (Phase 4)
- Auth, rate limiting, multi-tenant (Phase 5)

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose up` fails with "Cannot connect to Docker daemon" | Start Docker Desktop. |
| Backend health reports `"database":false` | The DB container isn't ready yet; wait ~10s and re-check. |
| `npm install` fails with MSYS path errors on Windows | Set `MSYS_NO_PATHCONV=1` before the command. |
| `curl` returns exit code 23 on Windows | Same — `MSYS_NO_PATHCONV=1 curl …`. |
| Ingest returns 0 files | Check path is reachable from the backend container. Inside Docker, prefer `/app/workspace/...`. |
| Want to use a real OpenAI key | Set `LLM_API_KEY` and `EMBEDDING_API_KEY` in `.env`, then `docker compose up -d backend`. |
| Switching embedding model changes dimension | Update `EMBEDDING_DIMENSIONS` in `.env` and `vector(N)` in `backend/scripts/init_db.sql`, then recreate the database volume. |
