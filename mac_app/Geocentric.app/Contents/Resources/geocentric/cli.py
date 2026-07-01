from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from geocentric.checkpoint import sft_checkpoint_name
from geocentric.collaborative_pipeline import run_distributed_pipeline_train as run_pipeline_train
from geocentric.collaborative_train import run_collaborative_pretrain
from geocentric.data import iter_texts
from geocentric.hardware_auto import (
    apply_overrides,
    detect_hardware,
    first_existing,
    merge_capability_sft_data,
    optimized_training_overrides,
    print_plan,
    save_capabilities,
    slugify_model_name,
)
from geocentric.param_compiler import compute_fluid_dimensions
from geocentric.tokenizer_train import train_byte_bpe_tokenizer
from geocentric.train_pretrain import pretrain
from geocentric.train_sft import sft
from scripts.download_alpaca import download_alpaca
from scripts.download_wikipedia import download_wikitext103

MODEL_DOWNLOAD_REGISTRY = {
    "wizardlm-3b": {"repo": "TheBloke/WizardLM-3B-v1.0", "public": True, "description": "3B WizardLM for 6GB VRAM"},
    "wizardlm-4b": {"repo": "TheBloke/wizardlm-4b-v1.0", "public": True, "description": "4B WizardLM, smaller than 7B"},
    "guanaco-3b": {"repo": "TheBloke/guanaco-3b", "public": True, "description": "3B Guanaco public model"},
    "llama-3b": {"repo": "meta-llama/Llama-2-3b-chat-hf", "public": True, "description": "3B Llama 2 chat model alias"},
    "llama-2-3b-chat-hf": {"repo": "meta-llama/Llama-2-3b-chat-hf", "public": True, "description": "3B Llama 2 chat model"},
    "falcon-7b-instruct": {"repo": "tiiuae/falcon-7b-instruct", "ollama": "falcon-7b-instruct", "public": True, "description": "7B Falcon instruct model"},
    "mistral-7b": {"repo": "MistralAI/mistral-7b", "ollama": "mistral-7b", "public": True, "description": "7B Mistral model"},
    "gemma": {"repo": "google/gemma-2b", "public": True, "description": "2B Gemma public model for low-VRAM use"},
    "gemma-3b": {"repo": "iprajwaal/gemma-3b-chat-support", "public": True, "description": "3B Gemma chat model"},
    "qwen-4b": {"repo": "Qwen/Qwen-4B", "ollama": "qwen-4b", "public": False, "description": "Official gated Qwen 4B"},
    "qwen-4b-int4": {"repo": "Qwen/Qwen-4B", "ollama": "qwen-4b", "public": False, "description": "Gated Qwen 4B expected as quantized Int4"},
}


