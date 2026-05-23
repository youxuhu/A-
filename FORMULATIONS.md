# 绿电直连型电氢氨园区优化运行 — 公式与模型文档

## 目录

1. [符号与变量定义](#1-符号与变量定义)
2. [问题一：满负荷基准分析](#2-问题一满负荷基准分析)
3. [问题二：离散 ON/OFF 调度 (MILP)](#3-问题二离散-onoff-调度-milp)
4. [问题三：连续功率调节 (LP)](#4-问题三连续功率调节-lp)
5. [问题四：离网运行与储能配置](#5-问题四离网运行与储能配置)
6. [绿电直连指标](#6-绿电直连指标)
7. [成本计算](#7-成本计算)

---

## 1. 符号与变量定义

### 1.1 索引与常量

| 符号 | 含义 | 值 | 单位 |
|------|------|-----|------|
| $t$ | 时段索引，$t=0,1,\dots,23$ | — | h |
| $T$ | 全天时段数 | 24 | h |
| $P_{load}(t)$ | 常规电负荷（附件1 × 6MW） | — | MW |
| $P_{wind}(t)$ | 风电出力（附件2/3 × 40MW） | — | MW |
| $P_{solar}(t)$ | 光伏出力（附件2/4 × 64MW） | — | MW |
| $P_{ALKEL}^{max}$ | 碱性电解槽额定功率 | 10 (基础) / 20 (2×) | MW |
| $P_{PEMEL}^{max}$ | PEM电解槽额定功率 | 10 (基础) / 20 (2×) | MW |
| $P_{NH3}^{max}$ | 合成氨装置额定功率 | 0.75 (基础) / 1.5 (2×) | MW |
| $r_{ALKEL}^{H2}$ | 碱性电解槽产氢率（满功率） | 140 (基础) / 280 (2×) | kg/h |
| $r_{PEMEL}^{H2}$ | PEM电解槽产氢率（满功率） | 160 (基础) / 320 (2×) | kg/h |
| $r_{NH3}$ | 合成氨产率（满功率） | 1.5 (基础) / 3.0 (2×) | t/h |
| $k_{H2}$ | 每吨氨需氢量 | 200 | kg/t |

### 1.2 决策变量

| 符号 | 含义 | 范围 | 适用问题 |
|------|------|------|---------|
| $x_{ALKEL}(t)$ | ALKEL ON/OFF | $\{0,1\}$ | Q2 |
| $x_{PEMEL}(t)$ | PEMEL ON/OFF | $\{0,1\}$ | Q2 |
| $x_{NH3}(t)$ | 合成氨 ON/OFF | $\{0,1\}$ | Q2 |
| $P_{ALKEL}(t)$ | ALKEL 功率（连续） | $[0, P_{ALKEL}^{max}]$ | Q3/Q4 |
| $P_{PEMEL}(t)$ | PEMEL 功率（连续） | $[0, P_{PEMEL}^{max}]$ | Q3/Q4 |
| $P_{NH3}(t)$ | 合成氨功率（连续） | $[0, P_{NH3}^{max}]$ | Q3/Q4 |
| $P_{buy}(t)$ | 网购电功率 | $\ge 0$ | Q1/Q2/Q3 |
| $P_{sell}(t)$ | 售电功率 | $\ge 0$ | Q1/Q2/Q3 |
| $P_{curt}(t)$ | 弃电功率 | $\ge 0$ | Q4 |
| $P_{ch}(t)$ | 储能充电功率 | $[0, P_{ch}^{max}]$ | Q4 |
| $P_{dch}(t)$ | 储能放电功率 | $[0, P_{dch}^{max}]$ | Q4 |
| $SOC(t)$ | 储能荷电状态 | $[0, C_{storage}]$ | Q4 |
| $H_2(t)$ | 氢气库存 | $\ge 0$ | Q3/Q4 |

### 1.3 电价参数

| 符号 | 含义 | 值 | 单位 |
|------|------|-----|------|
| $\pi_{peak}$ | 峰时电价 | 0.8024 | ¥/kWh |
| $\pi_{flat}$ | 平时电价 | 0.6074 | ¥/kWh |
| $\pi_{valley}$ | 谷时电价 | 0.3424 | ¥/kWh |
| $\pi_{sell}$ | 余电上网电价 | 0.3779 | ¥/kWh |
| $c_{wind}$ | 风电度电成本 | 0.15 | ¥/kWh |
| $c_{solar}$ | 光伏度电成本 | 0.12 | ¥/kWh |

电价时段划分：

| 时段 | 类型 |
|------|------|
| 10:00–15:00, 18:00–21:00 | 峰 |
| 7:00–10:00, 15:00–18:00, 21:00–23:00 | 平 |
| 23:00–7:00 | 谷 |

---

## 2. 问题一：满负荷基准分析

### 2.1 问题描述

电解槽与合成氨装置每日满负荷连续运行，不计功率损耗，计算功率平衡、各类电量、绿电指标和吨氨成本。

### 2.2 固定功率设定

$$P_{ALKEL}(t) = P_{ALKEL}^{max} = 10\ \text{MW},\quad \forall t$$
$$P_{PEMEL}(t) = P_{PEMEL}^{max} = 10\ \text{MW},\quad \forall t$$
$$P_{NH3}(t) = P_{NH3}^{max} = 0.75\ \text{MW},\quad \forall t$$

### 2.3 功率平衡

$$\Delta P(t) = P_{wind}(t) + P_{solar}(t) - [P_{load}(t) + P_{ALKEL}(t) + P_{PEMEL}(t) + P_{NH3}(t)]$$

$$P_{buy}(t) = \max(0, -\Delta P(t))$$
$$P_{sell}(t) = \max(0, \Delta P(t))$$

购售电互斥：$P_{buy}(t) \cdot P_{sell}(t) = 0$

### 2.4 日累计电量

$$E_{total} = \sum_{t=0}^{23} \big[P_{load}(t) + P_{ALKEL}(t) + P_{PEMEL}(t) + P_{NH3}(t)\big]$$

$$E_{renew} = \sum_{t} [P_{wind}(t) + P_{solar}(t)]$$

$$E_{buy} = \sum_{t} P_{buy}(t), \quad E_{sell} = \sum_{t} P_{sell}(t)$$

### 2.5 绿电指标

见[第6节](#6-绿电直连指标)。

### 2.6 吨氨成本（Q1 运营成本，不含折旧）

$$C_{buy} = \sum_t P_{buy}(t) \times 1000 \times \pi(t) \quad \text{(元)}$$
$$C_{renew} = E_{wind} \times 1000 \times 0.15 + E_{solar} \times 1000 \times 0.12 \quad \text{(元)}$$
$$C_{ope} = \sum_t \big[P_{ALKEL}(t) \times 100 + P_{PEMEL}(t) \times 150 + P_{NH3}(t) \times 2\big] \quad \text{(元)}$$
$$R_{sell} = E_{sell} \times 1000 \times 0.3779 \quad \text{(元)}$$

$$C_{total} = C_{buy} + C_{renew} + C_{ope} - R_{sell}$$

$$c_{ton} = \frac{C_{total}}{Q_{NH3}},\quad Q_{NH3} = 36\ \text{t}$$

---

## 3. 问题二：离散 ON/OFF 调度 (MILP)

### 3.1 问题描述

产能 2×（72 t/d 上限），设备只能全额开机或停机。产量从 72 t/d 按 9 t/d 递减至 36 t/d。在典型场景和 24 种风光场景下寻找成本最低的时段安排。

### 3.2 决策变量

$$x_{ALKEL}(t), x_{PEMEL}(t), x_{NH3}(t) \in \{0, 1\},\quad t = 0,\dots,23$$

$$P_{buy}(t) \ge 0, \quad P_{sell}(t) \ge 0$$

### 3.3 约束

**功率平衡：**

$$P_{wind}(t) + P_{solar}(t) + P_{buy}(t) = P_{load}(t) + P_{ALKEL}^{max}x_{ALKEL}(t) + P_{PEMEL}^{max}x_{PEMEL}(t) + P_{NH3}^{max}x_{NH3}(t) + P_{sell}(t)$$

**制氨产量目标：**

$$\sum_t x_{NH3}(t) \cdot r_{NH3} = Q_{target},\quad Q_{target} \in \{72, 63, 54, 45, 36\}$$

**氢气总量约束（无逐时存储）：**

$$\sum_t \big[x_{ALKEL}(t) \cdot r_{ALKEL}^{H2} + x_{PEMEL}(t) \cdot r_{PEMEL}^{H2}\big] \ge Q_{target} \cdot k_{H2}$$

**购售电上限：**

$$0 \le P_{buy}(t) \le P_{load}^{max} + P_{ALKEL}^{max} + P_{PEMEL}^{max} + P_{NH3}^{max}$$
$$0 \le P_{sell}(t) \le P_{wind}(t) + P_{solar}(t)$$

### 3.4 目标函数

$$\min \sum_t \Big[ P_{buy}(t) \times 1000 \times \pi(t) - P_{sell}(t) \times 1000 \times 0.3779 \Big] + C_{ope}$$

其中运维费用：

$$C_{ope} = \sum_t \big[ P_{ALKEL}^{max}x_{ALKEL}(t) \times 100 + P_{PEMEL}^{max}x_{PEMEL}(t) \times 150 + P_{NH3}^{max}x_{NH3}(t) \times 2 \big]$$

设备折旧在 MILP 目标函数中不计（固定成本不影响调度决策），在指标计算的 `compute_indicators` 后处理中加入。

### 3.5 求解方法

- 求解器：CBC MILP（分支定界法）
- 对 24 场景 × 5 产量 = 120 个 MILP 分别求解
- 每个场景选择吨氨成本最低的产量作为该场景最优方案

---

## 4. 问题三：连续功率调节 (LP)

### 4.1 问题描述

与 Q2 相同场景和产量，但设备功率在 $[0, P^{max}]$ 间连续可调。引入逐时氢气存储变量。

### 4.2 决策变量

$$P_{ALKEL}(t), P_{PEMEL}(t), P_{NH3}(t) \in [0, P^{max}],\quad t = 0,\dots,23$$
$$P_{buy}(t) \ge 0, \quad P_{sell}(t) \ge 0$$
$$H_2(t) \ge 0 \quad \text{(氢气库存)}$$

### 4.3 约束

**功率平衡：**

$$P_{wind}(t) + P_{solar}(t) + P_{buy}(t) = P_{load}(t) + P_{ALKEL}(t) + P_{PEMEL}(t) + P_{NH3}(t) + P_{sell}(t)$$

**制氨产量目标：**

$$\sum_t \frac{P_{NH3}(t)}{P_{NH3}^{max}} \cdot r_{NH3} = Q_{target}$$

**氢气逐时平衡：**

$$H_2(0) = \frac{P_{ALKEL}(0)}{P_{ALKEL}^{max}} r_{ALKEL}^{H2} + \frac{P_{PEMEL}(0)}{P_{PEMEL}^{max}} r_{PEMEL}^{H2} - \frac{P_{NH3}(0)}{P_{NH3}^{max}} r_{NH3} \cdot k_{H2}$$

$$H_2(t) = H_2(t-1) + \frac{P_{ALKEL}(t)}{P_{ALKEL}^{max}} r_{ALKEL}^{H2} + \frac{P_{PEMEL}(t)}{P_{PEMEL}^{max}} r_{PEMEL}^{H2} - \frac{P_{NH3}(t)}{P_{NH3}^{max}} r_{NH3} \cdot k_{H2}$$

$$H_2(t) \ge 0,\quad \forall t$$

**10% 下限处理后处理：** LP 在 $[0, P^{max}]$ 求解后将低于 10% 额定值的功率置 0：

$$P_{device}(t) = \begin{cases} 0, & 0 < P_{device}(t) < 0.1 P_{device}^{max} \\ P_{device}(t), & \text{otherwise} \end{cases}$$

### 4.4 目标函数

同 Q2（最小化购电+运维−售电收益），但功率是连续值：

$$\min \sum_t \Big[ P_{buy}(t) \times 1000 \times \pi(t) - P_{sell}(t) \times 1000 \times 0.3779 + P_{ALKEL}(t) \times 100 + P_{PEMEL}(t) \times 150 + P_{NH3}(t) \times 2 \Big]$$

### 4.5 Q2 vs Q3 差异

| 维度 | Q2 (MILP) | Q3 (LP) |
|------|-----------|---------|
| 功率 | $P^{max} \times \{0,1\}$ | $[0, P^{max}]$ 任意值 |
| 变量类型 | 72 × Binary + 48 × Continuous | 120 × Continuous |
| H₂ 存储 | 无（仅总量约束） | 逐时 H₂ 库存递推 |
| 求解器 | CBC MILP | CBC LP |

---

## 5. 问题四：离网运行与储能配置

### 5.1 问题描述

园区离网（无电网），仅靠风电、光伏和储能供电。设备功率连续可调（0–100%），目标 72 t/d。分析无储能和有储能两种场景。

### 5.2 决策变量

- 设备功率：$P_{ALKEL}(t), P_{PEMEL}(t), P_{NH3}(t) \in [0, P^{max}]$
- 弃电：$P_{curt}(t) \ge 0$
- 氢气库存：$H_2(t) \ge 0$
- 储能（若有）：$P_{ch}(t) \in [0, P_{ch}^{max}]$，$P_{dch}(t) \in [0, P_{dch}^{max}]$，$SOC(t) \in [0, C_{storage}]$

### 5.3 约束

**功率平衡：**

$$P_{wind}(t) + P_{solar}(t) + P_{dch}(t) = P_{load}(t) + P_{ALKEL}(t) + P_{PEMEL}(t) + P_{NH3}(t) + P_{curt}(t) + P_{ch}(t)$$

**储能 SOC 递推：**

$$SOC(0) = 0.5 \cdot C_{storage} \cdot (1 - \eta_{self}) + P_{ch}(0) \cdot \eta_{ch} - \frac{P_{dch}(0)}{\eta_{dch}}$$

$$SOC(t) = SOC(t-1) \cdot (1 - \eta_{self}) + P_{ch}(t) \cdot \eta_{ch} - \frac{P_{dch}(t)}{\eta_{dch}}$$

其中自放电率 $\eta_{self} = 0.002$，充放电效率 $\eta_{ch} = \eta_{dch} = 0.90$。

**氢气平衡：** 同 Q3 逐时递推。

**制氨目标：** 先尝试 $Q_{NH3} \ge 72$ 约束，不可行则转为最大化（无约束）。

### 5.4 目标函数

$$\max \sum_t \frac{P_{NH3}(t)}{P_{NH3}^{max}} \cdot r_{NH3}$$

离网无购电售电，所以目标变为**最大化制氨产量**。成本在后处理中计算（含储能折旧）。

### 5.5 成本计算（离网，含储能折旧）

$$C_{storage} = C_{capacity}(\text{MWh}) \times 1000 \times 1000\ \text{¥/kWh}$$
$$C_{storage}^{daily} = \frac{C_{storage}}{15 \times 365}$$

$$C_{total} = C_{ope} + C_{equip}^{dep} + C_{storage}^{daily}$$

$$c_{ton} = \frac{C_{total}}{Q_{NH3}}$$

### 5.6 最小风光装机估算

对当前风电 $W=40$ MW、光伏 $S=64$ MW 等比例缩放：
$$W' = \alpha W,\quad S' = \alpha S,\quad \alpha \in \{1, 1.5, 2, 2.5, \dots, 20\}$$

对每个 $\alpha$ 求解 24 场景 LP，找到使全部场景达标 72 t/d 的最小 $\alpha$。

### 5.7 储能定容

在最大弃电场景（风4光1, 弃电 174 MWh）上遍历不同容量 $C_{storage} \in \{20, 50, 100, 150, 200, 300, 500\}$ MWh，选择 NH₃ 增量边际收益不再显著提高的容量。

---

## 6. 绿电直连指标

### 6.1 指标定义

**新能源自发自用电量占总可用发电量比例：**

$$\eta_{self} = \frac{E_{total} - E_{sell} - E_{buy}}{E_{renew}} \times 100\% \quad (\text{要求} > 60\%)$$

分子含义：园区实际消耗的新能源电量 = 总用电 − 从网购的电 − 卖给网的电

**总用电量绿电比例：**

$$\eta_{green} = \frac{E_{renew} - E_{sell}}{E_{total}} \times 100\% \quad (\text{要求} > 30\%)$$

分子含义：园区自用的新能源电量

**新能源上网电量比例：**

$$\eta_{sell} = \frac{E_{sell}}{E_{renew}} \times 100\% \quad (\text{要求} < 20\%)$$

### 6.2 离网模式下的退化

离网时 $E_{buy} = E_{sell} = 0$，指标退化：

$$\eta_{self} = \frac{E_{total}}{E_{renew}} \times 100\% \quad (\text{风光自用率，衡量弃电})$$
$$\eta_{green} = \frac{E_{renew}}{E_{total}} \times 100\% \quad (\text{恒} \ge 100\%)$$
$$\eta_{sell} = 0\% \quad (\text{恒合格})$$

离网下仅有 $\eta_{self}$ 有意义——它衡量有多少绿电被实际利用了。

---

## 7. 成本计算

### 7.1 各问题的成本项目

| 成本项 | Q1 | Q2 | Q3 | Q4 |
|--------|:--:|:--:|:--:|:--:|
| 购电费 $C_{buy}$ | ✓ | ✓ | ✓ | ✗ |
| 新能源发电成本 $C_{renew}$ | ✓ | ✗ | ✗ | ✗ |
| 设备运维 $C_{ope}$ | ✓ | ✓ | ✓ | ✓ |
| 设备折旧 $C_{dep}$ | ✗ | ✓ | ✓ | ✓ |
| 售电收益 $R_{sell}$ | ✓ | ✓ | ✓ | ✗ |
| 储能折旧 $C_{sto}^{dep}$ | ✗ | ✗ | ✗ | ✓ |

### 7.2 设备折旧计算

$$C_{dep}^{ALKEL} = \frac{10 \times 1000 \times 10000 \times \alpha}{30 \times 365} \quad \text{¥/天}$$
$$C_{dep}^{PEMEL} = \frac{10 \times 1000 \times 10000 \times \alpha}{30 \times 365} \quad \text{¥/天}$$
$$C_{dep}^{NH3} = \frac{1.5 \times 0.2 \times 1000 \times 60000 \times \alpha}{30 \times 365} \quad \text{¥/天}$$

其中 $\alpha$ 为产能倍数（基础=1，扩容=2）。

### 7.3 储能折旧计算

$$C_{sto}^{dep} = \frac{C_{storage} \times 1000 \times 1000}{15 \times 365} \quad \text{¥/天}$$

其中 $C_{storage}$ 为储能容量（MWh），1000 ¥/kWh 为储能单价。

---

*文档版本：v1.0*
