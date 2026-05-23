import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pulp import LpProblem, LpMaximize, LpVariable, lpSum, PULP_CBC_CMD, value
from utils import (
    load_typical_load, load_wind_scenarios, load_solar_scenarios,
    compute_indicators, RESULTS_DIR, save_text_output, TeeStream,
    get_price, FEED_IN_PRICE, TOU_SCHEDULE,
)

T = 24
CAPACITY_FACTOR = 2.0
RATED_ALKEL = 10 * CAPACITY_FACTOR
RATED_PEMEL = 10 * CAPACITY_FACTOR
RATED_AMMONIA = 0.75 * CAPACITY_FACTOR
NH3_PER_HOUR = 1.5 * CAPACITY_FACTOR
H2_ALKEL_PER_HOUR = 140 * CAPACITY_FACTOR
H2_PEMEL_PER_HOUR = 160 * CAPACITY_FACTOR
H2_PER_TON_NH3 = 200

RATED_WIND = 40
RATED_PV = 64

STORAGE_COST_PER_KWH = 1000
STORAGE_LIFETIME_YEARS = 15
CHARGE_EFF = 0.90
DISCHARGE_EFF = 0.90
SELF_DISCHARGE = 0.002

DAYS_PER_SCENARIO = 15
TOTAL_DAYS = 24 * DAYS_PER_SCENARIO
TARGET_NH3 = 72.0

SOLVER = PULP_CBC_CMD(msg=False)


def build_q4_lp(P_wind, P_solar, P_load,
                storage_capacity=0, charge_max=0, discharge_max=0,
                target_nh3=None):
    prob = LpProblem("Q4_OffGrid", LpMaximize)

    P_alkel = [LpVariable(f"alk_{t}", 0, RATED_ALKEL) for t in range(T)]
    P_pemel = [LpVariable(f"pem_{t}", 0, RATED_PEMEL) for t in range(T)]
    P_ammonia = [LpVariable(f"am_{t}", 0, RATED_AMMONIA) for t in range(T)]
    P_curtail = [LpVariable(f"cur_{t}", 0) for t in range(T)]
    H2_stock = [LpVariable(f"h2_{t}", 0) for t in range(T)]

    has_storage = storage_capacity > 0 and charge_max > 0
    if has_storage:
        P_charge = [LpVariable(f"chg_{t}", 0, charge_max) for t in range(T)]
        P_discharge = [LpVariable(f"dch_{t}", 0, discharge_max) for t in range(T)]
        SOC = [LpVariable(f"soc_{t}", 0, storage_capacity) for t in range(T)]
    else:
        P_charge, P_discharge, SOC = [], [], []

    for t in range(T):
        gen = P_wind[t] + P_solar[t]
        dem = P_load[t] + P_alkel[t] + P_pemel[t] + P_ammonia[t] + P_curtail[t]
        if has_storage:
            gen += P_discharge[t]
            dem += P_charge[t]
        prob += gen == dem, f"pwr_{t}"

    if has_storage:
        soc0 = storage_capacity * 0.5
        prob += SOC[0] == soc0 * (1 - SELF_DISCHARGE) + P_charge[0] * CHARGE_EFF - P_discharge[0] / DISCHARGE_EFF
        for t in range(1, T):
            prob += SOC[t] == SOC[t - 1] * (1 - SELF_DISCHARGE) + P_charge[t] * CHARGE_EFF - P_discharge[t] / DISCHARGE_EFF

    for t in range(T):
        h2p = (P_alkel[t] / RATED_ALKEL * H2_ALKEL_PER_HOUR
               + P_pemel[t] / RATED_PEMEL * H2_PEMEL_PER_HOUR)
        h2c = P_ammonia[t] / RATED_AMMONIA * NH3_PER_HOUR * H2_PER_TON_NH3
        if t == 0:
            prob += H2_stock[t] == h2p - h2c
        else:
            prob += H2_stock[t] == H2_stock[t - 1] + h2p - h2c

    total_nh3 = lpSum(P_ammonia[t] / RATED_AMMONIA * NH3_PER_HOUR for t in range(T))
    if target_nh3 is not None:
        prob += total_nh3 >= target_nh3
    prob += total_nh3

    prob.solve(SOLVER)

    def _safe(arr):
        return np.array([v.varValue or 0 for v in arr])

    return {
        'status': prob.status,
        'P_alkel': _safe(P_alkel),
        'P_pemel': _safe(P_pemel),
        'P_ammonia': _safe(P_ammonia),
        'curtail': _safe(P_curtail),
        'H2_stock': _safe(H2_stock),
        'NH3_total': value(total_nh3) or 0,
        'SOC': _safe(SOC) if has_storage else np.zeros(T),
        'P_charge': _safe(P_charge) if has_storage else np.zeros(T),
        'P_discharge': _safe(P_discharge) if has_storage else np.zeros(T),
    }


