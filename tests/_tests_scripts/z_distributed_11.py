import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset

from catalyst import dl


class Projector(nn.Module):
    """
    Simpler neural network example - Projector.
    """

    def __init__(self, input_size: int):
        """
        Init method.

        Args:
            input_size(int): number of features in projected space.
        """
        super().__init__()
        self.linear = nn.Linear(input_size, 1)

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        """
        Forward method.

        Args:
            X(torch.Tensor): input tensor.

        Returns:
            (torch.Tensor): output projection.
        """
        return self.linear(X).squeeze(-1)


def datasets_fn(num_features: int):
    """
    Datasets closure.

    Args:
        num_features: number of features for dataset creation.
    """
    X = torch.rand(int(1e4), num_features)
    y = torch.rand(X.shape[0])
    dataset = TensorDataset(X, y)
    return {"train": dataset, "valid": dataset}


num_features = 10
model = Projector(num_features)

# example 11 - typical training with datasets closure
runner = dl.SupervisedRunner()
runner.train(
    model=model,
    # loaders={"train": loader, "valid": loader},
    datasets={
        "batch_size": 32,
        "num_workers": 1,
        "get_datasets_fn": datasets_fn,
        "num_features": num_features,
    },
    criterion=nn.MSELoss(),
    optimizer=optim.Adam(model.parameters()),
    logdir="logs/log_example_11",
    num_epochs=10,
    verbose=True,
    check=True,
    fp16=False,
    distributed=False,
)
