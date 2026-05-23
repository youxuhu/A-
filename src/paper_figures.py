import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from q2_milp import (
    build_dp, _step_cost_and_bs,
    PRODUCTION_LEVELS, T, RATED_ALKEL, RATED_PEMEL, RATED_AMMONIA,
    FEED_IN_PRICE, get_price, CAPACITY_FACTOR, NH3_PER_HOUR,
)
from utils import (
    load_typical_load, load_typical_wind_solar,
    load_wind_scenarios, load_solar_scenarios,
    compute_indicators, RESULTS_DIR,
)
import contextlib

OUT = RESULTS_DIR


# ═══════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════

def _sel_hours(P_w, P_s, P_l, target):
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


def _delta_c(P_w, P_s, P_l):
    d = []
    for t in range(T):
        pw, ps, pl = P_w[t], P_s[t], P_l[t]
        pr = get_price(t)
        c7, _, _ = _step_cost_and_bs(pw, ps, pl, 1, 1, 1, pr)
        c0, _, _ = _step_cost_and_bs(pw, ps, pl, 0, 0, 0, pr)
        d.append(c7 - c0)
    return np.array(d)


def _run_24():
    P_load = load_typical_load()
    ws = load_wind_scenarios()
    ss = load_solar_scenarios()
    costs = {t: [] for t in PRODUCTION_LEVELS}
    indicators = {t: [] for t in PRODUCTION_LEVELS}
    for wi in range(6):
        for si in range(4):
            P_w, P_s = ws[:, wi], ss[:, si]
            for tgt in PRODUCTION_LEVELS:
                sol = build_dp(P_w, P_s, P_load, tgt)
                if sol['status'] != 1:
                    continue
                a = sol['x_alkel'] * RATED_ALKEL
                p = sol['x_pemel'] * RATED_PEMEL
                n = sol['x_ammonia'] * RATED_AMMONIA
                ind = compute_indicators(P_w, P_s, sol['P_buy'], sol['P_sell'],
                                         P_load, a, p, n, NH3_total=tgt,
                                         capacity_factor=CAPACITY_FACTOR,
                                         include_depreciation=False)
                costs[tgt].append(ind['ton_cost'])
                ok = sum([ind['eta_self'] > 0.60, ind['eta_green'] > 0.30, ind['eta_sell'] < 0.20])
                indicators[tgt].append(ok)
    stats = {}
    for t in PRODUCTION_LEVELS:
        c = np.array(costs[t])
        if len(c):
            stats[t] = {'mean': c.mean(), 'min': c.min(), 'max': c.max(),
                        'p25': np.percentile(c, 25), 'p75': np.percentile(c, 75), 'std': c.std()}
    return costs, stats, indicators


def _run_typical():
    """Return typical scenario (costs[], indicators[][3]) for each target."""
    P_load = load_typical_load()
    P_w, P_s = load_typical_wind_solar()
    res = []
    for tgt in PRODUCTION_LEVELS:
        sol = build_dp(P_w, P_s, P_load, tgt)
        a = sol['x_alkel'] * RATED_ALKEL
        p = sol['x_pemel'] * RATED_PEMEL
        n = sol['x_ammonia'] * RATED_AMMONIA
        ind = compute_indicators(P_w, P_s, sol['P_buy'], sol['P_sell'],
                                 P_load, a, p, n, NH3_total=tgt,
                                 capacity_factor=CAPACITY_FACTOR,
                                 include_depreciation=False)
        res.append((ind['ton_cost'], ind['eta_self'], ind['eta_green'], ind['eta_sell']))
    return res


# ═══════════════════════════════════════════════════════
# Q2(1) 图1: 吨氨成本对比柱状图
# ═══════════════════════════════════════════════════════

def fig_q2_bar_cost(typical):
    costs = np.array([t[0] for t in typical])
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
    ax.set_title('【Q2(1)】不同日产量下吨氨成本对比（典型场景）', fontsize=13, fontweight='bold')
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
# Q2(1) 图2: 各小时成本增量排序图
# ═══════════════════════════════════════════════════════

