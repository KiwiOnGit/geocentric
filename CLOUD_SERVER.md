# Geocentric Cloud Server

The deployable cloud control plane lives outside this upstream repo at:

`~/Geocentric Cloud Server/server_backend`

This upstream project remains the local/open source base. The cloud server is a separate downstream project for global deployment and should stay closed source if it will hold production controls, user accounts, session records, agent tokens, or deployment secrets.

## What It Does

- Serves the lightweight web UI entrypoint.
- Handles user registration and login.
- Stores usernames, names, and emails encrypted at rest.
- Stores password hashes with Argon2id, never plaintext passwords.
- Stores session and agent tokens as hashes only.
- Provides an agent registry and heartbeat endpoint for local agents.
- Provides admin controls for registration, allowed origins, rate limits, audit logs, and agent revocation.

## Run

```bash
cd "$HOME/Geocentric Cloud Server/server_backend"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

For production, set `GEOCENTRIC_CLOUD_ENV=production`, exact CORS origins, HTTPS-only cookies, a long random secret key, and a Fernet field-encryption key before boot.
