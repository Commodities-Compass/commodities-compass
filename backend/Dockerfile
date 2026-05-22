FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Set work directory
WORKDIR /app

# Copy poetry files + vendored R&D packages (referenced by pyproject as
# path-deps, must exist on disk before `poetry install` resolves them).
COPY pyproject.toml poetry.lock ./
COPY vendor/ ./vendor/

# Install dependencies (without creating virtualenv)
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root

# Copy application code
COPY . .

# Ensure start script is executable
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 8000

# Run migrations and start server
CMD ["/app/start.sh"]
