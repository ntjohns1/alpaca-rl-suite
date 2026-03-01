# Complete Resources Guide

**Alpaca RL Suite** - Full Context from ML4T Book + Production Implementation

---

## 📚 Available Resources

### 1. Workflows (`.windsurf/workflows/`)

Comprehensive step-by-step guides for ML4T development:

#### **Primary: Reinforcement Learning Trading** (371 lines)
`@.windsurf/workflows/reinforcement-learning-trading.md`

Complete workflow covering:
- Trading environment design (state, actions, rewards)
- DDQN agent architecture and hyperparameters
- Training process and evaluation
- Deployment considerations
- Best practices and common pitfalls
- Advanced topics (multi-asset, hierarchical RL, meta-learning)

#### **Supporting Workflows**
- `alpha-factor-research.md` - Alpha factor development
- `ml-model-development.md` - End-to-end ML pipeline
- `strategy-backtesting.md` - Backtesting methodology
- `project-bootstrap.md` - Project setup guide

#### **Utilities**
- `bootstrap.py` - Automated project bootstrapping
- `context-export.py` - Context export tools

---

### 2. Reference Implementation

#### **A. Quick Reference** (`reference/original-notebook/`)
Extracted key files from Chapter 22:
- `trading_env.py` - Original gym environment (268 lines)
- `04_q_learning_for_trading.ipynb` - DDQN training notebook (64 cells)
- `README.md` - Chapter documentation

#### **B. Full ML4T Book** (`reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/`)
Complete repository with all 24 chapters:

**Primary Reference**:
- `22_deep_reinforcement_learning/` - RL for trading
  - `04_q_learning_for_trading.ipynb` - Main notebook
  - `trading_env.py` - Environment implementation
  - `01-03_*.ipynb` - Gridworld and Lunar Lander examples

**Supporting Chapters**:
- `04_alpha_factor_research/` - Feature engineering
- `05_strategy_evaluation/` - Performance metrics
- `06_machine_learning_process/` - ML workflow
- `07_linear_models/` - Baseline models
- `08_ml4t_workflow/` - Data pipeline
- `09_time_series_models/` - ARIMA, VAR, etc.
- `11_decision_trees_random_forests/` - Tree models
- `12_gradient_boosting_machines/` - XGBoost, LightGBM
- `17_deep_learning/` - Neural networks
- `18_convolutional_neural_nets/` - CNNs
- `19_recurrent_neural_nets/` - LSTMs, GRUs

---

### 3. Documentation

#### **Architecture & Validation**
- `reference/IMPLEMENTATION_MAPPING.md` - Original → Alpaca RL Suite mapping
- `reference/VALIDATION_REPORT.md` - Implementation comparison & validation
- `reference/README.md` - Usage guide
- `reference/CONTEXT_MERGE_COMPLETE.md` - Complete merge overview

#### **Main Documentation**
- `README.md` (root) - Project overview and quick start

---

### 4. Implementation Code

#### **Python Services** (RL-focused)
- `services/rl-train/`
  - `trading_env.py` - Gymnasium environment (adapted from original)
  - `ddqn_agent.py` - Custom PyTorch DDQN (available but not active)
  - `main.py` - Stable Baselines3 training service (active)
- `services/rl-infer/main.py` - FastAPI inference service
- `services/feature-builder/main.py` - 10 features (ta library)
- `services/backtest/engine.py` - Event-loop backtesting
- `services/dataset-builder/main.py` - Walk-forward splits

#### **Node/TypeScript Services**
- `services/api-gateway/` - Reverse proxy
- `services/auth/` - JWT authentication
- `services/alpaca-adapter/` - Alpaca API client
- `services/market-ingest/` - Data ingestion
- `services/orders/` - Order management
- `services/risk/` - Kill switch & limits
- `services/portfolio/` - Position tracking
- `services/strategy-runner/` - Execution scheduler

#### **Shared Packages**
- `packages/contracts/` - Zod schemas, DTOs
- `packages/config/` - Environment configuration
- `packages/observability/` - Metrics & tracing

---

## 🎯 Quick Navigation

