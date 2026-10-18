"""PyTorch LSTM trainer and inference for the Method Analysis demo.

The model takes a 20-day window of 6 sequence features and classifies
whether the stock will return >= +3 % in the next 5 trading days.

Architecture
    LSTM(input=6, hidden=64, layers=2, dropout=0.3)
    → last hidden state → Linear(64, 2)

Training uses a simple train/val split (80/20 chronological) with early
stopping on validation loss to avoid overfitting on the ~60k row dataset.

Dependencies
    torch  (CPU-only build is sufficient; ~700 MB)
    torch is optional — if missing, is_ready() returns False and train()
    raises a helpful ImportError rather than crashing the whole app.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..data import csv_store

log = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "models"
_PT_PATH = _MODEL_DIR / "signal_ranker_lstm.pt"
_META_PATH = _MODEL_DIR / "signal_ranker_lstm_meta.json"

WINDOW = 20
SEQ_FEATURES = [
    "rsi14",
    "macd_hist",
    "vol_ratio",
    "atr_pct",
    "close_vs_ema20",
    "return_5d",
]
_N_FEATURES = len(SEQ_FEATURES)


def is_ready() -> bool:
    return _PT_PATH.exists() and _META_PATH.exists()


def _model_dir() -> Path:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return _MODEL_DIR


def _build_model():
    """Construct the LSTM model.  Import torch here so the module loads even
    when torch is absent — is_ready() / train() will surface the error lazily."""
    import torch
    import torch.nn as nn

    class _LSTMClassifier(nn.Module):
        def __init__(self, n_features: int, hidden: int = 64, n_layers: int = 2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden,
                num_layers=n_layers,
                batch_first=True,
                dropout=0.3,
            )
            self.fc = nn.Linear(hidden, 2)

        def forward(self, x):
            _, (h, _) = self.lstm(x)
            return self.fc(h[-1])

    return _LSTMClassifier(_N_FEATURES)


def _normalise(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-feature z-score normalisation computed on the training split only."""
    mu = X.mean(axis=(0, 1), keepdims=True)    # (1, 1, n_features)
    sigma = X.std(axis=(0, 1), keepdims=True) + 1e-8
    return (X - mu) / sigma, mu.squeeze(), sigma.squeeze()


