FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tmux \
        asciinema \
        cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /tmp/requirements.lock
RUN python3 -m pip install --no-cache-dir --no-deps \
        -r /tmp/requirements.lock

WORKDIR /app

COPY app/ /app/
RUN cp /app/workflow/index_rebuild.py /app/workflow/.index_rebuild.original \
    && chmod a-w /app/workflow/.index_rebuild.original

# Host state left behind by the failed rollout. The deployment runbook defines the
# correct end state; the discrepancies are for recovery to discover and reconcile.
RUN printf '#!/bin/sh\nexec python3 /app/workflow/index_rebuild.py.legacy "$@"\n' > /usr/local/bin/index-rebuild \
    && chmod 0644 /usr/local/bin/index-rebuild \
    && mkdir -p /var/lock \
    && printf '4711\n' > /var/lock/index-rebuild.lock \
    && rm -f /etc/cron.d/index-rebuild \
    && mkdir -p /app/output \
    && chmod 0777 /app/output

# Further host state from the same rollout; recovery reconciles it against the runbook.
RUN mkdir -p /var/log/index-rebuild \
    && chmod 0777 /var/log/index-rebuild \
    && printf 'rollout 4711 aborted mid-compile\n' > /var/log/index-rebuild/compile.log.0 \
    && printf '' > /var/log/index-rebuild/compile.log \
    && rm -f /etc/logrotate.d/index-rebuild