def _add_speed_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auto_optimize", "--auto-optimize", action="store_true", help="Detect Mac Silicon/CUDA hardware and rewrite training settings for speed")
    parser.add_argument("--speed_profile", "--speed-profile", choices=["safe", "balanced", "max_speed"], default="max_speed", help="Hardware optimizer profile")
    parser.add_argument("--ask_model", "--ask-model", action="store_true", help="Interactively ask for model name/size/path before training")
    parser.add_argument("--ask_capabilities", "--ask-capabilities", action="store_true", help="Interactively ask what this chatbot should be capable of")
    parser.add_argument("--capabilities", default=None, help="Non-interactive capability plan for the chatbot")
    parser.add_argument("--metrics_every", "--metrics-every", type=int, default=10, help="Write training dashboard metrics every N optimizer steps")
    parser.add_argument("--save_every", "--save-every", type=int, default=100, help="Save checkpoint every N optimizer steps")
    parser.add_argument("--num_workers", "--num-workers", type=int, default=None, help="DataLoader workers; 0 is fastest on Apple MPS, more helps CUDA")
    parser.add_argument("--compile_mode", "--compile-mode", choices=["auto", "off"], default="auto", help="Use torch.compile on supported NVIDIA GPUs")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="geocentric", description="Geocentric 2.1 from-scratch local LLM platform")
    sub = p.add_subparsers(dest="cmd", required=True)

    wiz = sub.add_parser("wizard", aliases=["auto"], help="Interactive speed wizard: choose pretrain, sft, or pipeline, model, and chatbot capabilities")
    wiz.add_argument("--command", choices=["pretrain", "sft", "pipeline"], default=None, help="Skip asking which training command to run")
    wiz.add_argument("--data_path", default=None)
    wiz.add_argument("--sft_data_path", default=None)
    wiz.add_argument("--model_dir", default=None)
    wiz.add_argument("--output_dir", default=None)
    wiz.add_argument("--epochs", type=int, default=None, help="Pretrain/SFT epochs for single-stage modes")
    wiz.add_argument("--pretrain_epochs", type=int, default=None)
    wiz.add_argument("--sft_epochs", type=int, default=None)
    wiz.add_argument("--vocab_size", type=int, default=8192)
    wiz.add_argument("--learning_rate", type=float, default=None)
    wiz.add_argument("--sft_learning_rate", type=float, default=None)
    wiz.add_argument("--eval_ratio", type=float, default=0.05)
    wiz.add_argument("--patience", type=int, default=3)
    wiz.add_argument("--target_loss", type=float, default=0.0)
    wiz.add_argument("--pretrain_target_loss", type=float, default=0.0)
    wiz.add_argument("--sft_target_loss", type=float, default=0.0)
    wiz.add_argument("--dropout", type=float, default=0.1)
    wiz.add_argument("--tokenizer_path", default=None)
    wiz.add_argument("--overwrite_output_dir", action="store_true")
    wiz.add_argument("--modelver", default=None)
    wiz.add_argument("--preset", default=None)
    _add_speed_flags(wiz)

    t = sub.add_parser("train-tokenizer", help="Train tokenizer.json from local text/data")
    t.add_argument("--data_path", required=True)
    t.add_argument("--output", default="runs/geocentric2_1/tokenizer.json")
    t.add_argument("--vocab_size", type=int, default=8192)
    t.add_argument("--min_frequency", type=int, default=2)

    pr = sub.add_parser("pretrain", help="Train Geocentric 2.1 from random initialization")
    pr.add_argument("--data_path", required=True)
    pr.add_argument("--output_dir", "--model_dir", dest="output_dir", default="runs/geocentric2_1", help="Output/model directory for pretraining checkpoints")
    pr.add_argument("--vocab_size", type=int, default=8192)
    pr.add_argument("--block_size", type=int, default=256)
    pr.add_argument("--n_layer", type=int, default=6)
    pr.add_argument("--n_head", type=int, default=6)
    pr.add_argument("--n_embd", type=int, default=384)
    pr.add_argument("--dropout", type=float, default=0.1)
    pr.add_argument("--epochs", type=int, default=3)
    pr.add_argument("--batch_size", type=int, default=8)
    pr.add_argument("--gradient_accumulation_steps", type=int, default=4)
    pr.add_argument("--learning_rate", type=float, default=3e-4)
    pr.add_argument("--eval_ratio", type=float, default=0.05)
    pr.add_argument("--patience", type=int, default=3)
    pr.add_argument("--target_loss", type=float, default=0.0)
    pr.add_argument("--dtype", default="auto")
    pr.add_argument("--tokenizer_path", default=None)
    pr.add_argument("--preset", type=str, default="120m", help="Fluid size definition, e.g., '50m', '120m', '330m', '1b'")
    pr.add_argument("--gradient_checkpointing", action="store_true", help="Enable gradient checkpointing to save VRAM")
    pr.add_argument("--offload_layers", action="store_true", help="Enable layer-by-layer offloading for very large models")
    pr.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")
    pr.add_argument("--overwrite_output_dir", action="store_true", help="Start pretraining fresh by removing existing pretraining checkpoints in the output directory")
    _add_speed_flags(pr)

    sf = sub.add_parser("sft", help="Guided fine-tune after from-scratch pretraining")
    sf.add_argument("--model_dir", default="runs/geocentric2_1")
    sf.add_argument("--sft_data_path", required=True)
    sf.add_argument("--output_dir", default=None)
    sf.add_argument("--epochs", type=int, default=2)
    sf.add_argument("--batch_size", type=int, default=4)
    sf.add_argument("--sft_batch_size", type=int, default=None, help="Alias for --batch_size to match pipeline naming")
    sf.add_argument("--vocab_size", type=int, default=8192)
    sf.add_argument("--gradient_accumulation_steps", type=int, default=4)
    sf.add_argument("--learning_rate", type=float, default=2e-5)
    sf.add_argument("--eval_ratio", type=float, default=0.05)
    sf.add_argument("--patience", type=int, default=3)
    sf.add_argument("--target_loss", type=float, default=0.0)
    sf.add_argument("--min_delta", type=float, default=1e-4, help="Minimum validation improvement to reset patience")
    sf.add_argument("--dtype", default="auto")
    sf.add_argument("--preset", type=str, default="120m", help="Accepted for CLI consistency; SFT loads dimensions from checkpoint")
    sf.add_argument("--gradient_checkpointing", action="store_true", help="Enable gradient checkpointing to save VRAM")
    sf.add_argument("--offload_layers", action="store_true", help="Enable layer-by-layer offloading for very large models")
    sf.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")
    sf.add_argument("--overwrite_output_dir", action="store_true", help="Do not resume old SFT checkpoints; remove them and start SFT from the pretrained checkpoint")
    _add_speed_flags(sf)

    sv = sub.add_parser("serve", help="Start the Geocentric web UI and OpenAI-compatible API")
    sv.add_argument("--model_dir", default="runs/geocentric2_1")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--dtype", default="auto")
    sv.add_argument("--modelver", default="Geocentric 2.1", help="Model version name to load when serving")

    pl = sub.add_parser("pipeline", help="Automated end-to-end training pipeline (Pretrain -> SFT) with early stopping")
    pl.add_argument("--data_path", required=True)
    pl.add_argument("--sft_data_path", required=True)
    pl.add_argument("--output_dir", default="runs/geocentric2_1")
    pl.add_argument("--vocab_size", type=int, default=8192)
    pl.add_argument("--block_size", type=int, default=256)
    pl.add_argument("--dropout", type=float, default=0.1)
    pl.add_argument("--pretrain_epochs", type=int, default=15)
    pl.add_argument("--sft_epochs", type=int, default=10)
    pl.add_argument("--patience", type=int, default=3)
    pl.add_argument("--pretrain_target_loss", type=float, default=0.0)
    pl.add_argument("--sft_target_loss", type=float, default=0.0)
    pl.add_argument("--batch_size", type=int, default=8)
    pl.add_argument("--sft_batch_size", type=int, default=4)
    pl.add_argument("--gradient_accumulation_steps", type=int, default=4)
    pl.add_argument("--learning_rate", type=float, default=3e-4)
    pl.add_argument("--sft_learning_rate", type=float, default=5e-5)
    pl.add_argument("--eval_ratio", type=float, default=0.05)
    pl.add_argument("--dtype", default="auto")
    pl.add_argument("--tokenizer_path", default=None)
    pl.add_argument("--preset", type=str, default="120m", help="Fluid size definition, e.g., '50m', '120m', '330m', '1b'")
    pl.add_argument("--gradient_checkpointing", action="store_true", help="Enable gradient checkpointing to save VRAM")
    pl.add_argument("--offload_layers", action="store_true", help="Enable layer-by-layer offloading for very large models")
    pl.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")
    pl.add_argument("--overwrite_output_dir", action="store_true", help="Start the automated pipeline from fresh pretrain/SFT checkpoints")
    _add_speed_flags(pl)

    cp = sub.add_parser("collaborative-pretrain", help="Collaboratively train an AI together wirelessly across multiple computers (e.g. Mac + PC)")
    cp.add_argument("--master_ip", required=True, help="IP address of the Master (Rank 0) PC")
    cp.add_argument("--master_port", default="29500", help="Port for distributed network bridge")
    cp.add_argument("--rank", type=int, required=True, help="Rank of current device (0 = Master, 1 = Worker/Mac)")
    cp.add_argument("--world_size", type=int, default=2, help="Total number of nodes (default: 2)")
    cp.add_argument("--data_path", required=True)
    cp.add_argument("--output_dir", default="runs/geocentric2_1")
    cp.add_argument("--epochs", type=int, default=5)
    cp.add_argument("--batch_size", type=int, default=2)
    cp.add_argument("--gradient_accumulation_steps", type=int, default=16)
    cp.add_argument("--learning_rate", type=float, default=3e-4)
    cp.add_argument("--dtype", default="bfloat16")
    cp.add_argument("--preset", type=str, default="medium", help="Fluid size definition, e.g., '120m', '330m', '1b'")
    cp.add_argument("--gradient_checkpointing", action="store_true", help="Enable gradient checkpointing to save VRAM")
    cp.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")

    sub.add_parser("download-wiki", help="Automatically download and extract clean English Wikipedia pretraining data (WikiText-103)")
    sub.add_parser("download-alpaca", help="Automatically download and cache a clean subset of Stanford Alpaca instruction training dataset")
    dm = sub.add_parser("download-model", help="Download a Hugging Face or Ollama model repo to a local folder")
    dm.add_argument("--model", default=None, help="Model alias or Hugging Face repo ID to download")
    dm.add_argument("--output_dir", default="models", help="Output folder for downloaded model files")
    dm.add_argument("--source", choices=["ollama", "huggingface", "hf"], default="ollama", help="Download source: ollama (default) or huggingface")
    dm.add_argument("--list", action="store_true", help="List available download aliases")
    dm.add_argument("--public_only", action="store_true", help="Allow only public models; do not require login or auth token")
    dm.add_argument("--hf_token", default=None, help="Optional Hugging Face API token for gated/private repos")

    pt = sub.add_parser("pipeline-train", help="Collaborative Pipeline Parallel training sharded over network (Mac + PC)")
    pt.add_argument("--master_ip", default="127.0.0.1", help="Master node IP address")
    pt.add_argument("--master_port", default="29500", help="Master node socket port")
    pt.add_argument("--rank", type=int, default=0, help="Local rank (0 for MacBook, 1 for PC)")
    pt.add_argument("--world_size", type=int, default=1, help="Total devices: 1 for local, 2+ for sharding")
    pt.add_argument("--auto_wired_setup", action="store_true", default=False, help="Auto-detect and configure direct USB/Wired Link IPs")
    pt.add_argument("--data_path", required=True)
    pt.add_argument("--output_dir", default="runs/geocentric2_1")
    pt.add_argument("--epochs", type=int, default=5)
    pt.add_argument("--batch_size", type=int, default=2)
    pt.add_argument("--gradient_accumulation_steps", type=int, default=16)
    pt.add_argument("--learning_rate", type=float, default=3e-4)
    pt.add_argument("--dtype", default="bfloat16")
    pt.add_argument("--preset", type=str, default="medium", help="Fluid size definition, e.g., '120m', '330m', '1b'")
    pt.add_argument("--block_size", type=int, default=None, help="Override default preset block size (context length)")
    pt.add_argument("--gradient_checkpointing", action="store_true", help="Enable gradient checkpointing to save VRAM")
    pt.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")

    sub.add_parser("list-models", help="List all available local checkpoints in runs/ or models/ and any installed Ollama models")
    return p


