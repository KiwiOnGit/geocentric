  # Geocentric 2.1 - Complete Usage Guide

This guide contains clean, copy-paste-ready commands to run Geocentric 2.1 locally on a single machine or collaboratively across multiple devices (macOS and Linux).

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
