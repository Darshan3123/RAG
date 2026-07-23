# Mineru_Document_To_Markdown

A pip-installable, locally-runnable repackaging of [MinerU](https://github.com/opendatalab/MinerU) — a high-accuracy document parsing engine that converts PDFs, images, PPTX, and XLSX files into clean Markdown and JSON.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/gist/ThriveX2025/1b43f02a1e2420b30e7a50c02911b8a4/mineru_pdf_to_markdown.ipynb)

---

> ## Credits & Attribution
>
> This package is a repackaged distribution of the original **MinerU** project by [OpenDataLab](https://github.com/opendatalab).
> All core logic, models, algorithms, and VLM inference code belong entirely to the original authors.
>
> | Original Project Reference Links | |
> |---|---|
> | Original repository | [github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU) |
> | Original license | [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) |
> | Paper (MinerU) | [arXiv:2409.18839](https://arxiv.org/abs/2409.18839) |
> | Paper (MinerU 2.5) | [arXiv:2509.22186](https://arxiv.org/abs/2509.22186) |
> | Paper (MinerU 2.5 Pro) | [arXiv:2604.04771](https://arxiv.org/abs/2604.04771) |

---

## Why This Package?

The original `mineru` package is distributed on PyPI. This repackaged version (`Mineru_Document_To_Markdown`) exists to:

- Enable `pip install -e .` from a local directory for custom development and modifications.
- Support running the VLM engine with vLLM in GPU-constrained environments with fine-tuned environment variables.
- Run parsing pipelines entirely in-process without requiring background HTTP servers.
- Expose a simple, synchronous/asynchronous Python programmatic API.

---

## Installation

### 1. Prerequisites (CUDA & PyTorch Setup)

Install `uv` (if not already installed) and set up the PyTorch, vLLM, and FastAPI dependencies:

```bash
# Install uv
pip install uv

# Install PyTorch with CUDA 13.0 support
uv pip install torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130 -U

# Install vLLM with CUDA 13.0 support
uv pip install vllm==0.21.0 --torch-backend=cu130

# Install FastAPI with version constraints
uv pip install "fastapi<0.137.0"
```

### 2. Install Packages

Since the repositories are private, ensure you are authenticated (e.g. via `gh auth login` and `gh auth setup-git`). The git credential helper will automatically authenticate the installation.

#### Option A: Direct Installation from GitHub

```bash
# Install the utility package
uv pip install "git+https://github.com/ThriveX2025/Mineru_Utils.git"

# Install this package with all extras
uv pip install "Mineru_Document_To_Markdown[all] @ git+https://github.com/ThriveX2025/Mineru_Document_To_Markdown.git"
```

#### Option B: Editable Install (from local clone directory)

```bash
# Install the utility package
uv pip install "git+https://github.com/ThriveX2025/Mineru_Utils.git"

# Install this package in editable mode from this directory
uv pip install -e ".[all]"
```

> **Note:** The `[all]` extra pulls in the required transformers, vllm, and other components.
> The `-e` flag installs the package in editable mode so local code changes take effect immediately.

---

## CLI Entrypoints

After installation the following commands are available in your shell:

| Command | Description |
|---|---|
| `Mineru_Document_To_Markdown` | Main document conversion CLI (runs in-process) |
| `Mineru_Document_To_Markdown-models-download` | Download VLM models |
| `Mineru_Document_To_Markdown-vllm-server` | vLLM-compatible inference server |
| `Mineru_Document_To_Markdown-openai-server` | OpenAI-compatible inference server |

---

## Usage Modes & Examples

### 1. Command Line Interface (CLI)

Run the parser directly on any document:

```bash
Mineru_Document_To_Markdown \
  --path "/content/TEST-PDFS/GEM_2026_B_7628575.pdf" \
  --output ./output \
  --backend vlm-engine \
  --batch-size 2 \
  --max-gpu-util 0.8
```

### 2. Programmatic Python API

Import and run the document converter inside your own Python scripts or notebook cells.

To avoid event loop conflicts and resource leaks (especially in environments like Google Colab or Jupyter Notebooks), it is recommended to run the parsing sequence in a single async context using the following helper pattern.

#### A. Single Document Processing

Use the following snippet to process a single PDF/image/document:

```python
import asyncio
from Mineru_Document_To_Markdown import (
    async_convert_document,
    set_vlm_config,
    async_start_vllm_server,
    close_vllm_server
)

async def main():
    # 1. Configure VLM batch size & GPU memory utilization globally
    set_vlm_config(batch_size=16, max_gpu_util=0.5)

    # 2. Pre-warm and start the standalone vLLM server engine
    print("Starting vLLM server...")
    await async_start_vllm_server()

    # 3. Run the document conversion (reuses the running engine)
    print("Converting document...")
    result = await async_convert_document(
        input_path="/content/TEST-PDFS/GEM_2026_B_7628575.pdf",
        output_dir="./output",
        backend="vlm-engine",
        formula_enable=True,
        table_enable=True,
        image_analysis=True
    )
    print(f"Total inference time: {result['total_inference_time']:.2f} seconds")

    # 4. Explicitly shut down the server and free GPU resources
    print("Closing vLLM server...")
    close_vllm_server()


# Helper function to run the async sequence safely in both Jupyter/Colab and terminal scripts
def run_sequence(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # In Google Colab / Jupyter
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # In a Standalone Script (.py file)
        return asyncio.run(coro)

if __name__ == "__main__":
    run_sequence(main())
```

#### B. Folder Processing (Multiple Documents)

Use one of the two options below to process an entire folder containing multiple PDFs. Both options utilize the same pre-warmed standalone server and execute safely on the same event loop.

##### Option 1: Native Folder Processing (Pass directory directly)

The parser automatically scans the folder and processes all supported files sequentially:

```python
import asyncio
from Mineru_Document_To_Markdown import (
    async_convert_document,
    set_vlm_config,
    async_start_vllm_server,
    close_vllm_server
)

async def main():
    # 1. Configure VLM batch size & GPU memory utilization globally
    set_vlm_config(batch_size=16, max_gpu_util=0.5)

    # 2. Pre-warm and start the standalone vLLM server engine
    print("Starting vLLM server...")
    await async_start_vllm_server()

    # 3. Run the document conversion on the whole folder
    print("Converting all documents in the folder...")
    result = await async_convert_document(
        input_path="/content/TEST-PDFS/",  # Path to the directory containing PDFs
        output_dir="./output_folder",
        backend="vlm-engine",
        formula_enable=True,
        table_enable=True,
        image_analysis=True
    )
    print(f"Total inference time for folder: {result['total_inference_time']:.2f} seconds")

    # 4. Explicitly shut down the server and free GPU resources
    print("Closing vLLM server...")
    close_vllm_server()


# Helper function to run the async sequence safely in both Jupyter/Colab and terminal scripts
def run_sequence(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # In Google Colab / Jupyter
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # In a Standalone Script (.py file)
        return asyncio.run(coro)

if __name__ == "__main__":
    run_sequence(main())
```

##### Option 2: Custom Loop in Python (Ideal for individual progress tracking / error resilience)

Iterates over files in the folder individually so you can handle errors or log results per-document:

```python
import asyncio
from pathlib import Path
from Mineru_Document_To_Markdown import (
    async_convert_document,
    set_vlm_config,
    async_start_vllm_server,
    close_vllm_server
)

async def main():
    # 1. Configure VLM batch size & GPU memory utilization globally
    set_vlm_config(batch_size=16, max_gpu_util=0.5)

    # 2. Pre-warm and start the standalone vLLM server engine
    print("Starting vLLM server...")
    await async_start_vllm_server()

    # 3. Iterate and process each PDF individually
    pdf_folder = Path("/content/TEST-PDFS")
    for pdf_file in sorted(pdf_folder.glob("*.pdf")):
        print(f"\n--- Processing {pdf_file.name} ---")
        try:
            result = await async_convert_document(
                input_path=pdf_file,
                output_dir="./output_folder",
                backend="vlm-engine",
                formula_enable=True,
                table_enable=True,
                image_analysis=True
            )
            print(f"Completed {pdf_file.name} in {result['total_inference_time']:.2f} seconds")
        except Exception as e:
            print(f"Error processing {pdf_file.name}: {e}")

    # 4. Explicitly shut down the server and free GPU resources
    print("Closing vLLM server...")
    close_vllm_server()


# Helper function to run the async sequence safely in both Jupyter/Colab and terminal scripts
def run_sequence(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # In Google Colab / Jupyter
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # In a Standalone Script (.py file)
        return asyncio.run(coro)

if __name__ == "__main__":
    run_sequence(main())
```

---

## Configurable Options & Parameters

### CLI & Programmatic Arguments

All options can be specified both as CLI flags (e.g. `--formula True`) or passed as Python parameters to `convert_document` or `async_convert_document`.

| CLI Option | Python Argument | Type | Default | Description |
|---|---|---|---|---|
| `--path` | `input_path` | `str` / `Path` | *Required* | Local filepath or directory. Supports PDF, image, PPTX, XLSX files. |
| `--output` | `output_dir` | `str` / `Path` | *Required* | Output local directory. |
| `--backend` | `backend` | `str` | `"vlm-engine"` | VLM backend Choice: `vlm-engine` (local model), `vlm-http-client` (remote model). |
| `--url` | `server_url` | `str` | `None` | Endpoint for remote VLM model inference when backend is `vlm-http-client` (e.g. `http://127.0.0.1:30000`). |
| `--start` | `start_page_id` | `int` | `0` | The starting page for PDF parsing, beginning from `0`. |
| `--end` | `end_page_id` | `int` | `None` | The ending page for PDF parsing (inclusive, starting from `0`). |
| `--formula` | `formula_enable` | `bool` | `True` | Enable LaTeX formula parsing. |
| `--table` | `table_enable` | `bool` | `True` | Enable table structure layout and HTML extraction. |
| `--image-analysis` | `image_analysis` | `bool` | `True` | Enable image and chart layout analysis using the VLM. |
| `--client-side-output-generation` | `client_side_output_generation` | `bool` | `False` | Generate markdown and content lists locally from server-returned middle json, images, and original files. |
| `--batch-size` | `batch_size` | `int` | `None` | VLM inference batch size (overrides `MINERU_BATCH_SIZE` environment variable). |
| `--max-gpu-util` | `max_gpu_util` | `float` | `None` | VLM maximum GPU memory utilization fraction (overrides `MINERU_GPU_UTIL` environment variable). |
| `--model-len` | `model_len` | `int` | `None` | VLM maximum model length (overrides `MINERU_MODEL_LEN` environment variable). |
| `--enforce-eager` | `enforce_eager` | `bool` | `None` | VLM enforce eager execution (overrides `MINERU_ENFORCE_EAGER` environment variable). |
| `--model-name` | `model_name` | `str` | `None` | VLM model name or path (overrides `MINERU_MODEL_NAME` environment variable). |
| `--disable-chunked-prefill` | `disable_chunked_prefill` | `bool` | `None` | VLM disable chunked prefill (overrides `MINERU_DISABLE_CHUNKED_PREFILL` environment variable). |

### Global Programmatic Configuration

To configure resource utilization globally before running the converter:

```python
from Mineru_Document_To_Markdown import set_vlm_config

set_vlm_config(
    batch_size=1,       # Sets MINERU_BATCH_SIZE env variable
    max_gpu_util=0.45,  # Sets MINERU_GPU_UTIL env variable
    model_len=4096,     # Sets MINERU_MODEL_LEN env variable
    enforce_eager=False, # Keep CUDA graphs for speed
    model_name="opendatalab/MinerU2.5-Pro-2605-1.2B",
    disable_chunked_prefill=True
)
```

### Environment Variables

| Variable | Description | Example |
|---|---|---|
| `MINERU_GPU_UTIL` | Fraction of GPU memory to allocate to vLLM | `0.5` |
| `MINERU_BATCH_SIZE` | Inference batch size for VLM model processing | `1`, `2`, `4` |
| `MINERU_MODEL_LEN` | Maximum model length for VLM processing | `4096`, `8192` |
| `MINERU_ENFORCE_EAGER` | Disable CUDA graph profiling (saves additional VRAM) | `1` |
| `MINERU_MODEL_NAME` | Model path or identifier | `opendatalab/MinerU2.5...` |
| `MINERU_DISABLE_CHUNKED_PREFILL` | Disable chunked prefill for vLLM | `1` |
| `MINERU_LOG_LEVEL` | Log level for output output | `INFO`, `DEBUG`, `WARNING` |

---

## Core Capabilities (from MinerU)

- **Supported formats:** PDF, images (JPG/PNG), PPTX, XLSX
- **Outputs:** Structured Markdown and JSON
- **OCR:** 109-language support via VLM + OCR dual engine
- **Layout:** Multi-column, scanned docs, handwriting, cross-page table merging
- **Formulas:** LaTeX output · **Tables:** HTML output
- **Inference backends:** `vlm-engine` (vLLM-based, GPU)

---

## Project Structure

```
Mineru_Document_To_Markdown/
├── Mineru_Document_To_Markdown/   # Source package (renamed from mineru)
│   ├── backend/                   # VLM and OCR inference backends
│   ├── cli/
│   │   ├── client.py              # CLI client (Mineru_Document_To_Markdown entrypoint)
│   │   ├── vlm_server.py          # vLLM / OpenAI-compatible server
│   │   └── models_download.py     # Model downloader (Mineru_Document_To_Markdown-models-download)
│   ├── data/                      # Data readers/writers (local)
│   ├── model/                     # Model wrappers
│   ├── utils/                     # Shared utilities
│   └── version.py
├── pyproject.toml                 # Package metadata (name: Mineru_Document_To_Markdown)
├── RUN_COMMANDS.txt               # Quick-reference commands
└── README.md                      # This file
```

---

## License

The core source code is licensed under the [MinerU Open Source License](./LICENSE.md).
Please review the license carefully before any commercial use — it has restrictions.

---

## Original Project Links

| Resource | Link |
|---|---|
| GitHub | [opendatalab/MinerU](https://github.com/opendatalab/MinerU) |
| Web App | [mineru.net](https://mineru.net/) |
| Documentation | [opendatalab.github.io/MinerU](https://opendatalab.github.io/MinerU/) |
| HuggingFace Demo | [spaces/opendatalab/MinerU](https://huggingface.co/spaces/opendatalab/MinerU) |
| PyPI (original) | [pypi.org/project/mineru](https://pypi.org/project/mineru/) |
| Paper (MinerU) | [arXiv:2409.18839](https://arxiv.org/abs/2409.18839) |
| Paper (MinerU 2.5) | [arXiv:2509.22186](https://arxiv.org/abs/2509.22186) |
| Paper (MinerU 2.5 Pro) | [arXiv:2604.04771](https://arxiv.org/abs/2604.04771) |
