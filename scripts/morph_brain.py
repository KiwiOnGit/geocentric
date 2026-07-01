#!/usr/bin/env python3
"""Interactive Fluid Brain Morphing script.

Usage: run from repo root. Drag-and-drop your .pt checkpoint into the terminal when prompted.
"""
from pathlib import Path
import sys

# ensure repo root is importable when running script directly
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import torch

from geocentric.model import GeocentricGPT, GPTConfig
from geocentric.param_compiler import compute_fluid_dimensions


def fluid_morph_surgery():
    print("====================================================")
    print("🧠 GEOCENTRIC FLUID BRAIN SURGERY ENGINE")
    print("====================================================\n")

    # DRAG & DROP UX INTERFACE INTEGRATION
    print("📥 Drag and drop your trained checkpoint file (.pt) directly into this window, then press Enter.")
    src_input = input("Checkpoint path [default: runs/geocentric2_1/geocentric2_1_pretrained.pt]: ").strip()

    # Clean common drag-and-drop artifacts (wrapping quotes, stray spaces)
    src_input = (src_input or "").strip()
    if src_input.startswith(('"', "'")) and src_input.endswith(('"', "'")):
        src_input = src_input[1:-1]
    src_input = src_input.strip()

    src_path = Path(src_input if src_input else "runs/geocentric2_1/geocentric2_1_pretrained.pt").expanduser()

    if not src_path.exists():
        print(f"❌ Aborted. Could not locate source file: {src_path}")
        return

    target_input = input("\n🎯 Enter your fluid parameter target size for expansion (e.g., 350m, 1b, 2.5b): ").strip()
    if not target_input:
        print("❌ Aborted. Target size cannot be empty.")
        return

    # 1. Load checkpoint
    try:
        checkpoint = torch.load(src_path, map_location="cpu")
    except Exception as e:
        print(f"❌ Failed to load checkpoint {src_path}: {e}")
        return

    # Support different checkpoint key names used across the codebase
    orig_state = checkpoint.get("model_state") or checkpoint.get("model_state_dict") or checkpoint.get("model_state_dict", {})
    if orig_state is None:
        orig_state = {}

    cfg = checkpoint.get("config") or {}
    if isinstance(cfg, dict):
        vocab_size = int(cfg.get("vocab_size", 32000))
    elif hasattr(cfg, "vocab_size"):
        vocab_size = int(getattr(cfg, "vocab_size"))
    else:
        vocab_size = 32000

    # 2. Compute target dimensions
    dims = compute_fluid_dimensions(target_input, vocab_size=vocab_size)

    print("\n🏗️  COMPILING DYNAMIC ARCHITECTURE TARGETS:")
    print(f" ├─ Hidden Dimension (n_embd): {dims['n_embd']}")
    print(f" ├─ Target Layer Count (n_layer): {dims['n_layer']}")
    print(f" ├─ Attention Heads (n_head): {dims['n_head']}")
    print(f" └─ Context Block Size (block_size): {dims['block_size']}")

    new_config = GPTConfig(
        vocab_size=vocab_size,
        block_size=dims["block_size"],
        n_layer=dims["n_layer"],
        n_head=dims["n_head"],
        n_embd=dims["n_embd"],
        dropout=0.1,
    )

    # 3. Instantiate target model skeleton and state dict
    target_model = GeocentricGPT(new_config)
    new_state = target_model.state_dict()

    # 4. Determine original block naming pattern
    orig_has_transformer_h = any(k.startswith("transformer.h.") for k in orig_state.keys())
    orig_has_blocks = any(k.startswith("blocks.") for k in orig_state.keys())

    # Heuristic: new model uses 'blocks.<i>.' while older checkpoints might use 'transformer.h.<i>.'
    orig_block_prefix = None
    if orig_has_transformer_h:
        orig_block_prefix = "transformer.h"
    elif orig_has_blocks:
        orig_block_prefix = "blocks"

    # Collect original layer indices
    orig_layer_indices = set()
    for k in orig_state.keys():
        # pattern 'blocks.<i>.' or 'transformer.h.<i>.'
        if k.startswith("blocks.") or k.startswith("transformer.h."):
            parts = k.split('.')
            for part in parts:
                if part.isdigit():
                    orig_layer_indices.add(int(part))
                    break
    num_orig_layers = max(orig_layer_indices) + 1 if orig_layer_indices else 1

    # Helper to copy overlapping regions when shapes differ
    def copy_compatible(target_tensor, source_tensor):
        if target_tensor.shape == source_tensor.shape:
            target_tensor.copy_(source_tensor)
            return True
        # allow partial copy across same-dim tensors
        if target_tensor.dim() == source_tensor.dim():
            slices = tuple(slice(0, min(s, t)) for s, t in zip(source_tensor.shape, target_tensor.shape))
            try:
                target_tensor[slices].copy_(source_tensor[slices])
                return True
            except Exception:
                return False
        return False

    # 5. Graft parameters
    print("\n✂️  Performing matrix grafting...")
    copied = 0
    skipped = 0

    for name, param in new_state.items():
        # handle block-layer parameters specially
        if name.startswith("blocks."):
            # new naming 'blocks.<new_idx>.<rest>'
            try:
                _, new_idx_str, rest = name.split('.', 2)
                new_idx = int(new_idx_str)
            except Exception:
                # fallback to naive copy if parsing fails
                src = orig_state.get(name)
                if src is not None and copy_compatible(param, src):
                    copied += 1
                else:
                    skipped += 1
                continue

            # map new index into original depth
            orig_idx = int((new_idx / max(1, new_config.n_layer)) * num_orig_layers)
            orig_idx = min(orig_idx, num_orig_layers - 1)

            # attempt to build candidate original name using known prefix
            candidates = []
            if orig_block_prefix:
                candidates.append(f"{orig_block_prefix}.{orig_idx}.{rest}")
            # also try same 'blocks' naming as fallback
            candidates.append(f"blocks.{orig_idx}.{rest}")
            candidates.append(f"transformer.h.{orig_idx}.{rest}")

            found_src = None
            for cand in candidates:
                if cand in orig_state:
                    found_src = orig_state[cand]
                    break

            if found_src is not None:
                if copy_compatible(param, found_src):
                    copied += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        else:
            # Non-block parameters (embeddings, ln_f, lm_head, etc.)
            src = orig_state.get(name)
            # Try some common legacy names
            if src is None:
                alt = name.replace('token_embedding', 'transformer.wte')
                src = orig_state.get(alt, src)
            if src is None:
                src = orig_state.get(name.replace('blocks', 'transformer.h'))

            if src is not None:
                if copy_compatible(param, src):
                    copied += 1
                else:
                    skipped += 1
            else:
                skipped += 1

    print(f"Copied tensors: {copied}, skipped/mismatched: {skipped}")

    # 6. Save the morph output
    dest_path = src_path.parent / f"geocentric_{target_input.lower()}_base.pt"
    checkpoint["model_state"] = new_state
    checkpoint["config"] = new_config.__dict__

    try:
        torch.save(checkpoint, dest_path)
    except Exception as e:
        print(f"❌ Failed to save morphed checkpoint: {e}")
        return

    print(f"\n🎉 Successfully expanded and created fluid morphed brain: {dest_path}")


if __name__ == "__main__":
    fluid_morph_surgery()
