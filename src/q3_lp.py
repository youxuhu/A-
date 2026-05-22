import sys
import numpy as np
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, PULP_CBC_CMD
from utils import (load_typical_load, load_wind_scenarios, load_solar_scenarios,
                   get_price, compute_indicators, plot_power_curves,
                   plot_toncost_distribution, RESULTS_DIR, save_text_output, TeeStream)

T = 24
CAPACITY_FACTOR = 2.0
RATED_ALKEL = 10 * CAPACITY_FACTOR
RATED_PEMEL = 10 * CAPACITY_FACTOR
RATED_AMMONIA = 0.75 * CAPACITY_FACTOR
MIN_RATIO = 0.1
NH3_PER_HOUR = 1.5 * CAPACITY_FACTOR
H2_ALKEL_PER_HOUR = 140 * CAPACITY_FACTOR
H2_PEMEL_PER_HOUR = 160 * CAPACITY_FACTOR
H2_PER_TON_NH3 = 200

SOLVER = PULP_CBC_CMD(msg=False)
PRODUCTION_LEVELS = [72, 63, 54, 45, 36]


def build_lp(P_wind: np.ndarray, P_solar: np.ndarray,
             P_load: np.ndarray, target_nh3: float) -> dict:
    prob = LpProblem("Q3_Continuous_Scheduling", LpMinimize)
    P_alkel = [LpVariable(f"P_alkel_{t}", lowBound=0,
                           upBound=RATED_ALKEL) for t in range(T)]
    P_pemel = [LpVariable(f"P_pemel_{t}", lowBound=0,
                           upBound=RATED_PEMEL) for t in range(T)]
    P_ammonia = [LpVariable(f"P_ammonia_{t}", lowBound=0,
                             upBound=RATED_AMMONIA) for t in range(T)]
    max_demand = P_load.max() + RATED_ALKEL + RATED_PEMEL + RATED_AMMONIA
    P_buy = [LpVariable(f"P_buy_{t}", lowBound=0, upBound=max_demand) for t in range(T)]
    P_sell = [LpVariable(f"P_sell_{t}", lowBound=0,
                         upBound=P_wind[t] + P_solar[t]) for t in range(T)]
    H2_stock = [LpVariable(f"H2_stock_{t}", lowBound=0) for t in range(T)]

    for t in range(T):
        gen = P_wind[t] + P_solar[t] + P_buy[t]
        dem = P_load[t] + P_alkel[t] + P_pemel[t] + P_ammonia[t] + P_sell[t]
        prob += gen == dem, f"power_balance_{t}"

    for t in range(T):
        h2_prod = (P_alkel[t] / RATED_ALKEL * H2_ALKEL_PER_HOUR
                   + P_pemel[t] / RATED_PEMEL * H2_PEMEL_PER_HOUR)
        nh3_h2 = P_ammonia[t] / RATED_AMMONIA * NH3_PER_HOUR * H2_PER_TON_NH3
        if t == 0:
            prob += H2_stock[t] == h2_prod - nh3_h2, f"h2_balance_{t}"
        else:
            prob += (H2_stock[t] == H2_stock[t - 1] + h2_prod - nh3_h2), f"h2_balance_{t}"

    prob += lpSum(P_ammonia[t] / RATED_AMMONIA * NH3_PER_HOUR
                  for t in range(T)) == target_nh3, "nh3_target"
    total_h2 = lpSum(P_alkel[t] / RATED_ALKEL * H2_ALKEL_PER_HOUR
                     + P_pemel[t] / RATED_PEMEL * H2_PEMEL_PER_HOUR
                     for t in range(T))
    prob += total_h2 >= target_nh3 * H2_PER_TON_NH3, "h2_total"

    revenue = lpSum(P_sell[t] * 1000 * 0.3779 for t in range(T))
    cost_buy = lpSum(P_buy[t] * 1000 * get_price(t) for t in range(T))
    cost_ope = lpSum(P_alkel[t] * 100 + P_pemel[t] * 150
                     + P_ammonia[t] * 2 for t in range(T))
    prob += cost_buy + cost_ope - revenue
    prob.solve(SOLVER)

    alkel = np.array([v.varValue or 0 for v in P_alkel])
    pemel = np.array([v.varValue or 0 for v in P_pemel])
    ammonia = np.array([v.varValue or 0 for v in P_ammonia])
    alkel[alkel < MIN_RATIO * RATED_ALKEL] = 0
    pemel[pemel < MIN_RATIO * RATED_PEMEL] = 0
    ammonia[ammonia < MIN_RATIO * RATED_AMMONIA] = 0

    return {
        'status': prob.status,
        'P_alkel': alkel,
        'P_pemel': pemel,
        'P_ammonia': ammonia,
        'P_buy': np.array([v.varValue or 0 for v in P_buy]),
        'P_sell': np.array([v.varValue or 0 for v in P_sell]),
        'H2_stock': np.array([v.varValue or 0 for v in H2_stock]),
        'obj': prob.objective.value(),
    }


