FROM python:3.11-slim

WORKDIR /app

# The Invisible Passes uses standard library modules with zero runtime package dependencies
COPY src/ /app/src/
COPY data/ /app/data/
COPY web/ /app/web/
COPY scripts/ /app/scripts/
COPY pyproject.toml /app/

ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED="1"

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).getcode() == 200 else 1)"

CMD ["python", "scripts/run_app.py", "--host", "0.0.0.0", "--port", "8765"]
