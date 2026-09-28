FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY quiz_server ./quiz_server
COPY client ./client
RUN useradd --create-home app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "quiz_server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--ws-ping-interval", "20", "--ws-ping-timeout", "20", "--timeout-graceful-shutdown", "10"]