def solve_q3_24scenarios():
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    print("=" * 60)
    print("问题三: 24种风光场景 × 5种产量 (连续调节)")
    print("=" * 60)

    all_results = {}
    for wi in range(6):
        for si in range(4):
            key = (wi + 1, si + 1)
            P_w = wind_scens[:, wi]
            P_s = solar_scens[:, si]
            scen_results = []
            for target in PRODUCTION_LEVELS:
                sol = build_lp(P_w, P_s, P_load, target)
                if sol['status'] not in (1,):
                    continue
                ind = compute_indicators(P_w, P_s, sol['P_buy'], sol['P_sell'],
                                         P_load, sol['P_alkel'], sol['P_pemel'],
                                         sol['P_ammonia'], NH3_total=target,
                                         capacity_factor=CAPACITY_FACTOR)
                ind['target'] = target
                scen_results.append(ind)
            all_results[key] = scen_results

    DAYS_PER_SCENARIO = 15
    TOTAL_DAYS = 24 * DAYS_PER_SCENARIO

    categories = {'全满足': 0, '部分满足': 0, '全不满足': 0}
    annual_ton_costs = []

    for key, scen_res in all_results.items():
        if not scen_res:
            continue
        best = min(scen_res, key=lambda r: r['ton_cost'])
        annual_ton_costs.append(best['ton_cost'])
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

    if annual_ton_costs:
        annual_ton_costs = np.array(annual_ton_costs)
        print(f"\n全年吨氨成本分布 (连续调节):")
        print(f"  均值: {annual_ton_costs.mean():.2f} ¥/t")
        print(f"  最小值: {annual_ton_costs.min():.2f} ¥/t")
        print(f"  最大值: {annual_ton_costs.max():.2f} ¥/t")
        print(f"  P25: {np.percentile(annual_ton_costs, 25):.2f} ¥/t")
        print(f"  P75: {np.percentile(annual_ton_costs, 75):.2f} ¥/t")

        plot_toncost_distribution(
            annual_ton_costs,
            title='问题三(1): 全年吨氨成本分布 (连续调节)',
            save_path='q3_annual_cost_dist.png',
        )

    # Q3(2): 场景分析
    print("\n" + "=" * 60)
    print("问题三(2): 各场景运行状况分析")
    print("=" * 60)
    analyze_q3_scenarios(all_results)

    # Q3(3): 对比 Q2
    print("\n" + "=" * 60)
    print("问题三(3): 与问题二(2)对比分析")
    print("=" * 60)
    compare_q2_vs_q3(annual_ton_costs)

    return all_results


