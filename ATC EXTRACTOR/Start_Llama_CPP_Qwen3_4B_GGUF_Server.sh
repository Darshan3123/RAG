#!/bin/bash

TARGET_DIR="llama-cpp-binary"
TAR_FILE="temp_llama.tar.gz"
REPO="Kishan200308/llama.cpp-cuda"

# Ensure jq and curl are available
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is required to parse GitHub API responses. Please install it (e.g., sudo apt install jq)."
    exit 1
fi

# Step 1: Check for nvcc and detect CUDA version
if ! command -v nvcc &> /dev/null; then
    echo "Error: 'nvcc' not found. Please ensure the CUDA Toolkit is installed and added to your PATH."
    exit 1
fi

CUDA_VERSION=$(nvcc --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p')

if [ -z "$CUDA_VERSION" ]; then
    echo "Error: Could not extract CUDA version from 'nvcc --version'."
    exit 1
fi

echo "Detected CUDA version: $CUDA_VERSION"

# Step 2: Search across releases for an asset matching the detected CUDA version
if [ ! -d "$TARGET_DIR" ]; then
    echo "Searching releases for CUDA $CUDA_VERSION binary..."

    # Fetch release assets list from GitHub API
    RELEASES_JSON=$(curl -s "https://api.github.com/repos/${REPO}/releases")

    # Find the browser download URL of the first (latest) matching asset
    URL=$(echo "$RELEASES_JSON" | jq -r --arg cuda "$CUDA_VERSION" '
      [.[] | .assets[]? | select(.name | contains("cuda-" + $cuda))] | .[0].browser_download_url // empty
    ')

    if [ -z "$URL" ]; then
        echo "--------------------------------------------------------"
        echo "Error: No release found containing a binary for CUDA $CUDA_VERSION."
        echo "--------------------------------------------------------"
        exit 1
    fi

    echo "Found matching download URL: $URL"
    echo "Downloading binary..."

    if ! curl -f -L -o "$TAR_FILE" "$URL"; then
        echo "Error: Failed to download $URL"
        rm -f "$TAR_FILE"
        exit 1
    fi

    echo "Extracting contents..."
    mkdir -p "$TARGET_DIR"
    tar -xzf "$TAR_FILE" -C "$TARGET_DIR" --strip-components=1
    rm "$TAR_FILE"

    echo "Download and extraction complete."
else
    echo "Folder '$TARGET_DIR' already exists. Skipping download."
fi

# Step 3: Navigate to the folder and launch the server
echo "Launching llama-server..."
cd "$TARGET_DIR" || exit

./llama-server \
  -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M \
  -c 9216 \
  --threads -1 \
  --n-gpu-layers 999 \
  --jinja \
  --flash-attn auto \
  --port 8080
