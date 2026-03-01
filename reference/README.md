# Reference Materials from ML Trading Book

This directory contains the original implementation from the Machine Learning for Algorithmic Trading book that serves as the foundation for the alpaca-rl-suite.

## Directory Structure

```
reference/
├── README.md                      # This file
├── IMPLEMENTATION_MAPPING.md      # Detailed mapping of original → alpaca-rl-suite
└── original-notebook/
    ├── trading_env.py             # Original gym environment (gym, TensorFlow, TA-Lib)
    ├── 04_q_learning_for_trading.ipynb  # Complete DDQN training notebook
    └── README.md                  # Chapter 22 documentation
```

## What Was Copied

### From Worktree: `Machine-Learning-for-Algorithmic-Trading-Second-Edition-65137ef5`

**Source Path**: `22_deep_reinforcement_learning/`

**Files**:
1. **trading_env.py** - Complete gym environment with:
   - `DataSource` class (loads HDF5, computes features with TA-Lib)
   - `TradingSimulator` class (tracks positions, costs, NAV)
   - `TradingEnvironment` class (gym.Env implementation)

2. **04_q_learning_for_trading.ipynb** - Full training notebook with:
   - DDQNAgent implementation (TensorFlow/Keras)
   - Training loop (1000 episodes)
   - Results visualization
   - Performance: 46.8% agent return vs 17.6% market (57% win rate)

3. **README.md** - Chapter documentation

## How to Use This Reference

### For Understanding the Original Implementation

1. **Read** `IMPLEMENTATION_MAPPING.md` for architecture comparison
2. **Review** `original-notebook/trading_env.py` for environment logic
3. **Study** `original-notebook/04_q_learning_for_trading.ipynb` for DDQN agent

### For Implementing New Services

When building alpaca-rl-suite services, refer to:

- **services/rl-train/** → Use notebook cells 31-53 as reference for DDQN agent
- **services/feature-builder/** → Use DataSource.preprocess_data() for feature logic
- **services/backtest/** → Use TradingSimulator for cost model and NAV tracking
- **services/rl-infer/** → Use DDQNAgent.epsilon_greedy_policy() for inference

## Key Differences: Original vs Alpaca RL Suite

| Aspect | Original | Alpaca RL Suite |
|--------|----------|-----------------|
| **Purpose** | Research notebook | Production trading system |
| **Data** | HDF5 file | PostgreSQL + Alpaca API |
| **RL Framework** | gym | gymnasium |
| **DL Framework** | TensorFlow/Keras | PyTorch |
| **TA Library** | TA-Lib (C++) | ta (pure Python) |
| **Execution** | Simulation only | Paper + Live trading |
| **Safety** | None | Kill switch, max loss limits |
| **Observability** | Matplotlib plots | Prometheus + Grafana |

## State Vector (10 Features) - UNCHANGED

Both implementations use identical features:

1. `returns` - 1-day return
2. `ret_2` - 2-day return
3. `ret_5` - 5-day return
4. `ret_10` - 10-day return
5. `ret_21` - 21-day return
6. `rsi` - Stochastic RSI
7. `macd` - MACD signal line
8. `atr` - Average True Range
9. `stoch` - Stochastic oscillator (slowd - slowk)
10. `ultosc` - Ultimate Oscillator

## Action Space - UNCHANGED

- **0**: SHORT (short position)
- **1**: HOLD (flat/cash)
- **2**: LONG (long position)

## Cost Model - UNCHANGED

- **trading_cost_bps**: 10 (0.1% per trade)
- **time_cost_bps**: 1 (0.01% per period)

## Training Hyperparameters - REFERENCE

From the original notebook (to be matched in PyTorch):

```python
# Network
architecture = (256, 256)
learning_rate = 0.0001
l2_reg = 1e-6

# DDQN
gamma = 0.99
tau = 100  # target network update frequency

# Experience Replay
replay_capacity = 1_000_000
batch_size = 4096

# Epsilon-greedy
epsilon_start = 1.0
epsilon_end = 0.01
epsilon_decay_steps = 250
epsilon_exponential_decay = 0.99

# Training
trading_days = 252
max_episodes = 1000
```

## Next Steps

1. **Implement services/rl-train/** using PyTorch
   - Port DDQNAgent from TensorFlow to PyTorch
   - Use same hyperparameters
   - Add checkpoint management

2. **Implement services/rl-infer/** 
   - FastAPI service
   - Load PyTorch checkpoints
   - Serve policy predictions

3. **Validate against original**
   - Run same experiments
   - Compare training curves
   - Verify feature parity

## License

The original code is MIT licensed (see header in `trading_env.py`):
- Copyright (c) 2016 Tito Ingargiola
- Copyright (c) 2019 Stefan Jansen

Alpaca RL Suite adaptations maintain the same MIT license.
