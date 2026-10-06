FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GARMINTOKENS=/data/.garminconnect

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY garmin_sync.py .

# garmin.db, fit/ and the token cache all live in the /data volume.
WORKDIR /data
VOLUME /data

ENTRYPOINT ["python", "/app/garmin_sync.py"]
