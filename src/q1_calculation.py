import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from utils import (
    load_typical_load, load_typical_wind_solar,
    compute_indicators, RESULTS_DIR, save_text_output, TeeStream,
    RATED_ALKEL, RATED_PEMEL, RATED_AMMONIA, TOU_SCHEDULE,
)

T = 24
LABELS = ['风电', '光伏', '常规负荷', '电解槽', '合成氨', '总负荷', '总发电',
          '购电', '售电', '碱性电解槽', 'PEM电解槽']
COLORS = ['#2E86AB', '#F18F01', '#333333', '#8963BA', '#7F7F7F',
          '#C73E1D', '#3B8C6E', '#E56399', '#88CC88']


def _shade_price(ax):
    for t in range(T):
        p = TOU_SCHEDULE[t]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax.axvspan(t - 0.5, t + 0.5, color=c, alpha=0.06, lw=0)
    from matplotlib.patches import Patch
    leg = [Patch(color='red', alpha=0.10, label='峰'),
           Patch(color='green', alpha=0.06, label='平'),
           Patch(facecolor='gray', alpha=0.03, label='谷')]
    return leg


def _finish_ax(ax, ylabel, title):
    ax.set_xlabel('时段 (h)')
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.set_xticks(range(T))
    ax.set_xticklabels([f'{h}:00' for h in range(T)], rotation=45, fontsize=7)
    ax.grid(True, alpha=0.25, linestyle=':')
    ax.set_xlim(-0.5, 23.5)


def plot_q1_figures(P_wind, P_solar, P_load, P_buy, P_sell,
                    P_alkel, P_pemel, P_ammonia, ind):
    t = np.arange(T)
    P_total_load = P_load + P_alkel + P_pemel + P_ammonia
    P_total_gen = P_wind + P_solar

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # ── 图1: 负荷分解 (常数设备) ──
    ax1 = axes[0, 0]
    ax1.fill_between(t, 0, P_load, label='常规电负荷', color='#333333', alpha=0.5)
    ax1.fill_between(t, P_load, P_load + P_alkel + P_pemel, label='电解槽 (ALKEL+PEMEL)', color='#8963BA', alpha=0.4)
    ax1.fill_between(t, P_load + P_alkel + P_pemel, P_total_load, label='合成氨', color='#7F7F7F', alpha=0.4)
    ax1.plot(t, P_total_load, 'k-', linewidth=1.5, label='总负荷')
    _finish_ax(ax1, '功率 (MW)', '图1: 负荷分解 (耗电侧)')
    ax1.legend(fontsize=7, ncol=2, loc='upper right')

    # ── 图2: 发电分解 (独立曲线) ──
    ax2 = axes[0, 1]
    ax2.fill_between(t, 0, P_wind, color='#2E86AB', alpha=0.12)
    ax2.fill_between(t, 0, P_solar, color='#F18F01', alpha=0.12)
    ax2.plot(t, P_wind, 'o-', color='#2E86AB', linewidth=1.5, markersize=4, label='风电')
    ax2.plot(t, P_solar, 's-', color='#F18F01', linewidth=1.5, markersize=4, label='光伏')
    ax2.plot(t, P_total_gen, '^--', color='#C73E1D', linewidth=2, markersize=5, label='总发电')
    _finish_ax(ax2, '功率 (MW)', '图2: 发电分解 (产电侧)')
    ax2.legend(fontsize=7, loc='upper right')

    # ── 图3: 供需对比 ──
    ax3 = axes[1, 0]
    ax3.plot(t, P_total_load, 's-', color='#C73E1D', linewidth=2, markersize=4, label='总负荷')
    ax3.plot(t, P_total_gen, 'o-', color='#3B8C6E', linewidth=2, markersize=4, label='总发电')
    deficit = np.maximum(0, P_total_load - P_total_gen)
    surplus = np.maximum(0, P_total_gen - P_total_load)
    ax3.fill_between(t, 0, deficit, where=(deficit > 0), color='red', alpha=0.15, label='缺电')
    ax3.fill_between(t, 0, surplus, where=(surplus > 0), color='green', alpha=0.15, label='余电')
    _finish_ax(ax3, '功率 (MW)', '图3: 总负荷 vs 总发电 (供需对比)')
    ax3.legend(fontsize=7, loc='upper right')

    # ── 图4: 购电与售电 ──
    ax4 = axes[1, 1]
    ax4.bar(t - 0.15, P_buy, width=0.3, color='#E56399', alpha=0.8, label='购电')
    ax4.bar(t + 0.15, P_sell, width=0.3, color='#88CC88', alpha=0.8, label='售电')
    _finish_ax(ax4, '功率 (MW)', '图4: 购电与售电功率')
    ax4.legend(fontsize=7, loc='upper right')

    fig.suptitle('问题一: 满负荷运行功率平衡 (36 t/d 基础产能)', fontsize=14, fontweight='bold', y=1.02)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = str(RESULTS_DIR / 'q1_power_curves_4panel.png')
    fig.savefig(path, dpi=180, bbox_inches='tight', pad_inches=0.3)
    plt.close(fig)
    print(f"[Saved] {path}")