def _solve_one_scn(P_w, P_s, P_load, storage_capacity=0, charge_max=0, discharge_max=0):
    sol = build_q4_lp(P_w, P_s, P_load, storage_capacity, charge_max, discharge_max, target_nh3=TARGET_NH3)
    if sol['status'] != 1:
        sol = build_q4_lp(P_w, P_s, P_load, storage_capacity, charge_max, discharge_max)
    if sol['status'] != 1:
        return None
    return sol


def _calc_indicators(P_w, P_s, P_load, sol, storage_capacity=0):
    P_buy = np.zeros(T)
    P_sell = np.zeros(T)

    ind = compute_indicators(
        P_w, P_s, P_buy, P_sell,
        P_load, sol['P_alkel'], sol['P_pemel'], sol['P_ammonia'],
        NH3_total=max(sol['NH3_total'], 0.1),
        capacity_factor=CAPACITY_FACTOR,
    )

    actual_h2 = ((sol['P_alkel'] / RATED_ALKEL * H2_ALKEL_PER_HOUR
                  + sol['P_pemel'] / RATED_PEMEL * H2_PEMEL_PER_HOUR).sum())
    h2_cap_total = H2_ALKEL_PER_HOUR + H2_PEMEL_PER_HOUR
    util_h2 = actual_h2 / (h2_cap_total * T) * 100

    util_nh3 = (sol['P_ammonia'] / RATED_AMMONIA).mean() * 100

    E_renewable = P_w.sum() + P_s.sum()
    E_curtail = sol['curtail'].sum()
    util_re = (E_renewable - E_curtail) / E_renewable * 100 if E_renewable > 0 else 0

    storage_daily_dep = 0.0
    if storage_capacity > 0:
        total_invest = storage_capacity * 1000 * STORAGE_COST_PER_KWH
        storage_daily_dep = total_invest / (STORAGE_LIFETIME_YEARS * 365)

    total_cost = ind['ope_cost'] + ind['daily_depreciation'] + storage_daily_dep
    ton_cost = total_cost / max(sol['NH3_total'], 0.1)

    return {
        'NH3': sol['NH3_total'],
        'ton_cost': ton_cost,
        'util_nh3': util_nh3,
        'util_h2': util_h2,
        'util_re': util_re,
        'curtail': E_curtail,
        'E_wind': P_w.sum(),
        'E_solar': P_s.sum(),
        'E_renewable': E_renewable,
        'E_used': ind['E_total_used'],
        'E_buy': 0.0,
        'E_sell': 0.0,
        'cost_buy': 0.0,
        'rev_sell': 0.0,
        'eta_self': ind['E_total_used'] / E_renewable if E_renewable > 0 else 0,
        'eta_green': (E_renewable - 0) / ind['E_total_used'] if ind['E_total_used'] > 0 else 0,
        'eta_sell': 0.0,
        'storage_daily_dep': storage_daily_dep,
        'equip_daily_dep': ind['daily_depreciation'],
        'ope_cost': ind['ope_cost'],
        'meets_target': sol['NH3_total'] >= TARGET_NH3 - 0.1,
    }