def fig_q2_delta_sorted(P_w, P_s, P_l):
    deltas = _delta_c(P_w, P_s, P_l)
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
    ax.set_title('【Q2(1)】典型场景下各小时成本增量排序', fontsize=13, fontweight='bold')
    ax.set_xticks(range(24))
    ax.set_xticklabels([f'{h}:00' for h in range(24)], rotation=45, fontsize=7)
    ax.grid(True, alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_delta_sorted.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_delta_sorted.png')


# ═══════════════════════════════════════════════════════
# Q2(1) 图3: 最优开机时段热力图
# ═══════════════════════════════════════════════════════

def fig_q2_heatmap(P_w, P_s, P_l):
    from matplotlib.colors import ListedColormap
    schedule = np.zeros((5, 24), dtype=int)
    for i, target in enumerate(PRODUCTION_LEVELS):
        sel = _sel_hours(P_w, P_s, P_l, target)
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
    ax.set_title('【Q2(1)】不同日产量下的最优开机时段分布', fontsize=13, fontweight='bold')
    legend_elements = [Patch(facecolor='#B22222', label='开机'),
                       Patch(facecolor='#FFF8DC', label='停机')]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(OUT / 'q2_heatmap.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_heatmap.png')


# ═══════════════════════════════════════════════════════
# Q2(2) 图4: 24场景吨氨成本箱线图
# ═══════════════════════════════════════════════════════

def fig_q2_boxplot(all_costs):
    fig, ax = plt.subplots(figsize=(8, 3.8))
    data = [all_costs[t] for t in PRODUCTION_LEVELS]
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
    ax.set_title('【Q2(2)】24种风光场景下吨氨成本分布', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_boxplot.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_boxplot.png')


# ═══════════════════════════════════════════════════════
# Q2(2) 图5: 绿电指标达标堆积柱状图
# ═══════════════════════════════════════════════════════

def fig_q2_indicator_stacked(indicators, all_stats):
    counts = {}
    for t in PRODUCTION_LEVELS:
        ok_list = indicators[t]
        full = sum(1 for v in ok_list if v == 3)
        none = sum(1 for v in ok_list if v == 0)
        part = len(ok_list) - full - none
        counts[t] = {'全满足': full, '部分满足': part, '全不满足': none}

    fig, ax = plt.subplots(figsize=(8, 3.5))
    xs = np.arange(len(PRODUCTION_LEVELS))
    cats = ['全满足', '部分满足', '全不满足']
    colors = ['#3B8C6E', '#F18F01', '#C73E1D']
    bottom = np.zeros(len(PRODUCTION_LEVELS))
    for cat, color in zip(cats, colors):
        vals = np.array([counts[t][cat] for t in PRODUCTION_LEVELS])
        ax.bar(xs, vals, bottom=bottom, width=0.55, label=cat, color=color, alpha=0.85, edgecolor='white')
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(i, bottom[i] + v / 2, str(v), ha='center', va='center', fontsize=9, fontweight='bold')
        bottom += vals
    # Add cost annotation above each bar
    for i, t in enumerate(PRODUCTION_LEVELS):
        s = all_stats[t]
        ax.text(i, 25, f'{s["mean"]:.0f}±{s["std"]:.0f} ¥/t',
                ha='center', fontsize=7, color='#333',
                bbox=dict(facecolor='white', edgecolor='none', alpha=0.7, pad=1))
    ax.set_xticks(xs)
    ax.set_xticklabels([f'{t} t/d' for t in PRODUCTION_LEVELS])
    ax.set_xlabel('日产量', fontsize=12)
    ax.set_ylabel('场景数', fontsize=12)
    ax.set_title('【Q2(2)】不同日产量下绿电指标达标情况（24场景）', fontsize=13, fontweight='bold')
    ax.legend(fontsize=9, loc='upper right')
    ax.set_ylim(0, 28)
    ax.grid(axis='y', alpha=0.2, linestyle=':')
    fig.tight_layout()
    fig.savefig(OUT / 'q2_indicator_stacked.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print('[Saved] results/q2_indicator_stacked.png')


# ═══════════════════════════════════════════════════════
# Tables
# ═══════════════════════════════════════════════════════

def export_tables(all_costs, all_stats, all_indicators, typical):
    lines = []
    lines.append('# 论文数据表格\n')
    lines.append('---\n')

    # ── Q1 ──
    lines.append('## Q1 结果\n')
    from q1_calculation import solve_q1
    with contextlib.redirect_stdout(None):
        ind = solve_q1()

    lines.append('### 表1: 日累计电量\n')
    lines.append('| 指标 | 数值 (MWh) |')
    lines.append('|------|-----------|')
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
    alkel_om = ind['E_alkel'] * 100
    pemel_om = ind['E_pemel'] * 150
    amm_om = ind['E_ammonia'] * 2
    lines.append(f'| 碱性电解槽运维费 | {alkel_om:.2f} |')
    lines.append(f'| PEM电解槽运维费 | {pemel_om:.2f} |')
    lines.append(f'| 合成氨运维费 | {amm_om:.2f} |')
    lines.append(f'| 售电收益 $R_{{\\text{{sell}}}}$ | -{ind["rev_sell"]:.2f} |')
    lines.append(f'| 总运营成本 $C_{{\\text{{total}}}}$ | {ind["ton_cost"]*36:.2f} |')
    lines.append(f'| **吨氨成本** | **{ind["ton_cost"]:.2f}** 元/吨 |')
    lines.append('')

    # ── Q2(1) ──
    lines.append('## Q2 结果\n')
    lines.append('### 【Q2(1)】表4: 典型场景各产量最优调度结果\n')
    lines.append('| 日产量(t) | 开机小时 | 吨氨成本(¥/t) | $\\eta_{self}$ | $\\eta_{green}$ | $\\eta_{sell}$ |')
    lines.append('|-----------|---------|-------------|:-------------:|:--------------:|:------------:|')
    for i, tgt in enumerate(PRODUCTION_LEVELS):
        c, e1, e2, e3 = typical[i]
        h = int(tgt // NH3_PER_HOUR)
        lines.append(f'| {tgt} | {h}h | {c:.2f} | {e1*100:.2f}% | {e2*100:.2f}% | {e3*100:.2f}% |')
    lines.append('')
    lines.append(f'**最优日产量**: {PRODUCTION_LEVELS[np.argmin([t[0] for t in typical])]} t/d\n')
    lines.append('')

    # ── Q2(2) ──
    lines.append('### 【Q2(2)】表5: 24场景绿电指标统计与成本分布\n')
    lines.append('**（a）绿电指标达标情况**\n')
    lines.append('| 产量 (t/d) | 全满足 | 部分满足 | 全不满足 | 平均成本 (¥/t) |')
    lines.append('|:----------:|:------:|:--------:|:--------:|:--------------:|')
    for t in PRODUCTION_LEVELS:
        ok_list = all_indicators[t]
        full = sum(1 for v in ok_list if v == 3)
        none = sum(1 for v in ok_list if v == 0)
        part = len(ok_list) - full - none
        s = all_stats[t]
        lines.append(f'| {t} | {full} | {part} | {none} | {s["mean"]:.2f}±{s["std"]:.2f} |')
    lines.append('')

    lines.append('**（b）全年吨氨成本分布**\n')
    lines.append('| 统计量 | 值 (¥/t) |')
    lines.append('|--------|----------|')
    all_vals = np.concatenate([all_costs[t] for t in PRODUCTION_LEVELS])
    lines.append(f'| 均值 | {all_vals.mean():.2f} |')
    lines.append(f'| 标准差 | {all_vals.std():.2f} |')
    lines.append(f'| 最小值 | {all_vals.min():.2f} |')
    lines.append(f'| 最大值 | {all_vals.max():.2f} |')
    lines.append(f'| P25 | {np.percentile(all_vals, 25):.2f} |')
    lines.append(f'| P75 | {np.percentile(all_vals, 75):.2f} |')
    lines.append('')
    lines.append('**说明**：产量越高，全满足绿电指标的场景数越多，但平均成本也越高。')
    lines.append('成本标准差随产量降低而增大，反映低产量场景下成本波动更大。\n')

    text = '\n'.join(lines)
    (OUT / 'paper_tables.md').write_text(text, encoding='utf-8')
    print('[Saved] results/paper_tables.md')


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    P_load = load_typical_load()
    P_w, P_s = load_typical_wind_solar()

    print('=' * 50)
    print('Computing all data from model...')
    print('=' * 50)

    print('  Q2(1) typical scenario...')
    typical = _run_typical()

    print('  Q2(2) 24 scenarios...')
    all_costs, all_stats, all_indicators = _run_24()

    print()
    print('=' * 50)
    print('Generating figures...')
    print('=' * 50)

    fig_q2_bar_cost(typical)
    fig_q2_delta_sorted(P_w, P_s, P_load)
    fig_q2_heatmap(P_w, P_s, P_load)
    fig_q2_boxplot(all_costs)
    fig_q2_indicator_stacked(all_indicators, all_stats)

    print()
    print('=' * 50)
    print('Generating tables...')
    print('=' * 50)
    export_tables(all_costs, all_stats, all_indicators, typical)

    print()
    print('Done! All figures and tables from model.')
