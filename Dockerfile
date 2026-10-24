# Multi-stage production container image for GeMBridge workers & API
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Set non-interactive debian frontend & UTF-8 encoding
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS="ignore::FutureWarning" \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install essential libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies
RUN playwright install chromium

# Copy full application code
COPY . .

# Default execution
CMD ["celery", "-A", "tasks.celery_app", "worker", "-c", "2", "--loglevel=INFO"]
