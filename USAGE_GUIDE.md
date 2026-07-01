# Geocentric 2.5 - Complete Usage Guide

Geocentric 2.5 is a comprehensive local AI platform for building, training, serving, and using language models on your own machine. It is designed for users who want full control over model behavior, data, training pipeline, runtime environment, and tool use without depending on a remote cloud service. This guide is a practical handbook for installing the project, launching the interface, training models, running the agent, and extending the platform with your own workflows.

This document walks through the full lifecycle of Geocentric from setup to deployment:

- installing Python dependencies and creating a local environment
- training a tokenizer from your own corpora
- pretraining a decoder-only Transformer from scratch
- fine-tuning the model for instruction-following and chat behavior
- serving the model locally through the web UI or CLI
- using the interactive agent terminal and desktop app for coding and workspace tasks
- connecting remotely to another machine over the local network
- enabling collaborative multi-device training across macOS and Linux hosts

The platform is intentionally flexible. Some users will use it as a research sandbox to study language model training, while others will use it as a personal local AI workstation with coding, file editing, web-aware search, and project automation features. Geocentric is designed to support both styles of use.

## What You Can Do With Geocentric

### Build Models Locally
You can create tokenizer vocabularies from your own data, train models from scratch, and fine-tune them for chat or instruction tasks without sending prompts or training data to external providers.

### Run a Local AI Assistant
You can interact with the model through a terminal-based CLI, a local web interface, or a desktop app. The assistant can respond conversationally and can optionally use tools for file operations, command execution, and web search.

### Work on Projects in a Local Workspace
When the agent mode is enabled, Geocentric can operate inside a project workspace. It can inspect files, create or edit files, run commands, and keep changes organized so you can review them before accepting them.

### Train at Larger Scale
Geocentric supports multi-machine collaborative training using a custom networking bridge. This is useful when you want to scale beyond the limits of a single system or compare distributed training behavior across machines.

### Customize the Experience
You can adjust models, prompts, tools, system prompts, data paths, model presets, optimization flags, hardware profiles, and various other settings to tailor the experience to your hardware and goals.

## Platform Components

### CLI
The CLI provides commands for training, serving, interacting, and managing the workflow. It is the main entry point for developers using the repository directly.

### Server and Web UI
The local server exposes a web interface and an OpenAI-compatible API surface, so you can use your local model through a browser or other compatible clients.

### Interactive Agent
The terminal-based agent gives you a Claude-style conversational experience with slash commands, tool use, and project awareness.

### Desktop App
The macOS desktop app packages the local service and agent experience into a native application for easier day-to-day use.

### Remote Clients
Geocentric can also connect to a remote host so you can run the client from another machine and interact with a model hosted elsewhere on your LAN.

## Typical Workflow

1. Install dependencies and create a virtual environment.
2. Train or prepare a tokenizer.
3. Pretrain a model.
4. Fine-tune the model for chat/instructions.
5. Run the local server or interactive CLI.
6. Use the agent tools to inspect or edit files, launch commands, or browse the web.
7. If desired, connect another machine over the network and use the remote client.

## Installation & Setup

---

## 1. ⚙️ Installation & Setup

Set up the virtual environment and install the required dependencies on your Mac and Linux machines:

### macOS / Linux:
```bash
# Clone the repository and navigate into it
git clone https://github.com/KiwiOnGit/geocentric.git
cd geocentric

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install requirements
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 1.5. 🖥️ Native macOS Desktop App

The macOS app in `mac_app/` wraps the local agent service, Ollama model selection, project workspaces, scheduled tasks, and chat history. It now opens directly into the workspace, starts the private local service automatically, and can be packaged as a standalone `Geocentric.dmg`.

```bash
cd mac_app
./build_pkg.sh
open Geocentric.app
```

The build script writes `Geocentric.dmg` to the repository root. First launch creates the app-managed Python environment and starts the tool service, so normal users should not need to run server commands by hand.

For a public DMG, export `GEOCENTRIC_CODESIGN_IDENTITY` with your Developer ID Application certificate name. If you have a saved `notarytool` profile, export `GEOCENTRIC_NOTARY_PROFILE` too and the script will submit and staple the DMG.

Use the app this way:

1. Select or create a project folder before asking the agent to create files.
2. Use the single toolbar model menu to refresh, download, manage, and switch Ollama models.
3. Use New Chat from the toolbar or left drawer to start a clean thread.
4. Click the Agent status chip if the local tool service needs inspection; reachable service URLs are shown as ready.
5. Leave Agent mode enabled for file, code, command, project, and scheduled-task requests.
6. For complex code changes, review `Implementation Plan.md` in the right Agent Side Panel and Accept or Deny before execution.
7. Ask web/current-information questions naturally. Prompts like “search the latest news about...” are routed through the search tool when Agent mode is active.

Tool behavior:

- Simple chat stays fast and goes straight to the selected model.
- Explicit workspace requests such as “make hello.txt,” “edit this file,” “run this command,” or “build a website” use workspace tools.
- Explicit search/current requests such as “search,” “look up,” “latest,” “today,” or “news” use web search before answering.
- Every agent run starts by defining the objective, then reports specific status updates while tools run.
- File edits are captured as red/green diff viewports with Approve and Rollback actions.
- The context ring tracks the active prompt envelope and offers compaction near 80% usage.
- Pinned files appear as staged context cards below the composer and are included in the next agent payload.
- The Agent Side Panel includes a compact telemetry HUD for local CPU, memory, disk, and GPU availability.
- Web search now uses multiple HTML-search fallbacks and is available both through normal web-enabled chat and explicit `<search>query</search>` agent tool calls.
- Structured file-management tools include `<list_directory>`, `<stat_path>`, `<make_directory>`, `<copy_file>`, `<move_file>`, and `<download_url>`.

Cloud deployment backend:

```bash
cd "$HOME/Geocentric Cloud Server/server_backend"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

