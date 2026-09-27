FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.10.8
WORKDIR /app
COPY agent /app/agent
RUN uv sync --project /app/agent --frozen --no-dev
ENV PATH="/app/agent/.venv/bin:${PATH}"
CMD ["uvicorn", "resolveflow.api.app:app", "--host", "0.0.0.0", "--port", "8082"]
