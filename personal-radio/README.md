# BM Radio

Private premium radio, music player, and audiobook bookshelf built from NAS media library.

## Project Structure

- `backend/`: FastAPI + SQLAlchemy backend (port 8094).
- `frontend/`: React + Vite + TypeScript frontend (port 5174).
- `docs/`: Product blueprint, technical runbook, handoff notes, and source-of-truth docs.

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm or yarn

## Getting Started

1. **Environment** - Copy `.env.example` to `.env` in the project root and adjust your media paths.

2. **Backend**:
   ```bash
   cd backend
   python -m venv venv
   .\venv\Scripts\activate   # Windows
   # source venv/bin/activate  # macOS/Linux
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8094
   ```
   API available at `http://127.0.0.1:8094` (Swagger UI at `/docs`).

3. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   App available at `http://localhost:5174`.

4. Open `http://localhost:5174` and start listening.

## Docs

| File | Purpose |
|---|---|
| `docs/blueprint.md` | Product definition, design direction, V1/V2 feature map |
| `docs/runbook.md` | Architecture, API routes, scanner/playback behavior, safety rules |
| `docs/source-of-truth.md` | How BM Radio fits into the full NAS system |
| `docs/handoff.md` | Current status, what works, remaining issues, next priorities |