See `CLOUD_SERVER.md` for the secure downstream server notes.

---

## 2. 📝 Step 1: Train Tokenizer
You **must** build a tokenizer (vocabulary) from your training data before starting any model training. This takes less than 2 seconds:

```bash
python -m geocentric.cli train-tokenizer --data_path data/pretrain_seed.txt
```


---

## 2.5. 🚀 Fast Interactive Training Wizard

Use this when you do not want to hand-tune settings for Mac Silicon or NVIDIA CUDA:

```bash
python -m geocentric.cli wizard
```

It asks:

1. Whether to run `pretrain`, `sft`, or `pipeline`.
2. The model name/version and size preset.
3. What this chatbot should actually be capable of.
4. The needed data paths.

Then it runs with hardware-optimized settings. The same system is available on the normal commands:

```bash
python -m geocentric.cli pretrain \
  --data_path data/wikipedia_pretrain.txt \
  --auto-optimize \
  --ask-model \
  --ask-capabilities

python -m geocentric.cli sft \
  --model_dir runs/geocentric2_1 \
  --sft_data_path data/alpaca_data.json \
  --auto-optimize \
  --ask-model \
  --ask-capabilities

python -m geocentric.cli pipeline \
  --data_path data/wikipedia_pretrain.txt \
  --sft_data_path data/alpaca_data.json \
  --auto-optimize \
  --ask-model \
  --ask-capabilities
```

Useful speed flags:

```bash
--auto-optimize          # Detect MPS/CUDA/CPU and tune settings
--speed-profile safe     # Use smaller batches if memory is tight
--speed-profile balanced # Middle ground
--speed-profile max_speed# Default, highest practical throughput
--metrics-every 25       # Fewer dashboard writes, less sync overhead
--save-every 250         # Fewer checkpoints, less disk overhead
--num-workers 0          # Best for Apple Silicon MPS
--compile-mode off       # Disable torch.compile
```

The capability prompt writes `capabilities.json`. For `sft` and `pipeline`, it also injects a tiny capability seed file into the SFT data so the final chatbot knows what role it is supposed to perform.

---

## 3. 🧠 Step 2: Model Pretraining (From Scratch)

Choose either **Single-Machine** or **Collaborative (Mac + Linux)** training:

### Option A: Local Single-Device Pretraining (Standard)
```bash
python -m geocentric.cli pretrain \
  --data_path data/pretrain_seed.txt \
  --output_dir runs/geocentric2_1 \
  --vocab_size 8192 \
  --block_size 256 \
  --n_layer 6 \
  --n_head 6 \
  --n_embd 384 \
  --epochs 5 \
  --batch_size 4 \
  --gradient_accumulation_steps 8 \
  --dtype auto
```

### Option B: High-Speed Collaborative Pretraining over Wi-Fi (Mac + Linux)
Uses the cross-OS socket network bridge.

*   **Mac (Rank 0 - Master):**
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
    *(Replace `192.168.1.30` with your Mac's active IP)*

*   **Linux (Rank 1 - Worker):**
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

---

## 4. 💬 Step 3: Supervised Fine-Tuning (SFT)
Teach the model conversational and reasoning abilities. First, download the 5,000 instruction-pair Alpaca dataset:

```bash
python -m geocentric.cli download-alpaca
```

Then choose either **Single-Machine** or **Collaborative (Mac + Linux)** SFT:

### Option A: Local Single-Device SFT (Standard)
```bash
python -m geocentric.cli sft \
  --model_dir runs/geocentric2_1 \
  --sft_data_path data/alpaca_data.json \
  --epochs 3 \
  --batch_size 4 \
  --gradient_accumulation_steps 8 \
  --dtype auto
```

### Option B: Collaborative SFT over Wi-Fi (Mac + Linux)
Automatically loads the pretrained stage weights from pretraining and fine-tunes together over the network!

*   **Mac (Rank 0 - Master):**
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
    *(Replace `192.168.1.30` with your Mac's active IP)*

*   **Linux (Rank 1 - Worker):**
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

## 5. 🔌 Step 4: High-Speed Link Cable Mode (Auto-Configured)
If you have a direct USB 3.0 / USB-C / Thunderbolt cable connected between your Mac and Linux PC:

1.  **On Mac:**
    ```bash
    python scripts/setuplink.py
    ```
    *(Select Option `5` for en1 or Option `7` for bridge0 when prompted)*

2.  **On Linux:**
    ```bash
    .venv/bin/python scripts/setuplink.py
    ```

3.  **Run collaborative training** on both machines pointing to the dedicated link cable IP (`192.168.99.1`):
    *   **Mac (Rank 0):** Add `--master_ip 192.168.99.1` to your Mac command.
    *   **Linux (Rank 1):** Add `--master_ip 192.168.99.1` to your Linux command.

---

## 6. 🌐 Step 5: Start Web Server & OpenAI API
Once your model is fully trained, start the interactive web UI and OpenAI-compatible completions API:

```bash
python -m geocentric.cli serve \
  --model_dir runs/geocentric2_1 \
  --host 127.0.0.1 \
  --port 8000 \
  --dtype auto
```
Open **`http://localhost:8000`** in your browser to chat with your local AI!

> Note: Geocentric can now load Hugging Face-style checkpoint folders containing `model.safetensors`, `pytorch_model.bin`, `config.json`, and `tokenizer.json` when the directory structure matches a standard transformer model.

You can also monitor training progress live at **`http://localhost:8000/training-dashboard`** after starting the server.