def _print_scn_out(key, res, storage_capacity=0):
    tag = "✓" if res['meets_target'] else f"✗ 差{TARGET_NH3 - res['NH3']:.0f}t"
    parts = [
        f"  风{key[0]}光{key[1]}: NH3={res['NH3']:.1f}t",
        f"成本={res['ton_cost']:.0f}¥/t",
        f"H2={res['util_h2']:.0f}% NH3={res['util_nh3']:.0f}%",
        f"风光利={res['util_re']:.0f}%",
        f"弃电={res['curtail']:.0f}MWh",
        f"[{tag}]",
    ]
    if storage_capacity > 0:
        parts.insert(4, f"储能={res['SOC_avg']:.1f}MWh")
    print("  ".join(parts))


def _summarize_24_scn(results, label, storage_capacity=0):
    valid = [r for r in results.values() if r is not None]
    if not valid:
        return
    nh3_vals = np.array([r['NH3'] for r in valid])
    costs = np.array([r['ton_cost'] for r in valid])
    util_nh3 = np.mean([r['util_nh3'] for r in valid])
    util_h2 = np.mean([r['util_h2'] for r in valid])
    util_re = np.mean([r['util_re'] for r in valid])
    curtail_avg = np.mean([r['curtail'] for r in valid])
    n_meet = sum(1 for r in valid if r['meets_target'])

    annual_nh3 = nh3_vals.sum() * DAYS_PER_SCENARIO

    print(f"\n{'─' * 55}")
    print(f"{label} 汇总")
    print(f"{'─' * 55}")
    print(f"  全年制氨: {annual_nh3:.0f} t (日均 {nh3_vals.mean():.1f} t/d)")
    print(f"  达标72t: {n_meet}/{len(valid)} 场景")
    print(f"  吨氨成本: {costs.mean():.0f} ¥/t  [{costs.min():.0f} ~ {costs.max():.0f}]")
    print(f"  设备利用: NH3={util_nh3:.0f}%  H2={util_h2:.0f}%")
    print(f"  风光利用: {util_re:.1f}%  | 日均弃电 {curtail_avg:.0f} MWh")


# ========================================================================
# Q4(1): 无储能
# ========================================================================
def solve_q4_no_storage():
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    print("=" * 58)
    print("Q4(1): 离网无储能 — 尽限利用风光发电")
    print("=" * 58)

    results = {}
    max_curtail = -1
    max_curtail_key = None

    for wi in range(6):
        for si in range(4):
            key = (wi + 1, si + 1)
            P_w = wind_scens[:, wi]
            P_s = solar_scens[:, si]

            sol = _solve_one_scn(P_w, P_s, P_load)
            if sol is None:
                print(f"  风{key[0]}光{key[1]}: 求解失败")
                results[key] = None
                continue

            res = _calc_indicators(P_w, P_s, P_load, sol)
            results[key] = res

            if res['curtail'] > max_curtail:
                max_curtail = res['curtail']
                max_curtail_key = key

            _print_scn_out(key, res)

    _summarize_24_scn(results, "Q4(1) 无储能")

    valid = [r for r in results.values() if r is not None]
    if valid:
        nh3_vals = np.array([r['NH3'] for r in valid])
        costs = np.array([r['ton_cost'] for r in valid])
        print(f"\n  能源自给分析:")
        print(f"    达标72t且有弃电: {sum(1 for r in valid if r['meets_target'] and r['curtail']>10)} 场景")
        print(f"    无法达标72t: {sum(1 for r in valid if not r['meets_target'])} 场景")
        print(f"    弃电最多: 风{max_curtail_key[0]}光{max_curtail_key[1]} ({max_curtail:.0f} MWh)")

    return results, max_curtail_key


