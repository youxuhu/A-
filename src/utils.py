from pathlib import Path
import sys
import io
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

PROJ_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJ_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)
FONT_DIR = PROJ_DIR / 'data' / 'fonts'
FONT_DIR.mkdir(exist_ok=True)

# Register Chinese font if available
_font_registered = False
for _f in FONT_DIR.glob('*'):
    try:
        fm.fontManager.addfont(str(_f))
        _font_registered = True
        break
    except:
        pass

_cn_font = None
if _font_registered:
    for _f in fm.fontManager.ttflist:
        if 'wenquan' in _f.name.lower() or 'noto' in _f.name.lower() or 'cjk' in _f.name.lower() or 'hei' in _f.name.lower():
            _cn_font = _f.name
            break

if _cn_font:
    matplotlib.rcParams['font.family'] = _cn_font
else:
    matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['axes.unicode_minus'] = False

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
RAW_DIR = Path(__file__).resolve().parent.parent

RATED_WIND = 40  # MW
RATED_PV = 64    # MW
RATED_LOAD = 6   # MW (peak)

RATED_ALKEL = 10   # MW
RATED_PEMEL = 10   # MW
RATED_AMMONIA = 0.75  # MW
ALKEL_H2_RATE = 140   # kg/h
PEMEL_H2_RATE = 160   # kg/h
AMMONIA_NH3_RATE = 1.5  # t/h
H2_PER_NH3 = 0.2       # kgH2 / kgNH3
ELEC_PER_NH3 = 0.5     # kWh / kgNH3

TOU_PRICES = {
    'peak': 0.8024,
    'flat': 0.6074,
    'valley': 0.3424,
}
FEED_IN_PRICE = 0.3779

TOU_SCHEDULE = {}
for t in range(24):
    if t in range(10, 16) or t in range(18, 22):
        TOU_SCHEDULE[t] = 'peak'
    elif t in range(7, 11) or t in range(15, 19) or t in range(21, 24):
        TOU_SCHEDULE[t] = 'flat'
    else:
        TOU_SCHEDULE[t] = 'valley'


def load_attachment(name_idx: int) -> pd.DataFrame:
    names = {
        1: '附件1：园区典型日常规电负荷标幺功率曲线.xlsx',
        2: '附件2：典型日风电、光伏标幺功率表.xlsx',
        3: '附件3：园区6种场景的风电标幺功率表.xlsx',
        4: '附件4：园区4种场景的光伏标幺功率表.xlsx',
        5: '附件5：风光发电与制氢设备技术参数.xlsx',
        6: '附件6：储能设备和合成氨装置技术参数.xlsx',
        7: '附件7：分时电价表.xlsx',
        8: '附件8：风电、光伏余电上网电价.xlsx',
    }
    path = RAW_DIR / names[name_idx]
    if name_idx >= 3:
        path = DATA_DIR / names[name_idx]
        if not path.exists():
            path = RAW_DIR / names[name_idx]
    df = pd.read_excel(path, header=0)
    return df


def load_typical_load() -> np.ndarray:
    df = load_attachment(1)
    return df.iloc[:, 1].values * RATED_LOAD


def load_typical_wind_solar() -> tuple[np.ndarray, np.ndarray]:
    df = load_attachment(2)
    return df.iloc[:, 1].values * RATED_WIND, df.iloc[:, 2].values * RATED_PV


def load_wind_scenarios() -> np.ndarray:
    df = load_attachment(3)
    return df.iloc[:, 1:].values * RATED_WIND


def load_solar_scenarios() -> np.ndarray:
    df = load_attachment(4)
    return df.iloc[:, 1:].values * RATED_PV


def get_price(t: int) -> float:
    return TOU_PRICES[TOU_SCHEDULE[t]]


def get_price_array() -> np.ndarray:
    return np.array([get_price(t) for t in range(24)])


