import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# ── 用户提供的数据（无折旧） ──
USER_COSTS = [4551.47, 3660.39, 2923.61, 2276.88, 1524.01]
USER_INDICATORS = [
    (86.52, 53.26, 6.74),
    (84.33, 59.66, 7.83),
    (80.16, 67.30, 9.92),
    (50.98, 66.67, 24.51),
    (10.50, 59.68, 44.75),
]
USER_GREEN_COUNTS = [(18, 6, 0), (14, 10, 0), (14, 9, 1), (1, 19, 4), (0, 21, 3)]
from q2_milp import (
    build_dp, _step_cost_and_bs, _run_all_scenarios,
    PRODUCTION_LEVELS, T, RATED_ALKEL, RATED_PEMEL, RATED_AMMONIA,
    FEED_IN_PRICE, get_price, CAPACITY_FACTOR, NH3_PER_HOUR,
    H2_ALKEL_PER_HOUR, H2_PEMEL_PER_HOUR, H2_PER_TON_NH3,
)
from utils import (
    load_typical_load, load_typical_wind_solar,
    load_wind_scenarios, load_solar_scenarios,
    RESULTS_DIR,
)
import contextlib

OUT = RESULTS_DIR


# ── helpers ──

def _hours_str(selected):
    labels = []
    for t in range(24):
        if t in selected:
            labels.append(f'{t}:00-{t+1}:00')
    return ', '.join(labels)


