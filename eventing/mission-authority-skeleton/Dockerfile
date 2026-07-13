FROM python:3.11-slim

WORKDIR /app

# README.md is copied alongside pyproject.toml because pyproject.toml references
# it (readme = "README.md") and hatchling validates its existence during install.
# Copy application code first so all source is present before pip resolves deps.
COPY pyproject.toml README.md ./
COPY mission_authority ./mission_authority

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

CMD ["uvicorn", "mission_authority.main:app", "--host", "0.0.0.0", "--port", "8000"]
