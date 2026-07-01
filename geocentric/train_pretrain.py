from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import DataLoader, random_split
from tqdm.auto import tqdm

from geocentric.checkpoint import load_checkpoint, pretrained_checkpoint_name, save_checkpoint
from geocentric.training_metrics import initialize_training_metrics, update_training_metrics
from geocentric.data import CausalTextDataset, iter_texts, pad_collate
from geocentric.device import cleanup_mps, resolve_dtype, runtime_check, select_device
from geocentric.model import GPTConfig, GeocentricGPT, count_parameters
from geocentric.optimizer import CPUAdamW
from geocentric.tokenizer_train import load_tokenizer, token_id, train_byte_bpe_tokenizer

class PadCollateWrapper:
    def __init__(self, pad_id):
        self.pad_id = pad_id

    def __call__(self, batch):
        return pad_collate(batch, self.pad_id)

def pretrain(
    data_path: str,
    output_dir: str,
    vocab_size: int = 8192,
    block_size: int = 256,
    n_layer: int = 6,
    n_head: int = 6,
    n_embd: int = 384,
    dropout: float = 0.1,
    epochs: int = 3,
    batch_size: int = 8,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 3e-4,
    eval_ratio: float = 0.05,
    dtype_name: str = "auto",
    tokenizer_path: Optional[str] = None,
    gradient_checkpointing: bool = False,
    patience: int = 3,
    target_loss: float = 0.0,
    modelver: str = "Geocentric 2.1",
    overwrite_output_dir: bool = False,
    metrics_every: int = 10,
    save_every: int = 100,
    num_workers: Optional[int] = None,
    compile_mode: str = "auto",
) -> None:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    if overwrite_output_dir:
        removed = []
        for pattern in ("*_pretrained.pt", "*_pretrained_best.pt", "model.pt"):
            for old_ckpt in out.glob(pattern):
                try:
                    old_ckpt.unlink()
                    removed.append(old_ckpt.name)
                except OSError:
                    pass
        if removed:
            print("Overwrite requested. Removed old pretraining checkpoint(s): " + ", ".join(sorted(removed)))

    device = select_device(prefer_mps=True)
    dtype = resolve_dtype(device, dtype_name)

    # float16 on MPS is slower and less stable than bfloat16 — MPS hardware is
    # optimized for bfloat16 and Apple's own ML frameworks never use float16 for training.
    if device.type == "mps" and dtype == torch.float16:
        print("INFO: Upgrading float16 → bfloat16 on MPS (faster and more stable on Apple Silicon).")
        dtype = torch.bfloat16

    runtime_check(device, dtype)

    if device.type == "cuda" and not gradient_checkpointing:
        props = torch.cuda.get_device_properties(device)
        if props.total_memory < 8 * 1024**3 and n_layer >= 12 and batch_size >= 2 and block_size >= 512:
            print("WARNING: Low GPU memory detected. Enabling gradient checkpointing for safer pretraining.")
            gradient_checkpointing = True

    tok_out = out / "tokenizer.json"
    if tokenizer_path:
        shutil.copyfile(tokenizer_path, tok_out)
        tokenizer = load_tokenizer(tok_out)
    elif tok_out.exists():
        tokenizer = load_tokenizer(tok_out)
    else:
        print("Training Byte-level BPE tokenizer from scratch...")
        tokenizer = train_byte_bpe_tokenizer(iter_texts(data_path), tok_out, vocab_size=vocab_size)

    pad_id = token_id(tokenizer, "<pad>")
    dataset = CausalTextDataset(tokenizer, iter_texts(data_path), block_size=block_size)
    eval_len = max(1, int(len(dataset) * eval_ratio)) if len(dataset) > 20 else 1
    train_len = max(1, len(dataset) - eval_len)
    train_ds, eval_ds = random_split(dataset, [train_len, eval_len], generator=torch.Generator().manual_seed(42))

    config = GPTConfig(
        vocab_size=tokenizer.get_vocab_size(),
        block_size=block_size,
        n_layer=n_layer,
        n_head=n_head,
        n_embd=n_embd,
        dropout=dropout,
        gradient_checkpointing=gradient_checkpointing,
        model_name=modelver,
    )
    pretrained_name = pretrained_checkpoint_name(modelver)
    pretrained_best_name = pretrained_checkpoint_name(modelver, best=True)
    pretrained_path = out / pretrained_name
    if pretrained_path.exists():
        print(f"Resuming pretraining from existing checkpoint: {pretrained_path}")
        model = load_checkpoint(out, device=device, dtype=dtype, checkpoint_name=pretrained_name, modelver=modelver, kind="pretrained")
    else:
        print("No existing pretraining checkpoint found. Initializing model with random weights.")
        if dtype == torch.float16:
            model = GeocentricGPT(config).to(device=device)
        else:
            model = GeocentricGPT(config).to(device=device, dtype=dtype)
    print(f"Model parameters: {count_parameters(model):,}")

    initialize_training_metrics(
        out,
        phase="pretraining",
        config={
            "vocab_size": tokenizer.get_vocab_size(),
            "block_size": block_size,
            "n_layer": n_layer,
            "n_head": n_head,
            "n_embd": n_embd,
            "dropout": dropout,
            "epochs": epochs,
            "batch_size": batch_size,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "eval_ratio": eval_ratio,
            "dtype": str(dtype),
            "gradient_checkpointing": gradient_checkpointing,
            "modelver": modelver,
            "overwrite_output_dir": overwrite_output_dir,
            "metrics_every": metrics_every,
            "save_every": save_every,
            "num_workers": num_workers,
            "compile_mode": compile_mode,
        },
    )

    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        import contextlib
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        import contextlib
        autocast_ctx = contextlib.nullcontext()

    # MPS (Apple Silicon) performs significantly worse with multiprocessing DataLoader workers
    # due to IPC overhead and MPS context conflicts. num_workers=0 uses the main process
    # and is substantially faster on Mac. CUDA benefits from workers; CPU is indifferent.
    if num_workers is None:
        if device.type == "mps":
            num_workers = 0
        elif device.type == "cuda":
            num_workers = max(2, min(8, (os.cpu_count() or 1) - 1))
        else:
            num_workers = max(0, min(4, (os.cpu_count() or 1) - 1))
    else:
        num_workers = max(0, int(num_workers))
    pin_memory = device.type == "cuda"
    # prefetch_factor is only valid when num_workers > 0
    prefetch_factor = 2 if num_workers > 0 else None

    # Initialize the picklable collation wrapper
    collate_wrapper = PadCollateWrapper(pad_id)

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_wrapper,
        num_workers=num_workers,
        pin_memory=pin_memory,
        prefetch_factor=prefetch_factor,
        persistent_workers=(num_workers > 0),
    )
    eval_loader = DataLoader(
        eval_ds,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=collate_wrapper,
        num_workers=num_workers,
        pin_memory=pin_memory,
        prefetch_factor=prefetch_factor,
        persistent_workers=(num_workers > 0),
    )

    use_cpu_offload = False
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device)
        if props.total_memory < 10 * 1024**3 and dtype in {torch.float16, torch.bfloat16}:
            use_cpu_offload = True
            print("WARNING: GPU memory is limited. Offloading optimizer state to CPU.")

    optim = CPUAdamW(
        model.parameters(),
        lr=learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.1,
        offload_state_to_cpu=use_cpu_offload,
    )
    compiled_model = None
    if compile_mode != "off" and hasattr(torch, "compile") and device.type == "cuda":
        try:
            props = torch.cuda.get_device_properties(device)
            if props.major >= 8:
                compiled_model = torch.compile(model, mode="reduce-overhead")
                print("Compiled model with torch.compile for faster training.")
            else:
                print("Skipping torch.compile on compute capability < 8 for stability.")
        except Exception as e:
            print(f"torch.compile failed; continuing without compilation: {e}")

    total_steps = max(1, math.ceil(len(train_loader) / gradient_accumulation_steps) * epochs)
    step = 0
    optim.zero_grad(set_to_none=True)
    use_scaler = device.type == "cuda" and dtype == torch.float16
    scaler = torch.amp.GradScaler(enabled=use_scaler)
    # Cosine LR schedule: warms up for 2% of steps then decays to 10% of peak LR.
    # This is meaningfully better than flat LR for both loss and final model quality.
    warmup_steps = max(1, int(total_steps * 0.02))
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optim,
        max_lr=learning_rate,
        total_steps=total_steps,
        pct_start=warmup_steps / total_steps,
        anneal_strategy="cos",
        div_factor=10.0,
        final_div_factor=10.0,
    )
    epoch = 0
    best_eval_loss = float("inf")
    epochs_no_improve = 0
    active_model = compiled_model if compiled_model is not None else model
    try:
        while True:
            epoch += 1
            if epochs > 0 and epoch > epochs:
                break
                
            if epochs == 0 and epoch == 1:
                print("\n" + "=" * 80)
                print("INFINITE TRAINING MODE ACTIVE")
                print("The model will train continuously. Press Ctrl+C at any time to halt and save!")
                print("=" * 80 + "\n")

            model.train()
            pbar = tqdm(train_loader, desc=f"Pretrain epoch {epoch if epochs == 0 else f'{epoch}/{epochs}'}")
            running = torch.tensor(0.0, device=device)
            seen = 0
            for micro, batch in enumerate(pbar, start=1):
                input_ids = batch["input_ids"].to(device, non_blocking=(device.type == "cuda"))
                labels = batch["labels"].to(device, non_blocking=(device.type == "cuda"))
                try:
                    with autocast_ctx:
                        _, loss = active_model(input_ids, labels=labels)
                except Exception as exc:
                    if compiled_model is not None:
                        print(f"Compiled model failed during forward pass: {exc}. Falling back to uncompiled model.")
                        compiled_model = None
                        active_model = model
                        with autocast_ctx:
                            _, loss = active_model(input_ids, labels=labels)
                    else:
                        raise
                if loss is None:
                    raise RuntimeError("Loss was not computed")
                if not torch.isfinite(loss):
                    print(f"WARNING: Non-finite loss detected at step {step+1}, skipping batch.")
                    optim.zero_grad(set_to_none=True)
                    continue

                if use_scaler:
                    scaler.scale(loss / gradient_accumulation_steps).backward()
                else:
                    (loss / gradient_accumulation_steps).backward()
                # Accumulate on GPU — avoid .cpu() transfer every microstep
                running += loss.detach()
                seen += 1

                if micro % gradient_accumulation_steps == 0 or micro == len(train_loader):
                    if use_scaler:
                        try:
                            scaler.unscale_(optim)
                        except ValueError as exc:
                            if "Attempting to unscale FP16 gradients" not in str(exc):
                                raise
                    # clip_grad_norm_ returns the total norm; if it's finite the grads are
                    # fine. Checking torch.isfinite on every parameter tensor every step
                    # forces a GPU→CPU sync per param — replaced with a single norm check.
                    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    if not torch.isfinite(grad_norm):
                        print(f"WARNING: Non-finite gradients detected at step {step+1}; skipping optimizer step.")
                        optim.zero_grad(set_to_none=True)
                        if use_scaler:
                            scaler.update()
                        continue
                    if use_scaler:
                        scaler.step(optim)
                        scaler.update()
                    else:
                        optim.step()
                    if step < total_steps:
                        scheduler.step()
                    optim.zero_grad(set_to_none=True)
                    step += 1
                    # Only write metrics to disk every 10 steps — each write is a full
                    # JSON read+parse+rewrite and forces a CPU sync. Every-step writes
                    # were adding multiple seconds of overhead per iteration on MPS.
                    if metrics_every > 0 and step % metrics_every == 0:
                        avg_loss = float((running / max(1, seen)).cpu())
                        update_training_metrics(
                            out,
                            {
                                "step": step,
                                "epoch": epoch,
                                "batch": micro,
                                "loss": avg_loss,
                                "perplexity": float(math.exp(min(avg_loss, 20))),
                                "message": "Batch complete.",
                            },
                        )
                        pbar.set_postfix(loss=f"{avg_loss:.4f}", ppl=f"{math.exp(min(avg_loss, 20)):.2f}", step=step)
                        running = torch.tensor(0.0, device=device)
                        seen = 0
                    if save_every > 0 and step % save_every == 0:
                        save_checkpoint(model, out, step, name=pretrained_name)

            eval_loss = evaluate(active_model, eval_loader, device, dtype)
            print(f"Eval loss: {eval_loss:.4f} | perplexity: {math.exp(min(eval_loss, 20)):.2f}")
            update_training_metrics(
                out,
                {
                    "eval_loss": float(eval_loss),
                    "best_eval_loss": float(best_eval_loss),
                    "message": "Epoch evaluation complete.",
                },
            )
            
            # Save latest checkpoint
            save_checkpoint(model, out, step, name=pretrained_name)
            
            # Track best eval loss and check patience
            if eval_loss < best_eval_loss:
                best_eval_loss = eval_loss
                epochs_no_improve = 0
                save_checkpoint(model, out, step, name=pretrained_best_name)
                print(f" New best evaluation loss: {best_eval_loss:.4f}! Best checkpoint saved.")
            else:
                epochs_no_improve += 1
                print(f" No improvement in evaluation loss for {epochs_no_improve} epoch(s).")
                
            if patience > 0 and epochs_no_improve >= patience:
                print(f"\n[Early Stopping] Eval loss has not improved for {patience} epochs. Stopping pretraining.")
                best_path = out / pretrained_best_name
                std_path = out / pretrained_name
                if best_path.exists():
                    shutil.copyfile(best_path, std_path)
                update_training_metrics(out, {"status": "stopped", "message": "Early stopping reached."})
                break
                
            if target_loss > 0.0 and eval_loss <= target_loss:
                print(f"\n[Early Stopping] Target validation loss of {target_loss:.4f} reached. Stopping pretraining.")
                best_path = out / pretrained_best_name
                std_path = out / pretrained_name
                if best_path.exists():
                    shutil.copyfile(best_path, std_path)
                update_training_metrics(out, {"status": "stopped", "message": "Target loss reached."})
                break
    except KeyboardInterrupt:
        print("\n[Ctrl+C] Pretraining interrupted by user! Saving current checkpoint...")
        save_checkpoint(model, out, step, name=pretrained_name)
        update_training_metrics(out, {"status": "stopped", "message": "Interrupted by user."})
        print("Checkpoint successfully saved. Exiting gracefully.")
        return



    print(f"Pretraining complete. Saved to {out}")
    update_training_metrics(out, {"status": "stopped", "message": "Pretraining complete."})


@torch.no_grad()
def evaluate(model: GeocentricGPT, loader: DataLoader, device: torch.device, dtype: torch.dtype) -> float:
    model.eval()
    total = 0.0
    count = 0
    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        import contextlib
        autocast_ctx = contextlib.nullcontext()

    for batch in loader:
        input_ids = batch["input_ids"].to(device, non_blocking=(device.type == "cuda"))
        labels = batch["labels"].to(device, non_blocking=(device.type == "cuda"))
        with autocast_ctx:
            _, loss = model(input_ids, labels=labels)
        if loss is not None:
            total += float(loss.detach().cpu())
            count += 1
    model.train()
    return total / max(1, count)