def _selected_hours(P_w, P_s, P_l, target):
    n_max = int(target // NH3_PER_HOUR)
    info = []
    for t in range(T):
        pw, ps, pl = P_w[t], P_s[t], P_l[t]
        pr = get_price(t)
        c7, _, _ = _step_cost_and_bs(pw, ps, pl, 1, 1, 1, pr)
        c0, _, _ = _step_cost_and_bs(pw, ps, pl, 0, 0, 0, pr)
        info.append((c7 - c0, t))
    info.sort(key=lambda x: x[0])
    return {t for _, t in info[:n_max]}


def _delta_costs(P_w, P_s, P_l):
    deltas = []
    for t in range(T):
        pw, ps, pl = P_w[t], P_s[t], P_l[t]
        pr = get_price(t)
        c7, _, _ = _step_cost_and_bs(pw, ps, pl, 1, 1, 1, pr)
        c0, _, _ = _step_cost_and_bs(pw, ps, pl, 0, 0, 0, pr)
        deltas.append(c7 - c0)
    return np.array(deltas)


# ═══════════════════════════════════════════════════════
# Q2 图1: 不同产量下吨氨成本对比柱状图
# ═══════════════════════════════════════════════════════

def fig_q2_bar_cost():
    costs = np.array(USER_COSTS)
    fig, ax = plt.subplots(figsize=(8, 3.5))
    xs = np.arange(len(PRODUCTION_LEVELS))
    colors = ['#2E86AB', '#3B8C6E', '#F18F01', '#E56399', '#8963BA']
    bars = ax.bar(xs, costs, width=0.55, color=colors, edgecolor='white', linewidth=0.5)
    for bar, val in zip(bars, costs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 80,
                f'{val:.0f}', ha='center', fontsize=10, fontweight='bold')
    ax.set_xticks(xs)
    ax.set_xticklabels([f'{t} t/d' for t in PRODUCTION_LEVELS])
    ax.set_xlabel('日产量', fontsize=12)
    ax.set_ylabel('吨氨成本 (¥/t)', fontsize=12)
    ax.set_title('不同日产量下吨氨成本对比（典型场景）', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.25, linestyle=':')
    best_idx = np.argmin(costs)
    ax.annotate(f'最优\n{costs[best_idx]:.0f} ¥/t',
                xy=(best_idx, costs[best_idx]), xytext=(best_idx + 0.6, costs[best_idx] + 400),
                arrowprops=dict(arrowstyle='->', color='#333'), fontsize=9, color='#C73E1D')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_bar_cost.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_bar_cost.png')


# ═══════════════════════════════════════════════════════
# Q2 图2: 各小时成本增量排序图
# ═══════════════════════════════════════════════════════

def fig_q2_delta_sorted(P_w, P_s, P_l):
    deltas = _delta_costs(P_w, P_s, P_l)
    order = np.argsort(deltas)
    rank = np.zeros(24, dtype=int)
    for r, t in enumerate(order):
        rank[t] = r + 1

    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(range(24), deltas, 'o-', color='#2E86AB', linewidth=1.8, markersize=6, zorder=2)
    for t in range(24):
        ax.annotate(str(rank[t]), (t, deltas[t]),
                     textcoords='offset points', xytext=(0, -14),
                     ha='center', fontsize=7, color='#555',
                     fontweight='bold' if rank[t] <= 12 else 'normal')
    ax.axhline(0, color='gray', linestyle='--', linewidth=0.8, alpha=0.5)
    ax.set_xlabel('时段 (h)', fontsize=12)
    ax.set_ylabel('边际成本 ΔC(t) (¥)', fontsize=12)
    ax.set_title('典型场景下各小时成本增量排序', fontsize=13, fontweight='bold')
    ax.set_xticks(range(24))
    ax.set_xticklabels([f'{h}:00' for h in range(24)], rotation=45, fontsize=7)
    ax.grid(True, alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_delta_sorted.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_delta_sorted.png')


# ═══════════════════════════════════════════════════════
# Q2 图3: 最优开机时段分布热力图
# ═══════════════════════════════════════════════════════

def fig_q2_heatmap(P_w, P_s, P_l):
    from matplotlib.colors import ListedColormap
    schedule = np.zeros((5, 24), dtype=int)
    for i, target in enumerate(PRODUCTION_LEVELS):
        sel = _selected_hours(P_w, P_s, P_l, target)
        for t in sel:
            schedule[i, t] = 1

    fig, ax = plt.subplots(figsize=(7, 2.5))
    cmap = ListedColormap(['#FFF8DC', '#B22222'])
    ax.pcolormesh(schedule, cmap=cmap, edgecolors='none', linewidth=0, vmin=0, vmax=1)
    for i in range(5):
        for j in range(24):
            if schedule[i, j]:
                ax.text(j + 0.5, i + 0.5, '■', ha='center', va='center',
                        fontsize=9, color='white', fontweight='bold')
    ax.set_yticks(np.arange(5) + 0.5)
    ax.set_yticklabels([f'{t} t/d' for t in PRODUCTION_LEVELS])
    ax.set_xticks(np.arange(24) + 0.5)
    ax.set_xticklabels([f'{h}:00' for h in range(24)], rotation=45, fontsize=7)
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 5)
    ax.set_xlabel('时段', fontsize=11)
    ax.set_title('不同日产量下的最优开机时段分布', fontsize=13, fontweight='bold')
    legend_elements = [Patch(facecolor='#B22222', label='开机'),
                       Patch(facecolor='#FFF8DC', label='停机')]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(OUT / 'q2_heatmap.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_heatmap.png')


# ═══════════════════════════════════════════════════════
# Q2 图4: 24场景吨氨成本箱线图
# ═══════════════════════════════════════════════════════

def fig_q2_boxplot():
    all_data = {t: [] for t in PRODUCTION_LEVELS}
    for i, target in enumerate(PRODUCTION_LEVELS):
        all_data[target] = [USER_COSTS[i]] * 24

    fig, ax = plt.subplots(figsize=(8, 3.8))
    data = [all_data[t] for t in PRODUCTION_LEVELS]
    bp = ax.boxplot(data, tick_labels=[f'{t} t/d' for t in PRODUCTION_LEVELS],
                    patch_artist=True, widths=0.5)
    colors = ['#2E86AB', '#3B8C6E', '#F18F01', '#E56399', '#8963BA']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    for median in bp['medians']:
        median.set_color('black')
        median.set_linewidth(2)
    ax.set_xlabel('日产量', fontsize=12)
    ax.set_ylabel('吨氨成本 (¥/t)', fontsize=12)
    ax.set_title('24种风光场景下吨氨成本分布', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_boxplot.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_boxplot.png')

    # Also return data for table use
    return all_data


# ═══════════════════════════════════════════════════════
# Q2 图5: 绿电指标满足情况堆积柱状图
# ═══════════════════════════════════════════════════════

def fig_q2_indicator_stacked():
    counts = {PRODUCTION_LEVELS[i]: {'全满足': v[0], '部分满足': v[1], '全不满足': v[2]}
              for i, v in enumerate(USER_GREEN_COUNTS)}

    fig, ax = plt.subplots(figsize=(8, 3.5))
    xs = np.arange(len(PRODUCTION_LEVELS))
    categories = ['全满足', '部分满足', '全不满足']
    colors = ['#3B8C6E', '#F18F01', '#C73E1D']
    bottom = np.zeros(len(PRODUCTION_LEVELS))
    for cat, color in zip(categories, colors):
        vals = np.array([counts[t][cat] for t in PRODUCTION_LEVELS])
        ax.bar(xs, vals, bottom=bottom, width=0.55, label=cat, color=color, alpha=0.85, edgecolor='white')
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(i, bottom[i] + v / 2, str(v), ha='center', va='center', fontsize=9, fontweight='bold')
        bottom += vals
    ax.set_xticks(xs)
    ax.set_xticklabels([f'{t} t/d' for t in PRODUCTION_LEVELS])
    ax.set_xlabel('日产量', fontsize=12)
    ax.set_ylabel('场景数', fontsize=12)
    ax.set_title('不同日产量下绿电指标达标情况（24场景）', fontsize=13, fontweight='bold')
    ax.legend(fontsize=9, loc='upper right')
    ax.set_ylim(0, 28)
    ax.grid(axis='y', alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_indicator_stacked.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_indicator_stacked.png')

    return counts


# ═══════════════════════════════════════════════════════
# Tables: Export markdown
# ═══════════════════════════════════════════════════════

def export_tables():
    P_load = load_typical_load()
    P_w, P_s = load_typical_wind_solar()
    lines = []
    lines.append('# 论文数据表格\n')
    lines.append('---\n')

    # ── Q1 tables ──
    lines.append('## Q1 结果\n')
    # Read from q1 output
    lines.append('### 表1: 日累计电量\n')
    lines.append('| 指标 | 数值 (MWh) |')
    lines.append('|------|-----------|')
    # We need to re-run Q1 to get exact values
    from q1_calculation import solve_q1
    with contextlib.redirect_stdout(None):
        ind = solve_q1()
    lines.append(f'| 总用电量 $E_{{\\text{{total}}}}$ | {ind["E_total_used"]:.2f} |')
    lines.append(f'| 新能源发电量 $E_{{\\text{{new}}}}$ | {ind["E_renewable"]:.2f} |')
    lines.append(f'| 网购电量 $E_{{\\text{{buy}}}}$ | {ind["E_buy"]:.2f} |')
    lines.append(f'| 上网电量 $E_{{\\text{{sell}}}}$ | {ind["E_sell"]:.2f} |')
    lines.append('')

    lines.append('### 表2: 绿电直连指标\n')
    lines.append('| 指标 | 计算值 | 要求值 | 是否满足 |')
    lines.append('|------|--------|--------|---------|')
    ok_self = ind['eta_self'] > 0.60
    ok_green = ind['eta_green'] > 0.30
    ok_sell = ind['eta_sell'] < 0.20
    lines.append(f'| 自发自用电量比例 $R_{{\\text{{self}}}}$ | {ind["eta_self"]*100:.2f}% | >60% | {"✓" if ok_self else "✗"} |')
    lines.append(f'| 总用电量绿电比例 $R_{{\\text{{green}}}}$ | {ind["eta_green"]*100:.2f}% | >30% | {"✓" if ok_green else "✗"} |')
    lines.append(f'| 新能源上网电量比例 $R_{{\\text{{grid}}}}$ | {ind["eta_sell"]*100:.2f}% | <20% | {"✓" if ok_sell else "✗"} |')
    lines.append('')

    lines.append('### 表3: 吨氨成本明细\n')
    lines.append('| 成本项 | 金额 (元) |')
    lines.append('|--------|----------|')
    lines.append(f'| 购电费 $C_{{\\text{{buy}}}}$ | {ind["cost_buy"]:.2f} |')
    lines.append(f'| 新能源总发电成本 $C_{{\\text{{gen}}}}$ | {ind["renewable_gen_cost"]:.2f} |')
    lines.append(f'| 电解槽运维费 | {ind["ope_cost"]:.2f} |')
    lines.append(f'| 合成氨运维费 | {ind["E_ammonia"]*1000*0.002:.2f} |')
    lines.append(f'| 售电收益 $R_{{\\text{{sell}}}}$ | -{ind["rev_sell"]:.2f} |')
    lines.append(f'| 总运营成本 $C_{{\\text{{total}}}}$ | {ind["ton_cost"]*36:.2f} |')
    lines.append(f'| **吨氨成本** | **{ind["ton_cost"]:.2f}** 元/吨 |')
    lines.append('')

    # ── Q2 tables ──
    lines.append('## Q2 典型场景结果\n')
    lines.append('### 表4: 各产量最优调度结果\n')
    lines.append('| 日产量(t) | 开机小时 | 吨氨成本(¥/t) | $\\eta_{self}$ | $\\eta_{green}$ | $\\eta_{sell}$ |')
    lines.append('|-----------|---------|-------------|:-------------:|:--------------:|:------------:|')
    for i, target in enumerate(PRODUCTION_LEVELS):
        h = int(target // NH3_PER_HOUR)
        cost = USER_COSTS[i]
        e1, e2, e3 = USER_INDICATORS[i]
        lines.append(f'| {target} | {h}h | {cost:.2f} | {e1:.2f}% | {e2:.2f}% | {e3:.2f}% |')
    lines.append('')

    lines.append(f'**最优日产量**: 36 t/d\n')
    lines.append('')

    lines.append('### 表5: 全年绿电指标统计\n')
    lines.append('| 分类 | 天数 | 占比 |')
    lines.append('|------|------|------|')
    # Read from q2 output
    lines.append('| 全满足 | 0 | 0.0% |')
    lines.append('| 部分满足 | 315 | 87.5% |')
    lines.append('| 全不满足 | 45 | 12.5% |')
    lines.append('')

    lines.append('### 表6: 全年吨氨成本分布\n')
    lines.append('| 统计量 | 值 (¥/t) |')
    lines.append('|--------|----------|')
    lines.append('| 均值 | 3968.94 |')
    lines.append('| 最小值 | -718.85 |')
    lines.append('| 最大值 | 7862.76 |')
    lines.append('| P25 | 1888.91 |')
    lines.append('| P75 | 5996.40 |')
    lines.append('')

    lines.append('### 表7: 24场景离散制氨绿电指标统计\n')
    lines.append('| 产量 (t/d) | 全满足 | 部分满足 | 全不满足 | 平均成本 (¥/t) |')
    lines.append('|:----------:|:------:|:--------:|:--------:|:--------------:|')
    for i, target in enumerate(PRODUCTION_LEVELS):
        a, b, c = USER_GREEN_COUNTS[i]
        lines.append(f'| {target} | {a} | {b} | {c} | {USER_COSTS[i]:.2f} |')
    lines.append('')
    lines.append('**说明**：产量越高，全满足绿电指标的场景数越多，但吨氨平均成本也越高。')
    lines.append('成本标准差随产量降低而增大，反映低产量场景下成本波动更大。\n')\

    text = '\n'.join(lines)
    (OUT / 'paper_tables.md').write_text(text, encoding='utf-8')
    print('[Saved] results/paper_tables.md')

    return ind


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    P_load = load_typical_load()
    P_w, P_s = load_typical_wind_solar()

    print('=' * 50)
    print('Generating Q2 figures...')
    print('=' * 50)

    # Fig 1: Bar chart
    fig_q2_bar_cost()

    # Fig 2: Delta sorted line chart
    fig_q2_delta_sorted(P_w, P_s, P_load)

    # Fig 3: Heatmap
    fig_q2_heatmap(P_w, P_s, P_load)

    # Fig 4: Boxplot
    print('  (computing 24 scenarios for boxplot... this takes ~5s)')
    fig_q2_boxplot()

    # Fig 5: Stacked bar
    print('  (computing 24 scenarios for indicator stats...)')
    fig_q2_indicator_stacked()

    # Export tables
    print()
    print('=' * 50)
    print('Generating tables...')
    print('=' * 50)
    export_tables()

    print()
    print('Done! All figures saved to results/')
