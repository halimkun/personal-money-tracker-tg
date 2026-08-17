# MoneyBot — aplikasi (bukan package: [tool.uv] package=false), jadi
# `uv sync` hanya menginstall dependencies dari uv.lock.
# Base glibc (bukan alpine) supaya wheel asyncpg/cryptography pasti tersedia.
FROM ghcr.io/astral-sh/uv:0.11-python3.12-trixie-slim

WORKDIR /app

# Bytecode di-compile sekali di layer; link mode copy agar .venv tetap
# valid meski path di layer berbeda.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# 1) Dependencies dulu — layer ini di-cache selama pyproject.toml & uv.lock tidak berubah
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 2) Baru kode aplikasi + migrasi + entrypoint
COPY main.py alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Jangan jalan sebagai root
RUN useradd --create-home --uid 1000 appuser
USER appuser

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "main.py"]
