"""
Double Deep Q-Network (DDQN) agent.
Architecture and hyperparameters match 04_q_learning_for_trading.ipynb.
"""
import random
from collections import deque
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


class DQNetwork(nn.Module):
    """Fully-connected DQN with configurable hidden layers and dropout."""

    def __init__(self, state_dim: int, action_dim: int, hidden: list[int], dropout: float = 0.1):
        super().__init__()
        layers: list[nn.Module] = []
        in_dim = state_dim
        for h in hidden:
            layers += [nn.Linear(in_dim, h), nn.ReLU(), nn.Dropout(p=dropout)]
            in_dim = h
        layers.append(nn.Linear(in_dim, action_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class ReplayBuffer:
    """Circular replay buffer — capacity ~1M transitions."""

    def __init__(self, capacity: int):
        self.buffer: deque = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buffer.append((
            np.array(state, dtype=np.float32),
            int(action),
            float(reward),
            np.array(next_state, dtype=np.float32),
            bool(done),
        ))

    def sample(self, batch_size: int):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            np.array(states),
            np.array(actions),
            np.array(rewards),
            np.array(next_states),
            np.array(dones, dtype=np.float32),
        )

    def __len__(self) -> int:
        return len(self.buffer)


class DDQNAgent:
    """
    Double DQN agent.
    Hyperparameters match 04_q_learning_for_trading.ipynb defaults.
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int = 3,
        hidden: Optional[list[int]] = None,
        gamma: float = 0.99,
        learning_rate: float = 1e-4,
        l2_reg: float = 1e-6,
        tau: int = 100,                  # target network update every tau steps
        replay_capacity: int = 1_000_000,
        batch_size: int = 4096,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.01,
        epsilon_decay_steps: int = 250,
        epsilon_exponential_decay: float = 0.99,
        seed: Optional[int] = None,
        device: str = "cpu",
    ):
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
            random.seed(seed)

        self.action_dim   = action_dim
        self.gamma        = gamma
        self.tau          = tau
        self.batch_size   = batch_size
        self.epsilon      = epsilon_start
        self.epsilon_end  = epsilon_end
        self.epsilon_step = (epsilon_start - epsilon_end) / max(epsilon_decay_steps, 1)
        self.epsilon_exp_decay = epsilon_exponential_decay
        self.hidden       = hidden or [256, 256]
        self.device       = torch.device(device if torch.cuda.is_available() or device == "cpu" else "cpu")

        self.online_net = DQNetwork(state_dim, action_dim, self.hidden).to(self.device)
        self.target_net = DQNetwork(state_dim, action_dim, self.hidden).to(self.device)
        self.target_net.load_state_dict(self.online_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(
            self.online_net.parameters(), lr=learning_rate, weight_decay=l2_reg
        )
        self.replay = ReplayBuffer(replay_capacity)
        self.total_steps = 0

    def act(self, state: np.ndarray, greedy: bool = False) -> int:
        if not greedy and np.random.random() < self.epsilon:
            return np.random.randint(self.action_dim)
        with torch.no_grad():
            t = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            return int(self.online_net(t).argmax().item())

    def store(self, state, action, reward, next_state, done):
        self.replay.push(state, action, reward, next_state, done)

    def train_step(self) -> Optional[float]:
        if len(self.replay) < self.batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay.sample(self.batch_size)

        s  = torch.FloatTensor(states).to(self.device)
        a  = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        r  = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        ns = torch.FloatTensor(next_states).to(self.device)
        d  = torch.FloatTensor(dones).unsqueeze(1).to(self.device)

        # Online net picks best action in next state (Double DQN)
        with torch.no_grad():
            best_actions = self.online_net(ns).argmax(1, keepdim=True)
            target_q = self.target_net(ns).gather(1, best_actions)
            y = r + self.gamma * target_q * (1 - d)

        current_q = self.online_net(s).gather(1, a)
        loss = nn.SmoothL1Loss()(current_q, y)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online_net.parameters(), 1.0)
        self.optimizer.step()

        self.total_steps += 1

        # Update target network every tau steps
        if self.total_steps % self.tau == 0:
            self.target_net.load_state_dict(self.online_net.state_dict())

        # Decay epsilon (linear then exponential)
        if self.epsilon > self.epsilon_end:
            self.epsilon = max(self.epsilon_end, self.epsilon - self.epsilon_step)
        else:
            self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_exp_decay)

        return float(loss.item())

    def save_bundle(self, path: str, config: dict, metrics: dict):
        torch.save({
            "online_state_dict": self.online_net.state_dict(),
            "target_state_dict": self.target_net.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "config": config,
            "metrics": metrics,
        }, path)

    @classmethod
    def load(cls, path: str, device: str = "cpu") -> "DDQNAgent":
        bundle = torch.load(path, map_location=device)
        cfg    = bundle["config"]
        agent  = cls(
            state_dim=cfg["state_dim"],
            action_dim=3,
            hidden=cfg.get("architecture", [256, 256]),
            gamma=cfg.get("gamma", 0.99),
            learning_rate=cfg.get("learning_rate", 1e-4),
            device=device,
        )
        agent.online_net.load_state_dict(bundle["online_state_dict"])
        agent.target_net.load_state_dict(bundle["target_state_dict"])
        agent.optimizer.load_state_dict(bundle["optimizer_state_dict"])
        return agent
