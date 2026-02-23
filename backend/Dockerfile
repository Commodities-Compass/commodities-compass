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

# Copy poetry files
COPY pyproject.toml poetry.lock ./

# Install dependencies (without creating virtualenv)
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root

# Pre-install Playwright Chromium (used by barchart scraper cron)
RUN python -m playwright install chromium --with-deps

# Copy application code
COPY . .

# Ensure start script is executable
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 8000

# Run migrations and start server
CMD ["/app/start.sh"]
