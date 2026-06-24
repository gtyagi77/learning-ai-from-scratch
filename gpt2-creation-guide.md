# How to Create GPT-2 from Scratch

> Research extracted from Andrej Karpathy's GitHub:
> - [`karpathy/nanoGPT`](https://github.com/karpathy/nanoGPT) — 60k+ stars, simplest GPT-2 training repo
> - [`karpathy/build-nanogpt`](https://github.com/karpathy/build-nanogpt) — step-by-step video + code lecture

---

## 1. What GPT-2 Is

GPT-2 (124M parameters) is a decoder-only Transformer language model trained to predict the next token. It is an **autoregressive** model: given a sequence of tokens, it outputs a probability distribution over the next token. There is no encoder; the model only attends to past tokens (causal masking).

The 124M variant uses:
| Hyperparameter | Value |
|---|---|
| `block_size` (context length) | 1024 |
| `vocab_size` | 50257 (GPT-2 BPE) |
| `n_layer` | 12 |
| `n_head` | 12 |
| `n_embd` | 768 |

---

## 2. Dependencies

```bash
pip install torch numpy transformers datasets tiktoken wandb tqdm
```

- **PyTorch** — model and training
- **tiktoken** — OpenAI's BPE tokenizer (used by GPT-2)
- **transformers** — for loading pre-trained GPT-2 weights (optional)
- **datasets** — for downloading OpenWebText
- **wandb** — optional training logging

---

## 3. Architecture

### 3.1 Config

```python
from dataclasses import dataclass

@dataclass
class GPTConfig:
    block_size: int = 1024   # max sequence length
    vocab_size: int = 50257  # GPT-2 uses 50257 BPE tokens
    n_layer: int = 12        # number of transformer blocks
    n_head: int = 12         # attention heads per block
    n_embd: int = 768        # embedding dimension
    dropout: float = 0.0
    bias: bool = True        # bias in Linear and LayerNorm
```

### 3.2 CausalSelfAttention

Multi-head self-attention with **causal masking** (no future token leakage).

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class CausalSelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        # Q, K, V projections for all heads in one matrix
        self.c_attn = nn.Linear(config.n_embd, 3 * config.n_embd, bias=config.bias)
        # output projection
        self.c_proj = nn.Linear(config.n_embd, config.n_embd, bias=config.bias)
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)
        self.n_head = config.n_head
        self.n_embd = config.n_embd
        # causal mask: lower-triangular
        self.register_buffer("bias", torch.tril(torch.ones(config.block_size, config.block_size))
                                     .view(1, 1, config.block_size, config.block_size))

    def forward(self, x):
        B, T, C = x.size()  # batch, sequence length, embedding dim

        # Compute Q, K, V
        q, k, v = self.c_attn(x).split(self.n_embd, dim=2)
        head_size = C // self.n_head
        # reshape to (B, n_head, T, head_size)
        k = k.view(B, T, self.n_head, head_size).transpose(1, 2)
        q = q.view(B, T, self.n_head, head_size).transpose(1, 2)
        v = v.view(B, T, self.n_head, head_size).transpose(1, 2)

        # Flash Attention (PyTorch 2.0+) — more memory-efficient
        y = F.scaled_dot_product_attention(q, k, v,
                attn_mask=None, dropout_p=self.attn_dropout.p if self.training else 0,
                is_causal=True)
        # or manual:
        # att = (q @ k.transpose(-2,-1)) * (1.0 / math.sqrt(k.size(-1)))
        # att = att.masked_fill(self.bias[:,:,:T,:T] == 0, float('-inf'))
        # att = F.softmax(att, dim=-1)
        # y = att @ v

        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.resid_dropout(self.c_proj(y))
```

### 3.3 MLP (Feed-Forward)

Each token's representation passes through a 2-layer MLP that expands by **4×** then contracts back.

```python
class MLP(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.c_fc   = nn.Linear(config.n_embd, 4 * config.n_embd, bias=config.bias)
        self.gelu   = nn.GELU()
        self.c_proj = nn.Linear(4 * config.n_embd, config.n_embd, bias=config.bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        return self.dropout(self.c_proj(self.gelu(self.c_fc(x))))
```

### 3.4 Transformer Block

Pre-norm style: LayerNorm before each sub-layer, residual connection around each.

```python
class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.attn = CausalSelfAttention(config)
        self.ln_2 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.mlp  = MLP(config)

    def forward(self, x):
        x = x + self.attn(self.ln_1(x))   # attention residual
        x = x + self.mlp(self.ln_2(x))    # MLP residual
        return x
```

### 3.5 Full GPT Model

```python
class GPT(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config

        self.transformer = nn.ModuleDict(dict(
            wte  = nn.Embedding(config.vocab_size, config.n_embd),   # token embeddings
            wpe  = nn.Embedding(config.block_size, config.n_embd),   # position embeddings
            drop = nn.Dropout(config.dropout),
            h    = nn.ModuleList([Block(config) for _ in range(config.n_layer)]),
            ln_f = nn.LayerNorm(config.n_embd, bias=config.bias),
        ))
        # language model head (no bias); weight-tied with token embedding
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        self.transformer.wte.weight = self.lm_head.weight  # weight tying

        # initialize weights
        self.apply(self._init_weights)
        # special scaled init for residual projections (GPT-2 paper)
        for pn, p in self.named_parameters():
            if pn.endswith('c_proj.weight'):
                torch.nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * config.n_layer))

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                torch.nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        B, T = idx.size()
        assert T <= self.config.block_size

        pos = torch.arange(0, T, dtype=torch.long, device=idx.device)  # (T,)
        tok_emb = self.transformer.wte(idx)   # (B, T, n_embd)
        pos_emb = self.transformer.wpe(pos)   # (T, n_embd)

        x = self.transformer.drop(tok_emb + pos_emb)
        for block in self.transformer.h:
            x = block(x)
        x = self.transformer.ln_f(x)

        if targets is not None:
            logits = self.lm_head(x)   # (B, T, vocab_size)
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1),
                                   ignore_index=-1)
        else:
            # inference: only compute logits for the last token
            logits = self.lm_head(x[:, [-1], :])
            loss = None

        return logits, loss
