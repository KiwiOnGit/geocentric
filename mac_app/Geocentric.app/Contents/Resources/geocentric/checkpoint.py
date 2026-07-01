from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Tuple

import torch
from tokenizers import Tokenizer

from geocentric.model import GPTConfig, GeocentricGPT
from geocentric.tokenizer_train import load_tokenizer


DEFAULT_MODELVER = "Geocentric 2.1"
LEGACY_PRETRAINED_CHECKPOINT = "geocentric2_1_pretrained.pt"
LEGACY_SFT_CHECKPOINT = "geocentric2_1_sft.pt"
CheckpointKind = Literal["any", "pretrained", "sft", "full"]


def modelver_to_filename(modelver: str | None = None) -> str:
    """Convert a model version string into a stable, filename-safe prefix."""
    raw = (modelver or DEFAULT_MODELVER).strip().lower()
    safe = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return safe or modelver_to_filename(DEFAULT_MODELVER)


def pretrained_checkpoint_name(modelver: str | None = None, *, best: bool = False) -> str:
    suffix = "_pretrained_best.pt" if best else "_pretrained.pt"
    return f"{modelver_to_filename(modelver)}{suffix}"


def sft_checkpoint_name(modelver: str | None = None, *, best: bool = False) -> str:
    suffix = "_sft_best.pt" if best else "_sft.pt"
    return f"{modelver_to_filename(modelver)}{suffix}"


def pipeline_stage_checkpoint_name(modelver: str | None, rank: int, *, recovered: bool = False) -> str:
    recovery = "_recovered" if recovered else ""
    return f"{modelver_to_filename(modelver)}_pipeline_stage{rank}{recovery}.pt"


