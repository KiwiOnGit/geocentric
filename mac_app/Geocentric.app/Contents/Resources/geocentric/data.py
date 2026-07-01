from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence

import torch
from torch.utils.data import Dataset
from tokenizers import Tokenizer

from geocentric.tokenizer_train import token_id


def _data_path_candidates(path: str | Path) -> list[Path]:
    """Common fallback locations for user-friendly CLI paths."""
    raw = Path(path).expanduser()
    cwd = Path.cwd().expanduser().resolve()
    candidates: list[Path] = []

    def add(p: Path) -> None:
        try:
            resolved = p.expanduser().resolve()
        except Exception:
            return
        if resolved not in candidates:
            candidates.append(resolved)

    add(raw)
    if not raw.is_absolute():
        add(cwd / raw)

    text = str(raw).lower()
    if "wiki" in text or "wikipedia" in text:
        for rel in [
            "data/wikipedia_pretrain",
            "data/wikitext103",
            "data/wikitext-103",
            "data/wiki",
            "data/wikipedia",
            "data/wikitext103/wiki.train.tokens",
            "data/wikitext-103/wiki.train.tokens",
            "data/wiki.train.tokens",
        ]:
            add(cwd / rel)
    return candidates


def _resolve_data_path(path: str | Path) -> Path:
    candidates = _data_path_candidates(path)
    requested = Path(path).expanduser()
    try:
        requested_resolved = requested.resolve()
    except Exception:
        requested_resolved = requested

    for candidate in candidates:
        if candidate.exists():
            if candidate != requested_resolved:
                print(f"Data path not found exactly; using fallback data path: {candidate}")
            return candidate

    data_dir = Path.cwd() / "data"
    existing_hint = ""
    if data_dir.exists():
        try:
            children = sorted(str(p.relative_to(Path.cwd())) for p in data_dir.iterdir())[:30]
            if children:
                existing_hint = "\nExisting entries under ./data:\n  - " + "\n  - ".join(children)
        except Exception:
            pass
    searched = "\n  - ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"Training data path does not exist: {requested}\n"
        f"Searched:\n  - {searched}"
        f"{existing_hint}\n\n"
        "Fix options:\n"
        "  1) Point --data_path at an existing .txt/.md/.json/.jsonl/.csv file or folder.\n"
        "  2) Download the bundled wiki dataset first:\n"
        "     venv/bin/python -m geocentric.cli download-wiki\n"
        "  3) Then rerun pretrain with the actual folder shown under ./data."
    )


