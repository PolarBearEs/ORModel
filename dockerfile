FROM python:3.13-slim AS python-base

ENV PROJECT_ROOT=/app \
    VIRTUAL_ENV=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite+aiosqlite:////app/data/ormodel.db
ENV PATH="$VIRTUAL_ENV/bin:$PATH" \
    PYTHONPATH=$PROJECT_ROOT

WORKDIR $PROJECT_ROOT

FROM python-base AS builder

RUN pip install --no-cache-dir uv==0.9.0
RUN uv venv $VIRTUAL_ENV

COPY pyproject.toml ./
RUN uv pip install -r pyproject.toml --no-cache --extra dev

FROM python-base AS final

COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

CMD ["bash"]
