FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tmux \
        asciinema \
    && rm -rf /var/lib/apt/lists/*

# Fully resolved verifier lock; --no-deps keeps installation deterministic.
COPY requirements.lock /tmp/requirements.lock
RUN python3 -m pip install --no-cache-dir --no-deps \
        -r /tmp/requirements.lock

WORKDIR /app

COPY app/ /app/

# Unprivileged identity the verifier uses to run the candidate-controlled learner.
# It cannot read the root-only /tests tree, so a program that tries to copy the
# expected outputs via os.open/os.read is denied at the OS level.
RUN useradd --system --create-home --shell /usr/sbin/nologin tree-candidate