def _strip_drag_path(value: str) -> str:
    value = value.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        value = value[1:-1]
    return value.strip()


def _ask(prompt: str, default: Any = None) -> str:
    if not sys.stdin.isatty():
        return "" if default is None else str(default)
    suffix = f" [{default}]" if default not in (None, "") else ""
    ans = input(f"{prompt}{suffix}: ").strip()
    return _strip_drag_path(ans) if ans else ("" if default is None else str(default))


def prompt_for_model_path(default: str) -> str:
    if not sys.stdin.isatty():
        return default

    print("\n⚠️  No pretrained checkpoint found for the default model path.")
    choice = input("Would you like to (D)rag-and-drop a checkpoint file, or (S)elect a run folder? [D/s]: ").strip().lower()
    if choice == "" or choice.startswith("d"):
        print("📥 Drag and drop your pretrained model checkpoint file (.pt) or model folder here, then press Enter.")
        user_input = input(f"Model path [default: {default}]: ").strip()
        return _strip_drag_path(user_input) if user_input else default

    runs_root = Path.cwd() / "runs"
    candidates = []
    if runs_root.exists():
        candidates = [p for p in sorted(runs_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True) if p.is_dir()]
    if not candidates:
        print("No run folders found under ./runs/. Falling back to drag-and-drop.")
        user_input = input(f"Model path [default: {default}]: ").strip()
        return _strip_drag_path(user_input) if user_input else default
    print("Select a run folder to load:")
    for i, cand in enumerate(candidates[:40], start=1):
        print(f"  {i}) {cand}")
    sel = input("Enter number or full path (blank to cancel): ").strip()
    if not sel:
        return default
    try:
        return str(candidates[int(sel) - 1])
    except Exception:
        return str(Path(_strip_drag_path(sel)).expanduser().resolve())


