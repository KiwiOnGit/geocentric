from __future__ import annotations

import argparse
import math
import shutil
import contextlib
from pathlib import Path
from typing import Optional, Dict, Iterator, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from torch.optim import AdamW
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from geocentric.checkpoint import (
    DEFAULT_MODELVER,
    LEGACY_PRETRAINED_CHECKPOINT,
    find_tokenizer_path,
    pipeline_stage_checkpoint_name,
    pretrained_checkpoint_name,
    save_checkpoint,
)
from geocentric.data import CausalTextDataset, SFTDataset, iter_texts, pad_collate
from geocentric.device import resolve_dtype, runtime_check, select_device
from geocentric.model import GPTConfig, GeocentricGPT, Block, count_parameters
from geocentric.tokenizer_train import load_tokenizer, token_id


# ==============================================================================
# Pipeline Parallel Stages
# ==============================================================================

class GeocentricStage0(nn.Module):
    """Pipeline Stage 0: Embeddings + First Half of Transformer Blocks."""
    def __init__(self, config: GPTConfig, num_blocks: int):
        super().__init__()
        self.config = config
        self.token_embedding = nn.Embedding(config.vocab_size, config.n_embd)
        self.position_embedding = nn.Embedding(config.block_size, config.n_embd)
        self.dropout = nn.Dropout(config.dropout)
        
        # Instantiate only the first half of the blocks
        self.blocks = nn.ModuleList([
            Block(config) for _ in range(num_blocks)
        ])
        
        # Share gradient checkpointing state
        for block in self.blocks:
            block.gradient_checkpointing = config.gradient_checkpointing

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        b, t = input_ids.shape
        pos = torch.arange(0, t, dtype=torch.long, device=input_ids.device)
        x = self.token_embedding(input_ids) + self.position_embedding(pos)[None, :, :]
        x = self.dropout(x)
        for block in self.blocks:
            x = block(x)
        return x


class GeocentricStage1(nn.Module):
    """Pipeline Stage 1: Second Half of Transformer Blocks + LayerNorm + LM Head."""
    def __init__(self, config: GPTConfig, num_blocks: int):
        super().__init__()
        self.config = config
        
        # Instantiate the second half of the blocks
        self.blocks = nn.ModuleList([
            Block(config) for _ in range(num_blocks)
        ])
        
        self.ln_f = nn.LayerNorm(config.n_embd)
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        
        # Share gradient checkpointing state
        for block in self.blocks:
            block.gradient_checkpointing = config.gradient_checkpointing

    def forward(self, x: torch.Tensor, labels: Optional[torch.Tensor] = None) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)
        
        loss = None
        if labels is not None:
            loss = F.cross_entropy(
                logits.float().view(-1, logits.size(-1)),
                labels.reshape(-1),
                ignore_index=-100,
            )
        return logits, loss


# ==============================================================================
# Custom TCP Socket Network Bridge (Cross-OS macOS <-> Linux Compatible)
# ==============================================================================

import socket
import struct
import io
import threading
import queue as _queue
import numpy as np

_COMM_SOCKET: socket.socket | None = None

# Magic number used to detect misaligned or corrupted packets early
_PACKET_MAGIC = 0xDEADBEEF
_RECV_CHUNK_SIZE = 1 << 20  # 1 MB chunks to avoid blocking on small reads

# Socket buffer: 16 MB keeps Gigabit Ethernet (~125 MB/s) fed without stalls.
# 4 MB was fine for Wi-Fi (~20 MB/s) but caused head-of-line blocking on wired.
_SOCKET_BUF_SIZE = 16 * 1024 * 1024

# Per-attempt connect() timeout (seconds). Without this, a single attempt can
# block for the OS default TCP timeout (~127 s on Linux) and the retry loop
# never actually retries — which is why the wired link appeared to hang forever.
_CONNECT_TIMEOUT_S = 5

# Server accept() timeout (seconds). Rank 0 waits up to 5 minutes for Rank 1.
_ACCEPT_TIMEOUT_S = 300

# TCP keepalive: start probing after 60 s idle, repeat every 10 s, drop after 6 failures.
# Critical on a direct wired link where there is no NAT/router to keep the session alive
# during the long tokenizer + model-loading phase that happens after accept().
def _apply_socket_options(sock: socket.socket) -> None:
    """Apply TCP options tuned for large tensor transfers over a direct wired link."""
    # Disable Nagle — send each tensor chunk immediately, no 200 ms coalescing delay.
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    # Large send/recv buffers so the kernel can pipeline tensor data over Gigabit Ethernet.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, _SOCKET_BUF_SIZE)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _SOCKET_BUF_SIZE)
    # Keepalive prevents silent connection drops on direct Ethernet during model loading.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):   # Linux
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE,   60)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL,  10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT,     6)
    if hasattr(socket, "TCP_KEEPALIVE"):  # macOS
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE,  60)

def _send_raw_bytes(data: bytes):
    """Send raw bytes through the socket in chunks."""
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        sent = _COMM_SOCKET.send(view[offset:offset + _RECV_CHUNK_SIZE])
        if sent == 0:
            raise ConnectionError("Network socket closed by peer during send.")
        offset += sent

def socket_send_payload(payload: bytes):
    global _COMM_SOCKET
    if _COMM_SOCKET is None:
        raise RuntimeError("Network bridge socket is not initialized.")
    # Header: 4-byte magic + 4-byte payload length
    _COMM_SOCKET.sendall(struct.pack("!II", _PACKET_MAGIC, len(payload)))
    _send_raw_bytes(payload)

def socket_send_multipart(*parts):
    """Send multiple byte parts as a single framed payload WITHOUT concatenating them.
    Avoids allocating a temporary buffer equal to the full tensor size."""
    global _COMM_SOCKET
    if _COMM_SOCKET is None:
        raise RuntimeError("Network bridge socket is not initialized.")
    # Use .nbytes for memoryview (len() only gives first-dimension count for nd arrays)
    def _bytesize(p):
        return p.nbytes if isinstance(p, memoryview) else len(p)
    total = sum(_bytesize(p) for p in parts)
    _COMM_SOCKET.sendall(struct.pack("!II", _PACKET_MAGIC, total))
    for part in parts:
        if isinstance(part, memoryview):
            # Cast to 1-D byte view so _send_raw_bytes can slice it correctly
            _send_raw_bytes(part.cast("B"))
        else:
            _send_raw_bytes(part if isinstance(part, (bytes, bytearray)) else bytes(part))

