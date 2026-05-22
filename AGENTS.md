# AGENTS.md

Data-only repo for **风-光-氢-氨综合能源系统优化调度** modeling competition problem.

**Cannot read** `A题.pdf` (no PDF support). Ask user for text.

## Data files

| File | Content |
|---|---|
| 附件1 | 24h conventional electrical load per-unit curve |
| 附件2 | Typical daily wind & solar per-unit power |
| 附件3 | Wind power, 6 scenarios × 24h |
| 附件4 | Solar PV, 4 scenarios × 24h |
| 附件5 | Equipment parameters (turbine, PV, ALKEL, PEMEL) |
| 附件6 | Battery storage & ammonia synthesis parameters |
| 附件7 | TOU electricity price (peak 0.8024 / flat 0.6074 / valley 0.3424 元/kWh) |
| 附件8 | Surplus wind/solar feed-in price (0.3779 元/kWh) |

All sheets: 24 hourly periods, per-unit values.

## Key parameters

| Item | Value |
|------|-------|
| Wind capacity | 40 MW |
| PV capacity | 64 MW |
| ALKEL | 10 MW (140 kgH₂/h) |
| PEMEL | 10 MW (160 kgH₂/h) |
| Ammonia synthesis | 0.75 MW (1.5 tNH₃/h) |
| Conventional load peak | 6 MW |
| Initial ammonia capacity | 36 t/d |

## Solution plan

`SOLUTION_PLAN.md` — full plan, 5 questions.

## Code layout

```
src/
├── q1_calculation.py   Q1: fixed-load power balance
├── q2_milp.py          Q2: MILP (discrete ON/OFF)
├── q3_lp.py            Q3: LP (continuous power)
├── q4_rl/              Q4: LSTM+PPO for off-grid
├── rl_comparison/      Q2-3 RL baselines
│   ├── ddpg.py             DDPG (Q3 continuous)
│   ├── ppo_discrete.py     Per-step PPO (Q2 discrete)
│   ├── env_discrete_step.py Per-step env for Q2
│   ├── env_continuous.py   Continuous env for Q3
│   └── train_compare.py    All RL experiments
└── utils.py            Data loading, indicators, plots
```

## Commands

```bash
# Install
pip install -r requirements.txt

# Run Q1 (解析法满负荷)
python src/q1_calculation.py

# Run Q2 (MILP离散调度)
python src/q2_milp.py

# Run Q3 (LP连续调度)
python src/q3_lp.py

# Q2-3 RL对比实验
python src/rl_comparison/train_compare.py

# Q4 LSTM+PPO训练
python src/q4_rl/train.py
```

## Q4 known quirks

- All xlsx uses `openpyxl`; xlsx files in repo root (not `data/`).
- Q2/Q3 equipment ratings scale with ammonia capacity (2× at 72 t/d).
- MILP/LP solver: `pulp` + `CBC`. Any `status=-1` means infeasible (check scaling), `status=-2` means unbounded (add bounds on `P_buy`/`P_sell`).
- RL comparison: DQN with 2^72 actions is impossible; use per-timestep policy gradient instead.
- Q4 env `_get_obs()` reads `self.t` before increment; reward uses `self.t` (not `t-1`).