# ========================================================================
# Q4(1) 扩展: 最小风光装机估算
# ========================================================================
def estimate_min_capacity():
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    print(f"\n{'─' * 55}")
    print("Q4(1) 扩展: 能源自治的最小风、光装机容量")
    print(f"  当前风电={RATED_WIND}MW 光伏={RATED_PV}MW (等比例缩放)")
    print(f"{'─' * 55}")

    found_scale = None
    for scale in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0]:
        n_ok = 0
        for wi in range(6):
            for si in range(4):
                P_w = wind_scens[:, wi] * scale
                P_s = solar_scens[:, si] * scale
                sol = _solve_one_scn(P_w, P_s, P_load)
                if sol is not None and sol['NH3_total'] >= TARGET_NH3 - 0.1:
                    n_ok += 1
        print(f"  ×{scale:.1f} : 风电={RATED_WIND*scale:.0f}MW 光伏={RATED_PV*scale:.0f}MW → {n_ok}/24达标")
        if n_ok == 24 and found_scale is None:
            found_scale = scale
            print(f"\n  >>> 最小等比例扩容: ×{scale:.1f}")
            print(f"      风电 ≥ {RATED_WIND*scale:.0f} MW, 光伏 ≥ {RATED_PV*scale:.0f} MW")
            break

    if found_scale is None:
        print(f"\n  >>> 即使×20仍未全部达标（某些场景风光极弱不足以支撑72t）")
    return found_scale


# ========================================================================
# Q4(2): 储能定容
# ========================================================================
def storage_sizing(max_curtail_key):
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()
    wi, si = max_curtail_key[0] - 1, max_curtail_key[1] - 1
    P_w = wind_scens[:, wi]
    P_s = solar_scens[:, si]

    print(f"\n{'─' * 55}")
    print(f"Q4(2): 储能容量定容 (基于最大弃电 风{max_curtail_key[0]}光{max_curtail_key[1]})")
    print(f"{'─' * 55}")

    base_sol = _solve_one_scn(P_w, P_s, P_load)
    base_res = _calc_indicators(P_w, P_s, P_load, base_sol) if base_sol else None
    if base_res:
        print(f"  无储能: NH3={base_res['NH3']:.1f}t 弃电={base_res['curtail']:.0f}MWh "
              f"风光利用={base_res['util_re']:.0f}%")

    candidates = [20, 50, 100, 150, 200, 300, 500]
    best_cap = 0
    best_delta_nh3 = -999

    for cap in candidates:
        chg = min(cap * 0.2, 20)
        dchg = chg
        sol = _solve_one_scn(P_w, P_s, P_load, cap, chg, dchg)
        if sol is None:
            continue
        res = _calc_indicators(P_w, P_s, P_load, sol, cap)
        delta_nh3 = res['NH3'] - base_res['NH3'] if base_res else 0
        delta_cur = base_res['curtail'] - res['curtail'] if base_res else 0
        print(f"  容量{cap:>4}MWh: NH3={res['NH3']:.1f}t ({delta_nh3:+.1f}) "
              f"弃电={res['curtail']:.0f}MWh ({delta_cur:+.0f}) "
              f"风光利用={res['util_re']:.0f}%  "
              f"{'✓' if res['meets_target'] else '✗'}")

        if delta_nh3 > best_delta_nh3:
            best_delta_nh3 = delta_nh3
            best_cap = cap

    if best_cap == 0:
        best_cap = 50
        print(f"\n  储能效果不显著，使用 {best_cap}MWh")
    else:
        print(f"\n  >>> 推荐储能容量: {best_cap} MWh")
        print(f"      ΔNH3 = +{best_delta_nh3:.1f} t/d")

    return best_cap


# ========================================================================
# Q4(2): 全场景有储能
# ========================================================================
def solve_q4_with_storage(storage_capacity):
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    chg = min(storage_capacity * 0.2, 20)
    dchg = chg

    print(f"\n{'─' * 55}")
    print(f"Q4(2): 有储能 24场景调度 (容量={storage_capacity}MWh, 充放={chg:.0f}MW)")
    print(f"{'─' * 55}")

    results = {}
    for wi in range(6):
        for si in range(4):
            key = (wi + 1, si + 1)
            P_w = wind_scens[:, wi]
            P_s = solar_scens[:, si]

            sol = _solve_one_scn(P_w, P_s, P_load, storage_capacity, chg, dchg)
            if sol is None:
                print(f"  风{key[0]}光{key[1]}: 求解失败")
                results[key] = None
                continue

            res = _calc_indicators(P_w, P_s, P_load, sol, storage_capacity)
            res['SOC_avg'] = sol['SOC'].mean() if sol['SOC'] is not None else 0
            results[key] = res
            _print_scn_out(key, res, storage_capacity)

    _summarize_24_scn(results, f"Q4(2) 有储能 ({storage_capacity}MWh)", storage_capacity)
    return results