def socket_recv_payload() -> bytes:
    global _COMM_SOCKET
    if _COMM_SOCKET is None:
        raise RuntimeError("Network bridge socket is not initialized.")
    
    # Read 8-byte header: magic (4 bytes) + length (4 bytes)
    header = bytearray()
    for attempt in range(3): # Retry reading the header itself up to 3 times
        try:
            while len(header) < 8:
                chunk = _COMM_SOCKET.recv(8 - len(header))
                if not chunk:
                    raise ConnectionError("Network socket closed by peer during header handshake.")
                header.extend(chunk)
            magic, payload_len = struct.unpack("!II", header)
            if magic != _PACKET_MAGIC:
                raise RuntimeError(f"Packet framing error: expected magic 0x{_PACKET_MAGIC:08X}, got 0x{magic:08X}. The socket stream is desynchronized!")
            break # Success on header read
        except (ConnectionError, OSError) as e:
            if attempt < 2:
                print(f"⚠️ Failed to read full packet header. Retrying in 1s... ({attempt+1}/3)")
                header = bytearray() # Reset header for retry
                time.sleep(1)
            else:
                raise ConnectionError("Failed to read socket header after multiple retries.") from e

    # Read actual payload in chunks
    payload_bytes = bytearray(payload_len)
    offset = 0
    for attempt in range(3): # Retry reading the payload up to 3 times
        try:
            while offset < payload_len:
                chunk = _COMM_SOCKET.recv(min(_RECV_CHUNK_SIZE, payload_len - offset))
                if not chunk:
                    raise ConnectionError("Network socket closed by peer during data transmission.")
                payload_bytes[offset:offset + len(chunk)] = chunk
                offset += len(chunk)
            return bytes(payload_bytes)
        except (ConnectionError, OSError) as e:
            if attempt < 2:
                print(f"⚠️ Failed to read full payload. Retrying in 1s... ({attempt+1}/3)")
                # Clear the partially received data before retrying
                offset = 0
                payload_bytes = bytearray(payload_len)
                time.sleep(1)
            else:
                raise ConnectionError("Failed to read socket payload after multiple retries.") from e


# ==============================================================================
# Tensor Header Helpers
# ==============================================================================

def _make_tensor_header(t: torch.Tensor) -> bytes:
    """Build a compact binary header: [ndim:4B][dim_0..dim_n: 8B each][dtype_len:4B][dtype_str]"""
    dtype_str = str(t.dtype).encode()
    shape = list(t.shape)
    ndim = len(shape)
    return struct.pack(f"!I{ndim}QI", ndim, *shape, len(dtype_str)) + dtype_str


def _parse_tensor_header(data: bytes, offset: int = 0):
    """Parse header built by _make_tensor_header. Returns (shape, np_dtype, new_offset)."""
    _torch_to_np = {
        "torch.float32": np.float32, "torch.float16": np.float16,
        "torch.bfloat16": np.float32,
        "torch.int64": np.int64, "torch.int32": np.int32,
        "torch.int8": np.int8, "torch.uint8": np.uint8,
    }
    ndim = struct.unpack_from("!I", data, offset)[0]; offset += 4
    shape = struct.unpack_from(f"!{ndim}Q", data, offset); offset += 8 * ndim
    dtype_len = struct.unpack_from("!I", data, offset)[0]; offset += 4
    dtype_str = data[offset:offset + dtype_len].decode(); offset += dtype_len
    np_dtype = _torch_to_np.get(dtype_str, np.float32)
    return shape, np_dtype, offset


def _send_raw_tensor(t: torch.Tensor):
    """Send tensor as header + raw bytes. Zero-copy: sends header and data as multipart payload."""
    t = t.contiguous()
    header = _make_tensor_header(t)
    socket_send_multipart(header, memoryview(t.numpy()))


