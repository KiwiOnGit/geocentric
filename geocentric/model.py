from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class GPTConfig:
    vocab_size: int
    block_size: int = 256
    n_layer: int = 6
    n_head: int = 6
    n_embd: int = 384
    dropout: float = 0.1
    bias: bool = True
    model_name: str = "Geocentric 2.1"
    gradient_checkpointing: bool = False

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "GPTConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            vocab_size=data.get("vocab_size", data.get("vocab_size", 0)),
            block_size=data.get("block_size", data.get("max_position_embeddings", 256)),
            n_layer=data.get("n_layer", data.get("num_hidden_layers", 6)),
            n_head=data.get("n_head", data.get("num_attention_heads", 6)),
            n_embd=data.get("n_embd", data.get("hidden_size", 384)),
            dropout=data.get("dropout", 0.1),
            bias=data.get("bias", True),
            model_name=data.get("model_name", data.get("model_type", "Geocentric 2.1")),
            gradient_checkpointing=data.get("gradient_checkpointing", False),
        )


class CausalSelfAttention(nn.Module):
    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        if config.n_embd % config.n_head != 0:
            raise ValueError("n_embd must be divisible by n_head")
        self.n_head = config.n_head
        self.head_dim = config.n_embd // config.n_head
        self.qkv = nn.Linear(config.n_embd, 3 * config.n_embd, bias=config.bias)
        self.proj = nn.Linear(config.n_embd, config.n_embd, bias=config.bias)
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)
        mask = torch.tril(torch.ones(config.block_size, config.block_size, dtype=torch.bool))
        self.register_buffer("causal_mask", mask.view(1, 1, config.block_size, config.block_size), persistent=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, t, c = x.shape
        q, k, v = self.qkv(x).split(c, dim=2)
        q = q.view(b, t, self.n_head, self.head_dim).transpose(1, 2)
        k = k.view(b, t, self.n_head, self.head_dim).transpose(1, 2)
        v = v.view(b, t, self.n_head, self.head_dim).transpose(1, 2)

        if hasattr(F, "scaled_dot_product_attention"):
            y = F.scaled_dot_product_attention(
                q,
                k,
                v,
                attn_mask=None,
                dropout_p=self.attn_dropout.p if self.training else 0.0,
                is_causal=True,
            )
        else:
            att = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)
            att = att.masked_fill(~self.causal_mask[:, :, :t, :t], torch.finfo(att.dtype).min)
            att = F.softmax(att.float(), dim=-1).to(q.dtype)
            att = self.attn_dropout(att)
            y = att @ v

        y = y.transpose(1, 2).contiguous().view(b, t, c)
        y = self.resid_dropout(self.proj(y))
        return y


class MLP(nn.Module):
    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.fc = nn.Linear(config.n_embd, 4 * config.n_embd, bias=config.bias)
        self.proj = nn.Linear(4 * config.n_embd, config.n_embd, bias=config.bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # approximate='tanh' GELU is significantly faster on both CUDA and MPS
        return self.dropout(self.proj(F.gelu(self.fc(x), approximate='tanh')))


class Block(nn.Module):
    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.attn = CausalSelfAttention(config)
        self.ln_2 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.mlp = MLP(config)
        self.gradient_checkpointing = getattr(config, "gradient_checkpointing", False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.gradient_checkpointing and self.training:
            import torch.utils.checkpoint
            return torch.utils.checkpoint.checkpoint(self._forward_impl, x, use_reentrant=False)
        else:
            return self._forward_impl(x)

    def _forward_impl(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln_1(x))
        x = x + self.mlp(self.ln_2(x))
        return x


class GeocentricGPT(nn.Module):
    """Small GPT-style decoder-only causal language model trained from random init."""

    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.config = config
        self.token_embedding = nn.Embedding(config.vocab_size, config.n_embd)
        self.position_embedding = nn.Embedding(config.block_size, config.n_embd)
        self.dropout = nn.Dropout(config.dropout)
        self.blocks = nn.ModuleList([Block(config) for _ in range(config.n_layer)])
        self.ln_f = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        self.lm_head.weight = self.token_embedding.weight
        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                torch.nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        b, t = input_ids.shape
        if t > self.config.block_size:
            raise ValueError(f"Sequence length {t} exceeds block size {self.config.block_size}")

        pos = torch.arange(0, t, dtype=torch.long, device=input_ids.device)
        x = self.token_embedding(input_ids) + self.position_embedding(pos)[None, :, :]
        x = self.dropout(x)
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)

        loss = None
        if labels is not None:
            # Keep logits in their native dtype — cross_entropy handles mixed precision
            # internally. Casting to float32 here forces an expensive full-tensor copy
            # every forward pass, which is the single biggest training throughput killer.
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )
        return logits, loss

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,
        max_new_tokens: int,
        temperature: float = 0.8,
        top_k: int = 50,
        eos_id: Optional[int] = None,
        repetition_penalty: float = 1.15,
    ) -> torch.Tensor:
        for _ in range(max_new_tokens):
            idx_cond = input_ids[:, -self.config.block_size :]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :].float()
            
            # Vectorized repetition penalty — avoids slow Python loop over tokens
            if repetition_penalty != 1.0 and input_ids.size(1) > 0:
                # Gather scores for all previously seen tokens in one shot
                score = torch.gather(logits, 1, input_ids)
                # Divide positive logits, multiply negative ones (standard reptition penalty)
                score = torch.where(score > 0, score / repetition_penalty, score * repetition_penalty)
                logits.scatter_(1, input_ids, score)
                            
            if temperature <= 0:
                next_id = torch.argmax(logits, dim=-1, keepdim=True)
            else:
                logits = logits / max(temperature, 1e-5)
                if top_k > 0:
                    values, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                    logits[logits < values[:, [-1]]] = -float("inf")
                probs = F.softmax(logits, dim=-1)
                # Robust sanitization of probs to prevent multinomial RuntimeError
                if torch.isnan(probs).any() or torch.isinf(probs).any() or (probs < 0).any() or probs.sum() <= 0:
                    probs = torch.nan_to_num(probs, nan=0.0, posinf=0.0, neginf=0.0)
                    if probs.sum() <= 0:
                        probs = torch.ones_like(probs) / probs.size(-1)
                    else:
                        probs = probs / probs.sum()
                next_id = torch.multinomial(probs, num_samples=1)
            input_ids = torch.cat((input_ids, next_id), dim=1)
            if eos_id is not None and int(next_id.item()) == eos_id:
                break
        return input_ids


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
