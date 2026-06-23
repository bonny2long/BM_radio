# Frontend Documentation

The frontend is a React + TypeScript application powered by Vite.

## Setup

1. **Navigate to frontend folder**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

## Running the Frontend

### Development Mode

Start the Vite development server:
```bash
npm run dev
```

The app will be available at `http://localhost:5174` (or the port specified in your console).

### Production Build

To create a production-ready bundle:
```bash
npm run build
```
The output will be in the `dist/` directory.

## Design tokens

Styling is handled via CSS Variables defined in `src/styles/tokens.css`.
- `--bg-main`: App background
- `--accent-primary`: Brand color
- `--radius-m`: Standard border radius
