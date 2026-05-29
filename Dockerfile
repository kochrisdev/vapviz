# ── Stage 1: Build the React UI ───────────────────────────────────────────────
FROM node:20-alpine AS ui-builder

WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
RUN npm run build          # output → /app/ui/dist


# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim

# System deps (SQLite is bundled with Python — no extra install needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python package
COPY pyproject.toml ./
COPY vap/ ./vap/
RUN pip install --no-cache-dir -e .

# Copy built UI from stage 1
COPY --from=ui-builder /app/ui/dist ./ui/dist

# Data directory for SQLite persistence (mount a volume here)
RUN mkdir -p /data

EXPOSE 8001

# Default: persist to /data/vap.db and serve the built UI.
# Override CMD or set env vars at runtime to customise.
CMD ["vap", "serve", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--db", "/data/vap.db", \
     "--static-dir", "ui/dist", \
     "--log-level", "info"]