def compute_indicators(P_wind: np.ndarray, P_solar: np.ndarray,
                       P_buy: np.ndarray, P_sell: np.ndarray,
                       P_load: np.ndarray, P_alkel: np.ndarray,
                       P_pemel: np.ndarray, P_ammonia: np.ndarray,
                       NH3_total: float = 36.0,
                       capacity_factor: float = 1.0) -> dict:
    E_wind = P_wind.sum()
    E_solar = P_solar.sum()
    E_renewable = E_wind + E_solar
    E_buy = P_buy.sum()
    E_sell = P_sell.sum()
    E_load = P_load.sum()
    E_alkel = P_alkel.sum()
    E_pemel = P_pemel.sum()
    E_ammonia = P_ammonia.sum()
    E_total_used = E_load + E_alkel + E_pemel + E_ammonia

    eta_self = (E_total_used - E_sell - E_buy) / E_renewable if E_renewable > 0 else 0
    eta_green = (E_renewable - E_sell) / E_total_used if E_total_used > 0 else 0
    eta_sell = E_sell / E_renewable if E_renewable > 0 else 0

    cost_buy = np.sum(P_buy * 1000 * get_price_array())
    rev_sell = E_sell * 1000 * FEED_IN_PRICE

    # Depreciation & O&M (all ¥/kWh → ×1000 for MW→kW)
    invest_alkel = 10 * 1000 * 10000 * capacity_factor  # MW→kW, ¥/kW
    invest_pemel = 10 * 1000 * 10000 * capacity_factor
    invest_ammonia = (AMMONIA_NH3_RATE * H2_PER_NH3 * 1000) * 60000 * capacity_factor
    total_invest = invest_alkel + invest_pemel + invest_ammonia
    annual_depreciation = total_invest / 30  # 30 year life
    daily_depreciation = annual_depreciation / 365

    ope_cost = np.sum(P_alkel * 100 + P_pemel * 150 + P_ammonia * 2)

    total_cost = cost_buy + ope_cost + daily_depreciation - rev_sell
    ton_cost = total_cost / NH3_total if NH3_total > 0 else 0

    return {
        'E_wind': E_wind,
        'E_solar': E_solar,
        'E_renewable': E_renewable,
        'E_buy': E_buy,
        'E_sell': E_sell,
        'E_load': E_load,
        'E_alkel': E_alkel,
        'E_pemel': E_pemel,
        'E_ammonia': E_ammonia,
        'E_total_used': E_total_used,
        'eta_self': eta_self,
        'eta_green': eta_green,
        'eta_sell': eta_sell,
        'cost_buy': cost_buy,
        'rev_sell': rev_sell,
        'ope_cost': ope_cost,
        'daily_depreciation': daily_depreciation,
        'ton_cost': ton_cost,
    }


def _shade_price_periods(ax):
    for t in range(24):
        period = TOU_SCHEDULE[t]
        c = 'red' if period == 'peak' else ('green' if period == 'flat' else 'none')
        _ = ax.axvspan(t - 0.5, t + 0.5, color=c, alpha=0.06, lw=0)