def solve_q1():
    P_load = load_typical_load()
    P_wind, P_solar = load_typical_wind_solar()

    P_alkel = np.full(T, RATED_ALKEL)
    P_pemel = np.full(T, RATED_PEMEL)
    P_ammonia = np.full(T, RATED_AMMONIA)

    balance = P_wind + P_solar - P_load - P_alkel - P_pemel - P_ammonia
    P_buy = np.maximum(0, -balance)
    P_sell = np.maximum(0, balance)

    ind = compute_indicators(
        P_wind, P_solar, P_buy, P_sell,
        P_load, P_alkel, P_pemel, P_ammonia,
        NH3_total=36.0, capacity_factor=1.0,
        include_depreciation=False,
        include_renewable_cost=True,
    )

    print("=" * 60)
    print("问题一: 典型风光场景下满负荷运行指标")
    print("=" * 60)
    # ── 电量 ──
    print(f"\n{'─'*50}")
    print("日累计电量")
    print(f"{'─'*50}")
    print(f"  总用电量 (E_total_used):         {ind['E_total_used']:>8.2f} MWh")
    print(f"  新能源发电量 (E_renewable):      {ind['E_renewable']:>8.2f} MWh  (风电 {ind['E_wind']:.2f} + 光伏 {ind['E_solar']:.2f})")
    print(f"  网购电量 (E_buy):                {ind['E_buy']:>8.2f} MWh")
    print(f"  上网电量 (E_sell):               {ind['E_sell']:>8.2f} MWh")
    print(f"  常规负荷: {ind['E_load']:.2f} MWh  "
          f"ALKEL={ind['E_alkel']:.0f} MWh  PEMEL={ind['E_pemel']:.0f} MWh  "
          f"NH₃={ind['E_ammonia']:.2f} MWh")

    # ── 绿电指标 ──
    ok_self = ind['eta_self'] > 0.60
    ok_green = ind['eta_green'] > 0.30
    ok_sell = ind['eta_sell'] < 0.20
    print(f"\n{'─'*50}")
    print("绿电直连指标")
    print(f"{'─'*50}")
    print(f"  η_self (自发自用率)  = {ind['eta_self']*100:>5.2f}%  (要求 > 60%)  {'✓' if ok_self else '✗'}")
    print(f"  η_green (绿电比例)   = {ind['eta_green']*100:>5.2f}%  (要求 > 30%)  {'✓' if ok_green else '✗'}")
    print(f"  η_sell (上网比例)    = {ind['eta_sell']*100:>5.2f}%  (要求 < 20%)  {'✓' if ok_sell else '✗'}")

    # ── 成本 ──
    print(f"\n{'─'*50}")
    print("吨氨成本（运营成本，不含设备折旧）")
    print(f"{'─'*50}")
    print(f"  购电费:                      {ind['cost_buy']:>10.2f} ¥")
    print(f"  新能源总发电成本:            {ind['renewable_gen_cost']:>10.2f} ¥")
    print(f"  电解槽运维费:                {ind['ope_cost']:>10.2f} ¥")
    print(f"  合成氨运维费:                {ind['E_ammonia']*1000*0.002:>10.2f} ¥")
    print(f"  售电收益:                   {ind['rev_sell']:>10.2f} ¥")
    print(f"  ──────────────────────────────")
    print(f"  总运营成本:                  {ind['ton_cost']*36:>10.2f} ¥")
    print(f"  吨氨成本:                    {ind['ton_cost']:>10.2f} ¥/t")

    # ── 达标分析 ──
    print(f"\n{'─'*50}")
    print("指标达标分析")
    print(f"{'─'*50}")
    if not ok_self:
        print(f"  η_self = {ind['eta_self']*100:.2f}% < 60%")
        print(f"    满负荷用电仅 {ind['E_total_used']:.0f} MWh，绿电 {ind['E_renewable']:.0f} MWh，")
        print(f"    大量绿电上网导致自发自用率不足")
    if not ok_green:
        print(f"  η_green = {ind['eta_green']*100:.2f}% < 30%")
        print(f"    总用电中可再生能源比例不足（因网购电过多）")
    if not ok_sell:
        print(f"  η_sell = {ind['eta_sell']*100:.2f}% > 20%")
        print(f"    上网电量 {ind['E_sell']:.0f} MWh / 新能源发电 {ind['E_renewable']:.0f} MWh")
        print(f"    午间光伏大发时段负荷消纳能力不足")

    # ── 绘图 ──
    plot_q1_figures(P_wind, P_solar, P_load, P_buy, P_sell,
                    P_alkel, P_pemel, P_ammonia, ind)
    plot_q1_indicators(ind)

    return ind


