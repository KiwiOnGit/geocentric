import sys
from pathlib import Path
import torch

# Add workspace directory to path
sys.path.append("/Users/elywright/Documents/geocentric_2_1_from_scratch")

from geocentric.model import GPTConfig
from geocentric.collaborative_pipeline import GeocentricStage0, GeocentricStage1

def test_pipeline_local_logic():
    print("=" * 80)
    print("TESTING LOCAL PIPELINE PARALLEL SHARDING LOGIC")
    print("=" * 80)
    
    # Configure tiny model parameters
    config = GPTConfig(
        vocab_size=2048,
        block_size=64,
        n_layer=4,
        n_head=4,
        n_embd=128,
        dropout=0.0,
        gradient_checkpointing=True
    )
    
    num_stage_blocks = config.n_layer // 2
    print(f"Configuring sharded stages with {num_stage_blocks} blocks each...")
    
    # Initialize Stage 0 and Stage 1
    stage0 = GeocentricStage0(config, num_stage_blocks)
    stage1 = GeocentricStage1(config, num_stage_blocks)
    
    stage0.train()
    stage1.train()
    
    # Mock inputs
    batch_size = 2
    seq_len = 32
    input_ids = torch.randint(0, config.vocab_size, (batch_size, seq_len))
    labels = torch.randint(0, config.vocab_size, (batch_size, seq_len))
    
    print("\n--- Running Stage 0 Forward Pass ---")
    activations = stage0(input_ids)
    print(f"Stage 0 activations computed successfully! Shape: {activations.shape}")
    assert activations.shape == (batch_size, seq_len, config.n_embd), "ERROR: Stage 0 activations shape is incorrect!"
    
    print("\n--- Simulating TCP Transfer (Detaching activations & marking requires_grad) ---")
    activations_recv = activations.clone().detach().requires_grad_(True)
    
    print("\n--- Running Stage 1 Forward Pass ---")
    logits, loss = stage1(activations_recv, labels=labels)
    print(f"Stage 1 forward pass successful! Loss computed: {loss.item():.4f}")
    assert logits.shape == (batch_size, seq_len, config.vocab_size), "ERROR: Stage 1 logits shape is incorrect!"
    assert loss is not None, "ERROR: Loss was not computed!"
    
    print("\n--- Running Stage 1 Backward Pass ---")
    loss.backward()
    grad_activations = activations_recv.grad
    print(f"Stage 1 backward pass successful! Computed gradient activations shape: {grad_activations.shape}")
    assert grad_activations.shape == activations.shape, "ERROR: Boundary gradient shape is incorrect!"
    
    # Verify Stage 1 weights accumulated gradients
    for name, param in stage1.named_parameters():
        if param.requires_grad:
            assert param.grad is not None, f"ERROR: Parameter {name} in Stage 1 is missing gradients!"
            
    print("Stage 1 parameter gradients verified successfully.")
    
    print("\n--- Running Stage 0 Backward Pass using received gradients ---")
    activations.backward(grad_activations)
    
    # Verify Stage 0 weights accumulated gradients
    for name, param in stage0.named_parameters():
        if param.requires_grad:
            assert param.grad is not None, f"ERROR: Parameter {name} in Stage 0 is missing gradients!"
            
    print("Stage 0 parameter gradients verified successfully.")
    print("\n" + "=" * 80)
    print("SUCCESS: LOCAL PIPELINE PARALLEL LOGIC VERIFIED FLAWLESSLY!")
    print("=" * 80 + "\n")
    return True

if __name__ == "__main__":
    success = test_pipeline_local_logic()
    if not success:
        sys.exit(1)