def _annotate_metrics(ax, ind: dict, x=0.02, y=0.98):
    text = (
        f"吨氨成本: {ind['ton_cost']:.2f} ¥/t\n"
        f"η_self: {ind['eta_self']*100:.1f}%  η_green: {ind['eta_green']*100:.1f}%  η_sell: {ind['eta_sell']*100:.1f}%\n"
        f"绿电: {ind['E_renewable']:.0f} MWh  购电: {ind['E_buy']:.0f} MWh  售电: {ind['E_sell']:.0f} MWh"
    )
    ax.text(x, y, text, transform=ax.transAxes, fontsize=9,
            verticalalignment='top',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', alpha=0.85))


LABEL_MAP = {
    'wind': '风电',
    'solar': '光伏',
    'load': '常规负荷',
    'buy': '网购电',
    'sell': '售电',
    'alkel': '碱性电解槽',
    'pemel': 'PEM电解槽',
    'ammonia': '合成氨',
}


def plot_power_curves(P_wind, P_solar, P_load, P_buy, P_sell,
                      P_alkel=None, P_pemel=None, P_ammonia=None,
                      title='功率平衡曲线', save_path=None, ind=None):
    t = np.arange(24)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    _shade_price_periods(ax)

    ax.plot(t, P_wind, 'o-', color='#2E86AB', label=LABEL_MAP['wind'], linewidth=1.8, markersize=4)
    ax.plot(t, P_solar, 's-', color='#F18F01', label=LABEL_MAP['solar'], linewidth=1.8, markersize=4)
    ax.plot(t, P_load, 'd-', color='#333333', label=LABEL_MAP['load'], linewidth=2, markersize=4)
    ax.plot(t, P_buy, '^--', color='#C73E1D', label=LABEL_MAP['buy'], linewidth=1.5, markersize=5)
    ax.plot(t, P_sell, 'v--', color='#3B8C6E', label=LABEL_MAP['sell'], linewidth=1.5, markersize=5)
    if P_alkel is not None:
        ax.plot(t, P_alkel, 'x-', color='#8963BA', label=LABEL_MAP['alkel'], linewidth=1.5, markersize=5)
    if P_pemel is not None:
        ax.plot(t, P_pemel, '*-', color='#E56399', label=LABEL_MAP['pemel'], linewidth=1.5, markersize=5)
    if P_ammonia is not None:
        ax.plot(t, P_ammonia, '+-', color='#7F7F7F', label=LABEL_MAP['ammonia'], linewidth=1.5, markersize=6)

    # Annotate flat lines (ALKEL, PEMEL, AMMONIA) directly on the plot
    if P_alkel is not None and np.allclose(P_alkel, P_alkel[0]):
        ax.text(23.5, P_alkel[0], f'{P_alkel[0]:.0f} MW', color='#8963BA',
                fontsize=8, va='center', ha='left')
    if P_pemel is not None and np.allclose(P_pemel, P_pemel[0]):
        ax.text(23.5, P_pemel[0], f'{P_pemel[0]:.0f} MW', color='#E56399',
                fontsize=8, va='center', ha='left')
    if P_ammonia is not None and np.allclose(P_ammonia, P_ammonia[0]):
        ax.text(23.5, P_ammonia[0], f'{P_ammonia[0]:.2f} MW', color='#7F7F7F',
                fontsize=8, va='center', ha='left')

    # Legend: 2 columns, below plot
    from matplotlib.patches import Patch
    lines = [ax.get_lines()[i] for i in range(len(ax.get_lines()))]
    labels = [l.get_label() for l in lines]
    price_patches = [
        Patch(facecolor='red', alpha=0.10, label='峰时段'),
        Patch(facecolor='green', alpha=0.06, label='平时段'),
        Patch(facecolor='gray', alpha=0.03, label='谷时段'),
    ]
    legend1 = ax.legend(lines + price_patches, labels + ['', '', ''],
                        ncol=3, fontsize=8, loc='upper center',
                        bbox_to_anchor=(0.5, -0.08),
                        handlelength=1.2, columnspacing=1.2)
    ax.add_artist(legend1)
    # Price note as text
    ax.text(0.98, 0.02, '■峰 ■平 □谷', transform=ax.transAxes,
            fontsize=8, ha='right', va='bottom',
            bbox=dict(facecolor='white', alpha=0.7, pad=2))

    ax.set_xlabel('时段 (h)', fontsize=11)
    ax.set_ylabel('功率 (MW)', fontsize=11)
    ax.set_title(title, fontsize=13, fontweight='bold')
    ax.set_xticks(t)
    ax.set_xticklabels([f'{h}:00' for h in t], rotation=45, fontsize=8)
    ax.grid(True, alpha=0.25, linestyle=':')
    ax.set_xlim(-0.5, 23.5)

    if ind is not None:
        _annotate_metrics(ax, ind)

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.18)
    if save_path:
        save_path = str(RESULTS_DIR / Path(save_path).name)
        fig.savefig(save_path, dpi=180, bbox_inches='tight')
        plt.close(fig)
    else:
        plt.show()


class TeeStream:
    """Duplicate stdout to both console and a buffer."""
    def __init__(self):
        self.buf = io.StringIO()
        self.console = sys.stdout

    def write(self, data):
        self.console.write(data)
        self.buf.write(data)

    def flush(self):
        self.console.flush()
        self.buf.flush()

    def getvalue(self):
        return self.buf.getvalue()


def save_text_output(filename: str, content: str):
    """Save printed terminal output to a text file."""
    path = RESULTS_DIR / filename
    path.write_text(content, encoding='utf-8')
    print(f"[Saved] results/{filename}")


def plot_toncost_distribution(costs, title, save_path):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(costs, bins='auto', edgecolor='white', alpha=0.75, color='#2E86AB')
    mean_val = costs.mean()
    ax.axvline(mean_val, color='#C73E1D', linestyle='--', linewidth=2,
               label=f'均值 = {mean_val:.2f} ¥/t')
    ax.axvline(np.median(costs), color='#3B8C6E', linestyle=':',
               label=f'中位数 = {np.median(costs):.2f} ¥/t')
    ax.set_xlabel('吨氨成本 (¥/t)', fontsize=11)
    ax.set_ylabel('频次', fontsize=11)
    ax.set_title(title, fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.25, linestyle=':')
    fig.tight_layout()
    fig.savefig(str(RESULTS_DIR / save_path), dpi=180, bbox_inches='tight')
    plt.close(fig)
    print(f"[Saved] results/{save_path}")
