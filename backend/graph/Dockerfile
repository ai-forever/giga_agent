FROM mikelarg/aegra:0.0.7

USER root

RUN apt-get update && apt-get install -y ffmpeg libavcodec-extra

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -
RUN apt-get install -y nodejs
RUN npm install -g npm@latest

WORKDIR /

COPY ./pyproject.toml /pyproject.toml
COPY ./uv.lock /uv.lock
COPY ./README.md /README.md

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is available to all users
RUN mv /root/.local/bin/uv /usr/local/bin/uv
ENV PATH="/usr/local/bin:$PATH"

RUN uv venv --system-site-packages

RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY ./giga_agent ./giga_agent
COPY ./langgraph.json ./aegra.json