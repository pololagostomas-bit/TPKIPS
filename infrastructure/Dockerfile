FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    TRITON_DB_PATH=/home/data/triton.db \
    TRITON_BACKUP_DIR=/home/backups

RUN groupadd --system --gid 10001 triton \
    && useradd --system --uid 10001 --gid triton --home-dir /app --no-create-home triton \
    && mkdir -p /home/data /home/backups \
    && chown -R triton:triton /app /home/data /home/backups

COPY --chown=triton:triton requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY --chown=triton:triton backend/ ./backend/
COPY --chown=triton:triton frontend/ ./frontend/

EXPOSE 8000
VOLUME ["/home/data", "/home/backups"]

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import json,os,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health',timeout=4); d=json.load(r); assert r.status==200 and d.get('status')=='ok'"]

CMD ["python", "-m", "backend.wsgi"]
