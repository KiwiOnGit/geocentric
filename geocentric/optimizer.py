from __future__ import annotations

from typing import Any

import torch
from torch.optim import AdamW


class CPUAdamW(AdamW):
    """AdamW optimizer with optional CPU offloading of optimizer state tensors."""

    def __init__(
        self,
        params: Any,
        lr: float = 1e-3,
        betas: tuple[float, float] = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
        amsgrad: bool = False,
        offload_state_to_cpu: bool = False,
    ) -> None:
        super().__init__(params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay, amsgrad=amsgrad)
        self.offload_state_to_cpu = offload_state_to_cpu

    def _move_state_to_device(self, device: torch.device) -> None:
        for param, state in self.state.items():
            if not isinstance(param, torch.Tensor):
                continue
            for k, v in list(state.items()):
                if isinstance(v, torch.Tensor) and v.device != device:
                    state[k] = v.to(device)

    def _offload_state_to_cpu(self) -> None:
        for param, state in self.state.items():
            if not isinstance(param, torch.Tensor):
                continue
            for k, v in list(state.items()):
                if isinstance(v, torch.Tensor) and v.device.type != "cpu":
                    state[k] = v.cpu()

    def step(self, closure=None):
        if self.offload_state_to_cpu:
            device = self.param_groups[0]["params"][0].device
            self._move_state_to_device(device)
        result = super().step(closure)
        if self.offload_state_to_cpu:
            self._offload_state_to_cpu()
        return result
