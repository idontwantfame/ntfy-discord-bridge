FROM python:3.11-slim

# Install uv (pinned for reproducible builds).
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

# Unprivileged user that runs the service and the CLI.
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin app

WORKDIR /app

# Install the dependencies first, so this layer stays cached across code changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

# Copy the application into the container.
COPY . /app

# Expose the CLI as `cli` (e.g. `docker exec <container> cli list`).
RUN chmod +x /app/docker/entrypoint.sh /app/docker/cli.sh && \
    ln -sf /app/docker/cli.sh /app/.venv/bin/cli

# Ensure virtualenv binaries are available on PATH for runtime commands. The
# code is read-only for the app user, so don't try to write bytecode caches.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1

# Hands the data directory to the app user and drops root before running CMD.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "main.py"]