def _apply_interactive_model_prompts(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not sys.stdin.isatty():
        return payload

    if command in {"pretrain", "pipeline"}:
        default_name = payload.get("modelver") or "Geocentric 2.1 Custom"
        payload["modelver"] = _ask("Model name/version", default_name)
        default_slug = slugify_model_name(payload["modelver"])
        payload["output_dir"] = _ask("Output run folder", payload.get("output_dir") or f"runs/{default_slug}")
        payload["preset"] = _ask("Model size/preset for this hardware", payload.get("preset") or "50m")
    elif command == "sft":
        payload["modelver"] = _ask("Model name/version", payload.get("modelver") or "Geocentric 2.1 Custom")
        payload["model_dir"] = prompt_for_model_path(payload.get("model_dir") or "runs/geocentric2_1")
        payload["output_dir"] = _ask("Fine-tuned output folder", payload.get("output_dir") or payload.get("model_dir"))
    return payload


def _ask_capability_text(default: str | None = None) -> str:
    if not sys.stdin.isatty():
        return default or ""
    print("\nWhat should this AI chatbot actually be good at?")
    print("Examples: coding helper, VR Unity game dev assistant, math tutor, local OS assistant, roleplay bot, etc.")
    return _ask("Capability plan", default or "coding help, step-by-step debugging, and honest answers")


def _prepare_training_command(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    ask_model = payload.pop("ask_model", False)
    ask_capabilities = payload.pop("ask_capabilities", False)
    capabilities = payload.pop("capabilities", None)
    auto_optimize = payload.pop("auto_optimize", False)
    speed_profile = payload.pop("speed_profile", "max_speed")

    profile = None
    if auto_optimize:
        profile, overrides = optimized_training_overrides(command, speed_profile=speed_profile)
        payload = apply_overrides(payload, overrides)
        print_plan(command, profile, overrides)

    if ask_model:
        payload = _apply_interactive_model_prompts(command, payload)

    if ask_capabilities:
        capabilities = _ask_capability_text(capabilities)

    if capabilities:
        if profile is None:
            profile = detect_hardware()
        output_dir = payload.get("output_dir") or payload.get("model_dir") or "runs/geocentric2_1"
        save_capabilities(output_dir, payload.get("modelver", "Geocentric 2.1"), capabilities, profile)
        if command in {"sft", "pipeline"} and payload.get("sft_data_path"):
            payload["sft_data_path"] = merge_capability_sft_data(
                payload["sft_data_path"],
                output_dir,
                payload.get("modelver", "Geocentric 2.1"),
                capabilities,
            )

    return payload


def _resolve_pretrain_dims(payload: dict[str, Any], preset: str, grad_chk: bool) -> tuple[dict[str, Any], bool]:
    try:
        if preset == "tiny":
            payload.update({"n_layer": 6, "n_head": 6, "n_embd": 384, "block_size": payload.get("block_size", 256)})
        else:
            dims = compute_fluid_dimensions(preset, vocab_size=payload.get("vocab_size", 8192))
            payload.update({
                "n_layer": dims["n_layer"],
                "n_head": dims["n_head"],
                "n_embd": dims["n_embd"],
                "block_size": payload.get("block_size") or dims["block_size"],
            })
            if dims["n_embd"] >= 1024 or dims["n_layer"] >= 12:
                grad_chk = True
    except Exception as e:
        print(f"Failed to compute fluid dimensions from preset '{preset}': {e}")
        print("Falling back to provided numeric args or tiny defaults.")
    return payload, grad_chk


def run_pretrain_command(raw_payload: dict[str, Any]) -> None:
    payload = _prepare_training_command("pretrain", raw_payload)
    dtype = payload.pop("dtype", "auto")
    preset = payload.pop("preset", "tiny")
    grad_chk = payload.pop("gradient_checkpointing", False)
    payload.pop("offload_layers", None)
    payload, grad_chk = _resolve_pretrain_dims(payload, preset, grad_chk)
    pretrain(dtype_name=dtype, gradient_checkpointing=grad_chk, **payload)


def run_sft_command(raw_payload: dict[str, Any]) -> None:
    payload = _prepare_training_command("sft", raw_payload)
    dtype = payload.pop("dtype", "auto")
    payload.pop("preset", None)
    grad_chk = payload.pop("gradient_checkpointing", False)
    offload = payload.pop("offload_layers", False)
    sft_batch = payload.pop("sft_batch_size", None)
    payload.pop("vocab_size", None)
    if sft_batch is not None:
        payload["batch_size"] = sft_batch

    model_dir = payload.get("model_dir", "runs/geocentric2_1")
    if not Path(model_dir).expanduser().exists() and sys.stdin.isatty():
        payload["model_dir"] = prompt_for_model_path(model_dir)

    sft(dtype_name=dtype, gradient_checkpointing=grad_chk, offload_layers=offload, **payload)


def run_pipeline_command(raw_payload: dict[str, Any]) -> None:
    payload = _prepare_training_command("pipeline", raw_payload)
    dtype = payload.pop("dtype", "auto")
    preset = payload.pop("preset", "tiny")
    grad_chk = payload.pop("gradient_checkpointing", False)
    offload = payload.pop("offload_layers", False)

    pretrain_dims: dict[str, Any]
    try:
        if preset == "tiny":
            pretrain_dims = {"n_layer": 6, "n_head": 6, "n_embd": 384, "block_size": payload.get("block_size", 256)}
        else:
            pretrain_dims = compute_fluid_dimensions(preset, vocab_size=payload.get("vocab_size", 8192))
            if pretrain_dims["n_embd"] >= 1024 or pretrain_dims["n_layer"] >= 12:
                grad_chk = True
    except Exception as e:
        print(f"Could not compute pipeline pretrain dims from preset '{preset}': {e}")
        pretrain_dims = {"n_layer": 6, "n_head": 6, "n_embd": 384, "block_size": payload.get("block_size", 256)}

    pretrain_payload = {
        "data_path": payload["data_path"],
        "output_dir": payload["output_dir"],
        "vocab_size": payload["vocab_size"],
        "block_size": payload.get("block_size") or pretrain_dims["block_size"],
        "dropout": payload["dropout"],
        "epochs": payload["pretrain_epochs"],
        "batch_size": payload["batch_size"],
        "gradient_accumulation_steps": payload["gradient_accumulation_steps"],
        "learning_rate": payload["learning_rate"],
        "eval_ratio": payload["eval_ratio"],
        "tokenizer_path": payload["tokenizer_path"],
        "patience": payload["patience"],
        "target_loss": payload["pretrain_target_loss"],
        "modelver": payload["modelver"],
        "overwrite_output_dir": payload.get("overwrite_output_dir", False),
        "metrics_every": payload.get("metrics_every", 10),
        "save_every": payload.get("save_every", 100),
        "num_workers": payload.get("num_workers"),
        "compile_mode": payload.get("compile_mode", "auto"),
        "n_layer": pretrain_dims["n_layer"],
        "n_head": pretrain_dims["n_head"],
        "n_embd": pretrain_dims["n_embd"],
    }

    print("\n" + "=" * 80)
    print(" PIPELINE STEP 1: Starting Pretraining with Early Stopping")
    print("=" * 80 + "\n")
    pretrain(dtype_name=dtype, gradient_checkpointing=grad_chk, **pretrain_payload)

    print("\n" + "=" * 80)
    print(" PIPELINE STEP 2: Starting Supervised Fine-Tuning (SFT)")
    print("=" * 80 + "\n")
    sft_payload = {
        "model_dir": payload["output_dir"],
        "sft_data_path": payload["sft_data_path"],
        "output_dir": payload["output_dir"],
        "epochs": payload["sft_epochs"],
        "batch_size": payload["sft_batch_size"],
        "gradient_accumulation_steps": payload["gradient_accumulation_steps"],
        "learning_rate": payload["sft_learning_rate"],
        "eval_ratio": payload["eval_ratio"],
        "patience": payload["patience"],
        "target_loss": payload["sft_target_loss"],
        "modelver": payload["modelver"],
        "overwrite_output_dir": payload.get("overwrite_output_dir", False),
        "metrics_every": payload.get("metrics_every", 10),
        "save_every": payload.get("save_every", 100),
        "num_workers": payload.get("num_workers"),
        "compile_mode": payload.get("compile_mode", "auto"),
    }
    sft(dtype_name=dtype, gradient_checkpointing=grad_chk, offload_layers=offload, **sft_payload)

    print("\n" + "=" * 80)
    print(" AUTOMATED TRAINING PIPELINE COMPLETE!")
    print(f" Best model checkpoint saved to: {payload['output_dir']}/{sft_checkpoint_name(payload['modelver'])}")
    print("=" * 80 + "\n")


def _wizard_payload(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    profile, overrides = optimized_training_overrides("pipeline", speed_profile=args.speed_profile)
    print_plan("wizard", profile, overrides)

    command = args.command
    if command is None:
        choice = _ask("Run which command? pretrain, sft, or pipeline", "pipeline").lower().strip()
        command = choice if choice in {"pretrain", "sft", "pipeline"} else "pipeline"

    modelver = args.modelver or _ask("Model name/version", "Geocentric 2.1 Custom")
    default_output = args.output_dir or f"runs/{slugify_model_name(modelver)}"
    output_dir = _ask("Output run folder", default_output)
    preset = args.preset or _ask("Model size/preset", overrides.get("preset", "50m"))
    capabilities = args.capabilities or _ask_capability_text()

    data_default = first_existing(["data/wikipedia_pretrain.txt", "data/wikipedia_pretrain", "data/wikitext103", "data/wiki.train.tokens"]) or "data/wikipedia_pretrain.txt"
    sft_default = first_existing(["data/alpaca_data.json", "data/alpaca_data.jsonl", "data/alpaca.json"]) or "data/alpaca_data.json"

    base = {
        "output_dir": output_dir,
        "vocab_size": args.vocab_size,
        "block_size": overrides.get("block_size", 256),
        "dropout": args.dropout,
        "batch_size": overrides.get("batch_size", 8),
        "sft_batch_size": overrides.get("sft_batch_size", 4),
        "gradient_accumulation_steps": overrides.get("gradient_accumulation_steps", 4),
        "eval_ratio": args.eval_ratio,
        "dtype": overrides.get("dtype", "auto"),
        "preset": preset,
        "gradient_checkpointing": overrides.get("gradient_checkpointing", False),
        "offload_layers": overrides.get("offload_layers", False),
        "modelver": modelver,
        "overwrite_output_dir": args.overwrite_output_dir,
        "metrics_every": overrides.get("metrics_every", 25),
        "save_every": overrides.get("save_every", 250),
        "num_workers": overrides.get("num_workers"),
        "compile_mode": overrides.get("compile_mode", "auto"),
        "ask_model": False,
        "ask_capabilities": False,
        "capabilities": capabilities,
        "auto_optimize": False,
        "speed_profile": args.speed_profile,
    }

    if command == "pretrain":
        base.update({
            "data_path": args.data_path or _ask("Pretraining data path", data_default),
            "epochs": args.epochs if args.epochs is not None else 3,
            "learning_rate": args.learning_rate if args.learning_rate is not None else 3e-4,
            "patience": args.patience,
            "target_loss": args.target_loss,
            "tokenizer_path": args.tokenizer_path,
        })
    elif command == "sft":
        base.update({
            "model_dir": args.model_dir or prompt_for_model_path("runs/geocentric2_1"),
            "sft_data_path": args.sft_data_path or _ask("SFT/instruction data path", sft_default),
            "epochs": args.epochs if args.epochs is not None else 2,
            "learning_rate": args.learning_rate if args.learning_rate is not None else 2e-5,
            "patience": args.patience,
            "target_loss": args.target_loss,
            "min_delta": 1e-4,
        })
    else:
        base.update({
            "data_path": args.data_path or _ask("Pretraining data path", data_default),
            "sft_data_path": args.sft_data_path or _ask("SFT/instruction data path", sft_default),
            "pretrain_epochs": args.pretrain_epochs if args.pretrain_epochs is not None else 3,
            "sft_epochs": args.sft_epochs if args.sft_epochs is not None else 2,
            "learning_rate": args.learning_rate if args.learning_rate is not None else 3e-4,
            "sft_learning_rate": args.sft_learning_rate if args.sft_learning_rate is not None else 5e-5,
            "patience": args.patience,
            "pretrain_target_loss": args.pretrain_target_loss,
            "sft_target_loss": args.sft_target_loss,
            "tokenizer_path": args.tokenizer_path,
        })
    return command, base


def _run_collaborative_pretrain(payload: dict[str, Any]) -> None:
    preset = payload.pop("preset", "medium")
    grad_chk = payload.pop("gradient_checkpointing", False)
    try:
        if preset == "tiny":
            resolved = {"n_layer": 6, "n_head": 6, "n_embd": 384, "block_size": 256}
        else:
            resolved = compute_fluid_dimensions(preset, vocab_size=payload.get("vocab_size", 8192))
            if resolved["n_embd"] >= 1024 or resolved["n_layer"] >= 12:
                grad_chk = True
    except Exception as e:
        print(f"Failed to resolve preset for collaborative training: {e}")
        resolved = {"n_layer": 12, "n_head": 12, "n_embd": 768, "block_size": 512}
    payload.update({"n_layer": resolved["n_layer"], "n_head": resolved["n_head"], "n_embd": resolved["n_embd"], "block_size": resolved["block_size"], "gradient_checkpointing": grad_chk})

    class CollaborativeArgs:
        def __init__(self, d: dict[str, Any]):
            self.__dict__.update(d)

    run_collaborative_pretrain(CollaborativeArgs(payload))


def _run_pipeline_train(payload: dict[str, Any]) -> None:
    preset = payload.pop("preset", "medium")
    grad_chk = payload.pop("gradient_checkpointing", False)
    try:
        if preset == "tiny":
            resolved = {"n_layer": 6, "n_head": 6, "n_embd": 384, "block_size": 256}
        else:
            resolved = compute_fluid_dimensions(preset, vocab_size=payload.get("vocab_size", 8192))
            if resolved["n_embd"] >= 1024 or resolved["n_layer"] >= 12:
                grad_chk = True
    except Exception as e:
        print(f"Preset resolution failed for pipeline-train: {e}")
        resolved = {"n_layer": 12, "n_head": 12, "n_embd": 768, "block_size": 512}
    user_block_size = payload.pop("block_size", None)
    payload.update({"n_layer": resolved["n_layer"], "n_head": resolved["n_head"], "n_embd": resolved["n_embd"], "block_size": resolved["block_size"]})
    if user_block_size is not None:
        payload["block_size"] = user_block_size
    payload["gradient_checkpointing"] = grad_chk

    class PipelineArgs:
        def __init__(self, d: dict[str, Any]):
            self.__dict__.update(d)

    run_pipeline_train(PipelineArgs(payload))


def download_model_from_hub(
    repo_id: str,
    output_dir: str | Path,
    hf_token: str | None = None,
    force_public_only: bool = False,
) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ImportError(
            "huggingface_hub is required to download external models. "
            "Install it with `pip install huggingface_hub` or update requirements.txt."
        ) from exc

    env_keys = [
        "HUGGINGFACE_HUB_TOKEN",
        "HF_HUB_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HF_TOKEN",
    ]
    saved_tokens = {key: os.environ[key] for key in env_keys if key in os.environ}
    use_unauthenticated = hf_token is None

    def _restore_tokens() -> None:
        for key in env_keys:
            os.environ.pop(key, None)
        for key, value in saved_tokens.items():
            os.environ[key] = value

    if hf_token:
        os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token
    elif use_unauthenticated:
        for key in env_keys:
            os.environ.pop(key, None)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading model repository '{repo_id}' to {output_dir}...")

    try:
        try:
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(output_dir),
                allow_patterns=["*.bin", "*.pt", "*.pte", "*.safetensors", "*.json", "*.txt", "tokenizer*", "config*"],
                local_dir_use_symlinks=False,
                token=hf_token,
            )
        except Exception as first_exc:
            if use_unauthenticated and saved_tokens and not force_public_only:
                _restore_tokens()
                print("Retrying download with configured Hugging Face auth token...")
                try:
                    snapshot_download(
                        repo_id=repo_id,
                        local_dir=str(output_dir),
                        allow_patterns=["*.bin", "*.pt", "*.pte", "*.safetensors", "*.json", "*.txt", "tokenizer*", "config*"],
                        local_dir_use_symlinks=False,
                        token=saved_tokens.get("HUGGINGFACE_HUB_TOKEN") or saved_tokens.get("HF_HUB_TOKEN") or saved_tokens.get("HUGGINGFACE_TOKEN") or saved_tokens.get("HF_TOKEN"),
                    )
                except Exception as second_exc:
                    raise RuntimeError(
                        f"Failed to download {repo_id}. If this repo is gated or private, set --hf_token or configure a valid HUGGINGFACE_HUB_TOKEN.\n"
                        f"First attempt (unauthenticated) error: {first_exc}\n"
                        f"Second attempt (authenticated) error: {second_exc}"
                    ) from second_exc
            else:
                raise RuntimeError(
                    f"Failed to download {repo_id}. If this repo is gated or private, set --hf_token or configure a valid HUGGINGFACE_HUB_TOKEN.\n"
                    f"Original error: {first_exc}"
                ) from first_exc
    finally:
        if use_unauthenticated or hf_token:
            _restore_tokens()

    print(f"Downloaded model repository to {output_dir}")


def download_model_from_ollama(model_name: str, output_dir: str | Path) -> None:
    ollama_exec = shutil.which("ollama")
    if ollama_exec is None:
        raise RuntimeError(
            "Ollama CLI is not installed or not on PATH. "
            "Install Ollama from https://ollama.com and retry."
        )

    login_url = "https://ollama.com/login"
    print("Using Ollama as the default download source.")
    print(f"Opening Ollama login page: {login_url}")
    try:
        webbrowser.open_new_tab(login_url)
    except Exception:
        print("Could not open the browser automatically. Please open the URL manually:")
        print(login_url)

    if sys.stdin.isatty():
        input("After logging in to Ollama, press Enter to continue...")
    else:
        print("Please log in to Ollama in your browser, then rerun this command once authentication is complete.")

    try:
        subprocess.run([ollama_exec, "pull", model_name], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Failed to pull Ollama model '{model_name}'.\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}\n"
            "Verify the model name and Ollama login status."
        ) from exc

    local_model_dir = Path.home() / ".ollama" / "models" / model_name
    output_dir = Path(output_dir)
    if local_model_dir.exists():
        if output_dir.exists() and any(output_dir.iterdir()):
            print(f"Ollama model pulled to {local_model_dir}. Output directory {output_dir} already exists and was not overwritten.")
            return
        elif output_dir.exists():
            print(f"Copying Ollama model files from {local_model_dir} to {output_dir}...")
            shutil.rmtree(output_dir)
        shutil.copytree(local_model_dir, output_dir)
        print(f"Downloaded Ollama model to {output_dir}")
    else:
        print(f"Model pulled successfully, but local Ollama model directory was not found: {local_model_dir}")
        print("The model is still available through Ollama and can be used with ollama run.")


def run_download_model_command(payload: dict[str, Any]) -> None:
    if payload.pop("list", False):
        print("Available models:")
        for alias, entry in MODEL_DOWNLOAD_REGISTRY.items():
            public_flag = "[public]" if entry["public"] else "[gated]"
            desc = entry.get("description", "")
            ollama_note = f" (ollama: {entry['ollama']})" if entry.get("ollama") else ""
            print(f"  {alias}: {entry['repo']} {public_flag}{' - ' + desc if desc else ''}{ollama_note}")
        print("Default source: ollama. Use --source huggingface to pull from Hugging Face instead.")
        return

    model_name = payload.get("model")
    if not model_name:
        print("Please specify --model or use --list to view available aliases.")
        return

    source = payload.get("source", "ollama")
    if source == "hf":
        source = "huggingface"

    entry = MODEL_DOWNLOAD_REGISTRY.get(model_name)
    output_dir = payload.get("output_dir", "models")

    if source == "ollama":
        ollama_name = None
        if entry is not None:
            ollama_name = entry.get("ollama") or model_name
        else:
            ollama_name = model_name

        try:
            download_model_from_ollama(ollama_name, output_dir)
            return
        except RuntimeError as exc:
            if entry is not None and entry.get("repo"):
                print(f"Ollama download failed for '{ollama_name}': {exc}")
                print("Falling back to Hugging Face download if a repo is configured for this alias.")
                repo_id = entry["repo"]
                hf_token = payload.get("hf_token")
                force_public_only = payload.get("public_only", False)
                download_model_from_hub(repo_id, output_dir, hf_token=hf_token, force_public_only=force_public_only)
                return
            raise

    if entry is None:
        repo_id = model_name
        if payload.get("public_only", False):
            print("Warning: no public alias found for this model name. Attempting direct public repo download.")
    else:
        if payload.get("public_only", False) and not entry["public"]:
            print(f"The alias '{model_name}' is gated and requires authentication. Use a public alias instead.")
            return
        repo_id = entry["repo"]

    hf_token = payload.get("hf_token")
    force_public_only = payload.get("public_only", False)
    download_model_from_hub(
        repo_id,
        output_dir,
        hf_token=hf_token,
        force_public_only=force_public_only,
    )


def run_list_models_command() -> None:
    import json
    import urllib.request
    from pathlib import Path

    print("=" * 80)
    print("  AVAILABLE GEOCENTRIC LOCAL MODELS & CHECKPOINTS")
    print("=" * 80)

    # 1. Scan default/local directories
    local_dirs = ["models", "runs"]
    found_local = False
    seen_paths = set()
    
    for folder in local_dirs:
        p = Path(folder)
        if p.exists() and p.is_dir():
            for path in p.rglob("*"):
                if path.is_dir():
                    # Check if it looks like a valid model folder
                    if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                        rel_name = str(path.relative_to(p))
                        if rel_name not in seen_paths:
                            print(f"  [Local] {rel_name} (Path: {path})")
                            found_local = True
                            seen_paths.add(rel_name)

    if not found_local:
        print("  (No local custom checkpoints found under models/ or runs/)")

    print("\n" + "=" * 80)
    print("  INSTALLED OLLAMA MODELS (AVAILABLE FOR COMPANION CHAT)")
    print("=" * 80)

    # 2. Fetch Ollama models using HTTP request
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.0) as response:
            data = json.loads(response.read().decode())
            ollama_models = [m["name"] for m in data.get("models", [])]
            if ollama_models:
                for m in ollama_models:
                    print(f"  [Ollama] {m}")
            else:
                print("  (No models installed in Ollama. Run `ollama pull <model>` to install.)")
    except Exception as exc:
        print(f"  (Unable to contact local Ollama service: {exc})")
        print("  Make sure the Ollama service is running on your machine.")
    print("=" * 80)


