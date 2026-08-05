FROM python:3.12-slim

# ─────────────────────────────
# Instalar uv
# ─────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# ─────────────────────────────
# Variables de entorno
# ─────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/gatewayEMS

WORKDIR /gatewayEMS

# ─────────────────────────────
# Seguridad + dependencias mínimas
# ─────────────────────────────
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────
# Copiar config primero (cache 🔥)
# ─────────────────────────────
COPY pyproject.toml uv.lock ./

# Instalar dependencias
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# ─────────────────────────────
# Copiar código
# ─────────────────────────────
COPY . .

# Instalar proyecto (si lo necesitas)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# ─────────────────────────────
# Usuario no root (IMPORTANTE 🔥)
# ─────────────────────────────
RUN useradd -m appuser
USER appuser

# ─────────────────────────────
# Comando
# ─────────────────────────────
CMD ["uv", "run", "-m", "main"]