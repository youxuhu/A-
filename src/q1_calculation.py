import sys
import numpy as np
from utils import (
    load_typical_load, load_typical_wind_solar,
    compute_indicators, plot_power_curves,
    RESULTS_DIR, save_text_output, TeeStream,
    RATED_ALKEL, RATED_PEMEL, RATED_AMMONIA,
)

T = 24


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
    )

    print("=" * 60)
    print("问题一: 典型风光场景下满负荷运行指标")
    print("=" * 60)
    print(f"  风电: {ind['E_wind']:.2f} MWh  光伏: {ind['E_solar']:.2f} MWh  "
          f"绿电合计: {ind['E_renewable']:.2f} MWh")
    print(f"  常规负荷: {ind['E_load']:.2f} MWh  碱性电解槽: {ind['E_alkel']:.2f} MWh  "
          f"PEM电解槽: {ind['E_pemel']:.2f} MWh  合成氨: {ind['E_ammonia']:.2f} MWh")
    print(f"  网购电: {ind['E_buy']:.2f} MWh  售电: {ind['E_sell']:.2f} MWh  "
          f"总用电: {ind['E_total_used']:.2f} MWh")
    print()
    print(f"  购电成本: {ind['cost_buy']:.2f} ¥  售电收益: {ind['rev_sell']:.2f} ¥  "
          f"运维费用: {ind['ope_cost']:.2f} ¥  日折旧: {ind['daily_depreciation']:.2f} ¥")
    print(f"  吨氨成本 = {ind['ton_cost']:.2f} ¥/t  (含折旧+运维)")
    print()
    print("--- 绿电直连指标 ---")
    print(f"  新能源自发自用率 η_self = {ind['eta_self']*100:.2f}%  (要求 > 60%)")
    print(f"  总用电量绿电比例 η_green = {ind['eta_green']*100:.2f}%  (要求 > 30%)")
    print(f"  新能源上网电量比例 η_sell = {ind['eta_sell']*100:.2f}%  (要求 < 20%)")
    print()
    for name, key, req in [
        ('η_self', 'eta_self', 0.60),
        ('η_green', 'eta_green', 0.30),
        ('η_sell', 'eta_sell', 0.20),
    ]:
        ok = ind[key] > req if 'sell' not in key else ind[key] < req
        print(f"  {name}达标: {'✓' if ok else '✗'}")

    if ind['eta_self'] <= 0.60 or ind['eta_sell'] >= 0.20:
        print()
        print("--- 不达标原因分析 ---")
        if ind['eta_self'] <= 0.60:
            print(f"  η_self偏低: 自发自用不足"
                  f"（满负荷用电仅{ind['E_total_used']:.0f}MWh，"
                  f"绿电{ind['E_renewable']:.0f}MWh），大量绿电上网")
        if ind['eta_sell'] >= 0.20:
            print(f"  η_sell偏高: 上网电量过多"
                  f"（{ind['eta_sell']*100:.1f}%，超过20%上限），"
                  f"新能源消纳能力不足")

    plot_power_curves(
        P_wind, P_solar, P_load,
        P_buy, P_sell, P_alkel, P_pemel, P_ammonia,
        title='问题一: 满负荷运行功率平衡曲线 (36t/d基础产能)',
        save_path='q1_power_curves.png',
        ind=ind,
    )

    return ind


if __name__ == '__main__':
    _tee = TeeStream()
    sys.stdout = _tee
    try:
        solve_q1()
    finally:
        sys.stdout = _tee.console
        save_text_output('q1_output.txt', _tee.getvalue())
