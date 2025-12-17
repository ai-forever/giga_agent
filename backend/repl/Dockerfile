FROM python:3.11

USER root

ENV PYTHONUNBUFFERED 1

COPY pyproject.toml /
COPY uv.lock /

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
RUN apt-get install -y nodejs
RUN npm install -g npm@latest

ENV PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  POETRY_VERSION=1.2.2

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is available to all users
RUN mv /root/.local/bin/uv /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

RUN uv sync --locked

COPY ./app/ /app/

COPY ./__init__.py /

RUN mkdir -p /mnt/

RUN useradd -ms /bin/bash jupyter \
    && chgrp -R jupyter /mnt/ \
    && chgrp -R jupyter /home/jupyter/ \
    && chmod -R 777 /mnt/ \
    && chmod -R 777 /home/jupyter/

# Give the jupyter user ownership of the virtual environment and uv cache
ENV UV_CACHE_DIR=/var/cache/uv
RUN mkdir -p /var/cache/uv \
    && chown -R jupyter:jupyter /var/cache/uv \
    && chown -R jupyter:jupyter /.venv
