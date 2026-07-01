from __future__ import annotations

import json
import platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import psutil
import torch


@dataclass(frozen=True)
class HardwareProfile:
    kind: str
    name: str
    total_memory_gb: float
    available_memory_gb: float
    compute_capability: str | None = None
    bf16_supported: bool = False


def detect_hardware() -> HardwareProfile:
    memory = psutil.virtual_memory()
    total_gb = memory.total / 1024**3
    available_gb = memory.available / 1024**3

    if torch.cuda.is_available():
        device = torch.device("cuda")
        props = torch.cuda.get_device_properties(device)
        major, minor = props.major, props.minor
        return HardwareProfile(
            kind="cuda",
            name=torch.cuda.get_device_name(device),
            total_memory_gb=props.total_memory / 1024**3,
            available_memory_gb=available_gb,
            compute_capability=f"{major}.{minor}",
            bf16_supported=bool(getattr(torch.cuda, "is_bf16_supported", lambda: False)()),
        )

    if torch.backends.mps.is_available():
        machine = platform.machine() or "Apple Silicon"
        return HardwareProfile(
            kind="mps",
            name=f"Apple Silicon GPU ({machine})",
            total_memory_gb=total_gb,
            available_memory_gb=available_gb,
            bf16_supported=True,
        )

    return HardwareProfile(
        kind="cpu",
        name=platform.processor() or platform.machine() or "CPU",
        total_memory_gb=total_gb,
        available_memory_gb=available_gb,
    )


def _profile_defaults(profile: HardwareProfile, speed_profile: str) -> dict[str, Any]:
    speed_profile = (speed_profile or "max_speed").strip().lower()

    if profile.kind == "cuda":
        vram = profile.total_memory_gb
        if vram < 7.5:
            base = dict(preset="50m", block_size=256, batch_size=12, sft_batch_size=8, gradient_accumulation_steps=8)
        elif vram < 11.5:
            base = dict(preset="80m", block_size=256, batch_size=16, sft_batch_size=12, gradient_accumulation_steps=6)
        elif vram < 20:
            base = dict(preset="120m", block_size=384, batch_size=18, sft_batch_size=12, gradient_accumulation_steps=4)
        else:
            base = dict(preset="330m", block_size=512, batch_size=12, sft_batch_size=8, gradient_accumulation_steps=4)
        base.update(
            dtype="bfloat16" if profile.bf16_supported else "float16",
            gradient_checkpointing=False,
            offload_layers=False,
            num_workers=max(2, min(8, (psutil.cpu_count(logical=True) or 4) - 1)),
            metrics_every=25,
            save_every=250,
            compile_mode="auto",
        )
        if speed_profile == "safe":
            base["batch_size"] = max(2, int(base["batch_size"] * 0.5))
            base["sft_batch_size"] = max(2, int(base["sft_batch_size"] * 0.5))
            base["gradient_accumulation_steps"] = max(base["gradient_accumulation_steps"], 12)
            base["gradient_checkpointing"] = True
        elif speed_profile == "balanced":
            base["batch_size"] = max(2, int(base["batch_size"] * 0.75))
            base["sft_batch_size"] = max(2, int(base["sft_batch_size"] * 0.75))
        return base

    if profile.kind == "mps":
        mem = profile.total_memory_gb
        if mem < 12:
            base = dict(preset="25m", block_size=192, batch_size=6, sft_batch_size=4, gradient_accumulation_steps=10)
        elif mem < 20:
            base = dict(preset="50m", block_size=256, batch_size=8, sft_batch_size=6, gradient_accumulation_steps=8)
        elif mem < 40:
            base = dict(preset="80m", block_size=256, batch_size=10, sft_batch_size=8, gradient_accumulation_steps=6)
        else:
            base = dict(preset="120m", block_size=384, batch_size=8, sft_batch_size=6, gradient_accumulation_steps=6)
        base.update(
            dtype="auto",
            gradient_checkpointing=False,
            offload_layers=False,
            num_workers=0,
            metrics_every=25,
            save_every=250,
            compile_mode="off",
        )
        if speed_profile == "safe":
            base["batch_size"] = max(2, int(base["batch_size"] * 0.6))
            base["sft_batch_size"] = max(2, int(base["sft_batch_size"] * 0.6))
            base["gradient_accumulation_steps"] = max(base["gradient_accumulation_steps"], 12)
        elif speed_profile == "balanced":
            base["batch_size"] = max(2, int(base["batch_size"] * 0.8))
            base["sft_batch_size"] = max(2, int(base["sft_batch_size"] * 0.8))
        return base

    base = dict(
        preset="25m",
        block_size=128,
        batch_size=2,
        sft_batch_size=2,
        gradient_accumulation_steps=16,
        dtype="float32",
        gradient_checkpointing=True,
        offload_layers=False,
        num_workers=max(0, min(4, (psutil.cpu_count(logical=True) or 2) - 1)),
        metrics_every=50,
        save_every=500,
        compile_mode="off",
    )
    return base