# ========================================================================
# Q4(2): 储能改善分析
# ========================================================================
def analyze_storage_improvement(no_storage, with_storage, storage_capacity):
    print(f"\n{'─' * 55}")
    print(f"Q4(2): 储能改善效果分析 (容量={storage_capacity}MWh)")
    print(f"{'─' * 55}")

    ns_val = {k: v for k, v in no_storage.items() if v is not None}
    ws_val = {k: v for k, v in with_storage.items() if v is not None}
    common = sorted(set(ns_val) & set(ws_val))
    if not common:
        print("  无有效对比数据")
        return

    delta_nh3 = np.array([ws_val[k]['NH3'] - ns_val[k]['NH3'] for k in common])
    delta_re = np.array([ws_val[k]['util_re'] - ns_val[k]['util_re'] for k in common])
    delta_cur = np.array([ns_val[k]['curtail'] - ws_val[k]['curtail'] for k in common])

    annual_nh3_no = sum(ns_val[k]['NH3'] for k in common) * DAYS_PER_SCENARIO
    annual_nh3_ws = sum(ws_val[k]['NH3'] for k in common) * DAYS_PER_SCENARIO
    n_meet_no = sum(1 for k in common if ns_val[k]['meets_target'])
    n_meet_ws = sum(1 for k in common if ws_val[k]['meets_target'])

    avg_cost_no = np.mean([ns_val[k]['ton_cost'] for k in common])
    avg_cost_ws = np.mean([ws_val[k]['ton_cost'] for k in common])

    print(f"  全年NH3: {annual_nh3_no:.0f} → {annual_nh3_ws:.0f} t  "
          f"(+{annual_nh3_ws - annual_nh3_no:.0f}, +{(annual_nh3_ws / max(annual_nh3_no,1) - 1) * 100:.1f}%)")
    print(f"  达标72t: {n_meet_no} → {n_meet_ws} (+{n_meet_ws - n_meet_no})")
    print(f"  风光利用: {np.mean([ns_val[k]['util_re'] for k in common]):.1f}% → "
          f"{np.mean([ws_val[k]['util_re'] for k in common]):.1f}%  (+{delta_re.mean():.1f}pp)")
    print(f"  日均弃电: {np.mean([ns_val[k]['curtail'] for k in common]):.0f} → "
          f"{np.mean([ws_val[k]['curtail'] for k in common]):.0f} MWh  (-{delta_cur.mean():.0f})")
    print(f"  平均吨氨成本: {avg_cost_no:.0f} → {avg_cost_ws:.0f} ¥/t  "
          f"({avg_cost_ws - avg_cost_no:+.0f}, 正=储能折旧推高成本)")

    best_idx = np.argmax(delta_nh3)
    best_key = common[best_idx]
    print(f"\n  NH3提升最大的场景: 风{best_key[0]}光{best_key[1]}  (ΔNH3 = +{delta_nh3[best_idx]:.1f}t)")


