ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}
WORKDIR /app
ARG UV_VERSION=0.12.13
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv==${UV_VERSION}
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --python /usr/local/bin/python
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
EXPOSE 8000
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && .venv/bin/python -m app.seed && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]
