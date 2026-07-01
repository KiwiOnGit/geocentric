# Geocentric 2.5 - Local LLM Lab and Agent Desktop

Geocentric 2.5 is a full-stack local AI platform for building, training, serving, and interacting with language models entirely on your own hardware. It combines a from-scratch model training stack, a local inference and chat experience, a desktop agent workspace, and a set of tools for coding, file editing, command execution, web-aware research, and collaborative experimentation. The project is designed for developers, researchers, and power users who want complete control over data, model behavior, and runtime environment without depending on cloud APIs.

At its core, Geocentric is an educational and practical framework for training decoder-only Transformer language models from scratch. It includes support for:

- tokenization from your own text corpus
- pretraining on custom datasets
- supervised fine-tuning for instruction-following and chat behavior
- local serving through a web UI and OpenAI-compatible endpoints
- interactive terminal chat and agent workflows
- native desktop automation and workspace tooling
- distributed collaborative training across multiple machines

Geocentric is not just a model runner. It is a complete local experimentation platform that helps you understand the lifecycle of a language model from data collection through training, evaluation, deployment, and day-to-day use. The repository is organized around a Python-first CLI and supporting modules for training, serving, agent operations, and UI integration.

## What Geocentric Code Includes

### 1. Local Model Training Stack
Geocentric can train a causal language model entirely from scratch using a configurable decoder-only Transformer architecture. You control the tokenizer, dataset, architecture size, learning rate schedule, batch configuration, and optimization settings.

The training pipeline supports:

- tokenizer training from local text data
- pretraining from raw corpora
- SFT on instruction-style datasets
- hardware-aware optimization for Apple Silicon, NVIDIA GPUs, and CPU fallback
- checkpoint-based resumability and experiment organization

### 2. Local Chat and Agent Interface
Geocentric offers a local chat experience that can run models from Ollama or from a locally served Geocentric instance. The interface supports conversation history, model selection, tool use, search-enabled reasoning, and project-aware agent actions.

This makes it suitable for:

- coding assistants
- local research helpers
- workspace-aware document editing
- command execution and automation
- interactive debugging and prototyping

### 3. Native Desktop App
The macOS desktop app provides a polished environment for using the local agent service, switching models, managing conversations, and invoking workspace actions. It wraps the backend service and gives you a desktop-native UI for chat, files, status, and tool execution.

### 4. Collaborative Training
Geocentric includes a cross-machine training strategy that can distribute work across multiple devices, including Apple Silicon Macs and Linux machines. This is useful when you want to experiment with larger models or train beyond the limits of a single local machine.

### 5. Open and Extensible Architecture
The repository is intentionally modular. Training, model loading, CLI commands, tool execution, dashboard behavior, and networking are separated into clearly defined Python modules so you can study, extend, or repurpose pieces of the system without rewriting everything from scratch.

## How the Project Is Intended to Be Used

A typical Geocentric workflow looks like this:

1. Install dependencies and create a virtual environment.
2. Train or download a tokenizer.
3. Pretrain a model on a local corpus.
4. Fine-tune it with instruction-style data.
5. Serve it locally through the CLI or web UI.
6. Interact with it through the terminal, web app, or desktop agent experience.
7. Use agent tools to create files, run commands, inspect projects, and search the web.

This makes Geocentric useful as both a research sandbox and a practical personal AI workstation.

## Launch Options

Geocentric can be started in several ways depending on your preferred workflow:

- local CLI launcher via the repository scripts
- full GUI/server mode for the web interface
- terminal-based interactive agent mode
- remote client connection to a host machine over the network
- native macOS desktop app build

The repository includes a launcher script that helps you choose between GUI, CLI, remote connection, and remote instructions modes.

## Repository Layout

Key areas of the repository include:

- [geocentric](geocentric) — core training, CLI, agent runtime, server, and UI logic
- [scripts](scripts) — dataset downloaders, training helpers, and client utilities
- [mac_app](mac_app) — native macOS app sources and packaging scripts
- [data](data) — example datasets and seed corpora
- [tests](tests) — regression and behavior tests
- [runs](runs) — generated checkpoints and model outputs

## Hardware and Environment Notes