# ========================================================================
# Q4(3): 离网 vs 并网
# ========================================================================
def compare_offgrid_ongrid(offgrid_results):
    _rc = Path(__file__).resolve().parent
    sys.path.insert(0, str(_rc))
    from q3_lp import build_lp, CAPACITY_FACTOR as Q3_CF

    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    print(f"\n{'─' * 55}")
    print("Q4(3): 离网 vs 并网 经济性对比 (72t/d同基准)")
    print(f"{'─' * 55}")

    off_val = {k: v for k, v in offgrid_results.items() if v is not None}
    off_nh3_total = sum(r['NH3'] for r in off_val.values()) * DAYS_PER_SCENARIO
    off_cost_mean = np.mean([r['ton_cost'] for r in off_val.values()])
    off_cost_min = min([r['ton_cost'] for r in off_val.values()])
    off_cost_max = max([r['ton_cost'] for r in off_val.values()])
    n_meet_off = sum(1 for r in off_val.values() if r['meets_target'])

    ong_costs = []
    for wi in range(6):
        for si in range(4):
            P_w = wind_scens[:, wi]
            P_s = solar_scens[:, si]
            sol = build_lp(P_w, P_s, P_load, TARGET_NH3)
            if sol['status'] != 1:
                continue
            ind = compute_indicators(
                P_w, P_s, sol['P_buy'], sol['P_sell'],
                P_load, sol['P_alkel'], sol['P_pemel'], sol['P_ammonia'],
                NH3_total=TARGET_NH3, capacity_factor=Q3_CF,
            )
            ong_costs.append(ind['ton_cost'])

    ong_costs = np.array(ong_costs)
    ong_nh3_total = TARGET_NH3 * 24 * DAYS_PER_SCENARIO

    print(f"\n{'─' * 55}")
    print(f"  {'':25s} {'离网(有储能)':>15s} {'并网(Q3 LP)':>15s}")
    print(f"{'─' * 55}")
    print(f"  全年NH3(t)           {off_nh3_total:>15.0f} {ong_nh3_total:>15.0f}")
    print(f"  离网产量占比          {off_nh3_total/ong_nh3_total*100:>15.0f}% {'—':>15s}")
    print(f"  达标72t场景          {n_meet_off:>15} {'24/24':>15s}")
    print(f"  吨氨成本均值(¥/t)    {off_cost_mean:>15.0f} {ong_costs.mean():>15.0f}")
    print(f"  吨氨成本最小          {off_cost_min:>15.0f} {ong_costs.min():>15.0f}")
    print(f"  吨氨成本最大          {off_cost_max:>15.0f} {ong_costs.max():>15.0f}")
    print(f"{'─' * 55}")

    cost_gap = off_cost_mean - ong_costs.mean()
    print(f"\n  成本分析 (注意: 产量不等, 直接比较分母不同):")
    print(f"    离网均产 {off_nh3_total/360:.1f} t/d, 并网固定 72.0 t/d")
    if cost_gap > 0:
        print(f"    离网吨氨成本高出 {cost_gap:.0f} ¥/t (相同产量下)")
        print(f"    原因: (1) 离网弃电无法售出收入归零"
              f"\n           (2) 产量受限使固定折旧摊到更少产量"
              f"\n           (3) 储能折旧额外成本 {off_val[min(off_val.keys())]['storage_daily_dep']:.0f} ¥/d")
    else:
        print(f"    离网吨氨成本反而低 {abs(cost_gap):.0f} ¥/t")
        print(f"    原因: 离网不购电, 扣除全部电费; 但代价是产量仅并网的"
              f"{off_nh3_total/ong_nh3_total*100:.0f}%")
    print(f"\n  >>> 电网核心价值: 保障72t/d满产 + 允许余电上网回收成本")
    print(f"  >>> 离网放弃电网 = 放弃 {ong_nh3_total - off_nh3_total:.0f} t/年产能 "
          f"({(1 - off_nh3_total/ong_nh3_total)*100:.0f}% 产量损失)")

    return off_cost_mean, ong_costs.mean()