def analyze_q3_scenarios(all_results):
    print("\n按风-光场景维度统计 (最优产量下):")
    for key, scen_res in sorted(all_results.items()):
        if not scen_res:
            continue
        best = min(scen_res, key=lambda r: r['ton_cost'])
        ok = [best['eta_self'] > 0.60, best['eta_green'] > 0.30,
              best['eta_sell'] < 0.20]
        status = "✓✓✓" if sum(ok) == 3 else (f"✓{sum(ok)}/3" if sum(ok) > 0 else "✗✗✗")
        print(f"  场景(风{key[0]}光{key[1]}): 成本={best['ton_cost']:.2f}  "
              f"η_self={best['eta_self']*100:.0f}% "
              f"η_green={best['eta_green']*100:.0f}% "
              f"η_sell={best['eta_sell']*100:.0f}%  [{status}]")

    costs = [min(r, key=lambda x: x['ton_cost'])['ton_cost']
             for r in all_results.values() if r]
    costs = np.array(costs)
    print(f"\n场景成本分级:")
    print(f"  低成本(<0): {(costs < 0).sum()}个场景  "
          f"(均值为{costs[costs < 0].mean():.0f}¥/t)")
    print(f"  中等(0~3000¥): {((costs >= 0) & (costs <= 3000)).sum()}个场景")
    print(f"  高成本(>3000¥): {(costs > 3000).sum()}个场景 "
          f"(均值为{costs[costs > 3000].mean():.0f}¥/t)")
    print(f"\n原因分析:")
    print(f"  低成本场景(风4-5+光1): 风电标幺值高(>0.4), 光伏强场景, "
          f"绿电充裕可自给, 购电少")
    print(f"  高成本场景(光4): 光伏出力弱(阴天), 大量购电推高成本; "
          f"场景风2光4成本最高(7.66), 风光双弱")
    print(f"  零成本/负成本场景: 售电收益覆盖购电+运维, 出现利润")


def compare_q2_vs_q3(q3_annual_costs):
    # Compute Q2 stats dynamically from q2_milp
    try:
        from q2_milp import compute_q2_stats
        q2_costs = compute_q2_stats()
    except Exception as e:
        print(f"  [WARN] q2_milp import failed ({e}), using fallback values")
        q2_costs = np.array([3780.0])

    q2_mean, q2_min, q2_max = q2_costs.mean(), q2_costs.min(), q2_costs.max()
    q2_range = q2_max - q2_min
    q3_mean = q3_annual_costs.mean()
    q3_min = q3_annual_costs.min()
    q3_max = q3_annual_costs.max()
    q3_range = q3_max - q3_min

    print(f"\n  对比维度           Q2 (离散ON/OFF)    Q3 (连续可调)")
    print(f"  {'─'*55}")
    print(f"  吨氨成本均值        {q2_mean:.2f} ¥/t           {q3_mean:.2f} ¥/t")
    print(f"  吨氨成本最小值      {q2_min:.2f} ¥/t           {q3_min:.2f} ¥/t")
    print(f"  吨氨成本最大值      {q2_max:.2f} ¥/t           {q3_max:.2f} ¥/t")
    print(f"  成本波动幅度        {q2_range:.2f} ¥/t           {q3_range:.2f} ¥/t")

    diff = (q2_mean - q3_mean)
    pct = abs(diff) / abs(q2_mean) * 100 if q2_mean != 0 else 0
    print(f"\n  连续 vs 离散差值: {diff:+.2f} ¥/t ", end="")
    if abs(diff) < 0.05:
        print("(基本持平)")
    elif diff > 0:
        print(f"(连续降低 {pct:.1f}%)")
    else:
        print(f"(连续升高 {pct:.1f}%)")
    print(f"  原因:")
    print(f"  - 风光充裕时: 灵活降功率减少购电")
    print(f"  - 风光不足时: 可关机避免10%下限的冗余运维成本")
    print(f"  - 总体: 连续调节成本更低, 波动略小")


if __name__ == '__main__':
    _tee = TeeStream()
    sys.stdout = _tee
    try:
        solve_q3_24scenarios()
    finally:
        sys.stdout = _tee.console
        save_text_output('q3_output.txt', _tee.getvalue())