def plot_q1_indicators(ind):
    fig, axes = plt.subplots(1, 3, figsize=(12, 2.5))
    items = [
        ('新能源自发自用率 $\\eta_{self}$', ind['eta_self'] * 100, 60, '>'),
        ('总用电量绿电比例 $\\eta_{green}$', ind['eta_green'] * 100, 30, '>'),
        ('新能源上网电量比例 $\\eta_{sell}$', ind['eta_sell'] * 100, 20, '<'),
    ]
    for ax, (name, val, thresh, direction) in zip(axes, items):
        passed = (val > thresh) if direction == '>' else (val < thresh)
        color = '#3B8C6E' if passed else '#C73E1D'
        ax.barh(0, 100, color='gray', alpha=0.25, height=0.7, label='100%')
        ax.barh(0, min(val, 100), color=color, alpha=0.85, height=0.7)
        ax.axvline(thresh, color='black', linestyle='--', linewidth=1.5)
        ax.text(thresh, 0.6, f'{thresh}%', ha='center', fontsize=8,
                bbox=dict(facecolor='white', edgecolor='none', pad=1))
        ax.set_xlim(0, 100)
        ax.set_ylim(-0.8, 0.8)
        ax.set_yticks([])
        ax.set_title(f'{name}\n{val:.1f}%',
                     fontsize=10, color='#333333')
        ax.set_xlabel('比例 (%)' if ax == axes[-1] else '', fontsize=8)
        ax.tick_params(labelsize=7)
    fig.suptitle('绿电直连指标达标情况（问题一 满负荷运行）', fontsize=13, y=1.08)
    fig.tight_layout()
    path = str(RESULTS_DIR / 'q1_green_indicators.png')
    fig.savefig(path, dpi=180, bbox_inches='tight', pad_inches=0.3)
    plt.close(fig)
    print(f"[Saved] {path}")


if __name__ == '__main__':
    _tee = TeeStream()
    sys.stdout = _tee
    try:
        solve_q1()
    finally:
        sys.stdout = _tee.console
        save_text_output('q1_output.txt', _tee.getvalue())
