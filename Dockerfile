FROM python:3.11-slim

# Install uv (pinned for reproducible builds).
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /app

# Install the dependencies first, so this layer stays cached across code changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-cache --no-dev --no-install-project

# Copy the application into the container.
COPY . /app

# Make cli.py executable and create a symlink in venv bin for easy access
RUN chmod +x /app/cli.py && \
    ln -sf /app/cli.py /app/.venv/bin/cli

# Ensure virtualenv binaries are available on PATH for runtime commands
ENV PATH="/app/.venv/bin:${PATH}"

# Run the application.
CMD ["python", "main.py"]