def _unique_names(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def _sorted_pt_names(model_dir: Path, pattern: str) -> list[str]:
    """Return .pt filenames sorted newest-first, ignoring obvious non-full checkpoints."""
    names: list[str] = []
    if not model_dir.exists():
        return names
    for path in sorted(model_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        name = path.name
        lowered = name.lower()
        # Pipeline stage checkpoints are not complete GeocentricGPT models.
        if "pipeline_stage" in lowered:
            continue
        # Skip common training-side blobs that are not model checkpoints.
        if any(bad in lowered for bad in ("optimizer", "scheduler", "metrics", "tokenizer")):
            continue
        names.append(name)
    return names


def _candidate_checkpoint_names(
    model_dir: Path,
    checkpoint_name: str | None,
    modelver: str | None,
    kind: CheckpointKind = "any",
) -> list[str]:
    """Return preferred checkpoint names, then robust newest fallbacks.

    `kind="pretrained"` is used by SFT so it does not accidentally fine-tune
    on top of an existing SFT checkpoint unless the user explicitly wants resume.
    `kind="any"` is used by serving/inference and prefers SFT, then pretrained.
    """
    kind = kind or "any"
    names: list[str] = [checkpoint_name or ""]

    if kind in {"any", "sft", "full"}:
        names.extend([
            sft_checkpoint_name(modelver),
            sft_checkpoint_name(modelver, best=True),
            LEGACY_SFT_CHECKPOINT,
        ])
    if kind in {"any", "pretrained", "full"}:
        names.extend([
            pretrained_checkpoint_name(modelver),
            pretrained_checkpoint_name(modelver, best=True),
            LEGACY_PRETRAINED_CHECKPOINT,
            "model.pt",
            "model.pte",
            "pytorch_model.bin",
            "pytorch_model.pte",
            "pytorch_model.safetensors",
            "model.safetensors",
        ])

    if kind in {"any", "sft", "full"}:
        names.extend(_sorted_pt_names(model_dir, "*_sft.pt"))
        names.extend(_sorted_pt_names(model_dir, "*_sft_best.pt"))
    if kind in {"any", "pretrained", "full"}:
        names.extend(_sorted_pt_names(model_dir, "*_pretrained.pt"))
        names.extend(_sorted_pt_names(model_dir, "*_pretrained_best.pt"))

    # Last-resort fallback only for general loading. For SFT's base model load,
    # staying strict prevents silently using the wrong checkpoint stage.
    if kind in {"any", "full"}:
        names.extend(_sorted_pt_names(model_dir, "*.pt"))
        names.extend(_sorted_pt_names(model_dir, "*.pte"))
        names.extend(_sorted_pt_names(model_dir, "*.bin"))
        names.extend(_sorted_pt_names(model_dir, "*.safetensors"))
    return _unique_names(names)


def _candidate_tokenizer_paths(model_dir: Path, extra_dirs: Iterable[str | Path] = ()) -> list[Path]:
    """Return tokenizer.json candidates in the safest search order."""
    cwd = Path.cwd().expanduser().resolve()
    dirs: list[Path] = [model_dir]
    for extra in extra_dirs:
        try:
            dirs.append(Path(extra).expanduser().resolve())
        except Exception:
            pass

    paths: list[Path] = []
    for directory in dirs:
        paths.extend([
            directory / "tokenizer.json",
            directory / "tokenizer.model",
            directory / "tokenizer.spm",
            directory / "vocab.json",
            directory / "tokenizer_config.json",
        ])

    # Common Geocentric defaults and nearby run folders.
    paths.extend([
        cwd / "tokenizer.json",
        cwd / "tokenizer.model",
        cwd / "tokenizer.spm",
        cwd / "vocab.json",
        cwd / "tokenizer_config.json",
        cwd / "runs" / "geocentric2_1" / "tokenizer.json",
        cwd / "runs" / "geocentric_2_1" / "tokenizer.json",
        cwd / "runs" / "geocentric500m_scratch" / "tokenizer.json",
    ])

    search_roots = _unique_names(str(p) for p in [model_dir.parent, cwd / "runs"] if p.exists())
    for root_text in search_roots:
        root = Path(root_text)
        try:
            paths.extend(sorted(root.rglob("tokenizer.*"), key=lambda p: p.stat().st_mtime, reverse=True))
            paths.extend(sorted(root.rglob("vocab.json"), key=lambda p: p.stat().st_mtime, reverse=True))
        except Exception:
            pass

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            continue
        if resolved not in seen:
            ordered.append(resolved)
            seen.add(resolved)
    return ordered


def find_tokenizer_path(
    model_dir: str | Path,
    *,
    extra_dirs: Iterable[str | Path] = (),
    expected_vocab_size: Optional[int] = None,
) -> Path:
    """Find a tokenizer.json near the model directory, optionally matching model vocab size."""
    model_dir = Path(model_dir).expanduser().resolve()
    candidates = _candidate_tokenizer_paths(model_dir, extra_dirs)
    existing = [p for p in candidates if p.exists()]

    if expected_vocab_size is None:
        if existing:
            return existing[0]
    else:
        for path in existing:
            try:
                tokenizer = load_tokenizer(path)
                if tokenizer.get_vocab_size() == expected_vocab_size:
                    return path
            except Exception:
                continue

    searched = "\n  - ".join(str(p) for p in candidates[:40])
    match_note = f" matching vocab_size={expected_vocab_size}" if expected_vocab_size is not None else ""
    raise FileNotFoundError(
        f"No tokenizer.json{match_note} found for {model_dir}.\n"
        f"Searched:\n  - {searched}\n\n"
        "Fix options:\n"
        f"  1) Copy the tokenizer from the matching pretraining run:\n"
        f"     cp runs/geocentric2_1/tokenizer.json {model_dir}/tokenizer.json\n"
        f"  2) Or train one into this folder:\n"
        f"     venv/bin/python -m geocentric.cli train-tokenizer --data_path data --output {model_dir}/tokenizer.json\n"
        "Important: tokenizer vocab size must match the checkpoint config vocab_size."
    )


def save_checkpoint(model: GeocentricGPT, output_dir: str | Path, step: int, name: str = "model.pt") -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = {
        "model_state": model.state_dict(),
        "config": model.config.__dict__,
        "step": step,
    }
    path = out / name
    torch.save(ckpt, path)
    model.config.save(out / "config.json")
    return path


def resolve_checkpoint_dir(model_dir: Path) -> Path:
    # 1. Check if the directory itself has any checkpoint files
    checkpoint_patterns = ["*.pt", "*.pte", "*.bin", "*.safetensors"]
    if any(any(model_dir.glob(pat)) for pat in checkpoint_patterns):
        return model_dir
        
    # 2. Check if any immediate subdirectory has checkpoint files
    if model_dir.exists() and model_dir.is_dir():
        for sub in sorted(model_dir.iterdir()):
            if sub.is_dir():
                if any(any(sub.glob(pat)) for pat in checkpoint_patterns):
                    print(f"Automatically resolved checkpoint directory to subdirectory: {sub}")
                    return sub
                
    # 3. Check recursively up to depth 2
    if model_dir.exists() and model_dir.is_dir():
        for sub in sorted(model_dir.rglob("*")):
            if sub.is_dir():
                try:
                    depth = len(sub.relative_to(model_dir).parts)
                except Exception:
                    depth = 3
                if depth <= 2:
                    if any(any(sub.glob(pat)) for pat in checkpoint_patterns):
                        print(f"Automatically resolved checkpoint directory recursively to: {sub}")
                        return sub
                    
    return model_dir


def load_checkpoint(
    model_dir: str | Path,
    device: torch.device,
    dtype: torch.dtype = torch.float32,
    checkpoint_name: str | None = None,
    modelver: str | None = DEFAULT_MODELVER,
    kind: CheckpointKind = "any",
) -> GeocentricGPT:
    model_dir = Path(model_dir).expanduser().resolve()
    model_dir = resolve_checkpoint_dir(model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(
            f"Model directory does not exist: {model_dir}\n"
            "Fix: pass the folder that actually contains your checkpoint with --model_dir, "
            "or pretrain first with --output_dir/--model_dir pointing here."
        )

    candidates = _candidate_checkpoint_names(model_dir, checkpoint_name, modelver, kind=kind)
    existing_candidates = [model_dir / name for name in candidates if (model_dir / name).exists()]

    errors: list[str] = []
    checkpoint_path: Path | None = None
    model: GeocentricGPT | None = None

    for candidate in existing_candidates:
        try:
            if candidate.suffix == ".safetensors":
                try:
                    from safetensors.torch import load_file as safe_load
                    payload = safe_load(str(candidate), device="cpu")
                except Exception as exc:
                    raise
            else:
                try:
                    payload = torch.load(candidate, map_location="cpu")
                except RuntimeError as exc:
                    if "weights_only" in str(exc) or "Weights only" in str(exc):
                        payload = torch.load(candidate, map_location="cpu", weights_only=False)
                    else:
                        raise

            state_dict = None
            cfg_payload = None
            if isinstance(payload, dict):
                if "model_state" in payload:
                    state_dict = payload["model_state"]
                    cfg_payload = payload.get("config")
                elif "model_state_dict" in payload:
                    state_dict = payload["model_state_dict"]
                    cfg_payload = payload.get("config")
                elif "state_dict" in payload and isinstance(payload["state_dict"], dict):
                    state_dict = payload["state_dict"]
                    cfg_payload = payload.get("config")
                elif payload and all(isinstance(v, torch.Tensor) for v in payload.values()):
                    state_dict = payload
                else:
                    errors.append(f"{candidate.name}: not a Geocentric model checkpoint")
                    continue
            elif hasattr(payload, "state_dict"):
                state_dict = payload.state_dict()
            else:
                errors.append(f"{candidate.name}: unsupported checkpoint payload type {type(payload).__name__}")
                continue

            config_path = candidate.parent / "config.json"
            if cfg_payload is None and config_path.exists():
                cfg_payload = GPTConfig.load(config_path).__dict__

            if cfg_payload is None:
                errors.append(f"{candidate.name}: missing config in checkpoint and no config.json beside it")
                continue

            config = GPTConfig(**cfg_payload)
            candidate_model = GeocentricGPT(config)
            try:
                candidate_model.load_state_dict(state_dict, strict=True)
            except RuntimeError as strict_exc:
                try:
                    candidate_model.load_state_dict(state_dict, strict=False)
                    print(f"Warning: loaded {candidate.name} with strict=False; some weights were unmatched.")
                except Exception:
                    raise strict_exc
            checkpoint_path = candidate
            model = candidate_model
            break
        except Exception as exc:
            errors.append(f"{candidate.name}: {type(exc).__name__}: {exc}")

    if checkpoint_path is None or model is None:
        searched = ", ".join(candidates[:30])
        existing_all = sorted(p.name for p in model_dir.glob("*.pt"))
        found = ", ".join(p.name for p in existing_candidates) or "none"
        all_found = ", ".join(existing_all) or "none"
        error_text = "\n  - ".join(errors[:20])
        detail = f"\nTried existing .pt files but none loaded:\n  - {error_text}" if errors else ""
        kind_note = f" ({kind})" if kind != "any" else ""
        raise FileNotFoundError(
            f"No usable{kind_note} full-model checkpoint found in {model_dir}.\n"
            f"Searched names: {searched}\n"
            f"Existing .pt files considered: {found}\n"
            f"All .pt files in folder: {all_found}"
            f"{detail}\n\n"
            "Fix options:\n"
            f"  1) Check actual checkpoint files:\n"
            f"     find {model_dir} -maxdepth 1 -name '*.pt' -print\n"
            "  2) If the checkpoint is in another run folder, pass that folder with --model_dir.\n"
            "  3) If this is a new scratch model folder, pretrain it first, for example:\n"
            f"     venv/bin/python -m geocentric.cli pretrain --model_dir {model_dir} --data_path data --preset 500m --batch_size 1 --gradient_accumulation_steps 128 --dtype auto\n"
        )

    print(f"Loaded checkpoint: {checkpoint_path}")

    has_nan = False
    for _, param in model.state_dict().items():
        if torch.isnan(param).any():
            has_nan = True
            break
    if has_nan:
        print("\n" + "=" * 80)
        print("WARNING: Loaded model weights contain NaN values!")
        print("This usually happens when training with '--dtype auto' or '--dtype fp16' on Apple Silicon (MPS).")
        print("To fix this, retrain with a safer dtype, such as --dtype float32 on MPS or --dtype auto on CUDA.")
        print("=" * 80 + "\n")

    if dtype == torch.float16:
        model.to(device=device)
    else:
        model.to(device=device, dtype=dtype)
    model.eval()
    return model


def load_model_and_tokenizer(
    model_dir: str | Path,
    device: torch.device,
    dtype: torch.dtype,
    modelver: str | None = DEFAULT_MODELVER,
) -> tuple[Any, Any]:
    # Accept either a directory containing checkpoints OR a direct .pt checkpoint file
    model_path = Path(model_dir).expanduser().resolve()
    if model_path.is_file():
        checkpoint_name = model_path.name
        model_dir_parent = model_path.parent
        if _looks_like_transformers_model(model_dir_parent):
            model, tokenizer = _load_transformers_model_and_tokenizer(model_dir_parent, device=device, dtype=dtype)
            print(f"Loaded generic Transformer model from {model_dir_parent}")
            return model, tokenizer
        model = load_checkpoint(model_dir_parent, device=device, dtype=dtype, checkpoint_name=checkpoint_name, modelver=modelver, kind="any")
        tokenizer_path = find_tokenizer_path(model_dir_parent, expected_vocab_size=model.config.vocab_size)
        tokenizer = load_tokenizer(tokenizer_path)
        if tokenizer_path.parent != model_dir_parent:
            print(f"Using tokenizer from fallback location: {tokenizer_path}")
        return model, tokenizer
    else:
        model_dir = resolve_checkpoint_dir(model_path)
        if _looks_like_transformers_model(model_dir):
            model, tokenizer = _load_transformers_model_and_tokenizer(model_dir, device=device, dtype=dtype)
            print(f"Loaded generic Transformer model from {model_dir}")
            return model, tokenizer
        model = load_checkpoint(model_dir, device=device, dtype=dtype, modelver=modelver, kind="any")
        tokenizer_path = find_tokenizer_path(model_dir, expected_vocab_size=model.config.vocab_size)
        tokenizer = load_tokenizer(tokenizer_path)
        if tokenizer_path.parent != model_dir:
            print(f"Using tokenizer from fallback location: {tokenizer_path}")
        return model, tokenizer


def _looks_like_transformers_model(model_dir: Path) -> bool:
    config_path = model_dir / "config.json"
    if not config_path.exists():
        return False

    model_files = [
        "pytorch_model.bin",
        "pytorch_model.safetensors",
        "model.safetensors",
        "model.bin",
        "adapter_model.safetensors",
        "adapter_model.bin",
        "weights.bin",
        "tf_model.h5",
    ]
    if any((model_dir / name).exists() for name in model_files):
        return True
    if any(model_dir.glob("pytorch_model-*.bin")) or any(model_dir.glob("pytorch_model-*.safetensors")):
        return True
    return False


def _load_transformers_model_and_tokenizer(
    model_dir: Path,
    device: torch.device,
    dtype: torch.dtype = torch.float32,
) -> tuple[Any, Any]:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise ImportError(
            "transformers is required to load generic Hugging Face / safetensors models. "
            "Install it with `pip install transformers`."
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(model_dir, use_fast=True)
    model_kwargs: dict[str, Any] = {
        "low_cpu_mem_usage": True,
    }
    if dtype in {torch.float16, torch.bfloat16, torch.float32}:
        model_kwargs["torch_dtype"] = dtype

    # Enable bitsandbytes 4-bit or 8-bit if available to run large models on limited memory/VRAM
    try:
        import bitsandbytes  # noqa: F401
        # Use 4-bit quantization to prevent OOM halts on consumer GPUs/CPUs
        model_kwargs["load_in_4bit"] = True
        model_kwargs["device_map"] = "auto"
        print("Detected bitsandbytes. Loading model in 4-bit quantized mode to conserve memory.")
    except ImportError:
        model_kwargs["device_map"] = "auto"
        print("bitsandbytes not detected. Loading model with auto device mapping.")

    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        **model_kwargs,
    )
    # Manual .to(device) is not allowed and will throw/OOM when device_map is used
    if "device_map" not in model_kwargs and device.type != "cpu":
        model.to(device)
    model.eval()
    return model, tokenizer
