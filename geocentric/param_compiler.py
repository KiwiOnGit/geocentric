import math
from typing import Dict, Any


def parse_param_string(size_str: str) -> int:
    """Converts strings like '350m', '1.2b', '110M' into exact raw integers."""
    cleaned = size_str.strip().lower().replace("'", "").replace('"', "")
    if cleaned.endswith("m"):
        return int(float(cleaned[:-1]) * 1_000_000)
    elif cleaned.endswith("b"):
        return int(float(cleaned[:-1]) * 1_000_000_000)
    else:
        # Allow plain numeric strings
        return int(float(cleaned))


def compute_fluid_dimensions(target_size_str: str, vocab_size: int = 32000) -> Dict[str, Any]:
    """
    Reverse-engineers a mathematically balanced GPT config from a fluid parameter target.
    Balances the quadratic growth of the FFN layers alongside the embedding overhead.
    """
    target_params = parse_param_string(target_size_str)

    # 1. Deduct non-hidden structural components (Embedding & Language Model Head)
    # Assume embedding matrices for token + head weight tying
    embedding_params = vocab_size * 1024
    available_params = target_params - (embedding_params * 2)

    if available_params <= 0:
        raise ValueError(f"Target size {target_size_str} is too small to contain a {vocab_size} vocab matrix.")

    # 2. Heuristically derive ideal hidden size (n_embd) using typical scaling laws
    if target_params < 250_000_000:
        n_embd = 768
    elif target_params < 600_000_000:
        n_embd = 1024
    elif target_params < 2_000_000_000:
        n_embd = 2048
    else:
        n_embd = 4096

    # 3. Calculate parameter cost per individual layer block
    # Self-Attention (4 * n_embd^2) + FFN (8 * n_embd^2) = 12 * n_embd^2
    params_per_layer = 12 * (n_embd ** 2)

    # 4. Deriving the required layers
    n_layer = max(2, round(available_params / params_per_layer))

    # 5. Calculate matching attention heads (Must divide evenly)
    n_head = n_embd // 64 if (n_embd // 64) > 0 else 12

    # Context block constraints to preserve local system RAM / RAM overhead
    block_size = 256 if target_params < 1_000_000_000 else 512

    return {
        "n_layer": int(n_layer),
        "n_head": int(n_head),
        "n_embd": int(n_embd),
        "block_size": int(block_size),
        "intermediate_size": int(4 * n_embd),
    }
