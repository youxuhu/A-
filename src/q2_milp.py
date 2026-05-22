import sys
import numpy as np
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, PULP_CBC_CMD
from utils import (load_typical_load, load_typical_wind_solar,
                   load_wind_scenarios, load_solar_scenarios,
                   get_price, compute_indicators, plot_power_curves,
                   plot_toncost_distribution, save_text_output, TeeStream)

T = 24
CAPACITY_FACTOR = 2.0
RATED_ALKEL = 10 * CAPACITY_FACTOR
RATED_PEMEL = 10 * CAPACITY_FACTOR
RATED_AMMONIA = 0.75 * CAPACITY_FACTOR
NH3_PER_HOUR = 1.5 * CAPACITY_FACTOR
H2_ALKEL_PER_HOUR = 140 * CAPACITY_FACTOR
H2_PEMEL_PER_HOUR = 160 * CAPACITY_FACTOR
H2_PER_TON_NH3 = 200

SOLVER = PULP_CBC_CMD(msg=False)
PRODUCTION_LEVELS = [72, 63, 54, 45, 36]


def build_milp(P_wind: np.ndarray, P_solar: np.ndarray,
               P_load: np.ndarray, target_nh3: float) -> dict:
    prob = LpProblem("Q2_Discrete_Scheduling", LpMinimize)
    x_alkel = [LpVariable(f"x_alkel_{t}", cat='Binary') for t in range(T)]
    x_pemel = [LpVariable(f"x_pemel_{t}", cat='Binary') for t in range(T)]
    x_ammonia = [LpVariable(f"x_ammonia_{t}", cat='Binary') for t in range(T)]
    max_demand = P_load.max() + RATED_ALKEL + RATED_PEMEL + RATED_AMMONIA
    P_buy = [LpVariable(f"P_buy_{t}", lowBound=0, upBound=max_demand) for t in range(T)]
    P_sell = [LpVariable(f"P_sell_{t}", lowBound=0,
                         upBound=P_wind[t] + P_solar[t]) for t in range(T)]

    for t in range(T):
        gen = P_wind[t] + P_solar[t] + P_buy[t]
        dem = (P_load[t] + RATED_ALKEL * x_alkel[t]
               + RATED_PEMEL * x_pemel[t]
               + RATED_AMMONIA * x_ammonia[t] + P_sell[t])
        prob += gen == dem, f"power_balance_{t}"

    prob += lpSum(x_ammonia[t] * NH3_PER_HOUR for t in range(T)) == target_nh3, "nh3_target"
    total_h2 = lpSum(x_alkel[t] * H2_ALKEL_PER_HOUR + x_pemel[t] * H2_PEMEL_PER_HOUR
                     for t in range(T))
    prob += total_h2 >= target_nh3 * H2_PER_TON_NH3, "h2_supply"

    revenue = lpSum(P_sell[t] * 1000 * 0.3779 for t in range(T))
    cost_buy = lpSum(P_buy[t] * 1000 * get_price(t) for t in range(T))
    ope_cost = (
        lpSum(RATED_ALKEL * x_alkel[t] * 100 + RATED_PEMEL * x_pemel[t] * 150
              for t in range(T))
        + lpSum(RATED_AMMONIA * x_ammonia[t] * 2 for t in range(T))
    )
    prob += cost_buy + ope_cost - revenue
    prob.solve(SOLVER)

    return {
        'status': prob.status,
        'x_alkel': np.array([int(np.round(v.varValue or 0)) for v in x_alkel]),
        'x_pemel': np.array([int(np.round(v.varValue or 0)) for v in x_pemel]),
        'x_ammonia': np.array([int(np.round(v.varValue or 0)) for v in x_ammonia]),
        'P_buy': np.array([v.varValue or 0 for v in P_buy]),
        'P_sell': np.array([v.varValue or 0 for v in P_sell]),
        'obj': prob.objective.value(),
    }


def calc_utilization(sol: dict):
    return {
        'ALKEL': sol['x_alkel'].sum() / T * 100,
        'PEMEL': sol['x_pemel'].sum() / T * 100,
        'NH3': sol['x_ammonia'].sum() / T * 100,
    }


def solve_q2_typical():
    P_load = load_typical_load()
    P_wind, P_solar = load_typical_wind_solar()

    print("=" * 60)
    print("问题二(1): 典型场景离散调度 - 各产量方案")
    print("=" * 60)

    results = []
    for target in PRODUCTION_LEVELS:
        sol = build_milp(P_wind, P_solar, P_load, target)
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
        plot_power_curves(
            P_wind, P_solar, P_load,
            best_sol['P_buy'], best_sol['P_sell'],
            P_alkel, P_pemel, P_ammonia,
            title=f'问题二(1): 最优调度方案 (氨产量={best[0]}t/d)',
            save_path='q2_typical_optimal.png',
            ind=best_ind,
        )
    return results


def _run_all_scenarios():
    """Run all 24 scenarios × 5 targets, return all_results and annual_costs."""
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
                sol = build_milp(P_w, P_s, P_load, target)
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
    """Return Q2 annual cost stats for Q3 comparison (no print)."""
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
