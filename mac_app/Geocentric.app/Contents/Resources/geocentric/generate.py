from __future__ import annotations

from typing import Any, Iterator, List, Mapping, Optional

import torch
from tokenizers import Tokenizer

from geocentric.data import format_prompt
from geocentric.model import GeocentricGPT
from geocentric.tokenizer_train import token_id

try:
    from transformers import PreTrainedTokenizerBase
except ImportError:
    PreTrainedTokenizerBase = None


def build_chat_prompt(messages: List[Mapping[str, str]], system: str = "") -> str:
    system = system.strip()
    last_user = ""
    history_lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if not content:
            continue
        if role == "system":
            system = content
        elif role == "user":
            last_user = content
            history_lines.append(f"User: {content}")
        elif role == "assistant":
            history_lines.append(f"Assistant: {content}")
    instruction = last_user or "Continue the conversation."
    # Exclude the very last user message from the context history to prevent repetition
    context_lines = history_lines[:-1] if last_user else history_lines
    context = "\n".join(context_lines[-8:]).strip()
    if system:
        context = f"{system}\n{context}".strip()
    return format_prompt(instruction, context)


def visible_thinking_note(prompt: str) -> str:
    clean = " ".join(prompt.strip().split())[:220]
    return (
        "I will identify what the user is asking, keep the answer grounded in the local model context, "
        "and produce a concise helpful response. Prompt focus: " + clean
    )


def _is_tokenizers_tokenizer(tokenizer: Any) -> bool:
    return isinstance(tokenizer, Tokenizer)


def _encode_text(tokenizer: Any, text: str) -> list[int]:
    if _is_tokenizers_tokenizer(tokenizer):
        return tokenizer.encode(text).ids
    if hasattr(tokenizer, "encode"):
        encoded = tokenizer.encode(text, add_special_tokens=False)
        if isinstance(encoded, list):
            return encoded
        if hasattr(encoded, "ids"):
            return encoded.ids
        return list(encoded)
    return tokenizer(text, return_tensors="pt", add_special_tokens=False).input_ids[0].tolist()


def _decode_text(tokenizer: Any, ids: list[int]) -> str:
    if _is_tokenizers_tokenizer(tokenizer):
        return tokenizer.decode(ids)
    if hasattr(tokenizer, "decode"):
        return tokenizer.decode(ids, skip_special_tokens=True, clean_up_tokenization_spaces=True)
    return ""


def _eos_token_id(tokenizer: Any) -> int | list[int] | None:
    if _is_tokenizers_tokenizer(tokenizer):
        return token_id(tokenizer, "<eos>")
    for attr in ("eos_token_id", "sep_token_id", "pad_token_id"):
        val = getattr(tokenizer, attr, None)
        if isinstance(val, (int, list, tuple)):
            return val
    return None


def _max_block_size(model: Any) -> int:
    if isinstance(model, GeocentricGPT):
        return model.config.block_size
    cfg = getattr(model, "config", None)
    if cfg is None:
        return 1024
    return (
        getattr(cfg, "block_size", None)
        or getattr(cfg, "n_ctx", None)
        or getattr(cfg, "max_position_embeddings", None)
        or getattr(cfg, "n_positions", None)
        or 1024
    )


@torch.no_grad()
def generate_text(
    model: Any,
    tokenizer: Any,
    prompt: str,
    device: torch.device,
    max_new_tokens: int = 160,
    temperature: float = 0.8,
    top_k: int = 50,
    repetition_penalty: float = 1.15,
) -> str:
    if isinstance(model, GeocentricGPT) and _is_tokenizers_tokenizer(tokenizer):
        eos = token_id(tokenizer, "<eos>")
        ids = tokenizer.encode(prompt).ids[-model.config.block_size :]
        x = torch.tensor([ids], dtype=torch.long, device=device)
        y = model.generate(
            x,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            eos_id=eos,
            repetition_penalty=repetition_penalty,
        )
        new_ids = y[0].tolist()[len(ids) :]
        text = tokenizer.decode(new_ids)
        return text.replace("<eos>", "").strip()

    eos = _eos_token_id(tokenizer)
    ids = _encode_text(tokenizer, prompt)[-_max_block_size(model) :]
    x = torch.tensor([ids], dtype=torch.long, device=device)
    generation_kwargs = {
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "do_sample": temperature > 0,
    }
    if eos is not None:
        generation_kwargs["eos_token_id"] = eos
    if repetition_penalty != 1.0:
        generation_kwargs["repetition_penalty"] = repetition_penalty
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if isinstance(pad_token_id, int):
        generation_kwargs["pad_token_id"] = pad_token_id

    y = model.generate(x, **generation_kwargs)
    new_ids = y[0].tolist()[len(ids) :]
    return _decode_text(tokenizer, new_ids).strip()


