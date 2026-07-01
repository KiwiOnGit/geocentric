#!/usr/bin/env bash
set -euo pipefail

python -m geocentric.cli pretrain \
  --data_path data/pretrain_seed.txt \
  --output_dir runs/geocentric2_1 \
  --vocab_size 2048 \
  --block_size 128 \
  --n_layer 2 \
  --n_head 2 \
  --n_embd 128 \
  --epochs 1 \
  --batch_size 4 \
  --gradient_accumulation_steps 2 \
  --dtype fp32

python -m geocentric.cli sft \
  --model_dir runs/geocentric2_1 \
  --sft_data_path data/guided_sft_seed.jsonl \
  --epochs 1 \
  --batch_size 4 \
  --gradient_accumulation_steps 2 \
  --dtype fp32

python -m geocentric.cli serve --model_dir runs/geocentric2_1 --port 8000 --dtype fp32
