
Excellent! 🎉 Now that your training pipeline POC is working, let me outline the complete training regime and production workflow.

## **Complete Training Regime**

### **Phase 1: Initial Training (What You Just Did)**
```
Data → Kaggle GPU → Trained Model → Manual Download
```

**Purpose**: Proof of concept, baseline model
- **Duration**: 500K timesteps (~2-4 hours on Kaggle GPU)
- **Dataset**: SPY daily data (2022-2024)
- **Evaluation**: Basic metrics (mean reward, episode length)

### **Phase 2: Systematic Training Regime**

#### **A. Data Preparation**
```bash
# 1. Backfill comprehensive dataset
python scripts/backfill_data.py \
  --timeframe 1d \
  --start 2020-01-01 \
  --end 2024-12-31 \
  --groups indices tech

# 2. Verify data quality
docker-compose exec postgres psql -U rl_user -d alpaca_rl -c \
  "SELECT symbol, COUNT(*) as bars, MIN(time)::date, MAX(time)::date 
   FROM bar_1d GROUP BY symbol;"
```

#### **B. Training Iterations**

**Iteration 1: Single Asset Baseline**
- **Symbol**: SPY
- **Timesteps**: 1M
- **Purpose**: Establish baseline performance
- **Metrics to track**: Sharpe ratio, max drawdown, win rate

**Iteration 2: Multi-Asset**
- **Symbols**: SPY, QQQ, IWM (3 major indices)
- **Timesteps**: 2M per symbol
- **Purpose**: Test generalization across correlated assets

**Iteration 3: Sector Rotation**
- **Symbols**: XLF, XLE, XLK, XLV, XLI (sector ETFs)
- **Timesteps**: 3M
- **Purpose**: Learn sector rotation strategies

**Iteration 4: Individual Stocks**
- **Symbols**: AAPL, MSFT, GOOGL, AMZN, NVDA
- **Timesteps**: 5M
- **Purpose**: Handle higher volatility, company-specific events

#### **C. Hyperparameter Tuning**

After baseline, experiment with:
```python
# Architecture variations
"architecture": [[128, 128], [256, 256], [512, 256, 128]]

# Learning rates
"learning_rate": [1e-5, 1e-4, 1e-3]

# Cost parameters (critical for profitability)
"trading_cost_bps": [5, 10, 20]  # Test different transaction costs
"time_cost_bps": [0.5, 1, 2]     # Penalize inaction

# Exploration
"exploration_fraction": [0.1, 0.3, 0.5]
```

---

## **Model Evaluation & Promotion Criteria**

### **When to Download a Model**

Download when training completes successfully on Kaggle. You'll see:
```
Training complete!
Total episodes: XXX
Mean reward (last 50): X.XXXX
Model saved to policy_YYYYMMDD-HHMMSS.zip
```

### **Evaluation Metrics (Before Promotion)**

**1. Training Metrics (From Kaggle)**
```json
{
  "mean_reward": 0.0234,        // Should be positive
  "max_reward": 0.0891,
  "total_episodes": 1984,
  "sharpe_ratio": 1.2           // Target: > 1.0
}
```

**2. Backtesting (On Your Home Lab)**
```bash
# Run backtest on held-out data
python scripts/backtest_policy.py \
  --policy-path models/kaggle/20260303-012345/policy_best.zip \
  --symbol SPY \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --initial-capital 100000
```

**Expected Output:**
```
Backtest Results:
- Total Return: 12.3%
- Sharpe Ratio: 1.45
- Max Drawdown: -8.2%
- Win Rate: 54%
- Avg Trade Duration: 3.2 days
- Profit Factor: 1.8
```

**3. Promotion Criteria**

✅ **Promote if:**
- Sharpe ratio > 1.0 (risk-adjusted returns)
- Max drawdown < 15%
- Win rate > 50%
- Profit factor > 1.5
- Outperforms buy-and-hold on backtest

❌ **Don't promote if:**
- Negative mean reward
- Excessive trading (high costs)
- Overfitting (great on train, poor on test)
- Unstable behavior (erratic position changes)

### **Promotion Workflow**

```bash
# 1. Download model from Kaggle
# (Manual: Download from Kaggle notebook output)

# 2. Upload to MinIO
aws --endpoint-url http://localhost:9000 \
  s3 cp policy_20260303-012345.zip \
  s3://alpaca-rl-artifacts/models/production/spy_v1.zip

# 3. Register in database
curl -X POST http://localhost:8004/rl/policies \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SPY DQN v1",
    "symbol": "SPY",
    "s3_key": "models/production/spy_v1.zip",
    "metrics": {
      "sharpe_ratio": 1.45,
      "max_drawdown": -0.082,
      "win_rate": 0.54
    }
  }'

# 4. Promote for inference
curl -X POST http://localhost:8004/rl/policies/{policyId}/promote

# 5. Verify deployment
curl http://localhost:8005/rl/infer/health
```

