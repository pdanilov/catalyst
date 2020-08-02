from typing import Callable, Optional, Tuple
import collections

import torch
from torch.optim.optimizer import Optimizer


def _log_lamb_rs(optimizer: Optimizer, event_writer, token_count: int):
    """Log a histogram of trust ratio scalars in across layers."""
    results = collections.defaultdict(list)
    for group in optimizer.param_groups:
        for p in group["params"]:
            state = optimizer.state[p]
            for i in ("weight_norm", "adam_norm", "trust_ratio"):
                if i in state:
                    results[i].append(state[i])

    for k, v in results.items():
        event_writer.add_histogram(f"lamb/{k}", torch.tensor(v), token_count)


class Lamb(Optimizer):
    """Implements Lamb algorithm.

    It has been proposed in `Training BERT in 76 minutes`_.

    .. _`Training BERT in 76 minutes`:
        https://arxiv.org/abs/1904.00962
    """

    def __init__(
        self,
        params,
        lr: Optional[float] = 1e-3,
        betas: Optional[Tuple[float, float]] = (0.9, 0.999),
        eps: Optional[float] = 1e-6,
        weight_decay: Optional[float] = 0.0,
        adam: Optional[bool] = False,
    ):
        """
        Args:
            params (iterable): iterable of parameters to optimize or dicts
                defining parameter groups
            lr (float, optional): learning rate (default: 1e-3)
            betas (Tuple[float, float], optional): coefficients used for
                computing running averages of gradient
                and its square (default: (0.9, 0.999))
            eps (float, optional): term added to the denominator to improve
                numerical stability (default: 1e-8)
            weight_decay (float, optional): weight decay (L2 penalty)
                (default: 0)
            adam (bool, optional): always use trust ratio = 1, which turns
                this into Adam. Useful for comparison purposes.
        """
        if not 0.0 <= lr:
            raise ValueError(f"Invalid learning rate: {lr}")
        if not 0.0 <= eps:
            raise ValueError(f"Invalid epsilon value: {eps}")
        if not 0.0 <= betas[0] < 1.0:
            raise ValueError(f"Invalid beta parameter at index 0: {betas[0]}")
        if not 0.0 <= betas[1] < 1.0:
            raise ValueError(f"Invalid beta parameter at index 1: {betas[1]}")
        defaults = {
            "lr": lr,
            "betas": betas,
            "eps": eps,
            "weight_decay": weight_decay,
        }
        self.adam = adam
        super(Lamb, self).__init__(params, defaults)

    def step(self, closure: Optional[Callable] = None):
        """Makes optimizer step.

        Args:
            closure (callable, optional): A closure that reevaluates
                the model and returns the loss.

        Returns:
            computed loss

        Raises:
            RuntimeError: Lamb does not support sparse gradients
        """
        loss = None
        if closure is not None:
            loss = closure()

        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                grad = p.grad.data
                if grad.is_sparse:
                    raise RuntimeError(
                        "Lamb does not support sparse gradients, "
                        "consider SparseAdam instad."
                    )

                state = self.state[p]

                # State initialization
                if len(state) == 0:
                    state["step"] = 0
                    # Exponential moving average of gradient values
                    state["exp_avg"] = torch.zeros_like(p.data)
                    # Exponential moving average of squared gradient values
                    state["exp_avg_sq"] = torch.zeros_like(p.data)

                exp_avg, exp_avg_sq = state["exp_avg"], state["exp_avg_sq"]
                beta1, beta2 = group["betas"]

                state["step"] += 1

                # Decay the first and second moment
                # running average coefficient
                # m_t
                exp_avg.mul_(beta1).add_(1 - beta1, grad)
                # v_t
                exp_avg_sq.mul_(beta2).addcmul_(1 - beta2, grad, grad)

                # Paper v3 does not use debiasing.
                # bias_correction1 = 1 - beta1 ** state["step"]
                # bias_correction2 = 1 - beta2 ** state["step"]
                # Apply bias to lr to avoid broadcast.
                # * math.sqrt(bias_correction2) / bias_correction1
                step_size = group["lr"]

                weight_norm = p.data.pow(2).sum().sqrt().clamp(0, 10)

                adam_step = exp_avg / exp_avg_sq.sqrt().add(group["eps"])
                if group["weight_decay"] != 0:
                    adam_step.add_(group["weight_decay"], p.data)

                adam_norm = adam_step.pow(2).sum().sqrt()
                if weight_norm == 0 or adam_norm == 0:
                    trust_ratio = 1
                else:
                    trust_ratio = weight_norm / adam_norm
                state["weight_norm"] = weight_norm
                state["adam_norm"] = adam_norm
                state["trust_ratio"] = trust_ratio
                if self.adam:
                    trust_ratio = 1

                p.data.add_(-step_size * trust_ratio, adam_step)

        return loss
