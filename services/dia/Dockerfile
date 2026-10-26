FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/dia/requirements.txt /tmp/requirements.txt
# CPU wheels first, then Dia without letting it replace them with a CUDA build.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchaudio \
    && pip install --no-cache-dir -r /tmp/requirements.txt descript-audio-codec \
    && pip install --no-cache-dir --no-deps "git+https://github.com/nari-labs/dia.git"

COPY services/dia/server.py /app/server.py

ENV HF_HOME=/models \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DIA_MODEL=nari-labs/Dia-1.6B-0626

EXPOSE 8871
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8871"]
