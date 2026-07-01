from __future__ import annotations

import math
import os
from pathlib import Path

import torch
from torch.utils.data import DataLoader, random_split
from tqdm.auto import tqdm

from geocentric.checkpoint import find_tokenizer_path, load_checkpoint, pretrained_checkpoint_name, save_checkpoint, sft_checkpoint_name
from geocentric.training_metrics import initialize_training_metrics, update_training_metrics
from geocentric.data import SFTDataset, pad_collate
from geocentric.device import cleanup_mps, resolve_dtype, runtime_check, select_device
from geocentric.optimizer import CPUAdamW
from geocentric.tokenizer_train import load_tokenizer, token_id
from geocentric.offload import offload_forward_pass


class PadCollateWrapper:
    """Top-level picklable collate wrapper for use with DataLoader workers on macOS."""
    def __init__(self, pad_id: int) -> None:
        self.pad_id = pad_id

    def __call__(self, batch):
        return pad_collate(batch, self.pad_id)


def sft(
    model_dir: str,
    sft_data_path: str,
    output_dir: str | None = None,
    epochs: int = 2,
    batch_size: int = 4,
    gradient_accumulation_steps: int = 4,
    learning_rate: float = 2e-5,
    eval_ratio: float = 0.05,
    dtype_name: str = "auto",
    gradient_checkpointing: bool = False,
    patience: int = 3,
    target_loss: float = 0.0,
    min_delta: float = 1e-4,
    offload_layers: bool = False,
    modelver: str = "Geocentric 2.1",
    overwrite_output_dir: bool = False,
    metrics_every: int = 10,
    save_every: int = 100,
    num_workers: Optional[int] = None,
    compile_mode: str = "auto",
) -> None:
    src = Path(model_dir).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve() if output_dir else src
    out.mkdir(parents=True, exist_ok=True)

    device = select_device(prefer_mps=True)
    dtype = resolve_dtype(device, dtype_name)

    # float16 on MPS is slower and less stable than bfloat16.
    if device.type == "mps" and dtype == torch.float16:
        print("INFO: Upgrading float16 → bfloat16 on MPS (faster and more stable on Apple Silicon).")
        dtype = torch.bfloat16

    runtime_check(device, dtype)

    if device.type == "cuda" and not gradient_checkpointing and batch_size >= 2:
        # Use gradient checkpointing for larger fine-tuning runs on limited VRAM.
        print("WARNING: Low GPU memory detected. Enabling gradient checkpointing for safer SFT.")
        gradient_checkpointing = True

    sft_name = sft_checkpoint_name(modelver)
    sft_best_name = sft_checkpoint_name(modelver, best=True)
    pretrained_name = pretrained_checkpoint_name(modelver)

    if overwrite_output_dir:
        removed = []
        for pattern in ("*_sft.pt", "*_sft_best.pt"):
            for old_ckpt in out.glob(pattern):
                try:
                    old_ckpt.unlink()
                    removed.append(old_ckpt.name)
                except OSError:
                    pass
        if removed:
            print("Overwrite requested. Removed old SFT checkpoint(s): " + ", ".join(sorted(removed)))
        else:
            print("Overwrite requested. No old SFT checkpoints were present.")

    sft_path = out / sft_name
    if not overwrite_output_dir and not sft_path.exists() and src != out:
        sft_path = src / sft_name
        if not sft_path.exists():
            legacy = src / "geocentric2_1_sft.pt"
            if legacy.exists():
                sft_path = legacy

    if not overwrite_output_dir and sft_path.exists():
        print(f"Resuming fine-tuning from existing SFT checkpoint: {sft_path}")
        model = load_checkpoint(sft_path.parent, device=device, dtype=dtype, checkpoint_name=sft_path.name, modelver=modelver, kind="sft")
    else:
        print("Loading base pretrained model for fine-tuning...")
        try:
            model = load_checkpoint(src, device=device, dtype=dtype, checkpoint_name=pretrained_name, modelver=modelver, kind="pretrained")
        except FileNotFoundError:
            # If running interactively, offer drag-and-drop OR selecting a run folder
            import sys

            if sys.stdin.isatty():
                print("\n⚠️  No pretrained checkpoint found in the default model directory.")
                choice = input("Would you like to (D)rag-and-drop a checkpoint file, or (S)elect a run folder? [D/s]: ").strip().lower()
                if choice == "" or choice.startswith("d"):
                    prompt = f"Model path [default: {src}]: "
                    print("📥 Drag and drop your pretrained model checkpoint file (.pt) or model folder here, then press Enter.")
                    user_in = input(prompt).strip()
                else:
                    # Offer a simple selection from runs/ folders
                    runs_root = Path.cwd() / "runs"
                    candidates = []
                    if runs_root.exists():
                        candidates = [p for p in sorted(runs_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True) if p.is_dir()]
                    if not candidates:
                        print("No run folders found under ./runs/. Falling back to drag-and-drop.")
                        print("📥 Drag and drop your pretrained model checkpoint file (.pt) or model folder here, then press Enter.")
                        user_in = input(f"Model path [default: {src}]: ").strip()
                    else:
                        print("Select a run folder to load:")
                        for i, cand in enumerate(candidates[:40], start=1):
                            print(f"  {i}) {cand}")
                        sel = input("Enter number or full path (blank to cancel): ").strip()
                        if not sel:
                            print("No selection made; aborting.")
                            raise
                        try:
                            idx = int(sel)
                            user_in = str(candidates[idx - 1])
                        except ValueError:
                            user_in = sel

                if user_in:
                    if user_in.startswith(('"', "'")) and user_in.endswith(('"', "'")):
                        user_in = user_in[1:-1]
                    user_in = user_in.strip()
                    user_path = Path(user_in).expanduser().resolve()
                    # If the user provided a file, try loading that exact checkpoint (accept any kind)
                    try:
                        if user_path.is_file():
                            parent = user_path.parent
                            model = load_checkpoint(parent, device=device, dtype=dtype, checkpoint_name=user_path.name, modelver=modelver, kind="any")
                            src = parent
                        else:
                            # Directory: prefer pretrained but fall back to any
                            try:
                                model = load_checkpoint(user_path, device=device, dtype=dtype, checkpoint_name=None, modelver=modelver, kind="pretrained")
                                src = user_path
                            except FileNotFoundError:
                                model = load_checkpoint(user_path, device=device, dtype=dtype, checkpoint_name=None, modelver=modelver, kind="any")
                                src = user_path
                    except Exception as exc:
                        print(f"❌ Failed to load checkpoint from '{user_in}': {exc}")
                        raise
                else:
                    # No input provided; re-raise original error for clarity
                    raise
            else:
                # Non-interactive environment: re-raise
                raise
    tokenizer_path = find_tokenizer_path(src, extra_dirs=[out], expected_vocab_size=model.config.vocab_size)
    tokenizer = load_tokenizer(tokenizer_path)
    if tokenizer_path.parent != src:
        print(f"Using tokenizer from fallback location: {tokenizer_path}")
    pad_id = token_id(tokenizer, "<pad>")

    # Dynamically configure gradient checkpointing for SFT
    model.config.model_name = modelver
    model.config.gradient_checkpointing = gradient_checkpointing
    for block in model.blocks:
        block.gradient_checkpointing = gradient_checkpointing
    model.train()

    initialize_training_metrics(
        out,
        phase="sft",
        config={
            "model_dir": str(src),
            "block_size": model.config.block_size,
            "epochs": epochs,
            "batch_size": batch_size,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "eval_ratio": eval_ratio,
            "dtype": str(dtype),
            "gradient_checkpointing": gradient_checkpointing,
            "offload_layers": offload_layers,
            "modelver": modelver,
            "min_delta": min_delta,
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

    dataset = SFTDataset(tokenizer, sft_data_path, block_size=model.config.block_size)
    eval_len = max(1, int(len(dataset) * eval_ratio)) if len(dataset) > 20 else 1
    train_len = max(1, len(dataset) - eval_len)
    train_ds, eval_ds = random_split(dataset, [train_len, eval_len], generator=torch.Generator().manual_seed(42))

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
        weight_decay=0.01,
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

    use_scaler = device.type == "cuda" and dtype == torch.float16
    scaler = torch.amp.GradScaler(enabled=use_scaler)
    step = 0
    optim.zero_grad(set_to_none=True)

    total_sft_steps = max(1, math.ceil(len(train_loader) / gradient_accumulation_steps) * epochs)
    warmup_steps = max(1, int(total_sft_steps * 0.02))
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optim,
        max_lr=learning_rate,
        total_steps=total_sft_steps,
        pct_start=warmup_steps / total_sft_steps,
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
                print("INFINITE SFT TRAINING MODE ACTIVE")
                print("The model will fine-tune continuously. Press Ctrl+C at any time to halt and save!")
                print("=" * 80 + "\n")

            pbar = tqdm(train_loader, desc=f"Guided SFT epoch {epoch if epochs == 0 else f'{epoch}/{epochs}'}")
            running = torch.tensor(0.0, device=device)
            seen = 0
            for micro, batch in enumerate(pbar, start=1):
                input_ids = batch["input_ids"].to(device, non_blocking=(device.type == "cuda"))
                labels = batch["labels"].to(device, non_blocking=(device.type == "cuda"))
                try:
                    if offload_layers:
                        # Layer-by-layer offloading mode
                        with autocast_ctx:
                            logits = offload_forward_pass(model, input_ids, device, embeddings_device="cpu")
                            loss = torch.nn.functional.cross_entropy(
                                logits.view(-1, logits.size(-1)),
                                labels.view(-1),
                                ignore_index=-100,
                            )
                    else:
                        # Standard forward pass
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
                    print(f"WARNING: Non-finite SFT loss detected at step {step+1}, skipping batch.")
                    optim.zero_grad(set_to_none=True)
                    continue

                if use_scaler:
                    scaler.scale(loss / gradient_accumulation_steps).backward()
                else:
                    (loss / gradient_accumulation_steps).backward()
                running += loss.detach()
                seen += 1

                if micro % gradient_accumulation_steps == 0 or micro == len(train_loader):
                    if use_scaler:
                        try:
                            scaler.unscale_(optim)
                        except ValueError as exc:
                            if "Attempting to unscale FP16 gradients" not in str(exc):
                                raise
                    grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    if not torch.isfinite(grad_norm):
                        print(f"WARNING: Non-finite SFT gradients detected at step {step+1}; skipping optimizer step.")
                        optim.zero_grad(set_to_none=True)
                        if use_scaler:
                            scaler.update()
                        continue
                    if use_scaler:
                        scaler.step(optim)
                        scaler.update()
                    else:
                        optim.step()
                    if step < total_sft_steps:
                        scheduler.step()
                    optim.zero_grad(set_to_none=True)
                    step += 1
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
                        pbar.set_postfix(loss=f"{avg_loss:.4f}", ppl=f"{math.exp(min(avg_loss, 20)):.2f}")
                        running = torch.tensor(0.0, device=device)
                        seen = 0
                    if save_every > 0 and step % save_every == 0:
                        save_checkpoint(model, out, step, name=sft_name)

            eval_loss = evaluate(active_model, eval_loader, device, dtype)
            print(f"SFT eval loss: {eval_loss:.4f} | perplexity: {math.exp(min(eval_loss, 20)):.2f}")
            update_training_metrics(
                out,
                {
                    "eval_loss": float(eval_loss),
                    "best_eval_loss": float(best_eval_loss),
                    "message": "Epoch evaluation complete.",
                },
            )
            
            # Save latest checkpoint
            save_checkpoint(model, out, step, name=sft_name)
            
            # Track best SFT eval loss and check patience
            if eval_loss < best_eval_loss - min_delta:
                best_eval_loss = eval_loss
                epochs_no_improve = 0
                save_checkpoint(model, out, step, name=sft_best_name)
                print(f" New best SFT eval loss: {best_eval_loss:.4f}! Best SFT checkpoint saved.")
            else:
                epochs_no_improve += 1
                print(f" No improvement in SFT eval loss for {epochs_no_improve} epoch(s).")
                
            if patience > 0 and epochs_no_improve >= patience:
                print(f"\n[Early Stopping] SFT eval loss has not improved for {patience} epochs. Stopping SFT.")
                best_path = out / sft_best_name
                std_path = out / sft_name
                if best_path.exists():
                    import shutil
                    shutil.copyfile(best_path, std_path)
                update_training_metrics(out, {"status": "stopped", "message": "Early stopping reached."})
                break
                
            if target_loss > 0.0 and eval_loss <= target_loss:
                print(f"\n[Early Stopping] Target SFT validation loss of {target_loss:.4f} reached. Stopping SFT.")
                best_path = out / sft_best_name
                std_path = out / sft_name
                if best_path.exists():
                    import shutil
                    shutil.copyfile(best_path, std_path)
                update_training_metrics(out, {"status": "stopped", "message": "Target loss reached."})
                break
    except KeyboardInterrupt:
        print("\n[Ctrl+C] Guided SFT training interrupted by user! Saving current checkpoint...")
        save_checkpoint(model, out, step, name=sft_name)
        update_training_metrics(out, {"status": "stopped", "message": "Interrupted by user."})
        print("Checkpoint successfully saved. Exiting gracefully.")
        return

    out_tokenizer = out / "tokenizer.json"
    if tokenizer_path != out_tokenizer:
        import shutil
        shutil.copyfile(tokenizer_path, out_tokenizer)
    model.config.save(out / "config.json")
    print(f"Guided fine-tuning complete. Saved to {out}")
    update_training_metrics(out, {"status": "stopped", "message": "SFT complete."})


@torch.no_grad()
def evaluate(model, loader, device, dtype) -> float:
    """Evaluate model on `loader` using AMP autocast if appropriate."""
    model.eval()
    total = 0.0
    count = 0
    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        import contextlib
        autocast_ctx = contextlib.nullcontext()

    with torch.no_grad():
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
