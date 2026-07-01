from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, List

from tokenizers import Tokenizer
from tokenizers.decoders import ByteLevel as ByteLevelDecoder
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel
from tokenizers.processors import ByteLevel as ByteLevelProcessor
from tokenizers.trainers import BpeTrainer

SPECIAL_TOKENS = ["<pad>", "<unk>", "<bos>", "<eos>", "<think>", "</think>"]


def batch_iterator(texts: Iterable[str], batch_size: int = 1000) -> Iterator[List[str]]:
    batch: List[str] = []
    for text in texts:
        text = text.strip()
        if not text:
            continue
        batch.append(text)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def train_byte_bpe_tokenizer(
    texts: Iterable[str],
    output_path: str | Path,
    vocab_size: int = 8192,
    min_frequency: int = 2,
) -> Tokenizer:
    """Train a Byte-level BPE tokenizer from scratch and save tokenizer.json."""
    tokenizer = Tokenizer(BPE(unk_token="<unk>"))
    tokenizer.pre_tokenizer = ByteLevel(add_prefix_space=False)
    tokenizer.decoder = ByteLevelDecoder()
    tokenizer.post_processor = ByteLevelProcessor(trim_offsets=True)

    trainer = BpeTrainer(
        vocab_size=vocab_size,
        min_frequency=min_frequency,
        special_tokens=SPECIAL_TOKENS,
        show_progress=True,
    )

    batches = batch_iterator(texts)
    try:
        first_batch = next(batches)
    except StopIteration as exc:
        raise ValueError(
            "No training text was found for tokenizer training. "
            "Check --data_path and make sure it contains non-empty .txt/.md/.json/.jsonl/.csv data."
        ) from exc

    def chained_batches() -> Iterator[List[str]]:
        yield first_batch
        yield from batches

    tokenizer.train_from_iterator(chained_batches(), trainer=trainer)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(output))
    return tokenizer


def load_tokenizer(path: str | Path) -> Tokenizer:
    return Tokenizer.from_file(str(path))


def token_id(tokenizer: Tokenizer, token: str) -> int:
    tid = tokenizer.token_to_id(token)
    if tid is None:
        raise KeyError(f"Tokenizer does not contain required token: {token}")
    return int(tid)