# ========================================================================
# Q4(2): 绘制典型场景调度
# ========================================================================
def plot_q4_figures(P_w, P_s, P_load, sol, res, storage_capacity, wi, si):
    t = np.arange(T)
    P_total_load = P_load + sol['P_alkel'] + sol['P_pemel'] + sol['P_ammonia']
    P_total_gen = P_w + P_s
    has_storage = storage_capacity > 0

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # ── 图1: 负荷分解 ──
    ax1 = axes[0, 0]
    for tt in range(24):
        p = TOU_SCHEDULE[tt]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax1.axvspan(tt - 0.5, tt + 0.5, color=c, alpha=0.06, lw=0)
    ax1.fill_between(t, 0, P_load, label='常规电负荷', color='#333333', alpha=0.6)
    bottom = P_load.copy()
    ax1.fill_between(t, bottom, bottom + sol['P_alkel'], label='ALKEL', color='#8963BA', alpha=0.5)
    bottom += sol['P_alkel']
    ax1.fill_between(t, bottom, bottom + sol['P_pemel'], label='PEMEL', color='#E56399', alpha=0.5)
    bottom += sol['P_pemel']
    ax1.fill_between(t, bottom, bottom + sol['P_ammonia'], label='合成氨', color='#7F7F7F', alpha=0.5)
    ax1.plot(t, P_total_load, 'k-', linewidth=1.5, label='总负荷')
    ax1.set_xlabel('时段 (h)')
    ax1.set_ylabel('功率 (MW)')
    ax1.set_title('图1: 负荷分解', fontsize=11, fontweight='bold')
    ax1.set_xticks(t)
    ax1.set_xticklabels([f'{h}:00' for h in t], rotation=45, fontsize=7)
    ax1.grid(True, alpha=0.25, linestyle=':')
    ax1.set_xlim(-0.5, 23.5)
    ax1.legend(fontsize=7, ncol=2, loc='upper right')

    # ── 图2: 发电分解 ──
    ax2 = axes[0, 1]
    for tt in range(24):
        p = TOU_SCHEDULE[tt]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax2.axvspan(tt - 0.5, tt + 0.5, color=c, alpha=0.06, lw=0)
    ax2.fill_between(t, 0, P_w, label='风电', color='#2E86AB', alpha=0.6)
    ax2.fill_between(t, P_w, P_total_gen, label='光伏', color='#F18F01', alpha=0.6)
    ax2.plot(t, P_total_gen, '--', color='#3B8C6E', linewidth=1.5, label='总发电')
    ax2.set_xlabel('时段 (h)')
    ax2.set_ylabel('功率 (MW)')
    ax2.set_title('图2: 发电分解', fontsize=11, fontweight='bold')
    ax2.set_xticks(t)
    ax2.set_xticklabels([f'{h}:00' for h in t], rotation=45, fontsize=7)
    ax2.grid(True, alpha=0.25, linestyle=':')
    ax2.set_xlim(-0.5, 23.5)
    ax2.legend(fontsize=7, loc='upper right')

    # ── 图3: 供需对比 + 弃电 ──
    ax3 = axes[1, 0]
    for tt in range(24):
        p = TOU_SCHEDULE[tt]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax3.axvspan(tt - 0.5, tt + 0.5, color=c, alpha=0.06, lw=0)
    # With storage: net load = load + charge - discharge
    if has_storage:
        P_net_re = P_w + P_s + sol['P_discharge'] - sol['P_charge']
        net_label = '总发电+放电-充电'
    else:
        P_net_re = P_total_gen
        net_label = '总发电'
    ax3.plot(t, P_total_load, 's-', color='#C73E1D', linewidth=2, markersize=4, label='总负荷')
    ax3.plot(t, P_net_re, 'o-', color='#3B8C6E', linewidth=2, markersize=4, label=net_label)
    # Curtailment area
    curtail = sol['curtail']
    ax3.fill_between(t, 0, curtail, where=(curtail > 0), color='orange', alpha=0.15, label='弃电')
    ax3.set_xlabel('时段 (h)')
    ax3.set_ylabel('功率 (MW)')
    ax3.set_title('图3: 供需对比 (离网)', fontsize=11, fontweight='bold')
    ax3.set_xticks(t)
    ax3.set_xticklabels([f'{h}:00' for h in t], rotation=45, fontsize=7)
    ax3.grid(True, alpha=0.25, linestyle=':')
    ax3.set_xlim(-0.5, 23.5)
    ax3.legend(fontsize=7, loc='upper right')

    # ── 图4: 储能调度 (或弃电明细) ──
    ax4 = axes[1, 1]
    for tt in range(24):
        p = TOU_SCHEDULE[tt]
        c = 'red' if p == 'peak' else ('green' if p == 'flat' else 'none')
        ax4.axvspan(tt - 0.5, tt + 0.5, color=c, alpha=0.06, lw=0)
    if has_storage:
        ax4.bar(t - 0.2, sol['P_charge'], width=0.35, color='#2E86AB', alpha=0.7, label='充电')
        ax4.bar(t + 0.2, sol['P_discharge'], width=0.35, color='#C73E1D', alpha=0.7, label='放电')
        ax4_twin = ax4.twinx()
        ax4_twin.plot(t, sol['SOC'], 's-', color='#F18F01', linewidth=2, markersize=3, label='SOC')
        ax4_twin.set_ylabel('SOC (MWh)', fontsize=10)
        ax4_twin.legend(fontsize=7, loc='upper right')
    else:
        ax4.bar(t, sol['curtail'], width=0.6, color='orange', alpha=0.7, label='弃电')
    ax4.set_xlabel('时段 (h)')
    ax4.set_ylabel('功率 (MW)')
    ax4.set_title('图4: 储能调度' if has_storage else '图4: 弃电', fontsize=11, fontweight='bold')
    ax4.set_xticks(t)
    ax4.set_xticklabels([f'{h}:00' for h in t], rotation=45, fontsize=7)
    ax4.grid(True, alpha=0.25, linestyle=':')
    ax4.set_xlim(-0.5, 23.5)
    ax4.legend(fontsize=7, loc='upper left')

    label = f"离网(储能{storage_capacity}MWh)" if has_storage else "离网(无储能)"
    fig.suptitle(f'Q4: {label} (风{wi+1}光{si+1}, NH₃={res["NH3"]:.1f}t)', fontsize=14, fontweight='bold', y=1.02)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = str(RESULTS_DIR / f'q4_scn_{wi+1}_{si+1}_storage_{storage_capacity}.png')
    fig.savefig(path, dpi=180, bbox_inches='tight', pad_inches=0.3)
    plt.close(fig)
    print(f"[Saved] {path}")