Geocentric is designed to work on multiple environments:

- Apple Silicon Macs using MPS
- NVIDIA GPUs using CUDA
- Linux systems with compatible Python and PyTorch installs
- CPU-only development and experimentation

The CLI includes hardware-aware optimization flags to adjust preset size, batch size, accumulation steps, and compile behavior based on available hardware.

## Common Use Cases

Geocentric is especially useful for:

- building compact local chat models
- experimenting with training pipelines from scratch
- prototyping coding agents on local hardware
- automating local workflows with agent tools
- studying model behavior and training dynamics
- creating a private alternative to hosted AI services

## Getting Started

The shortest path is usually:

```bash
python -m geocentric.cli train-tokenizer --data_path data/pretrain_seed.txt
python -m geocentric.cli pipeline \
  --data_path data/pretrain_seed.txt \
  --sft_data_path data/alpaca_data.json \
  --preset tiny \
  --pretrain_epochs 2 \
  --sft_epochs 2
python -m geocentric.cli serve --model_dir runs/geocentric2_1 --port 8000
```

Then open the local web interface at http://localhost:8000.

---

## 🚀 New: Hardware-Speed Wizard

For the fastest local path on Apple Silicon or NVIDIA CUDA, use the new interactive wizard. It asks whether to run `pretrain`, `sft`, or `pipeline`, asks for the model name/size, asks what capabilities the chatbot should have, then applies hardware-tuned settings automatically.

```bash
python -m geocentric.cli wizard
# alias:
python -m geocentric.cli auto
```

You can also keep using the normal commands and add the speed/capability flags:

```bash
python -m geocentric.cli pipeline \
  --data_path data/wikipedia_pretrain.txt \
  --sft_data_path data/alpaca_data.json \
  --auto-optimize \
  --ask-model \
  --ask-capabilities
```

`--auto-optimize` detects Mac MPS, NVIDIA CUDA, or CPU and adjusts `preset`, `dtype`, `batch_size`, `sft_batch_size`, `gradient_accumulation_steps`, DataLoader workers, checkpoint frequency, metric writes, and CUDA compile mode for speed. On RTX 2060-class 6 GB CUDA cards it defaults to a smaller fast preset instead of trying huge batches that crawl or crash. On Apple Silicon it keeps workers at `0`, avoids torch.compile, and reduces disk sync overhead.


## ⚡ Quick Start: 3-Step Local Training

Train a tiny seed model locally in less than 2 minutes to test the whole pipeline:

```bash
# 1. Train Tokenizer
python -m geocentric.cli train-tokenizer --data_path data/pretrain_seed.txt

# 2. Pretrain & SFT pipeline in a single command
python -m geocentric.cli pipeline \
  --data_path data/pretrain_seed.txt \
  --sft_data_path data/guided_sft_seed.jsonl \
  --preset tiny \
  --pretrain_epochs 2 \
  --sft_epochs 2

# 3. Serve the Web Chat UI
python -m geocentric.cli serve --model_dir runs/geocentric2_1 --port 8000
```
Open **`http://localhost:8000`** to chat with your local model!

---

## 🖥️ Native macOS Agent App

The `mac_app/` folder contains the Geocentric desktop host. It starts the Python agent service automatically, manages Ollama models, and routes explicit tool requests such as “make a file,” “run this script,” or “search today’s news” through the tool runner instead of plain chat.

```bash
cd mac_app
./build_pkg.sh
open Geocentric.app
```

`./build_pkg.sh` also creates a distributable `Geocentric.dmg` at the repository root. On first launch, the app creates its private Python environment, installs the bundled requirements, starts the local service, and opens the native workspace without a manual setup screen.

For public distribution, set `GEOCENTRIC_CODESIGN_IDENTITY` to a Developer ID Application identity before building. Set `GEOCENTRIC_NOTARY_PROFILE` to a saved `notarytool` keychain profile to submit and staple the DMG automatically.

In the app:

- Use the single model menu in the toolbar to refresh, download, manage, or switch Ollama models.
- Use the New Chat button in the toolbar or left drawer to start a clean conversation.
- Use the Agent status chip to start or inspect the local tool service. A reachable local service is shown as ready.
- Enable Agent mode for workspace actions. Explicit file, command, project, and web-search requests are routed to tools automatically when the local service is available.
- Choose a project folder before asking the agent to create or edit files.
- Review `Implementation Plan.md` in the right Agent Side Panel before complex file-changing work runs; accept to execute or deny to revise.
- Inspect red/green file diffs after tool edits, then approve or roll back individual file changes.
- Watch the context gauge, pin multiple files into the composer staging area, and use the telemetry HUD to monitor CPU, memory, disk, and GPU availability.
- Agent mode includes structured tools for web search, browsing URLs, listing/statting workspace paths, creating directories, copying/moving files, downloading URLs into the workspace, running commands, checking ports, making HTTP requests, and capturing local web views.

The optional closed-source deployment backend is documented in [CLOUD_SERVER.md](/Users/elywright/geocentric/CLOUD_SERVER.md). Its source folder is created outside this repo at `~/Geocentric Cloud Server/server_backend` so this upstream project stays intact.

---

## 🌐 Heterogeneous Collaborative Training (Mac + Linux)

By sharding the model layers across your Mac and Linux PC over a local network, you can train a much larger model (like the `120m` parameter preset) cooperatively!

### 1. Configure the Network Link (Choose Wi-Fi or Cable)
*   **Via Local Wi-Fi:** Find your Mac's LAN IP (e.g., `192.168.1.30`).
*   **Via Direct Link Cable (Fastest 🚀):** Connect your Mac and Linux PC with a USB/Thunderbolt cable, then run `python scripts/setuplink.py` on both machines. This automatically sets the dedicated network link IP to `192.168.99.1`.

### 2. Run Pretraining:
*   **On macOS (Rank 0 - Master):**
    ```bash
    python -m geocentric.cli pipeline-train \
      --master_ip 192.168.1.30 \
      --master_port 29500 \
      --rank 0 \
      --world_size 2 \
      --data_path data/pretrain_seed.txt \
      --preset 120m \
      --block_size 256 \
      --batch_size 1 \
      --gradient_accumulation_steps 32 \
      --epochs 15 \
      --dtype bfloat16
    ```
*   **On Linux (Rank 1 - Worker):**
    ```bash
    .venv/bin/python -m geocentric.cli pipeline-train \
      --master_ip 192.168.1.30 \
      --master_port 29500 \
      --rank 1 \
      --world_size 2 \
      --data_path data/pretrain_seed.txt \
      --preset 120m \
      --block_size 256 \
      --batch_size 1 \
      --gradient_accumulation_steps 32 \
      --epochs 15 \
      --dtype bfloat16
    ```

### 3. Run Supervised Fine-Tuning (SFT):
First, download the 5,000 instruction-pair Alpaca dataset by running `.venv/bin/python -m geocentric.cli download-alpaca`.

Then run the SFT command:
*   **On macOS (Rank 0 - Master):**
    ```bash
    python -m geocentric.cli pipeline-train \
      --master_ip 192.168.1.30 \
      --master_port 29500 \
      --rank 0 \
      --world_size 2 \
      --data_path data/alpaca_data.json \
      --preset 120m \
      --block_size 256 \
      --batch_size 1 \
      --gradient_accumulation_steps 32 \
      --epochs 10 \
      --dtype bfloat16
    ```
*   **On Linux (Rank 1 - Worker):**
    ```bash
    .venv/bin/python -m geocentric.cli pipeline-train \
      --master_ip 192.168.1.30 \
      --master_port 29500 \
      --rank 1 \
      --world_size 2 \
      --data_path data/alpaca_data.json \
      --preset 120m \
      --block_size 256 \
      --batch_size 1 \
      --gradient_accumulation_steps 32 \
      --epochs 10 \
      --dtype bfloat16
    ```

---

## 📑 Detailed Flags & Presets

For a full breakdown of all command-line arguments, system optimization flags, and customized preset dimensions, open the interactive documentation hub:

*   **Offline Guide:** Open [USAGE_GUIDE.md](USAGE_GUIDE.md)
*   **Interactive Web Hub:** Open [index.html](index.html) in your browser!