def _recv_raw_tensor(device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    """Receive a raw tensor and restore to target device/dtype."""
    data = socket_recv_payload()
    shape, np_dtype, offset = _parse_tensor_header(data)
    arr = np.frombuffer(data[offset:], dtype=np_dtype).reshape(shape)
    return torch.from_numpy(arr.copy()).to(device=device, dtype=dtype)


# ==============================================================================
# INT8 Quantized Activation Transfer (2x bandwidth vs fp16, 4x vs fp32)
# ==============================================================================

def _send_quantized_activation(t: torch.Tensor):
    """Dynamic INT8 quantization: compute per-tensor scale, quantize, send scale+int8 data.
    Sanitizes NaN/Inf BEFORE quantization — early float16 training commonly produces inf
    activations which would corrupt the INT8 packet and cause NaN gradients on Rank 1."""
    t_f32 = t.detach().cpu().float()
    # Replace NaN/Inf so the quantizer sees finite values.
    # fp16 max finite is 65504; clamp to that range to avoid scale = inf.
    t_f32 = torch.nan_to_num(t_f32, nan=0.0, posinf=65504.0, neginf=-65504.0)
    abs_max = t_f32.abs().max().item()
    scale = abs_max / 127.0 if abs_max > 1e-8 else 1.0
    quantized = (t_f32 / scale).clamp(-128, 127).to(torch.int8).contiguous()
    scale_hdr = struct.pack("!f", scale)
    tensor_hdr = _make_tensor_header(quantized)
    socket_send_multipart(scale_hdr, tensor_hdr, memoryview(quantized.numpy()))


def _recv_quantized_activation(device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    """Receive and dequantize an INT8 activation tensor.
    Always dequantizes to float32 first — keeping the grad-tracking boundary tensor in
    float32 is standard AMP practice and prevents float16 backward instability on Rank 1.
    Autocast will cast it to fp16 inside the model forward pass automatically."""
    data = socket_recv_payload()
    scale = struct.unpack_from("!f", data, 0)[0]
    shape, _, offset = _parse_tensor_header(data, offset=4)
    arr = np.frombuffer(data[offset:], dtype=np.int8).reshape(shape)
    t_int8 = torch.from_numpy(arr.copy())
    # Dequantize to float32 on device — autocast handles fp16 cast inside the model
    return (t_int8.float() * scale).to(device=device)


# ==============================================================================
# Async Prefetch for Rank 1: overlap next activation recv with optimizer step
# ==============================================================================

_PREFETCH_QUEUE: _queue.Queue = _queue.Queue(maxsize=1)


def _start_async_recv_activations(device: torch.device, dtype: torch.dtype):
    """Start receiving the next batch's activations in a background thread.
    Call _collect_async_activations() to get the result. Safe: only one in-flight at a time."""
    def _worker():
        try:
            activ = _recv_quantized_activation(device, dtype)
            labels = _recv_raw_tensor(device, torch.long)
            _PREFETCH_QUEUE.put((activ, labels))
        except Exception as e:
            _PREFETCH_QUEUE.put(e)
    threading.Thread(target=_worker, daemon=True).start()


def _collect_async_activations() -> Tuple[torch.Tensor, torch.Tensor]:
    """Block until the async-prefetched (activations, labels) are ready."""
    result = _PREFETCH_QUEUE.get()
    if isinstance(result, Exception):
        raise result
    return result


# ==============================================================================
# Public send/recv API used by the training loop
# ==============================================================================

def send_tensor(tensor: torch.Tensor, dst: int):
    """Send gradient tensor as raw float16 bytes — no pickle, no zlib."""
    _send_raw_tensor(tensor.detach().cpu().half())


def recv_tensor(src: int, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
    """Receive a raw gradient tensor and restore to target device/dtype."""
    return _recv_raw_tensor(device, dtype)


def send_activations_and_labels(activations: torch.Tensor, labels: torch.Tensor):
    """Send INT8-quantized activations then labels. ~4x smaller than fp32, ~2x vs fp16."""
    _send_quantized_activation(activations)
    _send_raw_tensor(labels.detach().cpu())


def recv_activations_and_labels(device: torch.device, dtype: torch.dtype) -> Tuple[torch.Tensor, torch.Tensor]:
    """Receive INT8-quantized activations and raw labels."""
    activations = _recv_quantized_activation(device, dtype)
    labels = _recv_raw_tensor(device, torch.long)
    return activations, labels


# ==============================================================================
# AsyncSocketSender: background thread for non-blocking sends (Rank 0 & 1)
# Eliminates the GPU idle "bubble" — the network card blasts data over the wire
# at the exact same millisecond the GPU is computing the next micro-batch.
# ==============================================================================

class AsyncSocketSender:
    """Dedicated background thread for non-blocking tensor sends.
    
    Usage (1F1B pattern on Rank 0):
        sender.send_activation_nowait(activ, labels)  # returns immediately
        with autocast_ctx:                             # GPU computes next batch
            next_activ = model(next_input)             # ← overlaps with send!
        sender.wait()                                  # ensure send finished
    """

    def __init__(self):
        self._q: _queue.Queue = _queue.Queue(maxsize=1)
        self._done = threading.Event()
        self._done.set()  # initially not busy
        self._error: Optional[Exception] = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            item = self._q.get()
            if item is None:
                break  # sentinel: shut down
            try:
                fn, args = item
                fn(*args)
            except Exception as e:
                self._error = e
            finally:
                self._done.set()

    def _enqueue(self, fn, *args):
        """Queue a send operation. Blocks only if a prior send hasn't finished yet."""
        if self._error:
            raise self._error
        self._done.clear()
        self._q.put((fn, args))

    def send_activation_nowait(self, activations: torch.Tensor, labels: torch.Tensor):
        """Queue activation + labels for async background send. Returns immediately.
        The GPU is free to start computing the next batch before this finishes."""
        # Pre-move to CPU on the calling thread so the GPU finishes its work and
        # the background thread only does CPU/network work (no CUDA synchronization there).
        activ_cpu = activations.detach().cpu()
        labels_cpu = labels.detach().cpu()
        self._enqueue(send_activations_and_labels, activ_cpu, labels_cpu)

    def send_grad_nowait(self, grad: torch.Tensor):
        """Queue gradient for async background send (used on Rank 1)."""
        grad_cpu = grad.detach().cpu().half()
        self._enqueue(_send_raw_tensor, grad_cpu)

    def wait(self):
        """Block until the in-flight send completes. Call before you need the socket again."""
        self._done.wait()
        if self._error:
            raise self._error

    def stop(self):
        """Signal background thread to exit cleanly."""
        self._q.put(None)


# ==============================================================================
# Dynamic Pretrained Model Sharding & Robust Weight Loading
# ==============================================================================

def load_stage_weights(out: Path, stage_model: nn.Module, rank: int, stage0_blocks: int, stage1_blocks: int, device: torch.device, dtype: torch.dtype, modelver: str = DEFAULT_MODELVER) -> bool:
    """Load stage weights from stage checkpoint or dynamically shard from full pretrained checkpoint, discarding NaN-corrupted files."""
    checkpoint_name = pipeline_stage_checkpoint_name(modelver, rank)
    checkpoint_path = out / checkpoint_name
    
    # Check if stage checkpoint exists and does NOT contain NaN values
    if checkpoint_path.exists():
        print(f"Rank {rank}: Loading stage weights from existing checkpoint: {checkpoint_path}...")
        try:
            payload = torch.load(checkpoint_path, map_location="cpu")
            model_state = payload["model_state"]
            
            # Check for NaN values in loaded state to avoid loading corrupted runs
            has_nan = any(torch.isnan(param).any() for param in model_state.values())
            if not has_nan:
                stage_model.load_state_dict(model_state)
                stage_model.to(device=device, dtype=dtype)
                print(f"Rank {rank}: Stage weights loaded successfully from checkpoint.")
                return True
            else:
                print(f"WARNING: Stage checkpoint {checkpoint_name} is corrupted with NaN values! Discarding.")
        except Exception as e:
            print(f"WARNING: Failed to load stage checkpoint {checkpoint_name}: {e}. Discarding.")
            
    # Try to dynamically shard from the full pretrained model
    pretrained_candidates = [
        out / pretrained_checkpoint_name(modelver),
        out / LEGACY_PRETRAINED_CHECKPOINT,
        Path("runs/geocentric2_1") / pretrained_checkpoint_name(modelver),
        Path("runs/geocentric2_1") / LEGACY_PRETRAINED_CHECKPOINT,
    ]
    pretrained_path = next((path for path in pretrained_candidates if path.exists()), None)

    if pretrained_path is not None:
        print(f"Rank {rank}: Sharding from full pretrained checkpoint: {pretrained_path}...")
        try:
            payload = torch.load(pretrained_path, map_location="cpu")
            full_state_dict = payload["model_state"]
            
            # Verify that the full pretrained model does not contain NaN
            has_nan = any(torch.isnan(param).any() for param in full_state_dict.values())
            if has_nan:
                print("WARNING: Base pretrained checkpoint is also corrupted with NaN! Cannot load.")
                return False
                
            stage_state_dict = {}
            if rank == 0:
                stage_state_dict["token_embedding.weight"] = full_state_dict["token_embedding.weight"]
                stage_state_dict["position_embedding.weight"] = full_state_dict["position_embedding.weight"]
                for i in range(stage0_blocks):
                    for k, v in full_state_dict.items():
                        if k.startswith(f"blocks.{i}."):
                            stage_state_dict[k] = v
            else:
                for i in range(stage1_blocks):
                    full_block_idx = i + stage0_blocks
                    for k, v in full_state_dict.items():
                        if k.startswith(f"blocks.{full_block_idx}."):
                            new_key = k.replace(f"blocks.{full_block_idx}.", f"blocks.{i}.")
                            stage_state_dict[new_key] = v
                stage_state_dict["ln_f.weight"] = full_state_dict["ln_f.weight"]
                stage_state_dict["ln_f.bias"] = full_state_dict["ln_f.bias"]
                stage_state_dict["lm_head.weight"] = full_state_dict["lm_head.weight"]
                stage_state_dict["ln_f.bias"] = full_state_dict["ln_f.bias"]
                stage_state_dict["lm_head.weight"] = full_state_dict["lm_head.weight"]
                
            stage_model.load_state_dict(stage_state_dict, strict=True)
            stage_model.to(device=device, dtype=dtype)
            print(f"Rank {rank}: Dynamic sharding successful! Stage weights loaded and stable.")
            return True
        except Exception as e:
            print(f"WARNING: Failed to dynamically shard from {pretrained_path}: {e}")
        
    print(f"Rank {rank}: No valid checkpoints found. Initializing with clean random weights.")
    return False


def has_nan_gradients_or_weights(model: nn.Module) -> Tuple[bool, str]:
    """Check if any parameter gradients or parameter weights contain NaN values."""
    for name, param in model.named_parameters():
        if param.grad is not None and torch.isnan(param.grad).any():
            return True, f"Gradient of parameter '{name}' contains NaN!"
        if torch.isnan(param).any():
            return True, f"Parameter weight '{name}' contains NaN!"
    return False, ""


# ==============================================================================
# Distributed Loop Orchestrators
# ==============================================================================



def auto_setup_wired_link(rank: int) -> str:
    """
    Automatically detects the direct USB network interface on Linux or macOS,
    brings it up, and assigns a matching static IP.
    Returns the target Master IP (192.168.99.1).
    """
    import platform
    import subprocess
    import sys
    import os

    target_mac_ip = "192.168.99.1"
    target_linux_ip = "192.168.99.2"
    system_os = platform.system().lower()
    
    print("\n" + "=" * 60)
    print(f"RUNNING AUTOMATED USB WIRED LINK CONFIGURATION (Rank {rank})")
    print("=" * 60)

    if system_os == "linux":
        iface = None
        net_dir = "/sys/class/net"
        if os.path.exists(net_dir):
            # 1. Look for explicit USB subsystems
            for d in os.listdir(net_dir):
                if d in ["lo", "docker0"] or d.startswith("wlan") or d.startswith("wlp"):
                    continue
                dev_link = os.path.join(net_dir, d, "device")
                if os.path.exists(dev_link):
                    if "usb" in os.path.realpath(dev_link):
                        iface = d
                        break
            
            # 2. Fallback to standard predictable network interface naming for USB
            if not iface:
                for d in os.listdir(net_dir):
                    if d.startswith("enx") or d.startswith("usb"):
                        iface = d
                        break

        if not iface:
            print("❌ Error: Could not automatically pinpoint a USB network interface on Linux.")
            print("Ensure your MacBook is securely plugged into a USB-3/Type-C slot.")
            return target_mac_ip

        print(f"Found Linux USB network interface: {iface}")
        try:
            print(f"Bringing up {iface} and assigning {target_linux_ip} (Sudo password may be requested)...")
            subprocess.run(["sudo", "ip", "link", "set", iface, "up"], check=True)
            
            # Check if address is already assigned to avoid duplication errors
            addr_check = subprocess.run(["ip", "addr", "show", "dev", iface], capture_output=True, text=True)
            if target_linux_ip not in addr_check.stdout:
                subprocess.run(["sudo", "ip", "addr", "add", f"{target_linux_ip}/24", "dev", iface], check=True)
            print(f"✅ Success: {iface} is configured on Linux node.")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error executing configuration commands: {e}")

    elif system_os == "darwin":  # macOS
        iface = None
        try:
            # Parse hardware ports looking for a USB link or virtual bridge setup
            res = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True, check=True)
            lines = res.stdout.split("\n")
            for i, line in enumerate(lines):
                if "Hardware Port:" in line and any(k in line for k in ["USB", "Bridge", "Ethernet"]):
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if "Device:" in lines[j]:
                            iface = lines[j].split("Device:")[1].strip()
                            break
                if iface:
                    break
            
            # Fallback to scanning ifconfig for alternate link devices if hardware port metadata is missing
            if not iface:
                ifconfig_res = subprocess.run(["ifconfig", "-l"], capture_output=True, text=True, check=True)
                for f in ifconfig_res.stdout.split():
                    if f not in ["lo0", "en0", "gif0", "stf0"] and not f.startswith("utun"):
                        iface = f
                        break

            if iface:
                print(f"Found macOS network interface: {iface}")
                print(f"Bringing up {iface} and assigning {target_mac_ip} (Sudo password may be requested)...")
                subprocess.run(["sudo", "ifconfig", iface, target_mac_ip, "netmask", "255.255.255.0", "up"], check=True)
                print(f"✅ Success: {iface} is configured on macOS master node.")
            else:
                print("❌ Error: Could not automatically detect target network interface on macOS.")
        except Exception as e:
            print(f"❌ Error configuring macOS network stack: {e}")

    print("=" * 60 + "\n")
    return target_mac_ip


# ==============================================================================
# Distributed Loop Orchestrators
# ==============================================================================
 
def run_distributed_pipeline_train(args):
    """Orchestrate 2-device Pipeline Parallel distributed training loop using pure TCP socket connection."""
    
    # Trigger auto-setup if flag is enabled
    if getattr(args, "auto_wired_setup", False):
        args.master_ip = auto_setup_wired_link(args.rank)

    print("=" * 80)
    print("INITIALIZING CROSS-OS COLLABORATIVE PIPELINE PARALLEL TRAINER")
    print("=" * 80)
    print(f"Master IP: {args.master_ip}")
    print(f"Master Port: {args.master_port}")
    print(f"Local Node Rank: {args.rank}")
    print(f"Total Nodes: {args.world_size}")
    modelver = getattr(args, "modelver", DEFAULT_MODELVER)
    
    # 1. Initialize TCP Socket Connection
    global _COMM_SOCKET
    
    port = int(args.master_port)
    if args.rank == 0:
        # Rank 0 (Mac / Server) listens for incoming connections
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("0.0.0.0", port))
        server_sock.listen(1)
        # Time-box the wait so Rank 0 exits cleanly if Rank 1 never shows up.
        server_sock.settimeout(_ACCEPT_TIMEOUT_S)
        print(f"Server socket listening on 0.0.0.0:{port} (waiting up to {_ACCEPT_TIMEOUT_S}s for Rank 1 to connect)...")
        try:
            _COMM_SOCKET, addr = server_sock.accept()
        except socket.timeout:
            server_sock.close()
            raise RuntimeError(
                f"Timed out after {_ACCEPT_TIMEOUT_S}s waiting for Rank 1 to connect. "
                "Make sure the Linux PC is running the pipeline-train command "
                "with --rank 1 and the correct --master_ip."
            )
        server_sock.close()
        _apply_socket_options(_COMM_SOCKET)
        print(f"Cross-OS distributed TCP link successfully established with Linux Worker at {addr}!")
    else:
        # Rank 1 (Linux / Client) connects to Rank 0 (Mac / Master)
        print(f"Connecting to Master at {args.master_ip}:{port}...")
        import time
        connected = False
        for attempt in range(120):
            # Create a fresh socket each attempt — never reuse a socket whose
            # connect() already failed, as it may be in an undefined state.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # KEY FIX: set a per-attempt timeout BEFORE calling connect().
            # Without this, connect() blocks for the OS default TCP timeout
            # (~127 s on Linux) when the wired peer is slow to respond, so the
            # "retry every 1 s" loop never actually retried — it just hung.
            sock.settimeout(_CONNECT_TIMEOUT_S)
            try:
                sock.connect((args.master_ip, port))
                # Connection succeeded — switch back to blocking mode so
                # recv/send calls block until data arrives (expected behaviour).
                sock.settimeout(None)
                _COMM_SOCKET = sock
                _apply_socket_options(_COMM_SOCKET)
                connected = True
                print("Cross-OS distributed TCP link successfully established with Mac Master!")
                break
            except (OSError, socket.timeout) as e:
                # KEY FIX: always close the socket on failure to avoid leaking
                # file descriptors. The old code only reassigned _COMM_SOCKET
                # without closing the underlying OS socket handle.
                sock.close()
                print(f"Connection attempt {attempt+1}/120 failed: {e}. Retrying in 1s...")
                time.sleep(1)
        if not connected:
            raise RuntimeError(f"Could not connect to Master at {args.master_ip}:{port}")
            
    # 2. Select native computing device
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print("CUDA detected: Executing on high-performance NVIDIA GPU!")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        print("MPS detected: Executing on high-performance Apple Silicon GPU!")
    else:
        device = torch.device("cpu")
        print("No GPU detected. Running on CPU.")
        
    dtype = resolve_dtype(device, args.dtype)
    runtime_check(device, dtype)
    
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    
    tok_out = out / "tokenizer.json"
    if not tok_out.exists():
        tokenizer_path = find_tokenizer_path(out)
        if tokenizer_path != tok_out:
            shutil.copyfile(tokenizer_path, tok_out)
            print(f"Using tokenizer from fallback location: {tokenizer_path}")
    tokenizer = load_tokenizer(tok_out)
    pad_id = token_id(tokenizer, "<pad>")
    
    # 3. Model Configuration & Stage Setup
    config = GPTConfig(
        vocab_size=tokenizer.get_vocab_size(),
        block_size=args.block_size,
        n_layer=args.n_layer,
        n_head=args.n_head,
        n_embd=args.n_embd,
        dropout=getattr(args, "dropout", 0.1),
        gradient_checkpointing=args.gradient_checkpointing,
        model_name=modelver,
    )
    
    # Heterogeneous VRAM balancing: Rank 0 (MacBook Air M4 with 11GB training VRAM pool)
    # handles the first 2/3 of the layers, while Rank 1 (NVIDIA RTX 2060 with 5GB usable VRAM pool)
    # handles the concluding 1/3 of the layers.
    stage0_blocks = int(math.ceil(config.n_layer * (2 / 3)))
    stage1_blocks = config.n_layer - stage0_blocks
    print(f"Heterogeneous VRAM Balancing: Rank 0 (Mac) handles {stage0_blocks} layers | Rank 1 (PC) handles {stage1_blocks} layers")
    
    if args.rank == 0:
        # MacBook holds embedding + first 2/3 of Blocks (e.g. 16 blocks for 24-layer large model)
        stage_model = GeocentricStage0(config, stage0_blocks).to(device=device, dtype=dtype)
        print(f"Initial Stage: {stage0_blocks} blocks sharded successfully in MPS memory.")
        load_stage_weights(out, stage_model, 0, stage0_blocks, stage1_blocks, device, dtype, modelver=modelver)
    else:
        # PC holds concluding 1/3 of Blocks + LM Head (e.g. 8 blocks for 24-layer large model)
        stage_model = GeocentricStage1(config, stage1_blocks).to(device=device, dtype=dtype)
        print(f"Concluding Stage: {stage1_blocks} blocks sharded successfully in CUDA memory.")
        load_stage_weights(out, stage_model, 1, stage0_blocks, stage1_blocks, device, dtype, modelver=modelver)
        
    print(f"Local Stage parameters: {count_parameters(stage_model):,}")
    
    # 4. Data Loading (ONLY Rank 0 loads and iterates the dataset - it drives all batches!)
    # Rank 1 (PC) does NOT load any dataset. It only receives activations from Rank 0 via TCP.
    # Rank 0 sends the number of batches at the start of each epoch so Rank 1 loops in sync.
    train_loader = None
    if args.rank == 0:
        if args.data_path.endswith(".json") or args.data_path.endswith(".jsonl"):
            print(f"Detected SFT instruction dataset format! Loading SFTDataset...")
            dataset = SFTDataset(tokenizer, args.data_path, block_size=config.block_size)
        else:
            print(f"Detected standard text corpus format! Loading CausalTextDataset...")
            dataset = CausalTextDataset(tokenizer, iter_texts(args.data_path), block_size=config.block_size)
        train_loader = DataLoader(
            dataset, batch_size=args.batch_size, shuffle=True,
            collate_fn=lambda b: pad_collate(b, pad_id),
            num_workers=0,  # Must be 0: CausalTextDataset uses a generator which can't be pickled
        )
        print(f"Rank 0: Dataset loaded. {len(train_loader)} batches per epoch.")
    else:
        print("Rank 1: No local dataset needed. Waiting to receive activations from Rank 0 (Mac) over TCP...")
    
    optim = AdamW(stage_model.parameters(), lr=args.learning_rate, betas=(0.9, 0.95), weight_decay=0.1)
    
    # Initialize the backup state in CPU memory with the loaded stable weights
    last_good_state = {k: v.cpu().clone() for k, v in stage_model.state_dict().items()}
    
    # Autocast context
    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        autocast_ctx = contextlib.nullcontext()

    # GradScaler: essential for float16 — prevents gradient underflow/overflow.
    # MPS does not support GradScaler, so only enable on CUDA.
    use_scaler = (device.type == "cuda" and dtype == torch.float16)
    scaler = torch.amp.GradScaler(enabled=use_scaler)
        
    step = 0

    # -----------------------------------------------------------------------
    # READY handshake — both nodes must signal readiness before training.
    #
    # WHY THIS MATTERS ON A WIRED LINK:
    # After accept()/connect() returns, both sides race independently through
    # tokenizer loading, model sharding, and dataset loading. On a wired direct
    # Ethernet link the Mac and Linux box have very different load speeds and
    # there is no router buffering the idle time. If one side (e.g. the Mac)
    # crashes or hits an error during setup, its OS immediately closes the TCP
    # socket. The other side then gets an empty recv() at the very first
    # socket_recv_payload() call — which showed up as the cryptic:
    #   "ConnectionError: Network socket closed by peer during header handshake"
    # even though both sides had seemingly connected successfully.
    #
    # This barrier guarantees both sides have completed ALL setup (tokenizer,
    # model init, dataset) before any training tensors are exchanged.
    # -----------------------------------------------------------------------
    print(f"Rank {args.rank}: Setup complete. Waiting for other node ready signal...")
    if args.rank == 0:
        # Mac sends READY first, then waits for Linux to confirm.
        socket_send_payload(b"READY")
        ack = socket_recv_payload()
        if ack != b"READY":
            raise RuntimeError(f"Unexpected handshake response from Rank 1: {ack!r}")
    else:
        # Linux waits for Mac to be ready, then sends its own READY.
        ack = socket_recv_payload()
        if ack != b"READY":
            raise RuntimeError(f"Unexpected handshake response from Rank 0: {ack!r}")
        socket_send_payload(b"READY")
    print(f"Rank {args.rank}: Both nodes ready — link confirmed over {'wired' if '192.168.99' in args.master_ip else 'network'}.")

    print("=" * 80)
    print("PIPELINE PARALLEL SYSTEM FULLY OPERATIONAL. STARTING COOPERATIVE pretraining...")
    print("=" * 80 + "\n")
    
    # Rank 0 uses a background sender thread (1F1B pipeline: send batch N while computing batch N+1)
    _rank0_sender = AsyncSocketSender() if args.rank == 0 else None
    # Rank 1 uses a background sender thread for gradients (overlaps grad send with optimizer step)
    _rank1_sender = AsyncSocketSender() if args.rank == 1 else None

    try:
        for epoch in range(1, args.epochs + 1):
            stage_model.train()
            running_loss = 0.0
            seen = 0

            if args.rank == 0:
                # --- RANK 0: Tell Rank 1 how many batches to expect this epoch ---
                num_batches = len(train_loader)
                socket_send_payload(struct.pack("!I", num_batches))
                pbar = tqdm(train_loader, desc=f"Pipeline pretraining Epoch {epoch}")
            else:
                # --- RANK 1: Receive the batch count from Rank 0 ---
                raw = socket_recv_payload()
                num_batches = struct.unpack("!I", raw)[0]
                pbar = tqdm(range(num_batches), desc=f"Pipeline pretraining Epoch {epoch}")

            # 1F1B lookahead state for Rank 0
            _pending_activ = None   # activation tensor waiting for its gradient
            _pending_micro = 0      # which micro-batch index it belongs to

            for micro, batch in enumerate(pbar, start=1):
                if args.rank == 0:
                    # ----------------------------------------------------------
                    # RANK 0 (MacBook): 1F1B Async Pipeline
                    # ----------------------------------------------------------
                    # Step A: Compute forward for current batch
                    input_ids = batch["input_ids"].to(device)
                    labels = batch["labels"]

                    with autocast_ctx:
                        activations = stage_model(input_ids)

                    # Step B: Queue activation send in background thread — returns IMMEDIATELY.
                    # The GPU is now free to process the PREVIOUS batch's gradient while the
                    # network card blasts the current activation to Rank 1 over Wi-Fi.
                    _rank0_sender.send_activation_nowait(activations, labels)

                    # Step C: While the network sends current batch, receive & backward PREVIOUS batch.
                    if _pending_activ is not None:
                        grad_activations = recv_tensor(src=1, device=device, dtype=dtype)
                        _pending_activ.backward(grad_activations)

                        if _pending_micro % args.gradient_accumulation_steps == 0 or _pending_micro == num_batches:
                            torch.nn.utils.clip_grad_norm_(stage_model.parameters(), 1.0)
                            nan_found, msg = has_nan_gradients_or_weights(stage_model)
                            if nan_found:
                                print("\n" + "=" * 80)
                                print(f"CRITICAL WARNING: NaN on MacBook (Rank 0) at Step {step + 1}!")
                                print(msg)
                                print("Rolling back to last good state...")
                                print("=" * 80 + "\n")
                                stage_model.load_state_dict(last_good_state)
                                stage_model.to(device=device, dtype=dtype)
                                optim.zero_grad(set_to_none=True)
                                save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 0, recovered=True))
                                save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 0))
                            else:
                                optim.step()
                                optim.zero_grad(set_to_none=True)
                                step += 1
                                last_good_state = {k: v.cpu().clone() for k, v in stage_model.state_dict().items()}
                            if device.type == "mps":
                                torch.mps.synchronize()

                    # Step D: Wait for background send to finish before the socket is used again
                    _rank0_sender.wait()
                    _pending_activ = activations
                    _pending_micro = micro

                    # Step E: Last batch — drain the pending backward after loop
                    if micro == num_batches:
                        grad_activations = recv_tensor(src=1, device=device, dtype=dtype)
                        _pending_activ.backward(grad_activations)
                        if _pending_micro % args.gradient_accumulation_steps == 0 or _pending_micro == num_batches:
                            torch.nn.utils.clip_grad_norm_(stage_model.parameters(), 1.0)
                            nan_found, msg = has_nan_gradients_or_weights(stage_model)
                            if not nan_found:
                                optim.step()
                                optim.zero_grad(set_to_none=True)
                                step += 1
                                last_good_state = {k: v.cpu().clone() for k, v in stage_model.state_dict().items()}
                            if device.type == "mps":
                                torch.mps.synchronize()
                        _pending_activ = None
                            
                else:
                    # ----------------------------------------------------------
                    # RANK 1 (NVIDIA PC): Receive Activations & Forward+Backward
                    # ----------------------------------------------------------
                    if micro == 1:
                        activations, labels = recv_activations_and_labels(device=device, dtype=dtype)
                    else:
                        activations, labels = _collect_async_activations()

                    # Keep activation boundary in float32 — prevents float16 backward instability.
                    # autocast will cast it to fp16 inside the model forward automatically.
                    activations = activations.float().clone().detach().requires_grad_(True)

                    with autocast_ctx:
                        logits, loss = stage_model(activations, labels=labels)

                    if loss is None:
                        raise RuntimeError("Loss calculation error.")

                    # Scale loss before backward so Rank 1's parameter grads don't underflow.
                    scaler.scale(loss / args.gradient_accumulation_steps).backward()

                    # activations.grad is scaled by scaler — unscale it before sending to
                    # Rank 0 (Mac / MPS has no GradScaler, so it needs the true gradient).
                    grad_activations = activations.grad
                    if use_scaler and grad_activations is not None:
                        grad_activations = grad_activations / scaler.get_scale()

                    # Async send (unscaled) gradients back to Rank 0
                    _rank1_sender.send_grad_nowait(grad_activations)

                    running_loss += float(loss.detach().cpu())
                    seen += 1

                    # Kick off background recv for next batch while we do the optimizer step
                    if micro < num_batches:
                        _start_async_recv_activations(device, dtype)

                    if micro % args.gradient_accumulation_steps == 0 or micro == num_batches:
                        # Ensure grad send is done before any socket ops
                        _rank1_sender.wait()

                        # Unscale Rank 1's parameter gradients before clipping
                        scaler.unscale_(optim)
                        torch.nn.utils.clip_grad_norm_(stage_model.parameters(), 1.0)

                        nan_found, msg = has_nan_gradients_or_weights(stage_model)
                        if nan_found:
                            print("\n" + "=" * 80)
                            print(f"CRITICAL WARNING: NaN on NVIDIA PC (Rank 1) at Step {step + 1}!")
                            print(msg)
                            print("Rolling back to last good state...")
                            print("=" * 80 + "\n")
                            stage_model.load_state_dict(last_good_state)
                            stage_model.to(device=device, dtype=dtype)
                            optim.zero_grad(set_to_none=True)
                            scaler.update()  # still update scale (will reduce it)
                            save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 1, recovered=True))
                            save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 1))
                        else:
                            # scaler.step skips automatically if any remaining inf/NaN present
                            prev_scale = scaler.get_scale()
                            scaler.step(optim)
                            scaler.update()
                            optim.zero_grad(set_to_none=True)
                            if scaler.get_scale() >= prev_scale:
                                # Step was NOT skipped — count it
                                step += 1
                                last_good_state = {k: v.cpu().clone() for k, v in stage_model.state_dict().items()}
                    else:
                        # Non-accumulation step: wait for grad send before next recv starts
                        _rank1_sender.wait()

                    if step % 5 == 0 and seen > 0:
                        avg = running_loss / max(1, seen)
                        pbar.set_postfix(loss=f"{avg:.4f}", step=step, scale=f"{scaler.get_scale():.0f}")
                            
            # Synchronize nodes at epoch boundary
            if args.rank == 0:
                socket_send_payload(b"BARRIER")
                if socket_recv_payload() != b"BARRIER":
                    raise RuntimeError("Node synchronization failed at epoch boundary.")
            else:
                if socket_recv_payload() != b"BARRIER":
                    raise RuntimeError("Node synchronization failed at epoch boundary.")
                socket_send_payload(b"BARRIER")
            
            # Save weights on PC (Rank 1 holds the concluding layer which we can export)
            # In true sharded architecture, we save local slices, but to keep it simple,
            # Rank 1 checkpoint contains concluding layers.
            if args.rank == 1:
                save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 1))
                print("Rank 1: Saved stage 1 concluding layers successfully.")
            else:
                save_checkpoint(stage_model, out, step, name=pipeline_stage_checkpoint_name(modelver, 0))
                print("Rank 0: Saved stage 0 embedding layers successfully.")
                
    except KeyboardInterrupt:
        print("\nPipeline training interrupted by user!")
    finally:
        if _rank0_sender is not None:
            _rank0_sender.stop()
        if _rank1_sender is not None:
            _rank1_sender.stop()
        if _COMM_SOCKET is not None:
            _COMM_SOCKET.close()
            _COMM_SOCKET = None


