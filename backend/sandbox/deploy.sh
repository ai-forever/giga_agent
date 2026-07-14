#!/bin/bash

# Ensure script stops on first error
set -e

# Change directory to the script's location
cd "$(dirname "$0")"

VERSION_FILE="VERSION"
IMAGE_NAME="mikelarg/code-interpreter"

# Check if VERSION file exists, if not default to 0.0.0
if [ ! -f "$VERSION_FILE" ]; then
    echo "0.0.0" > "$VERSION_FILE"
fi

# Read current version
CURRENT_VERSION=$(cat "$VERSION_FILE")

# Split version into parts (assumes format X.Y.Z)
IFS='.' read -r -a parts <<< "$CURRENT_VERSION"
MAJOR=${parts[0]}
MINOR=${parts[1]}
PATCH=${parts[2]}

# Increment PATCH version
NEW_PATCH=$((PATCH + 1))
NEW_VERSION="$MAJOR.$MINOR.$NEW_PATCH"

echo "🚀 Bumping version: $CURRENT_VERSION -> $NEW_VERSION"

# Run Docker commands
echo "📦 Building image..."
docker buildx build --platform linux/amd64,linux/arm64 -t "$IMAGE_NAME:$NEW_VERSION" .

echo "pushing image..."
docker image push "$IMAGE_NAME:$NEW_VERSION"

# Update VERSION file
echo "$NEW_VERSION" > "$VERSION_FILE"

echo "✅ Done! New version $NEW_VERSION pushed."
