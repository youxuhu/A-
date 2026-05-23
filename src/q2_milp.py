import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from utils import (load_typical_load, load_typical_wind_solar,
                   load_wind_scenarios, load_solar_scenarios,
                   get_price, compute_indicators,
                   plot_toncost_distribution, save_text_output, TeeStream,
                   RESULTS_DIR, TOU_SCHEDULE, FEED_IN_PRICE)

T = 24
CAPACITY_FACTOR = 2.0
RATED_ALKEL = 10 * CAPACITY_FACTOR       # 20 MW
RATED_PEMEL = 10 * CAPACITY_FACTOR       # 20 MW
RATED_AMMONIA = 0.75 * CAPACITY_FACTOR   # 1.5 MW
NH3_PER_HOUR = 1.5 * CAPACITY_FACTOR     # 3.0 t/h
H2_ALKEL_PER_HOUR = 140 * CAPACITY_FACTOR
H2_PEMEL_PER_HOUR = 160 * CAPACITY_FACTOR
H2_PER_TON_NH3 = 200

PRODUCTION_LEVELS = [72, 63, 54, 45, 36]

# Action table: 8 actions (ALKEL, PEMEL, NH3) ON/OFF.
# Each entry: (x_alkel, x_pemel, x_ammonia, n_inc, h_inc)
# n_inc = NH3 produced / 3.0 (quantized to integer 0 or 1)
# h_inc = H2 produced / 40  (quantized, 280=7, 320=8, 600=15)

H2_STEP = 40  # kg per H2 index unit