### For Learning RL Trading
1. **Start**: `.windsurf/workflows/reinforcement-learning-trading.md`
2. **Original Notebook**: `reference/original-notebook/04_q_learning_for_trading.ipynb`
3. **Full Chapter**: `reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/22_deep_reinforcement_learning/`

### For Understanding Implementation
1. **Architecture**: `reference/IMPLEMENTATION_MAPPING.md`
2. **Validation**: `reference/VALIDATION_REPORT.md`
3. **Environment Code**: `services/rl-train/trading_env.py`
4. **Agent Code**: `services/rl-train/main.py` (SB3) or `ddqn_agent.py` (custom)

### For Development
1. **Feature Engineering**: `services/feature-builder/main.py`
2. **Training Service**: `services/rl-train/main.py`
3. **Inference Service**: `services/rl-infer/main.py`
4. **Backtesting**: `services/backtest/engine.py`

### For Alpha Factor Research
1. **Workflow**: `.windsurf/workflows/alpha-factor-research.md`
2. **Book Chapter**: `reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/04_alpha_factor_research/`
3. **Implementation**: `services/feature-builder/main.py`

### For Backtesting
1. **Workflow**: `.windsurf/workflows/strategy-backtesting.md`
2. **Book Chapter**: `reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/05_strategy_evaluation/`
3. **Implementation**: `services/backtest/engine.py`

---

## 📖 Key Concepts Reference

### State Vector (10 Features)
From `trading_env.py` and `feature-builder/main.py`:
1. `returns` / `ret_1d` - 1-day return
2. `ret_2` / `ret_2d` - 2-day return
3. `ret_5` / `ret_5d` - 5-day return
4. `ret_10` / `ret_10d` - 10-day return
5. `ret_21` / `ret_21d` - 21-day return
6. `rsi` - RSI indicator
7. `macd` - MACD signal
8. `atr` - Average True Range
9. `stoch` - Stochastic oscillator
10. `ultosc` - Ultimate Oscillator

### Action Space
- **0**: SHORT (short position)
- **1**: HOLD (flat/cash)
- **2**: LONG (long position)

### Cost Model
- **Trading Cost**: 10 bps (0.1%) per trade
- **Time Cost**: 1 bps (0.01%) per period

### Reward Function
```python
reward = position * market_return - costs
```

### DDQN Hyperparameters (Reference)
```python
architecture = [256, 256]
learning_rate = 1e-4
gamma = 0.99
replay_capacity = 1_000_000
batch_size = 4096
tau = 100  # target network update
epsilon_start = 1.0
epsilon_end = 0.01
epsilon_decay_steps = 250
epsilon_exponential_decay = 0.99
```

---

## 🔍 Search Tips

### Find Specific Topics

**RL Algorithm Details**:
```bash
# Workflow guide
cat .windsurf/workflows/reinforcement-learning-trading.md | grep -A 10 "DDQN"

# Original implementation
cat reference/original-notebook/trading_env.py | grep -A 20 "class DDQNAgent"

# Full notebook
jupyter notebook reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/22_deep_reinforcement_learning/04_q_learning_for_trading.ipynb
```

**Feature Engineering**:
```bash
# Workflow
cat .windsurf/workflows/alpha-factor-research.md

# Implementation
cat services/feature-builder/main.py | grep -A 30 "compute_features"

# Book chapter
cd reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/04_alpha_factor_research
```

**Backtesting**:
```bash
# Workflow
cat .windsurf/workflows/strategy-backtesting.md

# Implementation
cat services/backtest/engine.py

# Book chapter
cd reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/05_strategy_evaluation
```

---

## 🚀 Usage Examples

### Example 1: Understanding the Original DDQN Implementation
```bash
# Read the workflow first
cat .windsurf/workflows/reinforcement-learning-trading.md

# View the original environment
cat reference/original-notebook/trading_env.py

# Run the original notebook
jupyter notebook reference/original-notebook/04_q_learning_for_trading.ipynb

# Compare with production implementation
cat services/rl-train/trading_env.py
```

