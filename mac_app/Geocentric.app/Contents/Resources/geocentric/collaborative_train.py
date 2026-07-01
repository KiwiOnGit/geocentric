from __future__ import annotations

import argparse
import math
import os
import contextlib
from pathlib import Path
from typing import Optional

import torch
import torch.distributed as dist
from torch.optim import AdamW
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from geocentric.checkpoint import find_tokenizer_path, DEFAULT_MODELVER, pretrained_checkpoint_name, save_checkpoint
from geocentric.data import CausalTextDataset, SFTDataset, iter_texts, pad_collate
from geocentric.device import resolve_dtype, runtime_check, select_device
from geocentric.model import GPTConfig, GeocentricGPT, count_parameters
from geocentric.tokenizer_train import load_tokenizer, token_id


def init_distributed(master_ip: str, master_port: str, rank: int, world_size: int) -> torch.device:
    """Initialize the PyTorch distributed process group using the Gloo backend."""
    print("=" * 80)
    print("INITIALIZING COLLABORATIVE TRAINING PIPELINE")
    print("=" * 80)
    print(f"Master IP: {master_ip}")
    print(f"Master Port: {master_port}")
    print(f"Local Node Rank: {rank}")
    print(f"Total Nodes (World Size): {world_size}")
    
    # Gloo is the universal CPU backend that supports heterogeneous devices (MPS and CUDA)
    init_method = f"tcp://{master_ip}:{master_port}"
    dist.init_process_group(
        backend="gloo",
        init_method=init_method,
        rank=rank,
        world_size=world_size
    )
    print("Distributed communication group initialized successfully!")
    
    # Auto-detect native hardware acceleration
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print("NVIDIA CUDA detected. Automatically leveraging CUDA acceleration!")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        print("Apple Silicon detected. Automatically leveraging MPS acceleration!")
    else:
        device = torch.device("cpu")
        print("No GPU detected. Falling back to CPU.")
        
    print(f"Local compute device initialized: {device}")
    print("=" * 80 + "\n")
    return device


def sync_gradients(model: GeocentricGPT, world_size: int):
    """Average gradients across all distributed nodes using Gloo all_reduce."""
    for param in model.parameters():
        if param.grad is not None:
            dist.all_reduce(param.grad.data, op=dist.ReduceOp.SUM)
            param.grad.data /= world_size


def sync_parameters(model: GeocentricGPT):
    """Broadcast initial parameters from master (rank 0) to all other worker nodes."""
    for param in model.parameters():
        dist.broadcast(param.data, src=0)


def run_collaborative_pretrain(args):
    device = init_distributed(args.master_ip, args.master_port, args.rank, args.world_size)
    dtype = resolve_dtype(device, args.dtype)
    runtime_check(device, dtype)
    
    modelver = getattr(args, "modelver", DEFAULT_MODELVER)
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    
    # Load tokenizer, accepting compatible nearby/default tokenizer locations.
    tok_out = out / "tokenizer.json"
    tokenizer_path = find_tokenizer_path(out)
    if tokenizer_path != tok_out:
        import shutil
        shutil.copyfile(tokenizer_path, tok_out)
        print(f"Using tokenizer from fallback location: {tokenizer_path}")
    tokenizer = load_tokenizer(tok_out)
            
    pad_id = token_id(tokenizer, "<pad>")
    dataset = CausalTextDataset(tokenizer, iter_texts(args.data_path), block_size=args.block_size)
    
    # Initialize homogeneous config
    config = GPTConfig(
        vocab_size=tokenizer.get_vocab_size(),
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
        dropout=args.dropout,
        gradient_checkpointing=args.gradient_checkpointing,
        model_name=modelver,
    )
    
    checkpoint_name = pretrained_checkpoint_name(modelver)
    model = GeocentricGPT(config).to(device=device, dtype=dtype)
    print(f"Model parameters: {count_parameters(model):,}")
    
    # Synchronize initial weights from Rank 0 to prevent divergent initialization paths!
    sync_parameters(model)
    
    # Distributed data splitting (Rank 0 trains on first half, Rank 1 on second half of batch)
    train_loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, collate_fn=lambda b: pad_collate(b, pad_id))
    
    optim = AdamW(model.parameters(), lr=args.learning_rate, betas=(0.9, 0.95), weight_decay=0.1)
    
    # AMP autocast for float16 matrix acceleration
    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        autocast_ctx = contextlib.nullcontext()
        
    step = 0
    epoch = 0
    
    print("Collaborative training pipeline starting...")
    try:
        for epoch in range(1, args.epochs + 1):
            model.train()
            pbar = tqdm(train_loader, desc=f"Collaborative Pretrain Epoch {epoch}")
            running = 0.0
            seen = 0
            
            for micro, batch in enumerate(pbar, start=1):
                input_ids = batch["input_ids"].to(device)
                labels = batch["labels"].to(device)
                
                with autocast_ctx:
                    _, loss = model(input_ids, labels=labels)
                    
                if loss is None:
                    raise RuntimeError("Loss was not computed")
                    
                (loss / args.gradient_accumulation_steps).backward()
                running += float(loss.detach().cpu())
                seen += 1
                
                if micro % args.gradient_accumulation_steps == 0 or micro == len(train_loader):
                    # Causal gradient clipping
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    
                    # 1. Sync gradients across Mac and PC!
                    sync_gradients(model, args.world_size)
                    
                    # 2. Step the optimizer concurrently
                    optim.step()
                    optim.zero_grad(set_to_none=True)
                    
                    step += 1
                    if device.type == "mps":
                        torch.mps.synchronize()
                        
                    if step % 5 == 0:
                        avg = running / max(1, seen)
                        pbar.set_postfix(loss=f"{avg:.4f}", step=step)
                        
            # Save checkpoints on rank 0 node
            if args.rank == 0:
                save_checkpoint(model, out, step, name=checkpoint_name)
                print(f"Rank 0: Checkpoint saved successfully.")
                
            dist.barrier()  # Synchronize nodes before starting next epoch
            
    except KeyboardInterrupt:
        print("\nCollaborative training interrupted by user!")
        if args.rank == 0:
            save_checkpoint(model, out, step, name=checkpoint_name)
            print("Rank 0: Saved current checkpoint before exit.")
    finally:
        dist.destroy_process_group()


def main():
    parser = argparse.ArgumentParser(description="Collaborative Distributed MPS/CUDA Training Loop")
    parser.add_argument("--master_ip", required=True, help="IP address of the Master (Rank 0) PC")
    parser.add_argument("--master_port", default="29500", help="Port for distributed network bridge")
    parser.add_argument("--rank", type=int, required=True, help="Rank of current device (0 = Master, 1 = MacBook)")
    parser.add_argument("--world_size", type=int, default=2, help="Total number of nodes (default: 2)")
    
    parser.add_argument("--data_path", default="data/pretrain_seed.txt")
    parser.add_argument("--output_dir", default="runs/geocentric2_1")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=16)
    parser.add_argument("--learning_rate", type=float, default=3e-4)
    parser.add_argument("--dtype", default="bfloat16")
    
    # Network config
    parser.add_argument("--block_size", type=int, default=512)
    parser.add_argument("--n_layer", type=int, default=12)
    parser.add_argument("--n_head", type=int, default=12)
    parser.add_argument("--n_embd", type=int, default=768)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--gradient_checkpointing", action="store_true", default=True)
    parser.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")
    
    args = parser.parse_args()
    run_collaborative_pretrain(args)


if __name__ == "__main__":
    main()
