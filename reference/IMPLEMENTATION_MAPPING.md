# Implementation Mapping: ML Trading Book → Alpaca RL Suite

This document maps the original DDQN trading implementation from the Machine Learning for Algorithmic Trading book to the alpaca-rl-suite architecture.

## Source Material

**Original Location**: `Machine-Learning-for-Algorithmic-Trading-Second-Edition/22_deep_reinforcement_learning/`

**Key Files Copied**:
- `trading_env.py` - Original gym environment implementation
- `04_q_learning_for_trading.ipynb` - Complete DDQN training notebook
- `README.md` - Chapter documentation

## Architecture Mapping

### 1. Data Layer

#### Original Implementation
```python
# trading_env.py - DataSource class
- Loads from HDF5 file: '../data/assets.h5'
- Uses TA-Lib for technical indicators
- Features: returns (1/2/5/10/21d), RSI, MACD, ATR, Stoch, UltOsc
- Normalizes using sklearn.preprocessing.scale
```

#### Alpaca RL Suite Equivalent
```
services/market-ingest/
- Fetches from Alpaca API (historical + realtime)
- Stores in PostgreSQL/TimescaleDB (bar_1d table)

services/feature-builder/
- Computes same 10 features using 'ta' library (pure Python)
- Stores features in parquet/DB
- Feature set matches original: returns, RSI, MACD, ATR, Stoch, UltOsc
```

**Migration Notes**:
- Replace HDF5 with PostgreSQL queries
- Replace TA-Lib with 'ta' library (already planned)
- Keep same feature normalization approach

### 2. Environment Layer

#### Original Implementation
```python
# trading_env.py - TradingEnvironment class
- Gym environment with 3 actions: SHORT(0), HOLD(1), LONG(2)
- 252 trading days per episode
- Trading cost: 10bps (configurable)
- Time cost: 1bps (configurable)
- State: 10 features (normalized)
- Reward: position * market_return - costs
```

#### Alpaca RL Suite Equivalent
```
services/backtest/
- Event-loop engine
- Same cost model (trading_cost_bps=10, time_cost_bps=1)
- Same action space (0=SHORT, 1=HOLD, 2=LONG)
- Bias guards for lookahead/survivorship

services/rl-train/
- Should use gymnasium (modern gym)
- Custom environment matching original specs
```

**Migration Notes**:
- Port TradingEnvironment to gymnasium
- Integrate with PostgreSQL DataSource
- Keep same reward function
- Add reproducibility via config hash

### 3. Agent Layer

#### Original Implementation
```python
# Notebook cell 31 - DDQNAgent class
- Architecture: (256, 256) hidden layers
- Learning rate: 0.0001
- Gamma: 0.99
- Epsilon: 1.0 → 0.01 (linear decay 250 steps, then exponential 0.99)
- Replay buffer: 1M transitions
- Batch size: 4096
- Target network update: every 100 steps (tau=100)
- Framework: TensorFlow/Keras
```

#### Alpaca RL Suite Equivalent
```
services/rl-train/
- PyTorch implementation (not TensorFlow)
- Same hyperparameters
- Checkpoint management
- Training run tracking

services/rl-infer/
- FastAPI inference service
- Policy cache
- Load trained checkpoints
```

**Migration Notes**:
- Convert TensorFlow/Keras to PyTorch
- Keep same network architecture
- Implement same DDQN algorithm
- Add experiment tracking (config hash, metrics)

### 4. Training Loop

#### Original Implementation
```python
# Notebook cell 53
- Max episodes: 1000
- Random episode start (offset in time series)
- Tracks: NAV, market NAV, win ratio
- Stops early if 25 consecutive wins
```

#### Alpaca RL Suite Equivalent
```
services/rl-train/
- Configurable max episodes
- Same tracking metrics
- Stores training_run metadata
- Links to policy_bundle
```

### 5. Execution Layer

#### Original Implementation
- Not present (research-only)

#### Alpaca RL Suite Addition
```
services/strategy-runner/
- RTH scheduler
- Calls rl-infer for actions
- Submits orders via orders service

services/orders/
- Order lifecycle management
- Idempotency keys

services/risk/
- Kill switch
- Max daily loss circuit breaker
```

## Key Adaptations

### 1. Framework Changes
| Component | Original | Alpaca RL Suite |
|-----------|----------|-----------------|
| RL Framework | gym | gymnasium |
| DL Framework | TensorFlow/Keras | PyTorch |
| Data Storage | HDF5 | PostgreSQL/TimescaleDB |
| TA Library | TA-Lib (C++) | ta (pure Python) |

### 2. Feature Parity

**State Vector (10 features)** - IDENTICAL:
1. returns (1-day)
2. ret_2 (2-day)
3. ret_5 (5-day)
4. ret_10 (10-day)
5. ret_21 (21-day)
6. rsi (Stochastic RSI)
7. macd (MACD signal)
8. atr (Average True Range)
9. stoch (Stochastic oscillator difference)
10. ultosc (Ultimate Oscillator)

**Action Space** - IDENTICAL:
- 0: SHORT
- 1: HOLD
- 2: LONG

**Cost Model** - IDENTICAL:
- trading_cost_bps: 10 (0.1%)
- time_cost_bps: 1 (0.01%)

### 3. Production Enhancements

Alpaca RL Suite adds:
- **Data lineage**: dataset_manifest → training_run → policy_bundle → backtest_report
- **Reproducibility**: Config hash, seed tracking
- **Safety**: Kill switch, max loss limits
- **Observability**: Prometheus metrics, Grafana dashboards
- **Paper/Live trading**: Alpaca integration
- **API Gateway**: Authentication, rate limiting

## Implementation Checklist

### Phase 1: Core Environment ✓ (Planned)
- [x] PostgreSQL schema with TimescaleDB
- [x] Market data ingestion (Alpaca)
- [x] Feature builder service
- [x] Dataset builder service

### Phase 2: RL Training (TODO)
- [ ] Port TradingEnvironment to gymnasium
- [ ] Implement DDQN agent in PyTorch
- [ ] Match original hyperparameters
- [ ] Add training run tracking
- [ ] Checkpoint management

### Phase 3: Inference & Execution (TODO)
- [ ] RL inference service (FastAPI)
- [ ] Strategy runner integration
- [ ] Backtest validation
- [ ] Paper trading loop

### Phase 4: Production Hardening (TODO)
- [ ] Observability (metrics, logs)
- [ ] Kill switch testing
- [ ] Risk management validation
- [ ] End-to-end integration tests

## Training Results (Original)

From the notebook (1000 episodes on AAPL):
- **Final Agent Return**: 46.8% (100-episode MA)
- **Final Market Return**: 17.6% (100-episode MA)
- **Win Rate**: 57% (agent outperforms market)
- **Training Time**: ~5h 48m on GPU
- **Epsilon Decay**: 1.0 → 0.0 by episode 550

**Key Insight**: Agent learned to outperform buy-and-hold despite 10bps trading costs, achieving ~57% win rate after training on ~1000 years of simulated data.

## References

- Original notebook: `reference/original-notebook/04_q_learning_for_trading.ipynb`
- Original environment: `reference/original-notebook/trading_env.py`
- Book chapter: Machine Learning for Algorithmic Trading, 2nd Edition, Chapter 22
