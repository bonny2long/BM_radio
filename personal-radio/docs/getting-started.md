# Getting Started with BM Radio

BM Radio consists of a FastAPI backend and a React (Vite) frontend.

## Prerequisites

- Python 3.11+
- Node.js 18+
- npm or yarn

## Quick Setup

1. **Clone/Navigate to the project root**:
   ```bash
   cd personal-radio
   ```

2. **Environment Variables**:
   Copy `.env.example` to `.env` and adjust your media paths:
   ```bash
   cp .env.example .env
   ```

3. **Backend Setup**:
   Refer to [Backend Documentation](backend.md) for detailed steps.

4. **Frontend Setup**:
   Refer to [Frontend Documentation](frontend.md) for detailed steps.

## Running the App

For development, you will typically run two processes in separate terminals:
1. The Backend (Uvicorn)
2. The Frontend (Vite Dev Server)
