#!/usr/bin/env python3
"""
Patch the Kaggle training notebook(s) to add held-out test evaluation:
  1. A markdown header + eval code cell inserted right after the training cell.
  2. Extra test_* keys merged into the metrics dict in the save cell.

Idempotent: re-running detects the marker and skips. Notebook `source`
fields are written as list-of-strings (splitlines keepends) to avoid the
single-string corruption bug.
"""
import json
import sys

EVAL_MARKER = "# === HELD-OUT EVALUATION (auto-added) ==="

EVAL_MD = "## Held-out Evaluation (test split + buy-and-hold baseline)\n"

EVAL_CODE = '''# === HELD-OUT EVALUATION (auto-added) ===
# Trained only on the first train_ratio of each stock. Here we evaluate the
# DETERMINISTIC policy on the held-out tail via set_test_mode(True), and compare
# against buy-and-hold. The simulator already tracks `market_navs` (always-long,
# fully-invested) for the exact same window, so the baseline comes for free.

N_EVAL_EPISODES = 300


def run_eval(test_mode: bool, n_episodes: int = N_EVAL_EPISODES):
    raw_env.set_test_mode(test_mode)
    ep_rewards, agent_ret, market_ret = [], [], []
    action_counts = np.zeros(3, dtype=np.int64)
    for _ in range(n_episodes):
        obs, _ = raw_env.reset()
        done = False
        total_r = 0.0
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            action = int(action)
            action_counts[action] += 1
            obs, reward, done, _, info = raw_env.step(action)
            total_r += reward
        sim = raw_env.simulator
        ep_rewards.append(float(total_r))
        agent_ret.append(float(sim.navs[-1] - 1.0))         # compounded strategy return
        market_ret.append(float(sim.market_navs[-1] - 1.0))  # compounded buy-&-hold return
    return ep_rewards, np.array(agent_ret), np.array(market_ret), action_counts


def summarize(name, rewards, agent_ret, market_ret, actions):
    excess = agent_ret - market_ret
    tot = max(int(actions.sum()), 1)
    print(f"\\n=== {name} ({len(rewards)} episodes) ===")
    print(f"  mean episode reward (sum):   {np.mean(rewards):+.4f}")
    print(f"  agent  mean return (NAV-1):  {agent_ret.mean()*100:+.2f}%")
    print(f"  market mean return (B&H):    {market_ret.mean()*100:+.2f}%")
    print(f"  excess over buy-&-hold:      {excess.mean()*100:+.2f}%  "
          f"(beats B&H in {100*np.mean(excess > 0):.1f}% of episodes)")
    print(f"  action mix SHORT/HOLD/LONG:  "
          f"{100*actions[0]/tot:.1f}% / {100*actions[1]/tot:.1f}% / {100*actions[2]/tot:.1f}%")


# Held-out test (the number that actually matters) + a train-window reference
test_rewards, test_agent, test_market, test_actions = run_eval(test_mode=True)
train_rewards, train_agent, train_market, train_actions = run_eval(test_mode=False)

summarize("TRAIN window", train_rewards, train_agent, train_market, train_actions)
summarize("TEST (held-out)", test_rewards, test_agent, test_market, test_actions)

raw_env.set_test_mode(False)  # restore default for any later cells

_test_excess = test_agent - test_market
eval_metrics = {
    "test_episodes":          len(test_rewards),
    "test_mean_reward":       float(np.mean(test_rewards)),
    "test_agent_return_pct":  float(test_agent.mean() * 100),
    "test_market_return_pct": float(test_market.mean() * 100),
    "test_excess_return_pct": float(_test_excess.mean() * 100),
    "test_beat_bh_rate":      float(np.mean(_test_excess > 0)),
    "test_action_dist": {
        "short": int(test_actions[0]),
        "hold":  int(test_actions[1]),
        "long":  int(test_actions[2]),
    },
    "train_eval_mean_reward": float(np.mean(train_rewards)),
}
'''

METRICS_INJECT = '''    "episode_rewards": callback.episode_rewards[-100:],
    **eval_metrics,
'''
METRICS_ANCHOR = '    "episode_rewards": callback.episode_rewards[-100:],\n'


def as_source(code: str):
    """Return Jupyter cell source as list-of-strings with trailing newlines."""
    return code.splitlines(keepends=True)


def patch_notebook(path: str) -> bool:
    nb = json.load(open(path))
    cells = nb["cells"]

    # Idempotency check
    for c in cells:
        s = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        if EVAL_MARKER in s:
            print(f"  SKIP {path}: already patched")
            return False

    # 1. Find training cell (contains model.learn() but not the metrics dict)
    train_idx = None
    metrics_idx = None
    for i, c in enumerate(cells):
        if c["cell_type"] != "code":
            continue
        s = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        if "model.learn(" in s and train_idx is None:
            train_idx = i
        if METRICS_ANCHOR.strip() in s.replace(" ", "").replace("\n", "") or \
           '"episode_rewards": callback.episode_rewards[-100:]' in s:
            metrics_idx = i
    if train_idx is None or metrics_idx is None:
        print(f"  ERROR {path}: anchors not found (train={train_idx}, metrics={metrics_idx})")
        return False

    # 2. Inject test_* keys into the metrics dict
    mc = cells[metrics_idx]
    s = "".join(mc["source"]) if isinstance(mc["source"], list) else mc["source"]
    if METRICS_ANCHOR not in s:
        print(f"  ERROR {path}: metrics anchor line not matched exactly")
        return False
    s = s.replace(METRICS_ANCHOR, METRICS_INJECT, 1)
    mc["source"] = as_source(s)

    # 3. Insert eval markdown + code cell right after the training cell
    md_cell = {"cell_type": "markdown", "metadata": {}, "source": as_source(EVAL_MD)}
    code_cell = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": as_source(EVAL_CODE),
    }
    cells.insert(train_idx + 1, code_cell)
    cells.insert(train_idx + 1, md_cell)

    json.dump(nb, open(path, "w"), indent=1)
    open(path, "a").write("\n")
    print(f"  OK {path}: inserted eval cells after cell {train_idx}, "
          f"patched metrics at cell {metrics_idx}")
    return True


if __name__ == "__main__":
    targets = sys.argv[1:] or [
        "kaggle/notebooks/alpaca-rl-training.ipynb",
        "kaggle/kernel-setup/alpaca-rl-training.ipynb",
    ]
    for t in targets:
        print(f"Patching {t} ...")
        patch_notebook(t)
