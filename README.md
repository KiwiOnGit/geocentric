# Geocentric 2.1 - Local LLM Lab and Agent Desktop

Geocentric 2.1 is an educational, high-performance causal Language Model platform and native macOS agent workspace. The training stack can build a decoder-only Transformer **entirely from scratch**: you control the data diet, tokenizer, and architecture. The desktop app adds a local chat interface with Ollama model management, workspace tools, scheduled tasks, and web/search-enabled agent runs.

This repository features a **custom socket-based cross-OS network bridge** enabling seamless collaborative pipeline-parallel training between **Apple Silicon Macs** (using MPS) and **Linux machines** (using CUDA).

The project is published for the SnowStudios GitHub organization, owned by the KiwiOnGit GitHub account.

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

For Supabase server SDK setup, environment variables, and a starter Edge Function handler, see [SUPABASE_SETUP.md](SUPABASE_SETUP.md).

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
