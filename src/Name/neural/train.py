import torch
from torch import Tensor
from torch.optim import Optimizer
from torch.optim.lr_scheduler import LRScheduler

from typing import TypedDict, Iterator, IO, Any

from .model import ModelCfg, Model
from .batching import Batch
from .utils.modules import focal_loss


class TrainCfg(TypedDict):
    model_config:       ModelCfg
    num_epochs:         int
    warmup_epochs:      int
    warmdown_epochs:    int
    batch_size_s:       int
    batch_size_h:       int
    max_scope_size:     int
    max_ast_len:        int
    backprop_every:     int
    max_lr:             float
    min_lr:             float
    train_files:        list[str]
    dev_files:          list[str]
    test_files:         list[str]


class TrainStats(TypedDict):
    loss:               float
    predictions:        list[bool]
    truth:              list[bool]


def _add(x: TrainStats, y: TrainStats) -> TrainStats:
    return {'loss': x['loss'] + y['loss'],
            'predictions': x['predictions'] + y['predictions'],
            'truth': x['truth'] + y['truth']}


def binary_stats(predictions: list[bool], truths: list[bool]) -> tuple[int, int, int, int]:
    tp = sum([x == y for x, y in zip(predictions, truths) if y])
    fn = sum([x != y for x, y in zip(predictions, truths) if y])
    tn = sum([x == y for x, y in zip(predictions, truths) if not y])
    fp = sum([x != y for x, y in zip(predictions, truths) if not y])
    return tp, fn, tn, fp


def macro_binary_stats(tp: int, fn: int, tn: int, fp: int) -> tuple[float, float, float, float]:
    prec = tp / (tp + fp + 1e-08)
    rec = tp / (tp + fn + 1e-08)
    f1 = 2 * prec * rec / (prec + rec + 1e-08)
    accuracy = (tp + tn) / (tp + fn + tn + fp)
    return accuracy, f1, prec, rec


def subsample_mask(xs: Tensor, factor: float) -> Tensor:
    num_neg_samples = min(xs.sum() * factor, (~xs).sum())
    false_indices = torch.nonzero(~xs)
    sampled_false_indices = false_indices[torch.randperm(false_indices.size(0))][:num_neg_samples]
    mask = torch.zeros_like(xs)
    mask[xs] = True
    mask[sampled_false_indices] = True
    return mask


class Trainer(Model):
    def compute_loss(self, batch: Batch) -> tuple[list[bool], list[bool], Tensor]:
        scope_reprs, _, _, hole_reprs = self.encode(batch)
        predictions = self.predict_lemmas(scope_reprs=scope_reprs,
                                          hole_reprs=hole_reprs[:, :, 0],
                                          edge_index=batch.edge_index)
        loss = focal_loss(predictions, batch.lemmas, gamma=2)
        return (predictions.sigmoid().round().cpu().bool().tolist(),
                batch.lemmas.cpu().tolist(),
                loss)

    def train_epoch(self,
                    epoch: Iterator[Batch],
                    optimizer: Optimizer,
                    scheduler: LRScheduler,
                    backprop_every: int) -> TrainStats:
        self.train()

        epoch_stats = {'loss': 0, 'predictions': [], 'truth': []}
        for i, batch in enumerate(epoch):
            batch_stats = self.train_batch(
                batch=batch, optimizer=optimizer, scheduler=scheduler, backprop=(i + 1) % backprop_every == 0)
            epoch_stats = _add(epoch_stats, batch_stats)
        return epoch_stats

    def train_batch(self,
                    batch: Batch,
                    optimizer: Optimizer,
                    scheduler: LRScheduler,
                    backprop: bool) -> TrainStats:
        predictions, truth, loss = self.compute_loss(batch)
        loss.backward()

        if backprop:
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)

        return {'loss': loss.item(),
                'predictions': predictions,
                'truth': truth}

    def eval_batch(self, batch: Batch) -> TrainStats:
        predictions, truth, loss = self.compute_loss(batch)
        return {'loss': loss.item(), 'predictions': predictions, 'truth': truth}

    def eval_epoch(self, epoch: Iterator[Batch]) -> TrainStats:
        self.eval()
        epoch_stats = {'loss': 0, 'predictions': [], 'truth': []}

        for i, batch in enumerate(epoch):
            epoch_stats = _add(epoch_stats, self.eval_batch(batch))
        return epoch_stats


class Logger:
    def __init__(self, stdout: IO[str], log: str):
        self.stdout = stdout
        self.log = log

    def write(self, obj: Any) -> None:
        with open(self.log, 'a') as f:
            f.write(f'{obj}')
        self.stdout.write(f'{obj}')