### Example 2: Implementing a New Feature
```bash
# Check workflow
cat .windsurf/workflows/alpha-factor-research.md

# See examples in book
cd reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/04_alpha_factor_research

# View current implementation
cat services/feature-builder/main.py

# Add your feature to compute_features()
```

### Example 3: Training a New Agent
```bash
# Review workflow
cat .windsurf/workflows/reinforcement-learning-trading.md

# Check hyperparameters from reference
cat reference/IMPLEMENTATION_MAPPING.md | grep -A 20 "Hyperparameter"

# Start training service
cd services/rl-train
python main.py

# Submit training job
curl -X POST http://localhost:8004/rl/train -H 'Content-Type: application/json' -d '{
  "name": "aapl-v1",
  "symbols": ["AAPL"],
  "totalTimesteps": 500000
}'
```

---

## 📊 Training Results Reference

### Original Notebook Results (AAPL, 1000 episodes)
- **Agent Return**: 46.8% (100-episode MA)
- **Market Return**: 17.6% (100-episode MA)
- **Win Rate**: 57%
- **Training Time**: ~5h 48m (GPU)
- **Framework**: Custom TensorFlow DDQN

### Expected Results (Alpaca RL Suite)
- **Framework**: Stable Baselines3 DQN
- **Total Timesteps**: 500K (configurable)
- **Episodes**: ~2000 (252 steps each)
- **Results**: TBD - needs validation run

---

## 🛠️ Development Workflow

### 1. Research Phase
- Read: `.windsurf/workflows/reinforcement-learning-trading.md`
- Study: `reference/original-notebook/04_q_learning_for_trading.ipynb`
- Explore: `reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/22_deep_reinforcement_learning/`

### 2. Implementation Phase
- Reference: `reference/IMPLEMENTATION_MAPPING.md`
- Code: `services/rl-train/`
- Test: `services/rl-train/tests/`

### 3. Validation Phase
- Compare: `reference/VALIDATION_REPORT.md`
- Backtest: `services/backtest/`
- Metrics: Check against reference results

### 4. Deployment Phase
- Paper Trading: `services/strategy-runner/`
- Risk Management: `services/risk/`
- Monitoring: Prometheus + Grafana

---

## 🎓 Learning Path

### Beginner
1. Read: `README.md` (root)
2. Workflow: `.windsurf/workflows/reinforcement-learning-trading.md`
3. Notebook: `reference/original-notebook/04_q_learning_for_trading.ipynb`

### Intermediate
1. Architecture: `reference/IMPLEMENTATION_MAPPING.md`
2. Environment: `services/rl-train/trading_env.py`
3. Agent: `services/rl-train/ddqn_agent.py`
4. Full Chapter: `reference/Machine-Learning-for-Algorithmic-Trading-Second-Edition/22_deep_reinforcement_learning/`

### Advanced
1. Other RL Examples: `reference/.../22_deep_reinforcement_learning/01-03_*.ipynb`
2. Alpha Factors: `reference/.../04_alpha_factor_research/`
3. Advanced Models: `reference/.../17-19_*_neural_nets/`
4. Full Book: Explore all 24 chapters

---

## 📝 Notes

- **Framework Choice**: Implementation uses Stable Baselines3 instead of custom TensorFlow DDQN
- **Custom DDQN Available**: `services/rl-train/ddqn_agent.py` (PyTorch) if exact reproducibility needed
- **Feature Library**: Uses `ta` (pure Python) instead of TA-Lib (C++)
- **Data Storage**: PostgreSQL + TimescaleDB instead of HDF5
- **Production Ready**: All infrastructure and services implemented

---

## 🔗 External Resources

### From Workflow
- [OpenAI Gym](https://gym.openai.com/)
- [Stable-Baselines3](https://stable-baselines3.readthedocs.io/)
- [Playing Atari with Deep RL](https://arxiv.org/abs/1312.5602)
- [Double Q-learning Paper](https://arxiv.org/abs/1509.06461)

### Books
- Reinforcement Learning: An Introduction (Sutton & Barto)
- Deep Reinforcement Learning Hands-On (Lapan)

---

**Last Updated**: Context merge complete with full ML4T book and workflows
