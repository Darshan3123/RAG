#!/bin/bash

TARGET_DIR="llama-cpp-binary"
URL="https://github.com/Kishan200308/llama.cpp-cuda/releases/download/b10015/llama.cpp-b10015-cuda-12.6.tar.gz"
TAR_FILE="temp_llama.tar.gz"

# Step 1: Check if the folder exists, download and extract if it doesn't
if [ ! -d "$TARGET_DIR" ]; then
    echo "Folder '$TARGET_DIR' not found. Downloading..."
    
    # Download the archive (following GitHub redirects)
    curl -L -o "$TAR_FILE" "$URL"
    
    echo "Extracting contents..."
    mkdir -p "$TARGET_DIR"
    
    # Extract into the target directory. 
    # --strip-components=1 removes the root folder (e.g., cuda-12.6/) 
    # so only its contents go into llama-cpp-binary/
    tar -xzf "$TAR_FILE" -C "$TARGET_DIR" --strip-components=1
    
    # Clean up the tar file
    rm "$TAR_FILE"
    
    echo "Download and extraction complete."
else
    echo "Folder '$TARGET_DIR' already exists. Skipping download."
fi

# Step 2: Navigate to the folder and launch the server
echo "Launching llama-server..."
cd "$TARGET_DIR" || exit

./llama-server \
  -hf unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M \
  -c 9216 \
  --threads -1 \
  --n-gpu-layers 999 \
  --jinja \
  --flash-attn auto\
  --port 8080
