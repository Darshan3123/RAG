#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "========================================"
echo "1. Installing system dependencies..."
echo "========================================"
sudo apt-get update

# Download the deb file (always redownload and overwrite if it exists)
wget -O pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb https://github.com/pdf2htmlEX/pdf2htmlEX/releases/download/v0.18.8.rc1/pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb

# Install ninja-build, ghostscript, and the downloaded deb
sudo apt-get install -y ninja-build ghostscript ./pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb

# Clean up the downloaded deb file after successful installation
echo "Cleaning up downloaded .deb file..."
rm -f pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-bionic-x86_64.deb

echo "========================================"
echo "2. Creating/Resetting Virtual Environment..."
echo "========================================"
ENV_DIR="$HOME/VLLM_Env"

# Check if the environment already exists and delete it if it does
if [ -d "$ENV_DIR" ]; then
    echo "Found existing environment at $ENV_DIR. Removing it to start fresh..."
    rm -rf "$ENV_DIR"
fi

# Create the new environment using python 3.12
uv venv -p 3.12 --seed "$ENV_DIR"

echo "========================================"
echo "3. Installing Base Python Packages..."
echo "========================================"
# Using --python to install into the env without activating it
uv pip install --python "$ENV_DIR" uv "packaging>=24.2" "setuptools>=77.0.0"

echo "========================================"
echo "4. Installing Requirements for PyTorch/CUDA 130..."
echo "========================================"
# Using --python to install into the env without activating it
uv pip install --python "$ENV_DIR" -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cu130 \
    --index-strategy unsafe-best-match \
    --no-build-isolation

echo "========================================"
echo "Setup Complete! Fresh environment is ready at $ENV_DIR"
echo "========================================"