# ==============================================================================
# Single Device Training Loop (Homogeneous Option)
# ==============================================================================

def run_local_pretrain(args):
    """Local, single-device, standalone pretraining loop."""
    print("=" * 80)
    print("INITIALIZING LOCAL SINGLE-DEVICE PRETRAINING LOOP")
    print("=" * 80)
    modelver = getattr(args, "modelver", DEFAULT_MODELVER)
    checkpoint_name = pretrained_checkpoint_name(modelver)
    
    device = select_device(prefer_mps=True)
    dtype = resolve_dtype(device, args.dtype)
    runtime_check(device, dtype)
    
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    
    tok_out = out / "tokenizer.json"
    if not tok_out.exists():
        tokenizer_path = find_tokenizer_path(out)
        if tokenizer_path != tok_out:
            shutil.copyfile(tokenizer_path, tok_out)
            print(f"Using tokenizer from fallback location: {tokenizer_path}")
    tokenizer = load_tokenizer(tok_out)
    pad_id = token_id(tokenizer, "<pad>")
    
    dataset = CausalTextDataset(tokenizer, iter_texts(args.data_path), block_size=args.block_size)
    train_loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, collate_fn=lambda b: pad_collate(b, pad_id))
    
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
    
    model = GeocentricGPT(config).to(device=device, dtype=dtype)
    print(f"Model parameters: {count_parameters(model):,}")
    
    optim = AdamW(model.parameters(), lr=args.learning_rate, betas=(0.9, 0.95), weight_decay=0.1)
    
    if device.type in {"mps", "cuda"} and dtype in {torch.float16, torch.bfloat16}:
        autocast_ctx = torch.amp.autocast(device_type=device.type, dtype=dtype)
    else:
        autocast_ctx = contextlib.nullcontext()
        
    step = 0
    
    try:
        for epoch in range(1, args.epochs + 1):
            model.train()
            pbar = tqdm(train_loader, desc=f"Local Epoch {epoch}")
            running = 0.0
            seen = 0
            
            for micro, batch in enumerate(pbar, start=1):
                input_ids = batch["input_ids"].to(device)
                labels = batch["labels"].to(device)
                
                with autocast_ctx:
                    _, loss = model(input_ids, labels=labels)
                    
                if loss is None:
                    raise RuntimeError("Loss calculation error.")
                    
                (loss / args.gradient_accumulation_steps).backward()
                running += float(loss.detach().cpu())
                seen += 1
                
                if micro % args.gradient_accumulation_steps == 0 or micro == len(train_loader):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optim.step()
                    optim.zero_grad(set_to_none=True)
                    step += 1
                    if device.type == "mps":
                        torch.mps.synchronize()
                        
                    if step % 5 == 0:
                        avg = running / max(1, seen)
                        pbar.set_postfix(loss=f"{avg:.4f}", step=step)
                        
            save_checkpoint(model, out, step, name=checkpoint_name)
            print(f"Saved local checkpoint successfully.")
            
    except KeyboardInterrupt:
        print("\nLocal pretraining halted by user!")
        save_checkpoint(model, out, step, name=checkpoint_name)


