# Bupa ShiftGuard

ShiftGuard is a local web application with a React/Vite frontend, a Django REST backend, and an optional FastAPI AI service.
The backend connects to the team's hosted Supabase PostgreSQL database; you do not need to install PostgreSQL locally.

## Prerequisites

Install these before starting:

- **Git** to clone the repository.
- **Python 3.12 or newer** and `pip` for the backend (and optional AI service). Make sure Python is available on your `PATH`.
- **Node.js 20 or newer**, which includes `npm`, for the frontend.
- **Internet access** to download dependencies and connect to the team's Supabase project.
- **The Supabase database password** for the team's project. Obtain it from the project owner; do not commit it or share it in source control.

The optional AI service also requires a **Google Gemini API key**. It uses the same Supabase database, so its connection details are needed if you enable it.

The launchers use these local ports: frontend `5173`, backend `8000`, and optional AI service `8001`. Make sure they are available.

Check your installations:

```text
git --version
python --version       # Windows
python3 --version      # macOS/Linux
node --version
npm --version
```

## Setup on Windows

1. Clone the repository and open PowerShell in its root folder:

   ```powershell
   git clone https://github.com/supratik23/bupa-powerpioneer-2026.git
   cd bupa-powerpioneer-2026
   ```

2. Create the backend environment file and add the Supabase database password:

   ```powershell
   Copy-Item PowerPioneer-Backend-Core\.env.example PowerPioneer-Backend-Core\.env
   notepad PowerPioneer-Backend-Core\.env
   ```

   Set `SUPABASE_DB_PASSWORD` to the password provided by the project owner, save, and close the file.

3. Start the project:

   ```powershell
   .\start-all.bat
   ```

   On the first run, the launcher creates a Python virtual environment, installs backend and frontend dependencies, applies database migrations, and attempts to seed demo data. It opens the frontend in your browser. Keep the server windows open while using the app; close them to stop the services.

## Setup on macOS and Linux

1. Clone the repository and open a terminal in its root folder:

   ```bash
   git clone https://github.com/supratik23/bupa-powerpioneer-2026.git
   cd bupa-powerpioneer-2026
   ```

2. Create the backend environment file and add the Supabase database password:

   ```bash
   cp PowerPioneer-Backend-Core/.env.example PowerPioneer-Backend-Core/.env
   ```

   Edit `PowerPioneer-Backend-Core/.env` in your preferred text editor. Set `SUPABASE_DB_PASSWORD` to the password provided by the project owner, then save the file.

3. Start the project:

   ```bash
   ./start-all.sh
   ```

   If the script is not executable, run `chmod +x start-all.sh` once and then run it again. On the first run, the launcher creates a Python virtual environment, installs backend and frontend dependencies, applies database migrations, and attempts to seed demo data. Keep the terminal open while using the app; press **Ctrl+C** to stop the services.

## Optional AI service

The frontend and backend can run without the AI service. The launchers skip it unless `PowerPioneer-AI/langgraph-agent/.env` exists. To enable it, create that file with your Gemini API key and the Supabase connection details supplied by the project owner:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
SUPABASE_DB_HOST=your-supabase-session-pooler-host
SUPABASE_DB_PORT=5432
SUPABASE_DB_USER=your-supabase-database-user
SUPABASE_DB_PASSWORD=your-supabase-database-password
```

Keep the real values private. The launcher installs the AI dependencies and starts the service on port `8001` when this configuration is present. The Gemini key is required for the AI service to start; the Supabase settings are required for its database-backed tools.

## Open the app

- Frontend: <http://localhost:5173>
- Backend API documentation: <http://127.0.0.1:8000/api/docs/>
- AI API documentation, when enabled: <http://127.0.0.1:8001/docs>

The frontend uses the local backend URLs by default, so no frontend environment file is needed for a standard local setup. Demo accounts are only available if demo seeding succeeds; see [PowerPioneer-Backend-Core/README.md](./PowerPioneer-Backend-Core/README.md) for the account details and backend-specific instructions.