def plot_typical_schedule(storage_capacity, max_curtail_key=None):
    P_load = load_typical_load()
    wind_scens = load_wind_scenarios()
    solar_scens = load_solar_scenarios()

    if max_curtail_key:
        wi, si = max_curtail_key[0] - 1, max_curtail_key[1] - 1
    else:
        wi, si = 0, 0
    P_w = wind_scens[:, wi]
    P_s = solar_scens[:, si]

    chg = min(storage_capacity * 0.2, 20) if storage_capacity > 0 else 0
    dchg = chg

    sol = _solve_one_scn(P_w, P_s, P_load, storage_capacity, chg, dchg)
    if sol is None:
        print(f"  [skip] 风{wi+1}光{si+1} 不可行")
        return

    res = _calc_indicators(P_w, P_s, P_load, sol, storage_capacity)
    plot_q4_figures(P_w, P_s, P_load, sol, res, storage_capacity, wi, si)


# ========================================================================
# Main
# ========================================================================
if __name__ == '__main__':
    _tee = TeeStream()
    sys.stdout = _tee
    try:
        no_storage, max_curtail_key = solve_q4_no_storage()
        print()

        estimate_min_capacity()
        print()

        best_cap = storage_sizing(max_curtail_key)
        print()

        with_storage = solve_q4_with_storage(best_cap)
        print()

        analyze_storage_improvement(no_storage, with_storage, best_cap)
        print()

        compare_offgrid_ongrid(with_storage)
        print()

        plot_typical_schedule(0, max_curtail_key)
        plot_typical_schedule(best_cap, max_curtail_key)
    finally:
        sys.stdout = _tee.console
        save_text_output('q4_lp_output.txt', _tee.getvalue())
