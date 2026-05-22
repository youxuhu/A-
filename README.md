# 风-光-氢-氨综合能源系统优化调度

绿电直连型电氢氨园区优化运行 — 数学建模竞赛 A题

## 快速开始

```bash
pip install -r requirements.txt

# 问题1: 满负荷功率平衡计算
python src/q1_calculation.py

# 问题2: MILP离散调度
python src/q2_milp.py

# 问题3: LP连续调度
python src/q3_lp.py

# 问题2-3 RL对比实验
python src/rl_comparison/train_compare.py

# 问题4: LSTM+PPO离网调度
python src/q4_rl/train.py
```

## 目录结构

```
src/
├── q1_calculation.py    解析法满负荷计算
├── q2_milp.py           MILP离散ON/OFF调度
├── q3_lp.py             LP连续功率调节
├── q4_rl/               LSTM+PPO离网分析
├── rl_comparison/       DQN/PPO对比实验
└── utils.py             数据加载/指标/绘图

results/                  输出图表
data/                     附件xlsx (可选)
```

详见 `SOLUTION_PLAN.md` 和 `AGENTS.md`。
