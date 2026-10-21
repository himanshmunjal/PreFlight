FROM python:3.12-slim

# iproute2 gives `ss`, which PreFlight's check_listen.sh runs inside these containers.
# tzdata + TZ: log timestamps in IST, matching the alerts that quote them.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "redis==5.0.8" "psycopg[binary]==3.2.3" "pyyaml==6.0.2"

WORKDIR /srv
COPY *.py ./
ENV PYTHONUNBUFFERED=1 TZ=Asia/Kolkata
