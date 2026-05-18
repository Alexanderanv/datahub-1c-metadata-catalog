FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY datahub/pyproject.toml datahub/README.md /app/datahub/
COPY datahub/src /app/datahub/src
COPY datahub/scripts /app/datahub/scripts
COPY examples/recipes /app/examples/recipes

RUN pip install "/app/datahub[postgres]"

ENTRYPOINT ["python", "/app/datahub/scripts/reference_ingest.py"]
