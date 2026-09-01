FROM mikelarg/aegra:0.0.11

# Bring in the standalone `uv` binary for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

USER root

# ffmpeg is required by pydub to export podcast audio to mp3.
# kaleido requires a system Chrome/Chromium binary for image export.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    chromium \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

ENV BROWSER_PATH=/usr/bin/chromium
ENV GIGA_AGENT_SKIP_UI_BUNDLE_CHECK=1

WORKDIR /backend

# Copy only packaging metadata first for better layer caching
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/hatch_build.py ./hatch_build.py
COPY backend/hatch_metadata.py ./hatch_metadata.py
COPY README.md ./README.md
COPY README.md /README.md

# Copy the actual backend package (includes `giga_agent/ui_dist`)
COPY backend/giga_agent/ ./giga_agent/
# The UI is served by the separate nginx frontend container, so the bundle is not
# packaged here. Drop any synced `ui_dist` and leave an empty dir: a non-empty
# `ui_dist` would be force-included by hatch_build.py *and* picked up by the normal
# package walk (no `.git` in the build context disables the gitignore filter),
# making hatchling fail with "A second file is being added to the wheel archive".
RUN rm -rf ./giga_agent/ui_dist/ && mkdir -p ./giga_agent/ui_dist/

# Install the package (and dependencies from pyproject.toml)
RUN uv pip install --system --no-cache .

USER root
