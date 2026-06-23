# Backend Documentation

The backend is built with FastAPI and SQLAlchemy.

## Setup

1. **Navigate to backend folder**:

   ```bash
   cd backend
   ```

2. **Create and activate virtual environment**:

   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Backend

Start the development server with Uvicorn:

```bash
uvicorn app.main:app --reload --port 8094
.\venv\Scripts\python -m uvicorn app.main:app --reload --port 8094

```

The API will be available at `http://127.0.0.1:8094`.
Documentation (Swagger UI) is available at `http://127.0.0.1:8094/docs`.

## Database

The project uses SQLite by default (`bm_radio.db`). Tables are automatically created on startup by `app/main.py`.