# ==============================================================================
# Main Router
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Collaboratively train an AI together over network sharding")
    parser.add_argument("--master_ip", default="127.0.0.1", help="Master node IP address")
    parser.add_argument("--master_port", default="29500", help="Master node socket port")
    parser.add_argument("--rank", type=int, default=0, help="Local rank (0 for MacBook, 1 for PC)")
    parser.add_argument("--world_size", type=int, default=1, help="Total devices: 1 for local, 2+ for sharding")
    parser.add_argument("--auto_wired_setup", action="store_true", default=False, help="Auto-detect and configure direct USB/Wired Link IPs")
    
    parser.add_argument("--data_path", default="data/pretrain_seed.txt")
    parser.add_argument("--output_dir", default="runs/geocentric2_1")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=16)
    parser.add_argument("--learning_rate", type=float, default=3e-4)
    parser.add_argument("--dtype", default="bfloat16")
    
    # Model parameters
    parser.add_argument("--block_size", type=int, default=512)
    parser.add_argument("--n_layer", type=int, default=12)
    parser.add_argument("--n_head", type=int, default=12)
    parser.add_argument("--n_embd", type=int, default=768)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--gradient_checkpointing", action="store_true", default=True)
    parser.add_argument("--modelver", default="Geocentric 2.1", help="Model version name for checkpoint naming")
    
    args = parser.parse_args()
    
    if args.world_size > 1:
        run_distributed_pipeline_train(args)
    else:
        run_local_pretrain(args)


if __name__ == "__main__":
    main()
