# AgentForge Backend_Image — optimized, multi-stage, non-root build (Req 1.1-1.6).
#
# The application is NOT modified; only the build is optimized. Dependencies are
# installed into a virtualenv in a builder stage BEFORE the source is copied, so a
# source-only change reuses the cached dependency layer (Req 1.2). The slim runtime
# stage carries only the populated venv + application (src/ + migrations/) — no build
# toolchain, no pip caches, and no dev/test dependency groups (Req 1.4) — and runs as
# an unprivileged user (Req 1.3).

# ---------------------------------------------------------------------------
# Stage 1: builder — populate a virtualenv with pinned runtime dependencies,
# then install the application itself.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Self-contained virtualenv that the runtime stage copies verbatim.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 1) Dependency layer: copy only the manifest (+ the build-time constraints),
#    derive the pinned runtime requirements from it, and install them. This layer
#    is cached and only rebuilds when these inputs change — a source-only change
#    reuses it.
#
#    `torch` is installed as an ordinary transitive dependency (pulled by
#    sentence-transformers==3.3.1) from PyPI (files.pythonhosted.org) during the single
#    `pip install -r requirements.txt -c constraints.txt` below. We deliberately do NOT
#    use the PyTorch CPU wheel index (`--index-url https://download.pytorch.org/whl/cpu`):
#    its wheel downloads redirect to the R2 CDN (download-r2.pytorch.org), which is not
#    reliably reachable from the CI runner and fails the TLS handshake
#    (SSLV3_ALERT_HANDSHAKE_FAILURE). Resolving torch from PyPI is reliable; the trade-off
#    is a larger image (the PyPI Linux build bundles CUDA/NVIDIA wheels), which is why the
#    CI build/publish jobs free runner disk before building (see .github/workflows).
#
#    One build-only measure keeps the resolve deterministic WITHOUT touching pyproject's
#    [project].dependencies (behavior is identical): resolve under a build-time constraints
#    file (constraints.txt) that bounds the heavy transitive `transformers` dependency to a
#    compatible RANGE. This stops pip from backtracking through dozens of `transformers`
#    releases — deterministic and fast — while staying portable across runners (no exact
#    pin that might not exist on the real upstream index). `--retries`/`--timeout` add
#    resilience against transient network hiccups on the runner.
COPY pyproject.toml README.md constraints.txt ./
RUN python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); open('requirements.txt','w').write(chr(10).join(d['project']['dependencies']) + chr(10))" \
    && pip install --upgrade pip \
    && pip install --retries 5 --timeout 120 -r requirements.txt -c constraints.txt

# 2) Application layer: copy the frequently-changing source and install the
#    project itself WITHOUT re-resolving dependencies. An editable install keeps
#    the src/ layout so the migration runner resolves <repo>/migrations exactly as
#    in development (agentforge/db/migrations.py -> parents[3] == /app), and no
#    dev/test optional-dependency group is installed.
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-deps -e .

# ---------------------------------------------------------------------------
# Stage 2: runtime — slim image with only the venv + application, non-root.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

# Unprivileged runtime user (Req 1.3).
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# Copy the populated virtualenv and the application. The editable .pth inside the
# venv points at /app/src, which we place at the same path here.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/migrations ./migrations

RUN chown -R appuser:appgroup /app /opt/venv

USER appuser

EXPOSE 8000

# API_Service listens on the documented port (overridable via API_PORT env, Req 1.6).
CMD ["sh", "-c", "uvicorn agentforge.main:app --host 0.0.0.0 --port ${API_PORT:-8000}"]
