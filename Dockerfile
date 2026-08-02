FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    AGENT_FACTORY_DB=/data/agent-factory.db \
    AGENT_FACTORY_WORKSPACE=/workspace

RUN groupadd --system agentfactory \
    && useradd --system --gid agentfactory --create-home agentfactory

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-deps . \
    && mkdir -p /data /workspace \
    && chown -R agentfactory:agentfactory /data /workspace

USER agentfactory

VOLUME ["/data"]
WORKDIR /workspace

ENTRYPOINT ["agent-factory"]
CMD ["demo"]