```

---

## 4. Data Preparation

### Option A — Shakespeare (fast, CPU-friendly)

```bash
python data/shakespeare_char/prepare.py
```

Downloads ~1MB of Shakespeare text, encodes as character-level integers, saves `train.bin` / `val.bin`.

### Option B — OpenWebText (GPT-2 reproduction)

```bash
python data/openwebtext/prepare.py
```

- Downloads the full OpenWebText dataset (~54GB)
- Tokenizes with GPT-2 BPE (`tiktoken`)
- Saves tokenized shards as `train.bin` / `val.bin`

---

## 5. Training

### Single GPU

```bash
python train.py config/train_gpt2.py
```

### Multi-GPU (DDP)

```bash
torchrun --standalone --nproc_per_node=8 train.py config/train_gpt2.py
```

~4 days on 8× A100 40GB, reaches validation loss ~2.85.

### Quick local test (CPU / laptop GPU)

```bash
python train.py config/train_shakespeare_char.py \
    --device=cpu --compile=False --eval_iters=20 \
    --log_interval=1 --block_size=64 --batch_size=12 \
    --n_layer=4 --n_head=4 --n_embd=128 \
    --max_iters=2000 --lr_decay_iters=2000 --dropout=0.0
```

### Key Training Hyperparameters

| Parameter | GPT-2 124M value |
|---|---|
| Learning rate | 6e-4 |
| Batch size (tokens) | 524,288 (B=16 × T=1024 × grad_accum=32) |
| Warmup steps | 715 |
| Total steps | 19,073 |
| LR schedule | Cosine decay to `min_lr=6e-5` |
| Optimizer | AdamW, β₁=0.9, β₂=0.95, ε=1e-8, weight decay=0.1 |
| Gradient clip | 1.0 |

### Learning Rate Schedule

```python
import math

def get_lr(step, warmup_steps=715, max_steps=19073, max_lr=6e-4, min_lr=6e-5):
    if step < warmup_steps:
        return max_lr * (step + 1) / warmup_steps          # linear warmup
    if step > max_steps:
        return min_lr
    # cosine decay
    decay_ratio = (step - warmup_steps) / (max_steps - warmup_steps)
    coeff = 0.5 * (1.0 + math.cos(math.pi * decay_ratio))
    return min_lr + coeff * (max_lr - min_lr)