ACTIONS = []
for a in range(8):
    xa = (a >> 2) & 1
    xp = (a >> 1) & 1
    xm = a & 1
    n_inc = xm           # 3.0 t/h per NH3_PER_HOUR → index step
    h_inc = int((xa * H2_ALKEL_PER_HOUR + xp * H2_PEMEL_PER_HOUR) // H2_STEP)
    ACTIONS.append((xa, xp, xm, n_inc, h_inc))


def _step_cost_and_bs(pw, ps, pl, xa, xp, xm, price):
    p_alkel = xa * RATED_ALKEL
    p_pemel = xp * RATED_PEMEL
    p_nh3 = xm * RATED_AMMONIA
    bal = pw + ps - pl - p_alkel - p_pemel - p_nh3
    om = p_alkel * 100 + p_pemel * 150 + p_nh3 * 2

    if bal >= 0:
        P_buy = 0.0
        P_sell = bal
    else:
        P_buy = -bal
        P_sell = 0.0
    cost = P_buy * 1000 * price - P_sell * 1000 * FEED_IN_PRICE + om
    return cost, P_buy, P_sell


def build_dp(P_wind, P_solar, P_load, target_nh3):
    N_MAX = int(target_nh3 // NH3_PER_HOUR)
    H_TARGET = int(target_nh3 * H2_PER_TON_NH3 // H2_STEP)
    H_MAX = H_TARGET + 15

    INF = 1e20

    # Precompute step cost and associated buy/sell for each (t, action)
    step_cost = np.zeros((T, 8), dtype=np.float64)
    buy_sell = np.zeros((T, 8, 2), dtype=np.float64)
    for t in range(T):
        pw, ps, pl = P_wind[t], P_solar[t], P_load[t]
        pr = get_price(t)
        for a in range(8):
            xa, xp, xm, _, _ = ACTIONS[a]
            c, pb, ps_val = _step_cost_and_bs(pw, ps, pl, xa, xp, xm, pr)
            step_cost[t, a] = c
            buy_sell[t, a, 0] = pb
            buy_sell[t, a, 1] = ps_val

    # DP tables: store cost (float) as 2D rolling, prev (packed) as 3D
    N_STATES = N_MAX + 1
    H_STATES = H_MAX + 1
    cost = np.full((N_STATES, H_STATES), INF, dtype=np.float64)
    prev = np.zeros((T, N_STATES, H_STATES), dtype=np.int32)

    # t=0 initialization
    for a in range(8):
        _, _, _, ni, hi = ACTIONS[a]
        if ni > N_MAX or hi > H_MAX:
            continue
        if step_cost[0, a] < cost[ni, hi]:
            cost[ni, hi] = step_cost[0, a]
            prev[0, ni, hi] = a  # pack: just action, prev_n=prev_h=0

    # t = 1..23
    for t in range(1, T):
        new_cost = np.full((N_STATES, H_STATES), INF, dtype=np.float64)
        new_prev = np.zeros((N_STATES, H_STATES), dtype=np.int32)
        for a in range(8):
            _, _, _, ni, hi = ACTIONS[a]
            if ni > N_MAX or hi > H_MAX:
                continue
            step = step_cost[t, a]
            # Slide over previous states
            for n in range(N_STATES - ni):
                for h in range(H_STATES - hi):
                    prev_val = cost[n, h]
                    if prev_val >= INF / 2:
                        continue
                    val = prev_val + step
                    nn = n + ni
                    hh = h + hi
                    if val < new_cost[nn, hh]:
                        new_cost[nn, hh] = val
                        new_prev[nn, hh] = a | (n << 3) | (h << 8)
        cost = new_cost
        prev[t] = new_prev

    # Extract optimal: min cost at N_MAX, H >= H_TARGET
    best_cost = INF
    best_h = -1
    for h in range(H_TARGET, H_STATES):
        if cost[N_MAX, h] < best_cost:
            best_cost = cost[N_MAX, h]
            best_h = h

    if best_cost >= INF / 2:
        return {'status': -1, 'obj': best_cost}

    # Backtrack to get schedule
    x_alkel = np.zeros(T, dtype=int)
    x_pemel = np.zeros(T, dtype=int)
    x_ammonia = np.zeros(T, dtype=int)
    P_buy = np.zeros(T)
    P_sell = np.zeros(T)

    cn, ch = N_MAX, best_h
    for t in reversed(range(T)):
        packed = prev[t, cn, ch]
        if t == 0:
            a = packed
        else:
            a = packed & 0x7
            cn = (packed >> 3) & 0x1F
            ch = (packed >> 8) & 0x3FF

        xa, xp, xm, _, _ = ACTIONS[a]
        x_alkel[t] = xa
        x_pemel[t] = xp
        x_ammonia[t] = xm
        P_buy[t] = buy_sell[t, a, 0]
        P_sell[t] = buy_sell[t, a, 1]

    return {
        'status': 1,
        'x_alkel': x_alkel,
        'x_pemel': x_pemel,
        'x_ammonia': x_ammonia,
        'P_buy': P_buy,
        'P_sell': P_sell,
        'obj': best_cost,
    }


build_milp = build_dp


def calc_utilization(sol: dict):
    return {
        'ALKEL': sol['x_alkel'].sum() / T * 100,
        'PEMEL': sol['x_pemel'].sum() / T * 100,
        'NH3': sol['x_ammonia'].sum() / T * 100,
    }


def _shade_price(ax):
    for t in range(24):
        p = TOU_SCHEDULE[t]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax.axvspan(t - 0.5, t + 0.5, color=c, alpha=0.06, lw=0)


def _finish_ax(ax, ylabel, title):
    ax.set_xlabel('时段 (h)')
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11, fontweight='bold')
    ax.set_xticks(range(24))
    ax.set_xticklabels([f'{h}:00' for h in range(24)], rotation=45, fontsize=7)
    ax.grid(True, alpha=0.25, linestyle=':')
    ax.set_xlim(-0.5, 23.5)


def plot_q2_figures(P_wind, P_solar, P_load, P_buy, P_sell,
                    P_alkel, P_pemel, P_ammonia, ind, target):
    t = np.arange(24)
    P_total_load = P_load + P_alkel + P_pemel + P_ammonia
    P_total_gen = P_wind + P_solar

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    ax1 = axes[0, 0]
    ax1.fill_between(t, 0, P_load, label='常规电负荷', color='#333333', alpha=0.6)
    bottom = P_load.copy()
    if P_alkel.sum() > 0:
        ax1.fill_between(t, bottom, bottom + P_alkel, label='ALKEL', color='#8963BA', alpha=0.5, step='mid')
        bottom += P_alkel
    if P_pemel.sum() > 0:
        ax1.fill_between(t, bottom, bottom + P_pemel, label='PEMEL', color='#E56399', alpha=0.5, step='mid')
        bottom += P_pemel
    if P_ammonia.sum() > 0:
        ax1.fill_between(t, bottom, bottom + P_ammonia, label='合成氨', color='#7F7F7F', alpha=0.5, step='mid')
    ax1.plot(t, P_total_load, 'k-', linewidth=1.5, label='总负荷', drawstyle='steps-mid')
    on_h = f"ALKEL={int((P_alkel>0).sum())}h  PEMEL={int((P_pemel>0).sum())}h  NH₃={int((P_ammonia>0).sum())}h"
    ax1.text(0.98, 0.02, on_h, transform=ax1.transAxes, fontsize=7,
             ha='right', va='bottom', color='#555555',
             bbox=dict(facecolor='white', alpha=0.7, pad=2))
    _finish_ax(ax1, '功率 (MW)', '图1: 负荷分解 (离散 ON/OFF)')
    ax1.legend(fontsize=7, ncol=2, loc='upper right')

    ax2 = axes[0, 1]
    ax2.fill_between(t, 0, P_wind, label='风电', color='#2E86AB', alpha=0.6)
    ax2.fill_between(t, P_wind, P_total_gen, label='光伏', color='#F18F01', alpha=0.6)
    ax2.plot(t, P_total_gen, '--', color='#3B8C6E', linewidth=1.5, label='总发电')
    _finish_ax(ax2, '功率 (MW)', '图2: 发电分解')
    ax2.legend(fontsize=7, loc='upper right')

    ax3 = axes[1, 0]
    _shade_price(ax3)
    ax3.plot(t, P_total_load, 's-', color='#C73E1D', linewidth=2, markersize=4, label='总负荷')
    ax3.plot(t, P_total_gen, 'o-', color='#3B8C6E', linewidth=2, markersize=4, label='总发电')
    deficit = np.maximum(0, P_total_load - P_total_gen)
    surplus = np.maximum(0, P_total_gen - P_total_load)
    ax3.fill_between(t, 0, deficit, where=(deficit > 0), color='red', alpha=0.12, label='缺电')
    ax3.fill_between(t, 0, surplus, where=(surplus > 0), color='green', alpha=0.12, label='余电')
    _finish_ax(ax3, '功率 (MW)', '图3: 总负荷 vs 总发电')
    ax3.legend(fontsize=7, loc='upper right')

    ax4 = axes[1, 1]
    ax4.bar(t - 0.15, P_buy, width=0.3, color='#E56399', alpha=0.8, label='购电')
    ax4.bar(t + 0.15, P_sell, width=0.3, color='#88CC88', alpha=0.8, label='售电')
    _finish_ax(ax4, '功率 (MW)', '图4: 购电与售电功率')
    ax4.legend(fontsize=7, loc='upper right')

    fig.suptitle(f'问题二(1): 最优离散调度 (氨产量={target}t/d)', fontsize=14, fontweight='bold', y=1.02)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = str(RESULTS_DIR / 'q2_typical_optimal.png')
    fig.savefig(path, dpi=180, bbox_inches='tight', pad_inches=0.3)
    plt.close(fig)
    print(f"[Saved] {path}")


def solve_q2_typical():
    P_load = load_typical_load()
    P_wind, P_solar = load_typical_wind_solar()

    print("=" * 60)
    print("问题二(1): 典型场景离散调度 - 各产量方案")
    print("=" * 60)

    results = []
    for target in PRODUCTION_LEVELS:
        sol = build_dp(P_wind, P_solar, P_load, target)
        if sol['status'] not in (1,):
            print(f"\n[日产氨 {target} t]  ⚠ 求解失败 (status={sol['status']})")
            continue
        P_alkel = sol['x_alkel'] * RATED_ALKEL
        P_pemel = sol['x_pemel'] * RATED_PEMEL
        P_ammonia = sol['x_ammonia'] * RATED_AMMONIA
        ind = compute_indicators(P_wind, P_solar, sol['P_buy'], sol['P_sell'],
                                 P_load, P_alkel, P_pemel, P_ammonia,
                                 NH3_total=target, capacity_factor=CAPACITY_FACTOR)
        util = calc_utilization(sol)
        results.append((target, sol, ind, util))

        print(f"\n[日产氨 {target} t]")
        print(f"  吨氨成本 = {ind['ton_cost']:.2f} ¥/t  (购电{ind['cost_buy']:.0f}"
              f" 运维{ind['ope_cost']:.0f} 折旧{ind['daily_depreciation']:.0f}"
              f" 售电-{ind['rev_sell']:.0f})")
        print(f"  运行: ALKEL={sol['x_alkel'].sum()}h ({util['ALKEL']:.0f}%)  "
              f"PEMEL={sol['x_pemel'].sum()}h ({util['PEMEL']:.0f}%)  "
              f"NH3={sol['x_ammonia'].sum()}h ({util['NH3']:.0f}%)")
        print(f"  η_self={ind['eta_self']*100:.1f}%  "
              f"η_green={ind['eta_green']*100:.1f}%  "
              f"η_sell={ind['eta_sell']*100:.1f}%")

    if results:
        best = min(results, key=lambda r: r[2]['ton_cost'])
        print(f"\n>>> 最优日产量: {best[0]} t, 吨氨成本 = {best[2]['ton_cost']:.2f} ¥/t")
        print(f"    设备利用率: ALKEL={best[3]['ALKEL']:.0f}%, "
              f"PEMEL={best[3]['PEMEL']:.0f}%, NH3={best[3]['NH3']:.0f}%")
        ok = [best[2]['eta_self'] > 0.60, best[2]['eta_green'] > 0.30,
              best[2]['eta_sell'] < 0.20]
        print(f"    绿电指标: {'全部达标' if all(ok) else '不达标'}"
              f" ({sum(ok)}/3)")

        _, best_sol, best_ind, _ = best
        P_alkel = best_sol['x_alkel'] * RATED_ALKEL
        P_pemel = best_sol['x_pemel'] * RATED_PEMEL
        P_ammonia = best_sol['x_ammonia'] * RATED_AMMONIA
        plot_q2_figures(
            P_wind, P_solar, P_load,
            best_sol['P_buy'], best_sol['P_sell'],
            P_alkel, P_pemel, P_ammonia, best_ind, best[0],
        )
    return results


def _run_all_scenarios():
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()
    DAYS_PER_SCENARIO = 15

    all_results = {}
    for wi in range(6):
        for si in range(4):
            key = (wi + 1, si + 1)
            P_w = wind_scens[:, wi]
            P_s = solar_scens[:, si]
            scen_results = []
            for target in PRODUCTION_LEVELS:
                sol = build_dp(P_w, P_s, P_load, target)
                if sol['status'] not in (1,):
                    continue
                P_alkel = sol['x_alkel'] * RATED_ALKEL
                P_pemel = sol['x_pemel'] * RATED_PEMEL
                P_ammonia = sol['x_ammonia'] * RATED_AMMONIA
                ind = compute_indicators(P_w, P_s, sol['P_buy'], sol['P_sell'],
                                         P_load, P_alkel, P_pemel, P_ammonia,
                                         NH3_total=target,
                                         capacity_factor=CAPACITY_FACTOR)
                scen_results.append({**ind, 'target': target,
                                     'buy_hours': (sol['P_buy'] > 0.1).sum(),
                                     'sell_hours': (sol['P_sell'] > 0.1).sum()})
            all_results[key] = scen_results

    annual_ton_costs = []
    for key, scen_res in all_results.items():
        if not scen_res:
            continue
        best = min(scen_res, key=lambda r: r['ton_cost'])
        annual_ton_costs.append(best['ton_cost'])
    return all_results, np.array(annual_ton_costs)


def compute_q2_stats():
    _, costs = _run_all_scenarios()
    return costs


def solve_q2_24scenarios():
    all_results, annual_ton_costs = _run_all_scenarios()
    DAYS_PER_SCENARIO = 15
    TOTAL_DAYS = 24 * DAYS_PER_SCENARIO

    categories = {'全满足': 0, '部分满足': 0, '全不满足': 0}
    all_buy_hours, all_sell_hours = [], []

    for key, scen_res in all_results.items():
        if not scen_res:
            continue
        best = min(scen_res, key=lambda r: r['ton_cost'])
        all_buy_hours.append(best['buy_hours'])
        all_sell_hours.append(best['sell_hours'])
        ok = [best['eta_self'] > 0.60, best['eta_green'] > 0.30,
              best['eta_sell'] < 0.20]
        n_ok = sum(ok)
        if n_ok == 3:
            categories['全满足'] += DAYS_PER_SCENARIO
        elif n_ok == 0:
            categories['全不满足'] += DAYS_PER_SCENARIO
        else:
            categories['部分满足'] += DAYS_PER_SCENARIO

    print(f"\n按最优产量统计全年指标 ({TOTAL_DAYS}天):")
    for k, v in categories.items():
        print(f"  {k}: {v}天 ({v/TOTAL_DAYS*100:.1f}%)")

    if annual_ton_costs.size > 0:
        print(f"\n全年吨氨成本分布 (离散调度):")
        print(f"  均值: {annual_ton_costs.mean():.2f} ¥/t")
        print(f"  最小值: {annual_ton_costs.min():.2f} ¥/t")
        print(f"  最大值: {annual_ton_costs.max():.2f} ¥/t")
        print(f"  P25: {np.percentile(annual_ton_costs, 25):.2f} ¥/t")
        print(f"  P75: {np.percentile(annual_ton_costs, 75):.2f} ¥/t")

        print(f"\n购电/售电分布 (各场景最优方案):")
        print(f"  购电时长: 均值={np.mean(all_buy_hours):.1f}h  "
              f"范围=[{min(all_buy_hours)}, {max(all_buy_hours)}]h")
        print(f"  售电时长: 均值={np.mean(all_sell_hours):.1f}h  "
              f"范围=[{min(all_sell_hours)}, {max(all_sell_hours)}]h")

        plot_toncost_distribution(
            annual_ton_costs,
            title='问题二(2): 全年吨氨成本分布 (离散ON/OFF)',
            save_path='q2_annual_cost_dist.png',
        )

    return all_results


if __name__ == '__main__':
    _tee = TeeStream()
    sys.stdout = _tee
    try:
        solve_q2_typical()
        solve_q2_24scenarios()
    finally:
        sys.stdout = _tee.console
        save_text_output('q2_output.txt', _tee.getvalue())
