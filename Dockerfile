FROM ghcr.io/astral-sh/uv:python3.13-bookworm

RUN adduser agent
USER agent
WORKDIR /home/agent

COPY --chown=agent:agent pyproject.toml uv.lock README.md ./
COPY --chown=agent:agent src src
COPY --chown=agent:agent rooms rooms
COPY --chown=agent:agent benchmarks benchmarks

RUN \
    --mount=type=cache,target=/home/agent/.cache/uv,uid=1000 \
    uv sync --locked

ENTRYPOINT ["uv", "run", "green-server"]

CMD ["--host", "0.0.0.0", "--port", "9009"]
EXPOSE 9009