---

## **Next Steps: Production Deployment**

### **Immediate (Week 1-2)**

**1. Create Backtest Script** ✅ COMPLETE

```bash
# Run backtest on downloaded Kaggle model
python scripts/backtest_policy.py \
  --policy-path models/kaggle/policy_20260303.zip \
  --symbol SPY \
  --output-dir results/
```

**Features:**
- ✅ Loads trained Stable-Baselines3 DQN models
- ✅ Fetches 2024 test data from PostgreSQL
- ✅ Calculates features matching `trading_env.py`
- ✅ Runs backtest with proper cost modeling
- ✅ Generates 3 visualizations (equity, drawdown, positions)
- ✅ Evaluates promotion criteria automatically
- ✅ Outputs console summary + JSON report

**Promotion Criteria:**
- Sharpe ratio > 1.0
- Max drawdown < 15%
- Win rate > 50%
- Beats buy-and-hold (positive alpha)

**See:** `scripts/README.md` and `scripts/EXAMPLE.md` for detailed usage

**2. Set Up Model Registry**

Check if `rl-train` service has model management endpoints:
```bash
# List available policies
curl http://localhost:8004/rl/policies

# If not, we need to add this
```

**3. Automate Model Download**

Create a script to poll Kaggle and auto-download completed models:
```python
# scripts/download_kaggle_models.py
# - Check Kaggle notebook output
# - Download new models
# - Upload to MinIO
# - Trigger backtesting
```

### **Short-term (Month 1)**

**1. Paper Trading Integration**
```bash
# Deploy model to paper trading
curl -X POST http://localhost:8005/rl/infer/deploy \
  -d '{"policy_id": "xxx", "mode": "paper"}'

# Monitor paper trading performance
curl http://localhost:8005/rl/infer/stats
```

**2. Multi-Symbol Training**

Train separate models for:
- SPY (large cap)
- QQQ (tech)
- IWM (small cap)

**3. A/B Testing Framework**

Run multiple models in parallel:
- Model A: Conservative (low trading frequency)
- Model B: Aggressive (high trading frequency)
- Model C: Sector rotation

Compare performance over 30 days.

### **Medium-term (Month 2-3)**

**1. Continuous Training Pipeline**

Automate the full loop:
```
Weekly Schedule:
├─ Sunday: Backfill latest data
├─ Monday: Trigger Kaggle training
├─ Tuesday: Download & backtest model
├─ Wednesday: Promote if criteria met
└─ Thursday-Sunday: Monitor live performance
```

**2. Feature Engineering**

Add new features to improve performance:
- Sentiment data (news, social media)
- Alternative data (options flow, insider trading)
- Macro indicators (VIX, yields, economic data)

**3. Advanced Architectures**

Experiment with:
- **Recurrent PPO** (for temporal patterns)
- **Transformer-based** (attention mechanisms)
- **Ensemble models** (combine multiple agents)

### **Long-term (Month 4+)**

**1. Live Trading (Small Capital)**

Start with $1K-$5K real capital:
- Single symbol (SPY)
- Conservative position sizing
- Strict risk limits

**2. Portfolio Management**

Multi-asset allocation:
- Train meta-agent for portfolio allocation
- Individual agents per asset
- Risk parity / volatility targeting

**3. Monitoring & Alerting**

Set up alerts for:
- Unusual trading behavior
- Performance degradation
- System failures

---

## **Recommended Training Schedule**

### **Week 1: Foundation**
- ✅ POC complete (you are here!)
- Create backtest script
- Set up model registry
- Document evaluation criteria

### **Week 2-3: Baseline Models**
- Train SPY baseline (1M timesteps)
- Train QQQ baseline
- Train IWM baseline
- Backtest all three

### **Week 4: Hyperparameter Tuning**
- Grid search on best symbol
- Test different architectures
- Optimize cost parameters

### **Month 2: Multi-Asset**
- Train on 10 symbols
- Test generalization
- Deploy best model to paper trading

### **Month 3: Production**
- 30 days paper trading validation
- If successful: deploy with small capital
- Monitor and iterate

---

## **Key Metrics Dashboard**

Track these over time:

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Sharpe Ratio | > 1.5 | TBD | 🟡 |
| Max Drawdown | < 10% | TBD | 🟡 |
| Win Rate | > 52% | TBD | 🟡 |
| Avg Daily Return | > 0.05% | TBD | 🟡 |
| Paper Trading P&L | Positive | TBD | 🟡 |

---

## **Immediate Action Items**

1. **Create backtest script** (highest priority)
2. **Document your first model's performance**
3. **Set up model versioning in MinIO**
4. **Plan next training run with different hyperparameters**
5. **Backfill more historical data** (you'll need it for validation)

Would you like me to create the backtest script or help set up the model registry endpoints?