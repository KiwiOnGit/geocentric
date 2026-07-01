"""Layer-by-layer model offloading utilities for training large models on limited VRAM."""

from __future__ import annotations

import torch
import torch.nn as nn
from typing import Optional


def offload_forward_pass(
    model: nn.Module,
    input_ids: torch.Tensor,
    device: torch.device,
    embeddings_device: str = "cpu",
) -> torch.Tensor:
    """
    Execute forward pass with sequential layer offloading.
    Only one layer at a time lives on GPU; all others remain on CPU.
    """
    # 1. Move embeddings to GPU, compute, evict
    model.token_embedding.to(device)
    model.position_embedding.to(device)
    
    b, t = input_ids.shape
    pos = torch.arange(0, t, dtype=torch.long, device=device)
    x = model.token_embedding(input_ids) + model.position_embedding(pos)[None, :, :]
    x = model.dropout(x)
    
    model.token_embedding.to(embeddings_device)
    model.position_embedding.to(embeddings_device)
    torch.cuda.empty_cache()
    
    # 2. Sequential layer processing
    for block_idx, block in enumerate(model.blocks):
        block.to(device)
        x = block(x)
        block.to(embeddings_device)
        torch.cuda.empty_cache()
    
    # 3. Final layer norm to GPU
    model.ln_f.to(device)
    x = model.ln_f(x)
    model.ln_f.to(embeddings_device)
    torch.cuda.empty_cache()
    
    # 4. Language model head to GPU
    model.lm_head.to(device)
    logits = model.lm_head(x)
    model.lm_head.to(embeddings_device)
    torch.cuda.empty_cache()
    
    return logits


def offload_training_step(
    model: nn.Module,
    batch: dict,
    device: torch.device,
    scaler: Optional[torch.amp.GradScaler] = None,
    use_amp: bool = False,
) -> torch.Tensor:
    """
    Compute training step with layer-by-layer offloading and return loss.
    """
    input_ids = batch["input_ids"].to(device)
    labels = batch["labels"].to(device)
    
    # Forward pass with offloading
    logits = offload_forward_pass(model, input_ids, device, embeddings_device="cpu")
    
    # Compute loss
    loss = torch.nn.functional.cross_entropy(
        logits.view(-1, logits.size(-1)),
        labels.view(-1),
        ignore_index=-100,
    )
    
    return loss


class HardwareAwareOffloadEngine:
    """Asynchronous, hardware-aware offload engine using pinned host memory and CUDA streams.

    This engine stages module parameters into page-locked host memory and streams layer
    tensors asynchronously to the GPU while the previous layer computes.
    """

    def __init__(self, model: nn.Module, compute_device: torch.device):
        self.model = model
        self.device = compute_device
        self.memory_stream = torch.cuda.Stream() if self.device.type == "cuda" else None
        self._pin_model_parameters()

    def _pin_model_parameters(self) -> None:
        """Pin model parameter tensors in host memory to enable DMA transfers."""
        if self.device.type != "cuda":
            return
        print("🔒 Page-locking parameters into System RAM sticks...")
        for p in self.model.parameters():
            try:
                if not p.is_pinned():
                    # Move to CPU first then pin the underlying storage
                    p_cpu = p.detach().to("cpu")
                    p.data = p_cpu.pin_memory()
            except Exception:
                # Not all storages support pinning; skip gracefully
                continue

    def execute_forward_pass(self, input_ids: torch.Tensor) -> torch.Tensor:
        # Embedding stage: move embedding weights, compute, evict
        if self.device.type == "cuda":
            # non-blocking transfer using pinned memory
            self.model.token_embedding.to(self.device, non_blocking=True)
        hidden_states = self.model.token_embedding(input_ids)
        if self.device.type == "cuda":
            self.model.token_embedding.to("cpu", non_blocking=True)

        num_layers = len(self.model.blocks)

        for i in range(num_layers):
            current_layer = self.model.blocks[i]

            # Stage current layer to GPU
            if self.device.type == "cuda":
                current_layer.to(self.device, non_blocking=True)

            # Pre-fetch next layer while computing current
            if i + 1 < num_layers and self.memory_stream is not None:
                with torch.cuda.stream(self.memory_stream):
                    try:
                        self.model.blocks[i + 1].to(self.device, non_blocking=True)
                    except Exception:
                        pass

            hidden_states = current_layer(hidden_states)

            # Evict current layer back to CPU
            if self.device.type == "cuda":
                current_layer.to("cpu", non_blocking=True)

            # Periodically clear cache to mitigate fragmentation
            if i % 2 == 0:
                if self.device.type == "cuda":
                    torch.cuda.empty_cache()
                elif hasattr(torch, "mps"):
                    try:
                        torch.mps.empty_cache()
                    except Exception:
                        pass

        # Final norm and head
        if self.device.type == "cuda":
            self.model.ln_f.to(self.device, non_blocking=True)
        hidden_states = self.model.ln_f(hidden_states)
        if self.device.type == "cuda":
            self.model.ln_f.to("cpu", non_blocking=True)

        if self.device.type == "cuda":
            self.model.lm_head.to(self.device, non_blocking=True)
        logits = self.model.lm_head(hidden_states)
        if self.device.type == "cuda":
            self.model.lm_head.to("cpu", non_blocking=True)

        return logits
