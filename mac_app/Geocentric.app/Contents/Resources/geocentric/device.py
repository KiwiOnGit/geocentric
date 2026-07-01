from __future__ import annotations

import platform
from dataclasses import dataclass

import psutil
import torch


@dataclass(frozen=True)
class RuntimeInfo:
    device: torch.device
    dtype: torch.dtype
    mps_built: bool
    mps_available: bool
    cuda_available: bool
    total_memory_gb: float
    available_memory_gb: float


def select_device(prefer_cuda: bool = True, prefer_mps: bool = True) -> torch.device:
    """Pick NVIDIA CUDA or Apple MPS when available, otherwise CPU."""
    if prefer_cuda and torch.cuda.is_available():
        return torch.device("cuda")
    if prefer_mps and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def resolve_dtype(device: torch.device, requested: str = "auto") -> torch.dtype:
    """Resolve model dtype. bfloat16/float32 is safer for training stability without a GradScaler."""
    key = requested.lower().strip()
    if key in {"float32", "fp32", "32"}:
        return torch.float32
    if key in {"float16", "fp16", "16", "half"}:
        return torch.float16
    if key in {"bfloat16", "bf16", "bf"}:
        return torch.bfloat16
    if key == "auto":
        if device.type == "cuda":
            props = torch.cuda.get_device_properties(device)
            if props.major >= 8 and torch.cuda.is_bf16_supported():
                return torch.bfloat16
            return torch.float16
        if device.type == "mps":
            # MPS supports bfloat16 in newer PyTorch, which is much safer than float16 for training stability
            return torch.bfloat16
        return torch.float32
    if key in {"bfloat16", "bf16", "bf"}:
        if device.type == "cuda":
            props = torch.cuda.get_device_properties(device)
            if props.major < 8 or not torch.cuda.is_bf16_supported():
                raise ValueError(
                    "bfloat16 is not supported on this CUDA GPU. Use --dtype float16 or auto instead."
                )
        return torch.bfloat16
    raise ValueError(f"Unsupported dtype: {requested}")


def runtime_check(device: torch.device, dtype: torch.dtype) -> RuntimeInfo:
    memory = psutil.virtual_memory()
    info = RuntimeInfo(
        device=device,
        dtype=dtype,
        mps_built=torch.backends.mps.is_built(),
        mps_available=torch.backends.mps.is_available(),
        cuda_available=torch.cuda.is_available(),
        total_memory_gb=memory.total / 1024**3,
        available_memory_gb=memory.available / 1024**3,
    )

    print("=" * 80)
    print("Geocentric 2.1 runtime check")
    print("=" * 80)
    print(f"Platform: {platform.platform()}")
    print(f"Python: {platform.python_version()}")
    print(f"PyTorch: {torch.__version__}")
    print(f"MPS built: {info.mps_built}")
    print(f"MPS available: {info.mps_available}")
    print(f"CUDA available: {info.cuda_available}")
    if info.cuda_available:
        print(f"CUDA device count: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f"  Device {i}: {torch.cuda.get_device_name(i)}")
    print(f"Selected device: {info.device}")
    print(f"Selected dtype: {info.dtype}")
    print(f"System memory total: {info.total_memory_gb:.2f} GB")
    print(f"System memory available: {info.available_memory_gb:.2f} GB")

    try:
        torch.set_float32_matmul_precision("high")
    except Exception:
        pass

    if device.type == "mps":
        probe = torch.ones((8, 8), device=device, dtype=torch.float16)
        probe = probe @ probe
        torch.mps.synchronize()
        print(f"MPS probe mean: {probe.float().mean().item():.4f}")
        print("Mac GPU communication: OK")
    elif device.type == "cuda":
        # TF32 gives ~8x throughput vs FP32 on Ampere+ for matmuls and convolutions.
        # Both flags are required — matmul covers Linear layers, cudnn covers everything else.
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        probe = torch.ones((8, 8), device=device, dtype=torch.float16)
        probe = probe @ probe
        torch.cuda.synchronize()
        print(f"CUDA probe mean: {probe.float().mean().item():.4f}")
        print(f"NVIDIA GPU communication: OK (Device: {torch.cuda.get_device_name(device)})")
    else:
        print("MPS and CUDA unavailable. Running on CPU.")

    print("=" * 80)
    return info


def cleanup_mps() -> None:
    """Clear cached memory on MPS or CUDA devices."""
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