def optimized_training_overrides(command: str, speed_profile: str = "max_speed") -> tuple[HardwareProfile, dict[str, Any]]:
    profile = detect_hardware()
    config = _profile_defaults(profile, speed_profile)

    command = command.lower().strip()
    if command == "sft":
        config.pop("preset", None)
        config.pop("block_size", None)
    elif command == "pretrain":
        config.pop("sft_batch_size", None)

    return profile, config


def apply_overrides(payload: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    for key, value in overrides.items():
        if value is not None and key in updated:
            updated[key] = value
    return updated


def print_plan(command: str, profile: HardwareProfile, overrides: dict[str, Any]) -> None:
    print("\n" + "=" * 80)
    print("HARDWARE SPEED PLAN")
    print("=" * 80)
    print(f"Command: {command}")
    print(f"Detected: {profile.kind.upper()} - {profile.name}")
    print(f"Memory: {profile.total_memory_gb:.2f} GB total, {profile.available_memory_gb:.2f} GB system available")
    if profile.compute_capability:
        print(f"CUDA compute capability: {profile.compute_capability}")
    print("Optimized settings:")
    for key in sorted(overrides):
        print(f"  {key}: {overrides[key]}")
    print("=" * 80 + "\n")


def slugify_model_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return cleaned or "geocentric_custom"


def save_capabilities(output_dir: str | Path, modelver: str, capabilities: str, profile: HardwareProfile | None = None) -> Path:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": modelver,
        "capabilities": capabilities.strip(),
        "hardware": asdict(profile) if profile else None,
    }
    path = out / "capabilities.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved chatbot capability plan to: {path}")
    return path


def _read_sft_rows(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"SFT data file does not exist: {p}")
    if p.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
        return rows
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
    return []


def capability_examples(modelver: str, capabilities: str) -> list[dict[str, str]]:
    cap = capabilities.strip()
    return [
        {
            "instruction": "Introduce yourself and explain what you are built to help with.",
            "input": "",
            "output": f"I am {modelver}. I am built to help with: {cap}",
        },
        {
            "instruction": "What are your main capabilities?",
            "input": "",
            "output": f"My main capabilities are: {cap}",
        },
        {
            "instruction": "How should you answer when a user asks for something outside your capabilities?",
            "input": "",
            "output": "I should be honest about the limit, avoid pretending, and offer the closest useful safe alternative.",
        },
        {
            "instruction": "Follow the model capability plan while helping the user.",
            "input": cap,
            "output": "Understood. I will focus my answers around those capabilities, prioritize useful step-by-step help, and stay honest when something is uncertain.",
        },
    ]


def merge_capability_sft_data(sft_data_path: str | Path, output_dir: str | Path, modelver: str, capabilities: str) -> str:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = capability_examples(modelver, capabilities)
    rows.extend(_read_sft_rows(sft_data_path))
    merged_path = out / "capability_augmented_sft.json"
    merged_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Capability SFT seed examples merged into: {merged_path}")
    return str(merged_path)


def first_existing(paths: Iterable[str]) -> str | None:
    for raw in paths:
        p = Path(raw).expanduser()
        if p.exists():
            return str(p)
    return None
