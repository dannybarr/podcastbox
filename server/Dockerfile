FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/pyproject.toml /app/pyproject.toml
COPY server/inbox_brief /app/inbox_brief
RUN pip install --no-cache-dir .

COPY fixtures /app/fixtures
COPY demo /app/demo

ENV INBOX_BRIEF_DATA_DIR=/data \
    INBOX_BRIEF_FIXTURES_DIR=/app/fixtures \
    INBOX_BRIEF_DEMO_DIR=/app/demo \
    INBOX_BRIEF_OLLAMA_URL=http://ollama:11434 \
    INBOX_BRIEF_DIA_URL=http://dia:8871 \
    INBOX_BRIEF_SPEACHES_URL=http://speaches:8000

VOLUME /data
EXPOSE 8742
CMD ["uvicorn", "inbox_brief.main:app", "--host", "0.0.0.0", "--port", "8742"]