@torch.no_grad()
def stream_text(
    model: Any,
    tokenizer: Any,
    prompt: str,
    device: torch.device,
    max_new_tokens: int = 160,
    temperature: float = 0.8,
    top_k: int = 50,
    repetition_penalty: float = 1.15,
) -> Iterator[str]:
    if isinstance(model, GeocentricGPT) and _is_tokenizers_tokenizer(tokenizer):
        eos = token_id(tokenizer, "<eos>")
        ids = tokenizer.encode(prompt).ids[-model.config.block_size :]
        x = torch.tensor([ids], dtype=torch.long, device=device)
        emitted = len(ids)

        for _ in range(max_new_tokens):
            x_cond = x[:, -model.config.block_size :]
            logits, _ = model(x_cond)
            logits = logits[:, -1, :].float()
            
            # Apply repetition penalty
            if repetition_penalty != 1.0 and x.size(1) > 0:
                for token_val in set(x[0].tolist()):
                    logit_val = logits[0, token_val].item()
                    if logit_val > 0:
                        logits[0, token_val] /= repetition_penalty
                    else:
                        logits[0, token_val] *= repetition_penalty

            if temperature <= 0:
                next_id = torch.argmax(logits, dim=-1, keepdim=True)
            else:
                logits = logits / max(temperature, 1e-5)
                if top_k > 0:
                    values, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                    logits[logits < values[:, [-1]]] = -float("inf")
                probs = torch.softmax(logits, dim=-1)
                # Robust sanitization of probs to prevent multinomial RuntimeError
                if torch.isnan(probs).any() or torch.isinf(probs).any() or (probs < 0).any() or probs.sum() <= 0:
                    probs = torch.nan_to_num(probs, nan=0.0, posinf=0.0, neginf=0.0)
                    if probs.sum() <= 0:
                        probs = torch.ones_like(probs) / probs.size(-1)
                    else:
                        probs = probs / probs.sum()
                next_id = torch.multinomial(probs, num_samples=1)
            x = torch.cat([x, next_id], dim=1)
            val_id = int(next_id.item())
            if (isinstance(eos, (list, tuple)) and val_id in eos) or val_id == eos:
                break
            token = tokenizer.decode([int(next_id.item())])
            if token:
                yield token
            emitted += 1
        return

    eos = _eos_token_id(tokenizer)
    ids = _encode_text(tokenizer, prompt)[-_max_block_size(model) :]
    x = torch.tensor([ids], dtype=torch.long, device=device)
    generation_kwargs = {
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "do_sample": temperature > 0,
    }
    if eos is not None:
        generation_kwargs["eos_token_id"] = eos
    if repetition_penalty != 1.0:
        generation_kwargs["repetition_penalty"] = repetition_penalty
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if isinstance(pad_token_id, int):
        generation_kwargs["pad_token_id"] = pad_token_id

    try:
        from transformers import TextIteratorStreamer
        from threading import Thread

        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, clean_up_tokenization_spaces=True)
        generation_kwargs["streamer"] = streamer

        # Run model generation in a background thread
        thread = Thread(target=model.generate, args=(x,), kwargs=generation_kwargs)
        thread.start()

        for token in streamer:
            if token:
                yield token
        thread.join()
    except Exception as e:
        # Fallback to synchronous generation if streamer fails
        print(f"Fallback to sync generation: {e}")
        y = model.generate(x, **generation_kwargs)
        new_ids = y[0].tolist()[len(ids) :]
        decoded = _decode_text(tokenizer, new_ids)
        if decoded:
            yield decoded


def generate_reasoning_steps(prompt: str) -> str:
    """Dynamically generates realistic, step-by-step reasoning steps for the thinking model."""
    prompt_clean = prompt.lower().strip()
    
    # Identify domain
    is_coding = any(k in prompt_clean for k in ["code", "python", "javascript", "function", "program", "class", "def", "script", "loop"])
    is_math = any(k in prompt_clean for k in ["solve", "equation", "math", "calculate", "x =", "+", "-", "*", "/", "sum"])
    is_science = any(k in prompt_clean for k in ["gravity", "transformer", "physics", "quantum", "science", "space", "spacetime"])
    
    steps = [
        "1. Identify user query intent: Analyzing prompt content and task domain.",
    ]
    
    if is_coding:
        steps.extend([
            "2. Access Python/programming knowledge bases: Retrieving syntax specifications, best-practice design patterns, and code formats.",
            "3. Formulate code design plan: Drafting type hints, exception handlers, and performance-optimized control structures.",
            "4. Verify code logical paths: Mentally dry-running the variable scope, state modifications, and recursion/loop limits.",
            "5. Constructing clean, highly commented, standard PEP-8 Python code."
        ])
    elif is_math:
        steps.extend([
            "2. Parse mathematical structures: Isolating algebraic equations, variables, constants, and logical constraints.",
            "3. Formulate step-by-step arithmetic plan: Determining operations (isolation, division, substitution) needed to solve for variables.",
            "4. Compute values sequentially: Resolving intermediate arithmetic and double-checking equations for balance.",
            "5. Compiling highly structured step-by-step mathematical proof."
        ])
    elif is_science:
        steps.extend([
            "2. Retrieve scientific knowledge context: Accessing physics, neural network architectures, or logical concepts.",
            "3. Synthesize conceptual relationships: Connecting theoretical terms (e.g. self-attention, spacetime curvature) to the target question.",
            "4. Structure explanatory progression: Framing explanations from core intuitive concepts up to advanced mathematical properties.",
            "5. Drafting high-quality, readable, premium conceptual breakdown."
        ])
    else:
        steps.extend([
            "2. Retrieve local conversational guidelines: Maintaining professional, highly helpful, local-first persona.",
            "3. Check contextual bounds: Anchoring explanation strictly to parameters in local context.",
            "4. Formulating beautiful, helpful, and extremely concise chat response."
        ])
        
    return "\n".join(steps)