def iter_texts(path: str | Path) -> Iterator[str]:
    """Yield training text from txt, jsonl, json, csv, or a directory."""
    p = _resolve_data_path(path)

    if p.is_dir():
        found_supported = False
        for child in sorted(p.rglob("*")):
            if child.is_file() and child.suffix.lower() in {".txt", ".md", ".jsonl", ".json", ".csv"}:
                found_supported = True
                yield from iter_texts(child)
        if not found_supported:
            raise ValueError(
                f"No supported training files found in {p}. Supported: .txt, .md, .jsonl, .json, .csv"
            )
        return

    suffix = p.suffix.lower()
    if suffix in {".txt", ".md"}:
        with p.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    yield line
        return

    if suffix == ".jsonl":
        with p.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                yield format_record_for_text(row)
        return

    if suffix == ".json":
        payload = json.loads(p.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            yield format_record_for_text(row)
        return

    if suffix == ".csv":
        with p.open("r", encoding="utf-8", newline="") as handle:
            csv.field_size_limit(100_000_000)
            reader = csv.reader(handle)
            try:
                first_row = next(reader)
            except StopIteration:
                return
            
            header_keys = {"instruction", "input", "output", "response", "text", "messages"}
            has_header = any(col.lower() in header_keys for col in first_row if isinstance(col, str))
            
            if has_header:
                headers = first_row
                for row in reader:
                    if len(row) <= len(headers):
                        row_dict = {headers[i]: row[i] for i in range(len(row))}
                        yield format_record_for_text(row_dict)
            else:
                if len(first_row) == 1:
                    yield first_row[0]
                else:
                    yield "\n".join(first_row)
                
                for row in reader:
                    if len(row) == 1:
                        yield row[0]
                    elif len(row) > 1:
                        yield "\n".join(row)
        return

    raise ValueError(f"Unsupported data format: {p}")

def format_record_for_text(row: Mapping[str, object]) -> str:
    """Map common SFT records into a single training string."""
    if "messages" in row and isinstance(row["messages"], list):
        parts: List[str] = []
        for msg in row["messages"]:  # type: ignore[index]
            if not isinstance(msg, Mapping):
                continue
            role = str(msg.get("role", "user")).strip()
            content = str(msg.get("content", "")).strip()
            if content:
                parts.append(f"<|{role}|>\n{content}")
        return "\n".join(parts).strip() + "\n<eos>"

    instruction = str(row.get("instruction", "")).strip()
    input_text = str(row.get("input", "")).strip()
    response = str(row.get("response", row.get("output", ""))).strip()
    text = str(row.get("text", "")).strip()

    if instruction or response:
        prompt = f"### Instruction:\n{instruction}\n"
        if input_text:
            prompt += f"\n### Input:\n{input_text}\n"
        prompt += f"\n### Response:\n{response}\n<eos>"
        return prompt

    if text:
        return text

    return "\n".join(f"{k}: {v}" for k, v in row.items())


def format_prompt(instruction: str, input_text: str = "") -> str:
    prompt = f"### Instruction:\n{instruction.strip()}\n"
    if input_text.strip():
        prompt += f"\n### Input:\n{input_text.strip()}\n"
    prompt += "\n### Response:\n"
    return prompt


class CausalTextDataset(Dataset):
    """Fixed-length causal LM chunks for pretraining, chunked into non-overlapping blocks for speed."""

    def __init__(self, tokenizer: Tokenizer, texts: Iterable[str], block_size: int) -> None:
        eos = token_id(tokenizer, "<eos>")
        ids: List[int] = []
        
        batch_size = 8192
        current_batch: List[str] = []
        
        print("Tokenizing pretraining dataset in high-speed multi-threaded batches...")
        for text in texts:
            if text.strip():
                current_batch.append(text)
                
            if len(current_batch) >= batch_size:
                encodings = tokenizer.encode_batch(current_batch)
                for enc in encodings:
                    ids.extend(enc.ids + [eos])
                current_batch = []
                
        if current_batch:
            encodings = tokenizer.encode_batch(current_batch)
            for enc in encodings:
                ids.extend(enc.ids + [eos])
                
        print(f"Tokenization complete! Total processed tokens: {len(ids):,}")

        self.block_size = block_size
        self.chunks: List[Dict[str, torch.Tensor]] = []
        
        # Chunk into non-overlapping blocks of length block_size
        for i in range(0, len(ids) - block_size, block_size):
            chunk = ids[i : i + block_size + 1]
            if len(chunk) == block_size + 1:
                self.chunks.append({
                    "input_ids": torch.tensor(chunk[:-1], dtype=torch.long),
                    "labels": torch.tensor(chunk[1:], dtype=torch.long)
                })

        if not self.chunks:
            raise ValueError(
                f"Not enough tokens for block_size={block_size}. Got only {len(ids)} tokens."
            )

    def __len__(self) -> int:
        return len(self.chunks)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        return self.chunks[idx]


class SFTDataset(Dataset):
    """Instruction SFT dataset with prompt tokens masked from loss."""

    def __init__(self, tokenizer: Tokenizer, path: str | Path, block_size: int) -> None:
        self.examples: List[Dict[str, torch.Tensor]] = []
        eos = token_id(tokenizer, "<eos>")

        p = _resolve_data_path(path)
        records: List[tuple[str, str]] = []
        for row in self._read_rows(p):
            instruction = str(row.get("instruction", "")).strip()
            input_text = str(row.get("input", "")).strip()
            response = str(row.get("response", row.get("output", ""))).strip()
            if not instruction or not response:
                continue
            prompt = format_prompt(instruction, input_text)
            records.append((prompt, response))

        if not records:
            raise ValueError(f"No usable SFT examples found in {p}")

        prompt_texts, response_texts = zip(*records)
        prompt_encodings = tokenizer.encode_batch(list(prompt_texts))
        response_encodings = tokenizer.encode_batch(list(response_texts))

        for prompt_enc, response_enc in zip(prompt_encodings, response_encodings):
            prompt_ids = prompt_enc.ids
            response_ids = response_enc.ids + [eos]
            ids = (prompt_ids + response_ids)[:block_size]
            labels = ([-100] * len(prompt_ids) + response_ids)[:block_size]
            if len(ids) < 2:
                continue
            self.examples.append(
                {
                    "input_ids": torch.tensor(ids[:-1], dtype=torch.long),
                    "labels": torch.tensor(labels[1:], dtype=torch.long),
                }
            )

        if not self.examples:
            raise ValueError(f"No usable SFT examples found in {p}")

    @staticmethod
    def _read_rows(path: Path) -> Iterator[Mapping[str, object]]:
        if path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)
            return
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in (payload if isinstance(payload, list) else [payload]):
                yield row
            return
        raise ValueError("SFT data must be .jsonl or .json")

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        return self.examples[idx]


def pad_collate(batch: Sequence[Mapping[str, torch.Tensor]], pad_id: int) -> Dict[str, torch.Tensor]:
    max_len = max(x["input_ids"].numel() for x in batch)
    input_ids: List[torch.Tensor] = []
    labels: List[torch.Tensor] = []
    attention_mask: List[torch.Tensor] = []

    for item in batch:
        ids = item["input_ids"]
        lab = item["labels"]
        pad_len = max_len - ids.numel()
        input_ids.append(torch.cat([ids, torch.full((pad_len,), pad_id, dtype=torch.long)]))
        labels.append(torch.cat([lab, torch.full((pad_len,), -100, dtype=torch.long)]))
        attention_mask.append(torch.cat([torch.ones_like(ids), torch.zeros((pad_len,), dtype=torch.long)]))

    return {
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
        "attention_mask": torch.stack(attention_mask),
    }