```

### Optimizer Setup (weight decay only on 2D params)

```python
def configure_optimizer(model, weight_decay=0.1, lr=6e-4, betas=(0.9, 0.95), device='cuda'):
    decay_params    = [p for n, p in model.named_parameters() if p.dim() >= 2]
    no_decay_params = [p for n, p in model.named_parameters() if p.dim() < 2]
    optim_groups = [
        {'params': decay_params,    'weight_decay': weight_decay},
        {'params': no_decay_params, 'weight_decay': 0.0},
    ]
    use_fused = 'cuda' in device
    return torch.optim.AdamW(optim_groups, lr=lr, betas=betas,
                             fused=use_fused)
```

---

## 6. Inference / Text Generation

```python
@torch.no_grad()
def generate(model, idx, max_new_tokens, temperature=1.0, top_k=None):
    for _ in range(max_new_tokens):
        idx_cond = idx if idx.size(1) <= model.config.block_size \
                   else idx[:, -model.config.block_size:]
        logits, _ = model(idx_cond)
        logits = logits[:, -1, :] / temperature  # (B, vocab_size)
        if top_k is not None:
            v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
            logits[logits < v[:, [-1]]] = float('-inf')
        probs = F.softmax(logits, dim=-1)
        next_token = torch.multinomial(probs, num_samples=1)
        idx = torch.cat((idx, next_token), dim=1)
    return idx
```

Or sample from a pre-trained checkpoint:

```bash
python sample.py --init_from=gpt2 --num_samples=5 --max_new_tokens=200
```

---

## 7. Loading Pre-trained GPT-2 Weights

```python
model = GPT.from_pretrained('gpt2')  # loads OpenAI weights via HuggingFace
```

nanoGPT maps HuggingFace parameter names to its own names and transposes Conv1D → Linear where needed.

---

## 8. Performance Baselines (OpenWebText val loss)

| Model size | Validation loss |
|---|---|
| GPT-2 124M | 3.12 |
| GPT-2 350M | 2.84 |
| GPT-2 774M | 2.67 |
| GPT-2 1.5B | 2.54 |

nanoGPT reproduces the 124M result (~3.12) in ~4 days on 8× A100.

---

## 9. Key Design Insights from Karpathy

1. **Weight tying** — the token embedding and the final `lm_head` share the same weight matrix. This reduces parameters and improves performance.
2. **Pre-norm vs Post-norm** — GPT-2 uses pre-norm (LayerNorm before attention/MLP), not the original post-norm from "Attention is All You Need."
3. **Scaled residual init** — `c_proj` weights are initialised with `std = 0.02 / sqrt(2 * n_layer)` to keep residual stream magnitudes stable.
4. **Flash Attention** — use `F.scaled_dot_product_attention` (PyTorch 2.0+) for ~3× memory efficiency vs manual attention.
5. **`torch.compile`** — wrapping the model with `torch.compile()` gives another ~1.3× speedup with no code changes.
6. **vocab_size = 50304** — nanoGPT pads vocab from 50257 to 50304 (nearest multiple of 64) for GPU kernel efficiency; the extra tokens are never used.

---

## 10. Repo Structure (nanoGPT)

```
nanoGPT/
├── model.py          # GPTConfig + all model classes (~300 lines)
├── train.py          # training loop, DDP, checkpointing (~300 lines)
├── sample.py         # text generation from checkpoint or HF model
├── config/
│   ├── train_gpt2.py          # full GPT-2 124M config
│   └── train_shakespeare_char.py  # tiny test config
└── data/
    ├── shakespeare_char/prepare.py
    └── openwebtext/prepare.py
```

---

## Sources

- **nanoGPT repo**: https://github.com/karpathy/nanoGPT
- **build-nanogpt repo** (step-by-step lecture): https://github.com/karpathy/build-nanogpt
- **YouTube lecture** ("Let's build GPT-2 from scratch"): linked from build-nanogpt README
