FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite+aiosqlite:////app/data/ormodel.db

WORKDIR /app

RUN pip install --no-cache-dir uv==0.9.0

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY ormodel ./ormodel
COPY examples ./examples

RUN uv pip install --system --no-cache -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "examples.api:app", "--host", "0.0.0.0", "--port", "8000"]