def train(progress_cb: Optional[Callable[[float, str], None]] = None) -> Dict:
    """Train LSTM on all cached CSVs.  Saves .pt artefact and returns metrics dict."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:
        raise ImportError(
            "PyTorch is required for LSTM training.  "
            "Install it with: pip install torch --index-url https://download.pytorch.org/whl/cpu"
        ) from exc

    from ..analysis.ml_dataset import build_sequence_matrix

    def _cb(pct: float, msg: str = "") -> None:
        if progress_cb:
            progress_cb(pct, msg)

    _cb(0.02, "Building sequence matrix…")
    X_seq, y = build_sequence_matrix(window=WINDOW, seq_features=SEQ_FEATURES)

    if len(y) == 0:
        raise RuntimeError("No training data — run data refresh first.")

    _cb(0.15, f"Sequence matrix: {X_seq.shape[0]:,} samples, normalising…")

    # Chronological split — 80% train / 20% validation.
    split = int(len(y) * 0.8)
    X_tr, X_val = X_seq[:split], X_seq[split:]
    y_tr, y_val = y[:split], y[split:]

    # Normalise using only training statistics (no look-ahead into val).
    X_tr_n, mu, sigma = _normalise(X_tr)
    X_val_n = (X_val - mu) / (sigma + 1e-8)

    X_tr_t = torch.tensor(X_tr_n, dtype=torch.float32)
    y_tr_t = torch.tensor(y_tr, dtype=torch.long)
    X_val_t = torch.tensor(X_val_n, dtype=torch.float32)
    y_val_t = torch.tensor(y_val, dtype=torch.long)

    train_ds = TensorDataset(X_tr_t, y_tr_t)
    loader = DataLoader(train_ds, batch_size=256, shuffle=True)

    model = _build_model()
    optimiser = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()

    N_EPOCHS = 30
    best_val_loss = float("inf")
    patience = 5
    patience_count = 0
    best_state = None
    val_accs: List[float] = []

    _cb(0.20, "Training…")
    for epoch in range(1, N_EPOCHS + 1):
        model.train()
        epoch_loss = 0.0
        for xb, yb in loader:
            optimiser.zero_grad()
            out = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimiser.step()
            epoch_loss += loss.item()

        # Validation
        model.eval()
        with torch.no_grad():
            val_out = model(X_val_t)
            val_loss = criterion(val_out, y_val_t).item()
            val_pred = val_out.argmax(dim=1)
            val_acc = float((val_pred == y_val_t).float().mean())
        val_accs.append(val_acc)

        pct = 0.20 + 0.70 * (epoch / N_EPOCHS)
        _cb(pct, f"Epoch {epoch}/{N_EPOCHS} — val_loss {val_loss:.4f} · val_acc {val_acc:.3f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            patience_count = 0
        else:
            patience_count += 1
            if patience_count >= patience:
                log.info("Early stopping at epoch %d", epoch)
                _cb(pct, f"Early stop at epoch {epoch} — best val_loss {best_val_loss:.4f}")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    best_val_acc = float(max(val_accs)) if val_accs else 0.0
    _cb(0.92, "Saving artefact…")
    _model_dir()
    torch.save(model.state_dict(), _PT_PATH)

    meta_dict = {
        "window": WINDOW,
        "seq_features": SEQ_FEATURES,
        "n_features": _N_FEATURES,
        "best_val_acc": best_val_acc,
        "best_val_loss": best_val_loss,
        "train_samples": len(y_tr),
        "val_samples": len(y_val),
        "norm_mu": mu.tolist(),
        "norm_sigma": sigma.tolist(),
    }
    with open(_META_PATH, "w") as fh:
        json.dump(meta_dict, fh, indent=2)

    _cb(1.0, f"Done — best val_acc {best_val_acc:.3f}")
    log.info("LSTM model saved (val_acc %.3f)", best_val_acc)
    return meta_dict


def infer(
    symbols: Optional[List[str]] = None,
    name_map: Optional[Dict[str, str]] = None,
    top_k: int = 15,
) -> List[dict]:
    """Run LSTM inference on the latest 20-day window for each symbol."""
    try:
        import torch
    except ImportError as exc:
        raise ImportError(
            "PyTorch is required for LSTM inference.  "
            "Install with: pip install torch --index-url https://download.pytorch.org/whl/cpu"
        ) from exc

    if not is_ready():
        raise RuntimeError("LSTM model not trained yet — use the Train button first.")

    with open(_META_PATH) as fh:
        meta = json.load(fh)

    mu = np.array(meta["norm_mu"], dtype=np.float32)
    sigma = np.array(meta["norm_sigma"], dtype=np.float32) + 1e-8
    window = int(meta["window"])
    seq_features = meta["seq_features"]

    model = _build_model()
    model.load_state_dict(torch.load(_PT_PATH, map_location="cpu"))
    model.eval()

    if symbols is None:
        symbols = csv_store.list_cached_symbols()

    from ..analysis.indicators import compute_all
    from ..analysis.regime import classify
    from ..analysis.signal_decision import decide_from_rally_probability

    cards: List[dict] = []
    for sym in symbols:
        df_raw = csv_store.load(sym)
        if len(df_raw) < 210 + window:
            continue
        df = compute_all(df_raw)

        # Build close_vs_ema20 derived column
        df = df.copy()
        ema20 = df["ema20"]
        close = df["close"]
        df["close_vs_ema20"] = ((close / ema20.replace(0, float("nan"))) - 1.0) * 100.0

        window_slice = df[seq_features].iloc[-window:]
        if window_slice.isnull().any().any():
            continue

        X = window_slice.values.astype(np.float32)  # (window, n_features)
        X_norm = (X - mu) / sigma
        X_t = torch.tensor(X_norm[np.newaxis, :, :], dtype=torch.float32)  # (1, W, F)

        with torch.no_grad():
            logits = model(X_t)
            probs = torch.softmax(logits, dim=1).numpy()[0]

        prob = float(probs[1])   # P(+3% in 5d)
        close_val = float(df.iloc[-1]["close"])
        regime, _ = classify(df)
        direction, veto = decide_from_rally_probability(prob, regime)
        top_factors = [veto] if veto else []

        cards.append({
            "symbol": sym,
            "name": (name_map or {}).get(sym),
            "confidence": round(prob, 3),
            "direction": direction,
            "category": None,
            "regime": regime,
            "close": close_val,
            "top_factors": top_factors,
        })

    cards.sort(key=lambda c: -c["confidence"])
    return cards[:top_k]