def _serve(args: argparse.Namespace) -> None:
    import socket
    import uvicorn
    from pathlib import Path
    import urllib.request
    import json
    from geocentric.server import create_app

    # 1. Local models under 'runs' and 'models' (recursive scan)
    local_models = []
    seen_paths = set()
    for folder in ["models", "runs"]:
        p = Path(folder)
        if p.exists() and p.is_dir():
            for path in p.rglob("*"):
                if path.is_dir():
                    if any(path.glob("*.pt")) or any(path.glob("*.safetensors")) or (path / "config.json").exists():
                        rel_name = str(path.relative_to(p))
                        if rel_name not in seen_paths:
                            local_models.append({"type": folder, "name": rel_name, "path": path})
                            seen_paths.add(rel_name)
    local_models.sort(key=lambda x: x["name"])

    # 2. Installed Ollama models
    ollama_models = []
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.0) as response:
            data = json.loads(response.read().decode())
            ollama_models = [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    ollama_models.sort()

    all_options = []
    # Add local models first
    for m in local_models:
        all_options.append({"type": m["type"], "name": m["name"], "path": m["path"]})
    # Add ollama models
    for m in ollama_models:
        all_options.append({"type": "ollama", "name": m, "path": None})

    print("=" * 80)
    print("  STEP 1: SELECT THE PRIMARY MODEL TO RUN ON HOSTING (MAIN CHAT FALLBACK)")
    print("  (Note: You will select specialized Thinking and Instant models in the next steps!)")
    print("=" * 80)
    
    if not all_options:
        print("  No custom models or Ollama tags detected. Defaulting to local model...")
        selected_model = args.model_dir
    else:
        for idx, opt in enumerate(all_options, 1):
            print(f"  [{idx}] [{opt['type'].upper()}] {opt['name']}")
        print("=" * 80)
        try:
            choice = input(f"Select primary model to run [1-{len(all_options)}] (default 1): ").strip()
            if not choice:
                selected_index = 0
            else:
                selected_index = int(choice) - 1
                if selected_index < 0 or selected_index >= len(all_options):
                    selected_index = 0
        except Exception:
            selected_index = 0
            
        selected_opt = all_options[selected_index]
        selected_model = selected_opt["name"]
        
        # Adjust args.model_dir for the selected option
        if selected_opt["type"] == "ollama":
            args.model_dir = "ollama:" + selected_model
        else:
            args.model_dir = str(selected_opt["path"])
            
        print(f"  -> Selected model to run: {selected_model}")
        print("=" * 80)

    # Prompt for Dual Ollama models (Thinking / Instant) if available
    selected_thinking_model = None
    selected_instant_model = None
    if ollama_models:
        print("\n" + "=" * 80)
        print("  STEP 2: SELECT INSTALLED OLLAMA MODELS FOR THINKING & INSTANT MODES")
        print("=" * 80)
        for idx, m in enumerate(ollama_models, 1):
            print(f"  [{idx}] {m}")
        print("=" * 80)

        # Smart defaults:
        default_thinking_idx = 0
        for idx, m in enumerate(ollama_models):
            m_lower = m.lower()
            if any(k in m_lower for k in ["14b", "8b", "7b", "deepseek", "r1"]):
                default_thinking_idx = idx
                break
        
        default_instant_idx = 0
        for idx, m in enumerate(ollama_models):
            m_lower = m.lower()
            if any(k in m_lower for k in ["3b", "2b", "1.5b", "1b", "0.5b", "llama3.2"]):
                default_instant_idx = idx
                break

        # Prompt Thinking
        try:
            choice = input(f"Select a THINKING (Agentic) model [1-{len(ollama_models)}] (default {ollama_models[default_thinking_idx]}): ").strip()
            if not choice:
                selected_thinking_model = ollama_models[default_thinking_idx]
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(ollama_models):
                    selected_thinking_model = ollama_models[idx]
                else:
                    selected_thinking_model = ollama_models[default_thinking_idx]
        except Exception:
            selected_thinking_model = ollama_models[default_thinking_idx]

        # Prompt Instant
        try:
            choice = input(f"Select an INSTANT (Conversational) model [1-{len(ollama_models)}] (default {ollama_models[default_instant_idx]}): ").strip()
            if not choice:
                selected_instant_model = ollama_models[default_instant_idx]
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(ollama_models):
                    selected_instant_model = ollama_models[idx]
                else:
                    selected_instant_model = ollama_models[default_instant_idx]
        except Exception:
            selected_instant_model = ollama_models[default_instant_idx]

        print(f"  -> Thinking model configured: {selected_thinking_model}")
        print(f"  -> Instant model configured: {selected_instant_model}")
        print("=" * 80 + "\n")

    app = create_app(
        args.model_dir, 
        dtype_name=args.dtype, 
        modelver=args.modelver, 
        cli_model=selected_model if all_options else None,
        thinking_model=selected_thinking_model,
        instant_model=selected_instant_model
    )
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print("=" * 80)
    print("  GEOCENTRIC 2.1 WEB SERVER OPERATIONAL")
    print("=" * 80)
    print(f"  - Local host access:   http://localhost:{args.port}")
    if args.host not in {"127.0.0.1", "localhost"}:
        print(f"  - Network device access: http://{lan_ip}:{args.port}")
    else:
        print("  - Network device access: unavailable because server is bound to localhost")
        print("    Use --host 0.0.0.0 to allow other devices on your LAN to connect.")
    print("=" * 80)
    uvicorn.run(app, host=args.host, port=args.port)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = {k: v for k, v in vars(args).items() if k != "cmd"}

    if args.cmd == "train-tokenizer":
        train_byte_bpe_tokenizer(
            iter_texts(args.data_path),
            output_path=args.output,
            vocab_size=args.vocab_size,
            min_frequency=args.min_frequency,
        )
        print(f"Saved tokenizer to {args.output}")
    elif args.cmd in {"wizard", "auto"}:
        command, wizard_payload = _wizard_payload(args)
        if command == "pretrain":
            run_pretrain_command(wizard_payload)
        elif command == "sft":
            run_sft_command(wizard_payload)
        else:
            run_pipeline_command(wizard_payload)
    elif args.cmd == "pretrain":
        run_pretrain_command(payload)
    elif args.cmd == "sft":
        run_sft_command(payload)
    elif args.cmd == "pipeline":
        run_pipeline_command(payload)
    elif args.cmd == "collaborative-pretrain":
        _run_collaborative_pretrain(payload)
    elif args.cmd == "download-wiki":
        download_wikitext103()
    elif args.cmd == "download-alpaca":
        download_alpaca()
    elif args.cmd == "download-model":
        run_download_model_command(payload)
    elif args.cmd == "pipeline-train":
        _run_pipeline_train(payload)
    elif args.cmd == "list-models":
        run_list_models_command()
    elif args.cmd == "serve":
        _serve(args)


if __name__ == "__main__":
    main()
