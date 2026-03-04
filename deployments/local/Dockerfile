FROM mikelarg/aegra:0.0.8

USER root

# scikit-learn wheels require libgomp at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /backend

# Copy only packaging metadata first for better layer caching
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/hatch_build.py ./hatch_build.py
COPY backend/README.md ./README.md

# Copy the actual backend package (includes `giga_agent/ui_dist`)
COPY backend/giga_agent/ ./giga_agent/

# Install the package (and dependencies from pyproject.toml)
RUN pip install --no-cache-dir .

USER root
