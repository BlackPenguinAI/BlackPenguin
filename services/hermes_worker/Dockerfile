# Isolated Nous Research Hermes SDK runtime, NOT the public BlackPenguin API.
# Build context: repository root.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/blackpenguin
COPY backend/requirements.txt /tmp/bp-requirements.txt
RUN pip install --no-cache-dir -r /tmp/bp-requirements.txt
# Do not add the Nous SDK to the API container. Keep the vetted pinned revision.
RUN pip install --no-cache-dir 'hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb'
COPY backend/app /opt/blackpenguin/app
COPY services/hermes_worker/run_staged_simulation.py /opt/hermes-worker/run_staged_simulation.py
COPY services/hermes_worker/sdk_smoke.py /opt/hermes-worker/sdk_smoke.py

RUN useradd --system --create-home --uid 10001 hermes && mkdir -p /var/lib/hermes-agent \
    && chown -R hermes:hermes /var/lib/hermes-agent /opt/blackpenguin /opt/hermes-worker
USER hermes
ENV PYTHONPATH=/opt/blackpenguin \
    HERMES_HOME=/var/lib/hermes-agent \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=staging
# Not exposed to the network. No production queue/worker dispatch.
ENTRYPOINT ["python", "/opt/hermes-worker/run_staged_simulation.py"]
