FROM mikelarg/aegra:0.0.9

USER root

# scikit-learn wheels require libgomp at runtime.
# ffmpeg is required by pydub to export podcast audio to mp3.
# kaleido requires a system Chrome/Chromium binary for image export.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ffmpeg \
    libgomp1 \
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
RUN mkdir -p ./giga_agent/ui_dist/

# Install the package (and dependencies from pyproject.toml)
RUN pip install --no-cache-dir .

USER root
