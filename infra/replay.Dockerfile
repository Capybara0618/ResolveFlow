FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OTEL_SDK_DISABLED=true HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN pip install --no-cache-dir uv==0.9.18
WORKDIR /work/agent
COPY agent/pyproject.toml agent/uv.lock ./
COPY agent/src ./src
COPY contracts/core /work/contracts/core
RUN uv sync --frozen --no-dev
RUN useradd --system --uid 10001 replay
USER replay
ENTRYPOINT ["/work/agent/.venv/bin/python", "-m", "resolveflow.replay.cli", "strict", "/pack"]
