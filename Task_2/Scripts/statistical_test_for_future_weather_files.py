'''
MEWS / fAMY / fTMY Statistical Verification — Baseline vs. Future EPW
======================================================================
COMPARE_MODE 하나만 바꾸면 세 가지 소스 전부 지원

  'mews' : MEWS Stochastic EPW  (시나리오/연도별 그룹)
  'famy' : fAMY EPW             (RCP 시나리오/연도별 그룹)
  'ftmy' : fTMY EPW             (기간별 그룹)

ΔT 기준: Baseline TMYx EPW
  HW: TMAX > Baseline 월별 90th percentile
  CS: TMIN < Baseline 월별 10th percentile
  ΔT = 극한일 온도 − 해당 월 평균온도

Pass (p>0.05): 미래 극한 이벤트 강도 ≈ 현재
Fail (p≤0.05): 미래 극한 이벤트 강도 ≠ 현재 → 기후변화 신호
'''

from matplotlib.colors import ListedColormap
import os, glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from scipy.stats import gumbel_r
from itertools import combinations
from pathlib import Path
from mews.weather.alter import Alter
import matplotlib.dates as mdates
import re

# ══════════════════════════════════════════════════════════════════════
# ★ 사용자 설정 — 이 섹션만 수정
# ══════════════════════════════════════════════════════════════════════

location = ['Miami', 'Tampa', 'Tucson', 'Atlanta', 'ElPaso', 'SanDiego',
            'NewYork', 'Albuquerque', 'Seattle', 'Buffalo', 'Denver',
            'PortAngeles', 'Rochester', 'GreatFalls', 'InternationalFalls',
            'Fairbanks']

rcp_scenarios = ['RCP4.5', 'RCP7.0', 'RCP8.5']

file_type = ['mews', 'famy', 'ftmy', 'ftmy_direct']

base_year = ['2007-2021', '2009-2023']



test_loc     = location[13]         

COMPARE_MODE = file_type[3]              # 0 'mews' | 1 'famy' | 2 'ftmy' | 3 'ftmy_direct'

ftmy_scenario = rcp_scenarios[1]   # 'RCP4.5' | 'RCP7.0' | 'RCP8.5'

base_years = base_year[0]

# Baseline TMYx
main_c       = 'C:/Users/kkuio/OneDrive/바탕 화면/Weather data/'
base_epw_dir = main_c + f'TMYx/{test_loc}/{base_years}/'

# MEWS 
mews_dir     = main_c + f'MEWS/Stochastic/{test_loc}/'

# fAMY
famy_dir     = main_c + f'FAMY/{test_loc}/'

# fTMY 
ftmy_base     = main_c + 'FTMY/required/'

# fTMY_generated
ftmy_direct_dir  = main_c + f'FTMY/{test_loc}/'


# extreme event percentile
HW_PCTL      = 90
CS_PCTL      = 10
# ══════════════════════════════════════════════════════════════════════

COL          = 'Dry Bulb Temperature'
result_dir   = main_c + f'KSresult/{test_loc}/{COMPARE_MODE}/'
os.makedirs(result_dir, exist_ok=True)
MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun',
                'Jul','Aug','Sep','Oct','Nov','Dec']
print(f'분석: {test_loc}  모드: {COMPARE_MODE.upper()}'
      f'  (HW>{HW_PCTL}th / CS<{CS_PCTL}th percentile)')


# ── 색상 / 레이블 ────────────────────────────────────────────────────
FAMY_UNIFORM_COLOR = '#4C72B0'   # famy 막대 전용 단일 색상 (Fig3, Fig4 공통)

scenario_palette = {
    # SSP
    'SSP119':'#4CAF50', 'SSP126':'#8BC34A',
    'SSP245':'#2196F3', 'SSP370':'#FF9800',
    'SSP585':'#F44336', 'historical':'#9C27B0',
    # RCP
    'RCP2.6':'#8BC34A', 'RCP4.5':'#2196F3',
    'RCP6.0':'#FF9800', 'RCP8.5':'#F44336',
    # fTMY
    'fTMY':'#795548',
}

#%% pre-defined functions 

def label_colors(s):
    for k, c in scenario_palette.items():
        if k in str(s): return c
    return '#607D8B'

def clean_label(s, y=None):
    for k in scenario_palette:
        if k in str(s):
            base = f'{k}_{y}' if y else k
            return base
    return f'{s}_{y}' if y else str(s)


# ── EPW 로드 ──────────────────────────────────────────────────────────
# =============================================================================
# def conv_epw(path):
#     df = Alter(path).epwobj.dataframe.copy()
#     df['datetime'] = pd.to_datetime(dict(
#         year=2004, month=df['Month'], day=df['Day'], hour=df['Hour']-1))
#     return df.set_index('datetime')
# =============================================================================

BASE_YR = 2003   # 평년(365일) 기준 — conv_epw와 이벤트 윈도우 계산에서 공통으로 사용
def conv_epw(path):
    df = Alter(path).epwobj.dataframe.copy()
    df = df[~((df['Month'] == 2) & (df['Day'] == 29))].copy()   # 2/29 제거해서 모든 파일 365일로 통일
    df['datetime'] = pd.to_datetime(dict(
        year=BASE_YR, month=df['Month'], day=df['Day'], hour=df['Hour']-1))   # 2003=평년
    return df.set_index('datetime')

# ── 파일 파서 ────────────────────────────────────────────────────────
def parse_mews(f):
    """
    USA_WA_Seattle-Tacoma.Intl.AP.727930_TMYx.2007-2021SSP245_2020_5%_r0.epw
    → scenario='TMYx.2007-2021SSP245', year=2020, ci='5%'
    """
    nm    = os.path.basename(f).replace('.epw','')
    parts = nm.split('_')
    scen  = next((p for p in parts if 'SSP' in p or 'historical' in p.lower()), 'unknown')
    yr    = int(next((p for p in parts if p.isdigit() and len(p)==4), '0'))
    ci    = next((p for p in parts if '%' in p), '50%')
    real  = next((p for p in parts if p.startswith('r') and p[1:].isdigit()), 'r0')
    return {'scenario':scen, 'year':yr, 'ci':ci, 'real':real,
            'group_key':(scen, yr), 'label':clean_label(scen, yr)}

def parse_famy(f):
    """
    G53011603_RCP8.5_2045_lat47.639_long-122.372.epw
    5년 블록으로 그룹핑:
      2045-2049 → '2040s'
      2050-2054 → '2050s'
      2085-2089 → '2080s'
      2090-2094 → '2090s'
    """
    nm    = os.path.basename(f).replace('.epw','')
    parts = nm.split('_')
    scen  = next((p for p in parts if p.startswith('RCP')), 'unknown')
    yr    = int(next((p for p in parts if p.isdigit() and len(p)==4), '0'))

    # 5년 블록 매핑
    if   2045 <= yr <= 2049: block = '2040s'
    elif 2050 <= yr <= 2054: block = '2050s'
    elif 2085 <= yr <= 2089: block = '2080s'
    elif 2090 <= yr <= 2094: block = '2090s'
    else:                    block = f'{yr}'   # 범위 밖이면 연도 그대로

    label = f'{scen}_{block}'
    return {'scenario': scen, 'year': yr, 'block': block,
            'group_key': (scen, block),
            'label': label}

def parse_ftmy(f):
    """
    C:/.../FTMY/required/RCP8.5/Seattle/fTMY_Washington_King_B5303301_1980_1999.epw
    → scenario='RCP8.5' (폴더에서), period='1980_1999'
    """
    nm    = os.path.basename(f).replace('.epw', '')
    parts = nm.split('_')
    years = [p for p in parts if p.isdigit() and len(p) == 4]
    period = '_'.join(years) if len(years) >= 2 else 'unknown'
    # 폴더 경로에서 RCP 추출 (RCP로 시작하는 폴더명)
    rcp   = next((part for part in Path(f).parts
                  if part.startswith('RCP')), ftmy_scenario)
    key   = (rcp, period)
    return {'scenario': rcp, 'year': period,
            'group_key': key, 'label': f'{rcp}_{period}'}

def parse_ftmy_direct(f):
    """
    USA_WA_Port.Angeles-Fairchild.Intl.AP_Ensemble_ssp126_2050.epw
    → scenario='SSP126', year=2050
    """
    nm = os.path.basename(f).replace('.epw', '')
    scen_raw, yr = 'unknown', 0
    if '_Ensemble_' in nm:
        _, rest  = nm.split('_Ensemble_', 1)
        parts    = rest.split('_')
        raw      = parts[0].upper()
        yr       = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
        scen_raw = next((k for k in scenario_palette
                         if k.lower() == raw.lower()), raw)
    return {'scenario': scen_raw, 'year': yr,
            'group_key': (scen_raw, yr),
            'label': clean_label(scen_raw, yr)}



# ── Baseline 로드 ─────────────────────────────────────────────────────
base_epw = glob.glob(str(Path(base_epw_dir) / '*.epw'))
if not base_epw:
    raise FileNotFoundError(f'Baseline EPW 없음: {base_epw_dir}')
base_epw = base_epw[0]
df_base  = conv_epw(base_epw)
print(f'\nBaseline: {os.path.basename(base_epw)}')


# ── 비교 파일 로드 (모드별) ───────────────────────────────────────────
if COMPARE_MODE == 'mews':
    epw_list = glob.glob(str(Path(mews_dir) / '*.epw'))
    parser   = parse_mews
    mode_label = 'MEWS'

elif COMPARE_MODE == 'famy':
    epw_list = glob.glob(str(Path(famy_dir) / '*.epw'))
    parser   = parse_famy
    mode_label = 'fAMY'

elif COMPARE_MODE == 'ftmy':
    # ── 기존 코드 (required/RCP8.5/ 경로) ──────────────── 기존 유지
    ftmy_dir  = ftmy_base + f'{ftmy_scenario}/{test_loc}/'
    epw_list  = glob.glob(str(Path(ftmy_dir) / '*.epw'))
    epw_list += glob.glob(str(Path(ftmy_dir) / '**' / '*.epw'), recursive=True)
    epw_list  = sorted(set(f for f in epw_list
                           if os.path.basename(f).lower().startswith('ftmy')))
    parser     = parse_ftmy
    mode_label = 'fTMY'

# =============================================================================
#     # ── 신규: 직접 생성 fTMY (FTMY/{city}/) ─────────────────── 추가
#     if not epw_list and os.path.exists(ftmy_direct_dir):
#         epw_list = sorted(glob.glob(str(Path(ftmy_direct_dir) / '*.epw')))
#         parser     = parse_ftmy_direct
#         mode_label = 'fTMY (Generated, {ftmy_scenario})'
#         print(f'직접 생성 fTMY 사용: {ftmy_direct_dir} ({len(epw_list)}개)')
# =============================================================================

    if not epw_list:
        raise FileNotFoundError(
            f'fTMY EPW 파일 없음:\n'
            f'  기존 경로: {ftmy_dir}\n'
            f'  신규 경로: {ftmy_direct_dir}')

elif COMPARE_MODE == 'ftmy_direct':
    # 직접 생성 fTMY (FTMY/{city}/)
    if not os.path.exists(ftmy_direct_dir):
        raise FileNotFoundError(
            f'fTMY Direct 폴더 없음: {ftmy_direct_dir}')
    epw_list = sorted(glob.glob(str(Path(ftmy_direct_dir) / '*.epw')))
    if not epw_list:
        raise FileNotFoundError(
            f'fTMY Direct EPW 파일 없음: {ftmy_direct_dir}')
    parser     = parse_ftmy_direct
    mode_label = 'fTMY'
    print(f'직접 생성 fTMY: {ftmy_direct_dir} ({len(epw_list)}개)')

else:
    raise ValueError(f"COMPARE_MODE는 'mews'|'famy'|'ftmy' 중 하나여야 해요: {COMPARE_MODE}")

if not epw_list:
    raise FileNotFoundError(f'{mode_label} EPW 파일 없음: '
                            f'{mews_dir if COMPARE_MODE=="mews" else famy_dir if COMPARE_MODE=="famy" else ftmy_dir}')

# 파싱 + 로드
file_meta = []
print(f'\n{mode_label} 파일 파싱 중...')
for f in sorted(epw_list):
    try:
        meta = parser(f)
        meta['df'] = conv_epw(f)
        file_meta.append(meta)
    except Exception as e:
        print(f'  ⚠ 건너뜀: {os.path.basename(f)} → {e}')




# ────────────────────────────────────────────────────────────────────

# 그룹핑
scen_groups = {}
for m in file_meta:
    scen_groups.setdefault(m['group_key'], []).append(m['df'])
scen_keys = sorted(scen_groups.keys())

print(f'\n{mode_label} EPW: {len(file_meta)}개, {len(scen_keys)}개 그룹')
for key in scen_keys:
    lbl = file_meta[next(i for i,m in enumerate(file_meta) if m['group_key']==key)]['label']
    print(f'  {lbl:20s}: {len(scen_groups[key])}개')



# ── ΔT 추출 ──────────────────────────────────────────────────────────
def get_daily(df):
    d = df[COL].resample('1D').agg(['max','min'])
    d.columns = ['TMAX','TMIN']
    d['month'] = d.index.month
    return d

def compute_thresh(df_base):
    daily = get_daily(df_base)
    rows  = []
    for m in range(1, 13):
        sub = daily[daily['month']==m]
        rows.append({'month':m,
                     'TMAX_p':   sub['TMAX'].quantile(HW_PCTL/100),
                     'TMIN_p':   sub['TMIN'].quantile(CS_PCTL/100),
                     'TMAX_mean':sub['TMAX'].mean(),
                     'TMIN_mean':sub['TMIN'].mean()})
    return pd.DataFrame(rows)

def extract_dT(df, thresh, etype='hw'):
    daily  = get_daily(df)
    merged = daily.merge(thresh, on='month', how='left').dropna()
    result = {}
    for m in range(1, 13):
        sub = merged[merged['month']==m]
        if etype == 'hw':
            ext = sub[sub['TMAX'] > sub['TMAX_p']]
            dt  = (ext['TMAX'] - ext['TMAX_mean']).values
        else:
            ext = sub[sub['TMIN'] < sub['TMIN_p']]
            dt  = (ext['TMIN'] - ext['TMIN_mean']).values
        result[m] = dt
    return result

thresh      = compute_thresh(df_base)
hist_dT_hw  = extract_dT(df_base, thresh, 'hw')
hist_dT_cs  = extract_dT(df_base, thresh, 'cs')
comp_dT_hw  = [extract_dT(m['df'], thresh, 'hw') for m in file_meta]
comp_dT_cs  = [extract_dT(m['df'], thresh, 'cs') for m in file_meta]

print('\nBaseline 월별 극한일 수 (HW / CS):')
for m in range(1, 13):
    nh = len(hist_dT_hw[m]); nc = len(hist_dT_cs[m])
    print(f"  {MONTH_LABELS[m-1]:>4}: HW={nh:2d}  CS={nc:2d}  "
          f"{'✓' if nh>=3 and nc>=3 else '⚠ 부족(<3)'}")


# ── KS test ──────────────────────────────────────────────────────────
# group_key → label 매핑
key_to_label = {}
for m in file_meta:
    key_to_label[m['group_key']] = m['label']

def compute_ks(hist_dT, comp_dT_list, fm_list):
    keys  = sorted(scen_groups.keys())
    cols  = [key_to_label[k] for k in keys]
    pval  = pd.DataFrame(index=range(1,13), columns=cols, dtype=float)
    kst   = pd.DataFrame(index=range(1,13), columns=cols, dtype=float)

    grp_dT = {}
    for meta, dT in zip(fm_list, comp_dT_list):
        grp_dT.setdefault(meta['group_key'], []).append(dT)

    for key in keys:
        col  = key_to_label[key]
        dTs  = grp_dT.get(key, [])
        for m in range(1, 13):
            h = hist_dT[m]
            w = np.concatenate([d[m] for d in dTs]) if dTs else np.array([])
            if len(h)<3 or len(w)<3:
                pval.loc[m,col] = np.nan; kst.loc[m,col] = np.nan
            else:
                ks, p = stats.ks_2samp(h, w)
                pval.loc[m,col] = round(p,6); kst.loc[m,col] = round(ks,6)

    df_pass = pval > 0.05
    tv = pval.notna().sum().sum(); tp = (pval>0.05).sum().sum()
    print(f'  Pass: {tp}/{tv} ({tp/tv*100:.1f}%)' if tv>0 else '  데이터 없음')
    return pval, kst, df_pass

print('\n[HW ΔT KS]'); pval_hw, ks_hw, pass_hw = compute_ks(hist_dT_hw, comp_dT_hw, file_meta)
print('[CS ΔT KS]'); pval_cs, ks_cs, pass_cs = compute_ks(hist_dT_cs, comp_dT_cs, file_meta)

scen_cols  = [key_to_label[k] for k in sorted(scen_groups.keys())]
n_scen     = len(scen_cols)



# 각 파일의 총 시간 수, Month/Day 시퀀스에 빠지거나 중복된 날짜가 있는지 확인
def diagnose_leap(df, label):
    n = len(df)
    md = df[['Month','Day']].drop_duplicates()
    n_days = len(md)
    expected_days = 366 if n == 8784 else 365
    print(f'{label:25s}  시간수={n:5d}  날짜수={n_days:3d}  '
          f'{"OK" if n_days==expected_days else "⚠ 날짜 수 이상"}')
    # 순서상 비어있는 날짜(월-일) 찾기
    full_365 = pd.date_range('2003-01-01','2003-12-31',freq='D')
    have = pd.to_datetime(dict(year=2003, month=md['Month'], day=md['Day']),
                          errors='coerce')
    missing = full_365.difference(have.dropna())
    if len(missing) > 0 and n != 8784:
        print(f'   → 빠진 날짜(월-일 기준): {[d.strftime("%m-%d") for d in missing]}')

diagnose_leap(df_base, 'Baseline')
for key, dfs in scen_groups.items():
    for i, df in enumerate(dfs):
        diagnose_leap(df, f'{key_to_label[key]} #{i}')



# ── ★ Stochastic EPW 기반 최적 Event Window 자동 선정 ────────────────
# NOAA 역사 최극값 기반 초기값을 override
# SSP585 or 가장 극단적 미래 시나리오 파일 기준으로 ΔT 최대 구간 탐색

# =============================================================================
# def find_optimal_event_window(df_base, stoch_dfs, event_type='hw',
#                                window_days=5, top_n=1):
#     base_daily = df_base[COL].resample('1D').agg(['max','min'])
#     base_daily.columns = ['TMAX','TMIN']
# 
#     stoch_vals = np.array([
#         df[COL].resample('1D').agg(['max','min']).values
#         for df in stoch_dfs
#     ])
#     stoch_mean = pd.DataFrame(
#         stoch_vals.mean(axis=0),
#         index=base_daily.index,
#         columns=['TMAX','TMIN'])
# 
#     delta = (stoch_mean['TMAX'] - base_daily['TMAX'] if event_type == 'hw'
#              else base_daily['TMIN'] - stoch_mean['TMIN'])
# 
#     rolling = delta.rolling(window=window_days, center=True).mean()
#     best    = rolling.idxmax() if event_type == 'hw' else rolling.idxmin()
# 
#     start = pd.Timestamp(2004, best.month, best.day) - pd.Timedelta(days=window_days//2)
#     end   = start + pd.Timedelta(days=window_days)
#     return start, end
# 
# =============================================================================
def find_optimal_event_window(df_base, stoch_dfs, event_type='hw',
                               window_days=5, top_n=1):
    base_daily = df_base[COL].resample('1D').agg(['max','min'])
    base_daily.columns = ['TMAX','TMIN']

    stoch_vals = np.array([
        df[COL].resample('1D').agg(['max','min']).values
        for df in stoch_dfs])
    
    stoch_mean = pd.DataFrame(
        stoch_vals.mean(axis=0),
        index=base_daily.index,
        columns=['TMAX','TMIN'])

    # delta = (stoch_mean['TMAX'] - base_daily['TMAX'] if event_type == 'hw'
    #          else base_daily['TMIN'] - stoch_mean['TMIN'])
    delta = (stoch_mean['TMAX'] - base_daily['TMAX'] if event_type == 'hw'
             else stoch_mean['TMIN'] - base_daily['TMIN'])

    rolling = delta.rolling(window=window_days, center=True).mean()
    # 계절 제한 추가
    if event_type == 'hw':
        # HW: 6~9월만 탐색
        rolling = rolling.copy()
        mask = ~rolling.index.month.isin([6, 7, 8, 9])
        rolling[mask] = np.nan
    else:
        # CS: 11~2월만 탐색 (겨울 한정)
        rolling = rolling.copy()
        mask = ~rolling.index.month.isin([12, 1, 2])
        rolling[mask] = np.nan
    best    = rolling.idxmax() if event_type == 'hw' else rolling.idxmin()

    start = pd.Timestamp(BASE_YR, best.month, best.day) - pd.Timedelta(days=window_days//2)
    end   = start + pd.Timedelta(days=window_days)
    return start, end

# 가장 극단적 미래 시나리오 파일 선택 (SSP585 or 마지막 그룹)
extreme_key  = max(scen_groups.keys(),
                   key=lambda k: ('SSP585' in str(k) or 'RCP8.5' in str(k),
                                  k[1] if isinstance(k[1], int) else 0))
extreme_dfs  = scen_groups[extreme_key]

# 파일이 있으면 자동 선정, 없으면 역사 최극값 기반 유지
if extreme_dfs:
    HW_START, HW_END = find_optimal_event_window(df_base, extreme_dfs, 'hw')
    CS_START, CS_END = find_optimal_event_window(df_base, extreme_dfs, 'cs')
    print(f'\n[자동 선정] {key_to_label[extreme_key]} 기준')
    print(f'  HW: {HW_START.date()} ~ {HW_END.date()}')
    print(f'  CS: {CS_START.date()} ~ {CS_END.date()}')


# 레이블별 색상 사전 — 팔레트 매칭 실패 시 matplotlib 기본 색상 cycle 사용
import matplotlib as mpl
_default_colors = [p['color'] for p in mpl.rcParams['axes.prop_cycle']]

# 같은 RCP 시나리오 내 4단계 밝기 구분
# decade 블록별 고정 색상 (연대가 늦을수록 따뜻한 색)
DECADE_COLORS = {
    '2040s': '#2196F3',   # 파랑  — 근미래
    '2050s': '#4CAF50',   # 초록  — 중기
    '2080s': '#FF9800',   # 주황  — 원미래
    '2090s': '#F44336',   # 빨강  — 말기
}



def build_label_colors(labels):
    import matplotlib.colors as mc
    color_map = {}
    dc_idx = 0
    p_pat  = re.compile(r'_(\d{4})_(\d{4})$')   # fTMY 기간 패턴

    # fTMY: coolwarm 그라데이션 (시작연도 기준)
    ftmy_lbls = [(lbl, int(p_pat.search(str(lbl)).group(1)))
                 for lbl in labels if p_pat.search(str(lbl))]
    if ftmy_lbls:
        ftmy_sorted = sorted(ftmy_lbls, key=lambda x: x[1])
        n   = len(ftmy_sorted)
        cm_ = plt.cm.get_cmap('coolwarm')
        for i, (lbl, _) in enumerate(ftmy_sorted):
            color_map[lbl] = cm_(i / max(n - 1, 1))

    # 나머지 (fAMY decade, MEWS, SSP/RCP 팔레트)
    for lbl in labels:
        if lbl in color_map:
            continue
        s = str(lbl)
        # decade 블록 직접 ('RCP8.5_2040s', 'SSP245_2020')
        decade = next((d for d in DECADE_COLORS if d in s), None)
        if decade:
            color_map[lbl] = DECADE_COLORS[decade]; continue
        # 개별 연도 → decade 매핑 ('RCP8.5_2045')
        yr_m = re.search(r'_(\d{4})$', s)
        if yr_m:
            dk = get_decade(int(yr_m.group(1)))
            if dk:
                color_map[lbl] = DECADE_COLORS[dk]; continue
        # SSP/RCP 팔레트 fallback
        matched = next((c for k, c in scenario_palette.items() if k in s), None)
        color_map[lbl] = matched if matched else _default_colors[dc_idx % len(_default_colors)]
        if not matched: dc_idx += 1

    return color_map
# decade별 dark→light 그라데이션 정의 (earlier=dark, later=light)
DECADE_GRADIENT = {
    '2040s': ('#0D47A1', '#90CAF9'),   # 진한파랑 → 연한파랑
    '2050s': ('#1B5E20', '#A5D6A7'),   # 진한초록 → 연한초록
    '2080s': ('#E65100', '#FFCC80'),   # 진한주황 → 연한주황
    '2090s': ('#B71C1C', '#EF9A9A'),   # 진한빨강 → 연한빨강
}

# decade별 마커 모양
DECADE_MARKERS = {
    '2040s': 'o',   # 원
    '2050s': 's',   # 사각형
    '2080s': '^',   # 삼각형
    '2090s': 'D',   # 다이아몬드
}

# fTMY 기간별 마커 (기간 순서대로 할당)
FTMY_MARKERS = ['o', 's', '^', 'D', 'v', 'P']

DECADE_RANGES = {
    '2040s': (2045, 2049),
    '2050s': (2050, 2054),
    '2080s': (2085, 2089),
    '2090s': (2090, 2094),
}

def get_decade(yr):
    for d, (s, e) in DECADE_RANGES.items():
        if s <= yr <= e:
            return d
    return None

def build_gradient_colors(labels):
    """
    fAMY 개별 연도 (RCP8.5_2045)      → decade 내 dark→light 그라데이션
    fTMY 기간 레이블 (RCP8.5_1980_1999) → coolwarm 그라데이션
    MEWS/decade 그룹 레이블 (SSP245_2020, RCP8.5_2040s) → 고정색
    """
    import matplotlib.colors as mc
    color_map = {}
    dc_idx    = 0

    p_pat = re.compile(r'_(\d{4})_(\d{4})$')   # fTMY 기간 패턴
    y_pat = re.compile(r'_(\d{4})$')             # fAMY 개별 연도 패턴

    # ── Step 1: 레이블 분류 ──────────────────────────────────────────
    ftmy_lbls      = []          # fTMY 기간 레이블
    famy_by_decade = {}          # decade 별로 묶인 fAMY 개별 연도
    other_lbls     = []          # MEWS 그룹, decade 블록, 범위 외

    for lbl in labels:
        s = str(lbl)
        if p_pat.search(s):
            # fTMY: 'RCP8.5_1980_1999'
            start_yr = int(p_pat.search(s).group(1))
            ftmy_lbls.append((lbl, start_yr))
        elif y_pat.search(s):
            yr = int(y_pat.search(s).group(1))
            dk = get_decade(yr)
            if dk:
                # fAMY 개별 연도: decade 그룹으로 분류
                famy_by_decade.setdefault(dk, []).append((yr, lbl))
            else:
                other_lbls.append(lbl)
        else:
            other_lbls.append(lbl)

    # ── Step 2: fTMY → coolwarm 그라데이션 ──────────────────────────
    if ftmy_lbls:
        ftmy_sorted = sorted(ftmy_lbls, key=lambda x: x[1])
        n   = len(ftmy_sorted)
        cm_ = plt.cm.get_cmap('coolwarm')
        for i, (lbl, _) in enumerate(ftmy_sorted):
            color_map[lbl] = cm_(i / max(n - 1, 1))

    # ── Step 3: fAMY → decade 내 dark→light 그라데이션 ──────────────
    for dk, yr_lbls in famy_by_decade.items():
        yr_lbls_sorted = sorted(yr_lbls)          # 연도 오름차순
        n          = len(yr_lbls_sorted)
        dark_rgb   = mc.to_rgb(DECADE_GRADIENT[dk][0])
        light_rgb  = mc.to_rgb(DECADE_GRADIENT[dk][1])
        for i, (yr, lbl) in enumerate(yr_lbls_sorted):
            t = i / max(n - 1, 1)                 # 0=진함(earliest) → 1=연함
            color_map[lbl] = tuple(
                dark_rgb[c] + t * (light_rgb[c] - dark_rgb[c])
                for c in range(3))

    # ── Step 4: 나머지 (MEWS 그룹, decade 블록, 범위 외) ────────────
    for lbl in other_lbls:
        if lbl in color_map:
            continue
        s = str(lbl)
        # decade 블록 직접 ('2040s' in 'RCP8.5_2040s')
        decade = next((d for d in DECADE_COLORS if d in s), None)
        if decade:
            color_map[lbl] = DECADE_COLORS[decade]; continue
        # SSP/RCP 팔레트
        matched = next((c for k, c in scenario_palette.items() if k in s), None)
        color_map[lbl] = matched if matched else _default_colors[dc_idx % len(_default_colors)]
        if not matched: dc_idx += 1

    return color_map

label_colors = build_label_colors(scen_cols)
print('레이블-색상 매핑:')
for lbl, clr in label_colors.items():
    print(f'  {lbl}: {clr}')


# ── 추가 검증 ─────────────────────────────────────────────────────────
def window(df, s, e): return df.loc[s:e, COL]

def run_stats(na, a, nb, b):
    a = np.array(a,dtype=float); a=a[~np.isnan(a)]
    b = np.array(b,dtype=float); b=b[~np.isnan(b)]
    ks,kp = stats.ks_2samp(a,b)
    _,mp  = stats.mannwhitneyu(a,b,alternative='two-sided')
    ad,cv,_ = stats.anderson_ksamp([a,b])
    return {'comparison':f'{na} vs. {nb}',
            'n_a':len(a),'n_b':len(b),
            'mean_a':round(a.mean(),2),'mean_b':round(b.mean(),2),
            'KS stat':round(ks,4),'KS p':round(kp,6),
            'KS result':'Different' if kp<0.05 else 'Similar',
            'MW p':round(mp,6),'AD stat':round(ad,4),
            'Energy dist':round(stats.energy_distance(a,b),4)}

hw_rows,cs_rows = [],[]
for key, dfs in scen_groups.items():
    lbl = key_to_label[key]
    hw_rows.append(run_stats('Baseline', window(df_base,HW_START,HW_END), lbl,
                             np.concatenate([window(d,HW_START,HW_END).values for d in dfs])))
    cs_rows.append(run_stats('Baseline', window(df_base,CS_START,CS_END), lbl,
                             np.concatenate([window(d,CS_START,CS_END).values for d in dfs])))
df_hw_test = pd.DataFrame(hw_rows).set_index('comparison')
df_cs_test = pd.DataFrame(cs_rows).set_index('comparison')

peak = {key: np.mean([get_daily(df)['TMAX'].max() for df in dfs])
        for key, dfs in scen_groups.items()}

# Return period
# ── Return period / 관측 최대값 ─────────────────────────────────────
rp_rows = []
for key, dfs in scen_groups.items():
    maxes = np.array([get_daily(df)['TMAX'].max() for df in dfs])
    if len(maxes) == 0:
        continue
    lbl = key_to_label[key]
    yr  = key[1] if isinstance(key[1], int) else 0

    if len(maxes) >= 3:
        # Gumbel fit 가능 (MEWS 다수 realization)
        try:
            lg, sg = gumbel_r.fit(maxes)
            for rp in [10, 50]:
                rp_rows.append({'Label': lbl, 'Year': yr,
                                'Return Period': rp,
                                'Est. TMAX (°C)': round(gumbel_r.ppf(1-1/rp, lg, sg), 1)})
        except Exception:
            pass
    else:
        # 단일 파일 (fAMY/fTMY): 관측 최대값 직접 사용
        rp_rows.append({'Label': lbl, 'Year': yr,
                        'Return Period': 'obs_max',
                        'Est. TMAX (°C)': round(float(maxes.mean()), 1)})

df_rp = pd.DataFrame(rp_rows)


# ── Ensemble 일관성 (realization 2개 이상일 때만) ──────────────────
con_rows = []
for key, dfs in scen_groups.items():
    if len(dfs) < 2:
        continue   # fTMY/fAMY (단일 파일) skip
    pp = [stats.ks_2samp(window(d1, HW_START, HW_END).values,
                         window(d2, HW_START, HW_END).values)[1]
          for d1, d2 in combinations(dfs, 2)]
    con_rows.append({'Label'        : key_to_label[key],
                     'Consistent(%)': round(np.mean(np.array(pp) > 0.05) * 100, 1),
                     'Mean KS p'    : round(np.mean(pp), 4)})
df_con = pd.DataFrame(con_rows)   # realization 없으면 빈 DataFrame

if not df_con.empty:
    print('\n[Ensemble 일관성]')
    print(df_con.to_string(index=False))
else:
    print(f'\n[Ensemble 일관성] skip ({mode_label}: realization 1개)')


#%% Figures

# Figure font sizes
suptitle_size = 30
subtitle_size = 25
axis_font_size = 20
tick_size = 20
legend_size = 18

plt.rcParams['font.family'] = 'Times New Roman'



#Figure 1: Annual temperature variation + CDF  (2 rows x 1 col)
fig1, axes = plt.subplots(2, 1, figsize=(24, 12), dpi=300)
fig1.suptitle(f'Baseline (TMYx) vs. Future EPW ({mode_label}): {test_loc}',
              fontsize=suptitle_size, fontweight='bold')

# Annual temperature
ax = axes[0]
base_daily_mean = df_base[COL].resample('1D').mean()
ax.plot(base_daily_mean.index, base_daily_mean.values,
        color='gray', lw=1.8, label='Baseline (TMYx)', zorder=5)

for key, dfs in sorted(scen_groups.items()):
    clr = label_colors.get(key_to_label[key])
    lbl = key_to_label[key]
    daily_means = np.array(
        [df[COL].resample('1D').mean().reindex(base_daily_mean.index).values
         for df in dfs], dtype=float)
    ax.fill_between(base_daily_mean.index,
                    np.nanmin(daily_means, axis=0), np.nanmax(daily_means, axis=0),
                    color=clr, alpha=0.15)
    ax.plot(base_daily_mean.index, np.nanmean(daily_means, axis=0),
            color=clr, lw=1.0, label=lbl)
# =============================================================================
# 
# # ── 시나리오별 절대(hourly) 최고/최저 지점 찾기 (baseline 제외) ─────
# abs_max = {'val': -np.inf}
# abs_min = {'val':  np.inf}
# 
# for key, dfs in sorted(scen_groups.items()):
#     lbl = key_to_label[key]
#     clr = label_colors.get(lbl)
#     for df in dfs:
#         s = df[COL]
#         i_max, i_min = s.idxmax(), s.idxmin()
#         if s.loc[i_max] > abs_max['val']:
#             abs_max = {'val': s.loc[i_max], 'date': i_max, 'label': lbl, 'color': clr}
#         if s.loc[i_min] < abs_min['val']:
#             abs_min = {'val': s.loc[i_min], 'date': i_min, 'label': lbl, 'color': clr}
#     abs_max['color'] = abs_max['color'] if abs_max['color'] else 'black'
#     abs_min['color'] = abs_min['color'] if abs_min['color'] else 'black'
# print('MAX:', abs_max)
# print('MIN:', abs_min)
# 
# # ── 화살표 주석 ───────────────────────────────────────────────────────
# ax.annotate(
#     f"{abs_max['label']}\n{abs_max['val']:.1f}°C ({abs_max['date'].strftime('%m-%d')})",
#     xy=(abs_max['date'], abs_max['val']),
#     xytext=(30, 20), textcoords='offset points',
#     fontsize=8, fontweight='bold', color='black',
#     arrowprops=dict(arrowstyle='->', color='black', lw=1.3),
#     zorder=15, annotation_clip=False)
# 
# ax.annotate(
#     f"{abs_min['label']}\n{abs_min['val']:.1f}°C ({abs_min['date'].strftime('%m-%d')})",
#     xy=(abs_min['date'], abs_min['val']),
#     xytext=(30, -25), textcoords='offset points',
#     fontsize=8, fontweight='bold', color='black',
#     arrowprops=dict(arrowstyle='->', color='black', lw=1.3),
#     zorder=15, annotation_clip=False)
# 
# =============================================================================
# ax.axvspan(HW_START, HW_END, color='orange', alpha=0.12, label='HW window')
# ax.axvspan(CS_START, CS_END, color='skyblue', alpha=0.15, label='CS window')
ax.set_title(f'Annual Daily-Mean Temperature', fontsize=subtitle_size)
ax.set_ylabel('Dry Bulb Temperature [°C]', fontsize=axis_font_size)
ax.tick_params(axis='both', labelsize=tick_size)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
ax.legend(fontsize=legend_size, ncol=3,
          loc='upper left',
          bbox_to_anchor=(0, 1),
          framealpha=0.8)
ax.grid(alpha=0.3)

# ── 시나리오별: 실선(daily-mean 평균) + 음영(실제 TMAX/TMIN 전체 범위) ─
scen_mean_series = {}
scen_range = {}

for key, dfs in sorted(scen_groups.items()):
    clr = label_colors.get(key_to_label[key])
    lbl = key_to_label[key]

    # 실선: 기존과 동일 — realization들의 daily-mean을 평균
    daily_means = np.array(
        [df[COL].resample('1D').mean().reindex(base_daily_mean.index).values
         for df in dfs], dtype=float)
    mean_line = pd.Series(np.nanmean(daily_means, axis=0), index=base_daily_mean.index)

    # 음영: daily-mean의 범위가 아니라, 모든 realization의 실제 TMAX/TMIN 범위
    daily_list = [get_daily(df) for df in dfs]   # 각 realization의 daily TMAX/TMIN
    tmax_all = pd.concat([d['TMAX'] for d in daily_list], axis=1).reindex(base_daily_mean.index)
    tmin_all = pd.concat([d['TMIN'] for d in daily_list], axis=1).reindex(base_daily_mean.index)
    range_max = tmax_all.max(axis=1)   # 그날 여러 realization 중 가장 더웠던 순간(TMAX)의 최댓값
    range_min = tmin_all.min(axis=1)   # 그날 여러 realization 중 가장 추웠던 순간(TMIN)의 최솟값

    scen_mean_series[key] = mean_line
    scen_range[key] = {'max': range_max, 'min': range_min}

    ax.fill_between(base_daily_mean.index, range_min, range_max,
                    color=clr, alpha=0.15)
    ax.plot(base_daily_mean.index, mean_line, color=clr, lw=1.0, label=lbl)

# heat and cold peak
hw_key = max(scen_range, key=lambda k: scen_range[k]['max'].max())
hw_series = scen_range[hw_key]['max']
hw_idx = hw_series.idxmax()
hw_info = {'val': hw_series.loc[hw_idx], 'date': hw_idx, 'label': key_to_label[hw_key],
           'color': label_colors.get(key_to_label[hw_key]) or 'black'}

cs_key = min(scen_range, key=lambda k: scen_range[k]['min'].min())
cs_series = scen_range[cs_key]['min']
cs_idx = cs_series.idxmin()
cs_info = {'val': cs_series.loc[cs_idx], 'date': cs_idx, 'label': key_to_label[cs_key],
           'color': label_colors.get(key_to_label[cs_key]) or 'black'}


y_min, y_max = ax.get_ylim()
margin = (y_max - y_min) * 0.12   # 위아래 12% 여유
ax.set_ylim(y_min - margin, y_max + margin)

y_hw = 0.96 
y_cs = 0.03

x_cs_f = 0.25
x_cs_b = 0.85

if cs_info['date'].month <= 6:
    x_loc = x_cs_f
else:
    x_loc = x_cs_b

print(cs_info['date'].month)
print(x_loc)

# Hottest day
ax.annotate(
    f"Hottest day: {hw_info['date'].strftime('%m-%d')} ({hw_info['label']}, {hw_info['val']:.1f}°C)",
    xy=(hw_info['date'], hw_info['val']), xycoords='data',
    xytext=(0.55, y_hw), textcoords='axes fraction',
    ha='center', va='top',
    fontsize=tick_size, fontweight='bold', color='black',
    arrowprops=dict(arrowstyle='->', color='black', lw=1.3,
                    connectionstyle='arc3,rad=0.15'),
    )

# Coldest day
ax.annotate(
    f"Coldest day: {cs_info['date'].strftime('%m-%d')} ({cs_info['label']}, {cs_info['val']:.1f}°C)",
    xy=(cs_info['date'], cs_info['val']), xycoords='data',
    xytext=(x_loc, y_cs), textcoords='axes fraction',
    ha='center', va='bottom',
    fontsize=tick_size, fontweight='bold', color='black',
    arrowprops=dict(arrowstyle='->', color='black', lw=1.3,
                    connectionstyle='arc3,rad=-0.15'),
    )

# CDF plot
ax = axes[1]
base_s = np.sort(df_base[COL].values)
ax.plot(base_s, np.linspace(0,1,len(base_s)), color='gray', lw=2, label='Baseline (TMYx)')
for key, dfs in sorted(scen_groups.items()):
    all_ = np.sort(np.concatenate([df[COL].values for df in dfs]))
    ax.plot(all_, np.linspace(0,1,len(all_)),
            color=label_colors.get(key_to_label[key]), lw=1, alpha=0.7,
            label=key_to_label[key])
ax.set_title('Annual Temperature CDF', fontsize=subtitle_size)
ax.set_xlabel('Dry Bulb Temperature [°C]', fontsize=axis_font_size)
ax.set_ylabel('Cumulative Distribution Function', fontsize=axis_font_size)
ax.tick_params(axis='both', labelsize=tick_size)
ax.legend(fontsize=legend_size, ncol=2,
          loc='upper left',
          bbox_to_anchor=(0, 1),
          framealpha=0.8)
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(result_dir+'Fig1_annual_temp_CDF.png', dpi=300, bbox_inches='tight')
plt.show()


#%% Figure 2

# Figure font sizes
suptitle_size = 20
subtitle_size = 17
axis_font_size = 13
tick_size = 12
legend_size = 12

# pass/fail heatmap
cmap_pf = ListedColormap(['#F44336', '#4CAF50'])
cell_h  = max(0.55, 4.0 / n_scen)  
fig2, axes2 = plt.subplots(1, 2,
                            figsize=(16, max(5, n_scen * cell_h + 1.5)),
                            dpi=300)
fig2.suptitle(
    f'ΔT KS Test: {test_loc}  [{mode_label}] (Baseline: TMYx)\n'
    f'Normal(p>0.05): No significant climate change / Extreme (p≤0.05): Significant climate change',
    fontsize= suptitle_size, fontweight='bold')

for ax, pv, pf, lbl in [(axes2[0], pval_hw, pass_hw, 'Heat Wave'),
                         (axes2[1], pval_cs, pass_cs, 'Cold Snaps')]:
    pi   = pf[scen_cols].values.astype(float)
    pv_v = pv[scen_cols].values.astype(float)

    pi[np.isnan(pv_v)] = np.nan

    # pcolormesh: NaN = gray, extreme weather is less than 3 days in a month, 
    # cannot perform KS test due to lack of data
    cmap_with_nan = plt.cm.colors.ListedColormap(['#FF1100', '#01851B'])
    cmap_with_nan.set_bad(color='#EBEBEB')   

    mk = np.ma.masked_invalid(pi)
    ax.pcolormesh(np.arange(13), np.arange(n_scen + 1), mk.T,
                  cmap=cmap_with_nan, vmin=0, vmax=1,
                  edgecolors='#4F4F4F', linewidth=0.05)

    fs = max(7, min(10, int(60 / n_scen)))
    for i in range(12):
        for j in range(n_scen):
            v = pi[i, j]
            p = pv_v[i, j]
            if np.isnan(v):
                # lacks of data
                ax.text(i+0.5, j+0.5, 'N/A',
                        ha='center', va='center', fontsize=fs,
                        color='#555555', style='italic')
            else:
                result = 'Normal' if v == 1 else 'Extreme'
                p_str  = f'({p:.3f})' if not np.isnan(p) else ''
                ax.text(i+0.5, j+0.5, f'{result}\n{p_str}',
                        ha='center', va='center', fontsize=fs,
                        fontweight='bold', color='white')

    ax.set_xticks(np.arange(12) + 0.5)
    ax.set_xticklabels(MONTH_LABELS, fontsize= tick_size)
    ax.set_yticks(np.arange(n_scen) + 0.5)
    ax.set_yticklabels(scen_cols, fontsize= tick_size)
    ax.set_xlabel('Month', fontsize = axis_font_size)
    ax.set_ylabel('Scenario / Period', fontsize = axis_font_size)
    tp = int(np.nansum(pi == 1)); tot = int(np.sum(~np.isnan(pi)))
    ax.set_title(f'{lbl}\n'
                 'Green: Normal  Red: Extreme  Gray: N/A (Limited data)'
                 if tot > 0 else f'{lbl} — No data', fontsize = subtitle_size)

plt.tight_layout()
plt.savefig(result_dir + 'Fig2_passfail_heatmap.png', dpi= 300, bbox_inches='tight')
plt.show()

#%% Scenario analysis
fig3, axes3 = plt.subplots(1, 2, figsize=(14, 5), dpi=300)
fig3.suptitle(f'Scenario Analysis: {test_loc} [{mode_label}]',
              fontsize= suptitle_size, fontweight='bold')

ax = axes3[0]
base_tmax_max = get_daily(df_base)['TMAX'].max()

if COMPARE_MODE == 'mews':
    # line plot: SSP trends by year
    scen_by_type = {}
    for key, dfs in scen_groups.items():
        scen_str = key[0]   # 'TMYx.2007-2021SSP245' etc.
        yr       = key[1]
        ssp_key  = next((k for k in scenario_palette if k in str(scen_str)), 'unknown')
        scen_by_type.setdefault(ssp_key, []).append((yr, peak[key]))

    for ssp, yr_vals in sorted(scen_by_type.items()):
        yr_vals_sorted = sorted(yr_vals)
        yrs  = [v[0] for v in yr_vals_sorted]
        vals = [v[1] for v in yr_vals_sorted]
        ax.plot(yrs, vals, marker='o', color=label_colors.get(ssp), lw=2, label=ssp)
    ax.axhline(base_tmax_max, color='gray', lw=2, ls='--',
               label=f'Baseline (TMYx, {base_tmax_max:.1f}°C)')
    ax.set_xlabel('Future Year', fontsize = axis_font_size)
    actual_yrs = sorted({k[1] for k in scen_groups.keys()})
    ax.set_xticks(actual_yrs)
    ax.set_xticklabels([str(y) for y in actual_yrs], fontsize = tick_size)
    ax.set_title('Scenario ordering (SSP585 > SSP245)', fontsize = subtitle_size)
    ax.legend(fontsize=legend_size) 
else:
    # bar chart: fTMY and fAMY, comparison by year

    # generate (peak-key) individual label by each file
    file_peaks_indiv = {}
    for m in file_meta:
        # use individual label by year group
        indiv_lbl = f"{m['scenario']}_{m['year']}"   
        file_peaks_indiv[indiv_lbl] = get_daily(m['df'])['TMAX'].max()

    # sort by year
    labels_sorted = sorted(file_peaks_indiv.keys(),
                           key=lambda x: int(x.rsplit('_', 1)[-1]))

    # build individual color label with the color gradient
    # (famy는 단일 색상으로 통일, 그 외(fTMY 등)는 decade 그라데이션 유지)
    if COMPARE_MODE == 'famy':
        all_colors_indiv = {lbl: FAMY_UNIFORM_COLOR for lbl in labels_sorted}
    else:
        all_colors_indiv = build_gradient_colors(labels_sorted)
    
    # bar chart
    for lbl in labels_sorted:
        ax.bar(lbl, file_peaks_indiv[lbl],
               color=all_colors_indiv.get(lbl, '#2194FC'),
               alpha=0.85, edgecolor='black', lw=0.5)

    # ── famy: 전체 추세선 (연도 경과에 따른 선형 추세) ──────────────
    if COMPARE_MODE == 'famy' and len(labels_sorted) >= 2:
        trend_x = np.arange(len(labels_sorted))
        trend_y = [file_peaks_indiv[lbl] for lbl in labels_sorted]
        z = np.polyfit(trend_x, trend_y, 1)
        ax.plot(trend_x, np.poly1d(z)(trend_x), color='black', lw=1.5, ls='-.',
                zorder=6, label='Trend (linear)')

    ax.axhline(base_tmax_max, color='gray', lw=1, ls='--')
    ax.tick_params(axis='x', rotation=45, labelsize = tick_size)
    ax.set_title('Mean Annual Peak Tmeperature by Year'
                 + ('' if COMPARE_MODE == 'famy' else '\n(Color-mapped by decade)'),
                 fontsize = subtitle_size)

    import matplotlib.patches as mpatches
    legend_patches = []
    if COMPARE_MODE == 'famy':
        legend_patches.append(mpatches.Patch(color=FAMY_UNIFORM_COLOR, label='fAMY'))
        legend_patches.append(plt.Line2D([0],[0], color='black', lw=1.5, ls='-.',
                               label='Trend (linear)'))
    else:
        for dk, (dark_c, light_c) in DECADE_GRADIENT.items():

            # rep color: medium
            import matplotlib.colors as mc
            mid = tuple((mc.to_rgb(dark_c)[i] + mc.to_rgb(light_c)[i]) / 2 for i in range(3))
            legend_patches.append(mpatches.Patch(color=mid, label=dk))
    legend_patches.append(plt.Line2D([0],[0], color='gray', ls='--',
                           label=f'Baseline (TMYx, {base_tmax_max:.1f}°C)'))
    ax.legend(handles=legend_patches, fontsize=legend_size)

ax.set_ylabel('Mean Annual Peak Temperature (°C)', fontsize = axis_font_size)
ax.grid(alpha=0.3, axis='y')


ax = axes3[1]
if not df_rp.empty or file_meta:
    if COMPARE_MODE == 'mews':
        # line plot
        rp_by_type = {}
        for _, row in df_rp.iterrows():
            ssp = next((k for k in scenario_palette if k in str(row['Label'])), 'unknown')
            rp_by_type.setdefault((ssp, row['Return Period']), []).append(
                (row['Year'], row['Est. TMAX (°C)']))
        for (ssp, rp), yr_vals in sorted(rp_by_type.items()):
            yr_vals_sorted = sorted(yr_vals)
            yrs  = [v[0] for v in yr_vals_sorted]
            vals = [v[1] for v in yr_vals_sorted]
            # ax.plot(yrs, vals, marker='o', color=label_colors.get(ssp),
            #         ls='--' if rp == 10 else '-', lw=1.5, label=f'{ssp} {rp}yr')
            ax.plot(yrs, vals, marker='o',
        color=label_colors.get(
            ssp,
            next((c for k, c in scenario_palette.items() if k in str(ssp)), '#607D8B')
        ),
        
        ls='--' if rp == 10 else '-', lw=1.5,
        label=f'{ssp} {rp}yr')
        ax.set_xlabel('Future Year', fontsize = axis_font_size)
        ax.set_xticks(actual_yrs)
        ax.tick_params(axis = 'both', labelsize = tick_size)
        ax.set_xticklabels([str(y) for y in actual_yrs])
        ax.set_title('Return Period Analysis\n-- =10yr  — =50yr', fontsize = subtitle_size)
        ax.legend(fontsize=legend_size, ncol=2)
        ax.grid(alpha=0.3, axis='y')
    else:
        period_pattern = re.compile(r'_(\d{4})_(\d{4})$')
        period_lbls    = [(lbl, int(period_pattern.search(str(lbl)).group(1)))
                          for lbl in labels_sorted if period_pattern.search(str(lbl))]
        is_ftmy = len(period_lbls) > 0

        if is_ftmy:
            # fTMY: 기간별 고유 색상(coolwarm) 바 차트
            ftmy_sorted = sorted(period_lbls, key=lambda x: x[1])
            import matplotlib.patches as mpatches
            legend_handles = []

            for idx, (lbl, start_yr) in enumerate(ftmy_sorted):
                val  = file_peaks_indiv.get(lbl, None)
                if val is None: continue
                delta_val = val - base_tmax_max   # ← baseline 대비 변화량(ΔPeak)으로 표시
                clr  = all_colors_indiv.get(lbl, '#607D8B')
                period_name = '_'.join(str(lbl).split('_')[-2:])   # '1980_1999'
                ax.bar([lbl], [delta_val], color=clr,
                       zorder=3, edgecolor='black', lw=0.5)
                legend_handles.append(
                    mpatches.Patch(color=clr, label=period_name))

            legend_handles.append(
                plt.Line2D([0],[0], color='gray', ls='--',
                           label='Baseline (Δ=0°C)'))
            ax.legend(handles=legend_handles, fontsize=7)

        else:
            # fAMY: 단일 색상 바 차트 + 추세선
            plotted_labels = set()
            delta_vals = []
            for lbl in labels_sorted:
                val       = file_peaks_indiv[lbl]
                delta_val = val - base_tmax_max   # ← baseline 대비 변화량(ΔPeak)으로 표시
                clr  = all_colors_indiv.get(lbl, '#607D8B')
                ax.bar([lbl], [delta_val], color=clr,
                       zorder=3, edgecolor='black', lw=0.5)
                delta_vals.append(delta_val)

            # ── famy: 전체 추세선 (연도 경과에 따른 선형 추세) ──────
            if COMPARE_MODE == 'famy' and len(labels_sorted) >= 2:
                trend_x = np.arange(len(labels_sorted))
                z = np.polyfit(trend_x, delta_vals, 1)
                ax.plot(trend_x, np.poly1d(z)(trend_x), color='black', lw=1.5,
                        ls='-.',zorder=6,
                        label='Trend (linear)')

            import matplotlib.patches as mpatches
            import matplotlib.colors as mc
            legend_handles = []
            if COMPARE_MODE == 'famy':
                legend_handles.append(mpatches.Patch(color=FAMY_UNIFORM_COLOR, label='fAMY'))
                legend_handles.append(plt.Line2D([0],[0], color='black', lw=2, ls='-.',
                                       label='Trend (linear)'))
            else:
                for dk, (dark_c, light_c) in DECADE_GRADIENT.items():
                    mid = tuple((mc.to_rgb(dark_c)[i] + mc.to_rgb(light_c)[i]) / 2
                                for i in range(3))
                    legend_handles.append(
                        mpatches.Patch(color=mid, label=dk))
            legend_handles.append(
                plt.Line2D([0],[0], color='gray', ls='--',
                           label='Baseline (Δ=0°C)'))
            ax.legend(handles=legend_handles, fontsize=legend_size)

        ax.tick_params(axis='x', rotation=45)
        ax.set_title('Peak Temperature Increase vs. Baseline'
                     + ('' if COMPARE_MODE == 'famy' else '\n(Color-mapped by period/decade)'),
                     fontsize = subtitle_size)
        ax.axhline(0, color='gray', lw=1.5, ls='--')
        ax.set_ylabel('ΔPeak Temperature vs. Baseline (°C)', fontsize = axis_font_size)
        ax.grid(alpha=0.3, axis='y')


else:
    axes3[1].text(0.5, 0.5, 'No data', ha='center', va='center',
                  transform=axes3[1].transAxes, fontsize=12)


# Return period용 Year 컬럼 추가 (MEWS에서 필요)

df_rp = pd.DataFrame(rp_rows) if rp_rows else pd.DataFrame(
    columns=['Label','Return Period','Estimated TMAX (°C)'])
if 'Year' not in df_rp.columns and COMPARE_MODE == 'mews':
    df_rp['Year'] = df_rp['Label'].str.extract(r'_(\d{4})$').astype(float)

plt.tight_layout()
plt.savefig(result_dir+'Fig3_scenario_returnperiod.png', dpi=300, bbox_inches='tight')
plt.show()

#%% save file
df_hw_test.to_csv(result_dir+'hw_ks_test.csv')
df_cs_test.to_csv(result_dir+'cs_ks_test.csv')
pval_hw.to_csv(result_dir+'hw_monthly_pvalue.csv')
pval_cs.to_csv(result_dir+'cs_monthly_pvalue.csv')
pass_hw[scen_cols].to_csv(result_dir+'hw_monthly_passfail.csv')
pass_cs[scen_cols].to_csv(result_dir+'cs_monthly_passfail.csv')
df_rp.to_csv(result_dir+'return_period.csv',         index=False)
if not df_con.empty:
    df_con.to_csv(result_dir+'ensemble_consistency.csv', index=False)

# ── ΔT KS test 전체 결과 요약 테이블 (Fig2 히트맵 정보를 표로 통합) ────
def build_ks_summary_table(pval_df, ks_df, event_label):
    """월×시나리오 매트릭스(pval, KS stat)를 long-format 테이블로 변환.
       classification: p>0.05 → Normal, p<=0.05 → Extreme, NaN → N/A"""
    rows = []
    for col in pval_df.columns:
        for m in range(1, 13):
            p = pval_df.loc[m, col]
            k = ks_df.loc[m, col]
            if pd.isna(p):
                cls = 'N/A'
            elif p > 0.05:
                cls = 'Normal'
            else:
                cls = 'Extreme'
            rows.append({
                'Event Type': event_label,
                'Scenario'  : col,
                'Month'     : MONTH_LABELS[m-1],
                'Month #'   : m,
                'KS statistic': round(k, 4) if pd.notna(k) else np.nan,
                'p-value'     : round(p, 6) if pd.notna(p) else np.nan,
                'Classification': cls
            })
    return pd.DataFrame(rows)

df_ks_summary = pd.concat([
    build_ks_summary_table(pval_hw, ks_hw, 'Heat Wave'),
    build_ks_summary_table(pval_cs, ks_cs, 'Cold Snap'),
], ignore_index=True)

df_ks_summary.to_csv(result_dir + 'deltaT_ks_test_summary.csv', index=False)

# ── (참고용) 시나리오별 요약 — 계절 내 Extreme 비율 ────────────────────
SUMMER_MONTHS = [6, 7, 8, 9]      # HW 물리적으로 기대되는 계절
WINTER_MONTHS = [12, 1, 2]        # CS 물리적으로 기대되는 계절

def summarize_scenario_pass(df_summary, event_label, target_months):
    sub = df_summary[(df_summary['Event Type'] == event_label) &
                     (df_summary['Month #'].isin(target_months))]
    rows = []
    for scen, g in sub.groupby('Scenario'):
        n_valid   = (g['Classification'] != 'N/A').sum()
        n_extreme = (g['Classification'] == 'Extreme').sum()
        rate = n_extreme / n_valid if n_valid > 0 else np.nan
        rows.append({'Scenario': scen, 'Event Type': event_label,
                     'Valid months': n_valid, 'Extreme months': n_extreme,
                     'Extreme rate': round(rate, 2) if pd.notna(rate) else np.nan})
    return pd.DataFrame(rows)

df_scenario_summary = pd.concat([
    summarize_scenario_pass(df_ks_summary, 'Heat Wave', SUMMER_MONTHS),
    summarize_scenario_pass(df_ks_summary, 'Cold Snap', WINTER_MONTHS),
], ignore_index=True)
df_scenario_summary.to_csv(result_dir + 'deltaT_ks_scenario_summary.csv', index=False)

print(f'\nDone → {result_dir}')

#%% generated ftmy fig. 3 plotting
'''
suptitle_size = 20
subtitle_size = 18
axis_font_size = 13
tick_size = 12

'''

if COMPARE_MODE == 'ftmy_direct':

    # ── 색상/마커 설정 ────────────────────────────────────────────────
    # SSP 시나리오 순서 (약함 → 강함)
    SSP_ORDER = ['SSP126', 'SSP245', 'SSP370', 'SSP585']

    # 연도별 색상 패밀리 (시나리오 강도에 따라 연→진)
    YEAR_COLORS = {
        2050: ['#90CAF9', '#42A5F5', '#1E88E5', '#1565C0'],  # 파랑 (연→진)
        2080: ['#EF9A9A', '#EF5350', '#E53935', '#B71C1C'],  # 빨강 (연→진)
    }
    # 연도별 마커 모양 (2050=원, 2080=삼각형)
    YEAR_MARKERS = {2050: 'o', 2080: '^'}

    years_avail = sorted({y for s, y in scen_groups.keys()})
    n_ssp = len(SSP_ORDER)
    n_yr  = len(years_avail)

    # ── peak 계산 (존재하는 그룹만) ──────────────────────────────────
    peak_direct = {}
    for (s, y), dfs in scen_groups.items():
        # 팔레트 키와 매칭 (SSP126, SSP245 등)
        ssp_key = next((k for k in SSP_ORDER if k in str(s).upper()), None)
        if ssp_key:
            peak_direct[(ssp_key, y)] = np.mean(
                [get_daily(df)['TMAX'].max() for df in dfs])

    # ── Figure 생성 ──────────────────────────────────────────────────
    fig3d, axes3d = plt.subplots(1, 2, figsize=(14, 5), dpi=300)
    fig3d.suptitle(
        f'Scenario Analysis: {test_loc}  [{mode_label}]\n'
        '(Categorized by year and scenario)',
        fontsize= suptitle_size, fontweight='bold')

    # ── (좌) 바차트: 연도별 묶음, 시나리오(SSP) 색상, x축에 시나리오 표시 ─
    ax   = axes3d[0]
    import matplotlib.patches as mpatches

    bar_counter = 0
    for yr_idx, yr in enumerate(years_avail):
        clr_list = YEAR_COLORS.get(yr, ['#888888'] * n_ssp)
        trend_x, trend_y = [], []
        for ssp_idx, ssp in enumerate(SSP_ORDER):
            val = peak_direct.get((ssp, yr), None)
            if val is None:
                continue
            lbl = f'{yr}' if ssp_idx == 0 else ''
            ax.bar([f'{ssp}\n{yr}'], [val],
                   color=clr_list[ssp_idx],
                   edgecolor='black', lw=0.8, alpha=0.9,
                   label=lbl, zorder=3)
            trend_x.append(bar_counter)
            trend_y.append(val)
            bar_counter += 1
        # ── 연도별 추세선 ────────────────────────────────────────────
        if len(trend_x) >= 2:
            z = np.polyfit(trend_x, trend_y, 1)
            tx = np.linspace(min(trend_x), max(trend_x), 50)
            ax.plot(tx, np.poly1d(z)(tx),
                    color=clr_list[-1], lw=2, ls=':',
                    marker=YEAR_MARKERS.get(yr, 'o'), markevery=[0, -1],
                    markersize=7, zorder=4, label=f'{yr} trend')

    ax.axhline(base_tmax_max, color='gray', lw=2, ls='--',
               label=f'Baseline (TMYx, {base_tmax_max:.1f}°C)', zorder=3)
    ax.tick_params(axis='x', rotation=30, labelsize= tick_size)
    ax.set_ylabel('Mean Annual Peak Temperature (°C)', fontsize = axis_font_size)
    ax.set_title('Mean Annual Peak Temperature\n(grouped by year, colored by scenario intensity)', fontsize= subtitle_size)
    ax.grid(alpha=0.3, axis='y')

    # 범례 — 연도별 색상 + 추세선 + baseline
    legend_handles = []
    for yr in years_avail:
        clr_list = YEAR_COLORS.get(yr, ['#888888'] * n_ssp)
        mid_clr = clr_list[2] if len(clr_list) > 2 else clr_list[0]  # 중간 강도 색
        legend_handles.append(
            mpatches.Patch(color=mid_clr, label=f'{yr}'))
        legend_handles.append(
            plt.Line2D([0], [0], color=clr_list[-1], lw=2, ls=':',
                       marker=YEAR_MARKERS.get(yr, 'o'), markersize=7,
                       label=f'{yr} trend'))
    legend_handles.append(
        plt.Line2D([0], [0], color='gray', ls='--',
                   label=f'Baseline (TMYx, {base_tmax_max:.1f}°C)'))
    ax.legend(handles=legend_handles, fontsize=legend_size)

    # ── (우) 바차트: baseline 대비 ΔPeak, 연도별 색상 강도 유지 ─────────
    ax = axes3d[1]
    import matplotlib.lines as mlines
    import matplotlib.patches as mpatches

    bar_counter = 0
    for yr_idx, yr in enumerate(years_avail):
        clr_list = YEAR_COLORS.get(yr, ['#888888'] * n_ssp)
        trend_x, trend_y = [], []
        for ssp_idx, ssp in enumerate(SSP_ORDER):
            val = peak_direct.get((ssp, yr), None)
            if val is None:
                continue
            delta_val = val - base_tmax_max   # ← baseline 대비 변화량(ΔPeak)으로 표시
            lbl = f'{yr}' if ssp_idx == 0 else ''
            ax.bar([f'{ssp}\n{yr}'], [delta_val],
                   color=clr_list[ssp_idx],
                   edgecolor='black', lw=0.8, alpha=0.9,
                   label=lbl, zorder=3)
            trend_x.append(bar_counter)
            trend_y.append(delta_val)
            bar_counter += 1
        # ── 연도별 추세선 ────────────────────────────────────────────
        if len(trend_x) >= 2:
            z = np.polyfit(trend_x, trend_y, 1)
            tx = np.linspace(min(trend_x), max(trend_x), 50)
            ax.plot(tx, np.poly1d(z)(tx),
                    color=clr_list[-1], lw=2, ls=':',
                    marker=YEAR_MARKERS.get(yr, 'o'), markevery=[0, -1],
                    markersize=7, zorder=4, label=f'{yr} trend')

    ax.axhline(0, color='gray', lw=1.5, ls='--',
               label='Baseline (Δ=0°C)')
    ax.tick_params(axis='x', rotation=30, labelsize= tick_size)
    ax.set_ylabel('ΔPeak Temperature vs. Baseline (°C)', fontsize = axis_font_size)
    ax.set_title('Peak Temperature Increase vs. Baseline\n(grouped by year, colored by scenario intensity)', fontsize = subtitle_size)
    ax.grid(alpha=0.3, axis='y')

    # 범례 — 연도별 색상 + baseline
    legend_handles = []
    for yr in years_avail:
        clr_list = YEAR_COLORS.get(yr, ['#888888'] * n_ssp)
        mid_clr = clr_list[2] if len(clr_list) > 2 else clr_list[0]  # 중간 강도 색
        legend_handles.append(
            mpatches.Patch(color=mid_clr, label=f'{yr}'))
        legend_handles.append(
            plt.Line2D([0], [0], color=clr_list[-1], lw=2, ls=':',
                       marker=YEAR_MARKERS.get(yr, 'o'), markersize=7,
                       label=f'{yr} trend'))
    legend_handles.append(
        plt.Line2D([0], [0], color='gray', ls='--',
                   label='Baseline (Δ=0°C)'))
    ax.legend(handles=legend_handles, fontsize=legend_size)

    plt.tight_layout()
    plt.savefig(result_dir + 'Fig3_ftmy_direct_scenario.png',
                dpi=300, bbox_inches='tight')
    plt.show()

#%% figure 5


# ── 1. TMYx 기반 90th/10th 임계값 계산 ───────────────────────────────
def compute_tmyx_extreme_thresh(df_base):
    """
    TMYx baseline EPW 월별 90th/10th percentile 임계값
    월별 pooling → 월당 28~31개 데이터로 안정적 추정
    """
    daily = get_daily(df_base)
    rows  = []
    for m in range(1, 13):
        sub = daily[daily['month'] == m]
        rows.append({
            'month'    : m,
            'TMAX_n90' : sub['TMAX'].quantile(0.90),
            'TMIN_n90' : sub['TMIN'].quantile(0.90),
            'TMAX_n10' : sub['TMAX'].quantile(0.10),
            'TMIN_n10' : sub['TMIN'].quantile(0.10),
        })
    return pd.DataFrame(rows)

def count_extreme_days(df_epw, tmyx_thresh, event_type='hw'):
    """
    Villa et al. (2023) Section 2.2.1 정의 기반 극한 이벤트 일수 계산

    HW: TMAX > TMYx TMAX 90th percentile (hot daytime)
     OR TMIN > TMYx TMIN 90th percentile (hot nighttime)

    CS: TMAX < TMYx TMAX 10th percentile (cold daytime)
     OR TMIN < TMYx TMIN 10th percentile (cold nighttime)
    """
    daily = get_daily(df_epw)[['TMAX', 'TMIN']]
    daily['month'] = daily.index.month
    merged = daily.merge(tmyx_thresh, on='month', how='left').dropna()

    if event_type == 'hw':
        extreme = ((merged['TMAX'] > merged['TMAX_n90']) |
                   (merged['TMIN'] > merged['TMIN_n90']))
    else:
        extreme = ((merged['TMAX'] < merged['TMAX_n10']) |
                   (merged['TMIN'] < merged['TMIN_n10']))
    return int(extreme.sum())


# ── 2. Baseline 임계값 + 기준값 계산 ────────────────────────────────
tmyx_thresh = compute_tmyx_extreme_thresh(df_base)
baseline_hw = count_extreme_days(df_base, tmyx_thresh, 'hw')
baseline_cs = count_extreme_days(df_base, tmyx_thresh, 'cs')
print(f'Baseline (TMYx): HW={baseline_hw}일/년  CS={baseline_cs}일/년')


# ── 3. 모드별 데이터 준비 ────────────────────────────────────────────
if COMPARE_MODE == 'famy':
    # fAMY: 개별 연도별 (Fig3 바차트와 동일 방식), 막대는 단일 색상으로 통일
    fm_sorted  = sorted(file_meta, key=lambda x: x['year'])
    labels_f   = [f"{m['scenario']}_{m['year']}" for m in fm_sorted]
    colors_f   = [FAMY_UNIFORM_COLOR] * len(labels_f)
    x_f        = np.arange(len(labels_f))

    hw_vals = [count_extreme_days(m['df'], tmyx_thresh, 'hw') for m in fm_sorted]
    cs_vals = [count_extreme_days(m['df'], tmyx_thresh, 'cs') for m in fm_sorted]
    hw_means, hw_stds = hw_vals, [0] * len(hw_vals)
    cs_means, cs_stds = cs_vals, [0] * len(cs_vals)
    
elif COMPARE_MODE == 'ftmy_direct':
    # Fig3d(Observed Peak Temperature)와 동일한 팔레트: 연도(2050=블루/2080=레드) × SSP 강도(명→암)
    SSP_ORDER_F4 = ['SSP126', 'SSP245', 'SSP370', 'SSP585']
    YEAR_COLORS_F4 = {
        2050: ['#90CAF9', '#42A5F5', '#1E88E5', '#1565C0'],   # 블루, 연→진 (126→585)
        2080: ['#EF9A9A', '#EF5350', '#E53935', '#B71C1C'],   # 레드, 연→진 (126→585)
    }

    keys_sorted = sorted(
        scen_groups.keys(),
        key=lambda k: (k[1], SSP_ORDER_F4.index(
            next((s for s in SSP_ORDER_F4 if s in str(k[0]).upper()), 'SSP126'))))
    labels_f = [key_to_label[k] for k in keys_sorted]
    years_f4 = [k[1] for k in keys_sorted]

    colors_f = []
    for k in keys_sorted:
        yr = k[1]
        ssp_key = next((s for s in SSP_ORDER_F4 if s in str(k[0]).upper()), None)
        ssp_idx = SSP_ORDER_F4.index(ssp_key) if ssp_key else 0
        clr_list = YEAR_COLORS_F4.get(yr, ['#888888'] * len(SSP_ORDER_F4))
        colors_f.append(clr_list[ssp_idx])

    x_f = np.arange(len(keys_sorted))

    hw_means, hw_stds, cs_means, cs_stds = [], [], [], []
    for key in keys_sorted:
        dfs  = scen_groups[key]
        hw_c = [count_extreme_days(df, tmyx_thresh, 'hw') for df in dfs]
        cs_c = [count_extreme_days(df, tmyx_thresh, 'cs') for df in dfs]
        hw_means.append(np.mean(hw_c)); hw_stds.append(np.std(hw_c))
        cs_means.append(np.mean(cs_c)); cs_stds.append(np.std(cs_c))

else:
    # MEWS / fTMY / ftmy_direct: scen_groups 기준 (평균 + 표준편차)
    keys_sorted = sorted(scen_groups.keys())
    labels_f    = [key_to_label[k] for k in keys_sorted]
    colors_f    = [label_colors.get(lbl, '#607D8B') for lbl in labels_f]
    x_f         = np.arange(len(keys_sorted))

    hw_means, hw_stds, cs_means, cs_stds = [], [], [], []
    for key in keys_sorted:
        dfs  = scen_groups[key]
        hw_c = [count_extreme_days(df, tmyx_thresh, 'hw') for df in dfs]
        cs_c = [count_extreme_days(df, tmyx_thresh, 'cs') for df in dfs]
        hw_means.append(np.mean(hw_c)); hw_stds.append(np.std(hw_c))
        cs_means.append(np.mean(cs_c)); cs_stds.append(np.std(cs_c))

# Baseline 대비 변화량 (Δ)
delta_hw = [m - baseline_hw for m in hw_means]
delta_cs = [m - baseline_cs for m in cs_means]

# 콘솔 요약 출력
print(f'\n{"시나리오":20s}  {"HW(일/년)":>10s}  {"ΔHW":>7s}  {"CS(일/년)":>10s}  {"ΔCS":>7s}')
print('─' * 60)
for i, lbl in enumerate(labels_f):
    print(f'{lbl:20s}  {hw_means[i]:>9.1f}일  '
          f'{delta_hw[i]:>+6.1f}일  '
          f'{cs_means[i]:>9.1f}일  '
          f'{delta_cs[i]:>+6.1f}일')


# ── 4. Figure 4 (2×2) ───────────────────────────────────────────────
fig4, axes4 = plt.subplots(1, 2, figsize=(14, 5), dpi=300)
fig4.suptitle(
    f'Extreme Event Frequency: {test_loc}  [{mode_label}]',
    fontsize= suptitle_size, fontweight='bold')

# ── (0,0) HW 절대 발생 일수 ──────────────────────────────────────────
ax = axes4[0]
ax.bar(x_f, hw_means, color=colors_f, alpha=0.85, edgecolor='black', lw=0.5)
if any(s > 0 for s in hw_stds):
    ax.errorbar(x_f, hw_means, yerr=hw_stds,
                fmt='none', color='black', capsize=4, lw=1.2, zorder=5)
# =============================================================================
# if len(x_f) >= 2:
#     z_hw = np.polyfit(x_f, hw_means, 1)
#     ax.plot(x_f, np.poly1d(z_hw)(x_f), color='black', lw=1.5, ls='-.',
#             zorder=6, label='Trend (linear)')
# =============================================================================


if len(x_f) >= 2:
    if COMPARE_MODE == 'ftmy_direct':
        # ── 연도별 추세선 ────────────────────────────────────────────
        for yr in sorted(set(years_f4)):
            idx = [i for i, y in enumerate(years_f4) if y == yr]
            if len(idx) < 2:
                continue
            xs = [x_f[i] for i in idx]
            ys = [hw_means[i] for i in idx]
            clr = YEAR_COLORS_F4.get(yr, ['#888888'] * len(SSP_ORDER_F4))[-1]
            z_hw = np.polyfit(xs, ys, 1)
            tx = np.linspace(min(xs), max(xs), 50)
            ax.plot(tx, np.poly1d(z_hw)(tx), color=clr, lw=2, ls='-.',
                    marker='o', markevery=[0, -1], markersize=6,
                    zorder=6, label=f'{yr} trend')
    else:
        z_hw = np.polyfit(x_f, hw_means, 1)
        ax.plot(x_f, np.poly1d(z_hw)(x_f), color='black', lw=1.5, ls='-.',
                zorder=6, label='Trend (linear)')

ax.axhline(baseline_hw, color='gray', lw=2, ls='--',
           label=f'Baseline TMYx ({baseline_hw} days/yr)')
ax.set_xticks(x_f)
ax.set_xticklabels(labels_f, rotation=45, ha='right', fontsize= tick_size)
ax.set_ylabel('Extreme Hot Days per Year', fontsize = axis_font_size)
ax.set_title('Heat Wave', fontsize = subtitle_size)
ax.legend(fontsize=legend_size)
ax.grid(alpha=0.3, axis='y')
        
# ── (0,1) CS 절대 발생 일수 ──────────────────────────────────────────
ax = axes4[1]
ax.bar(x_f, cs_means, color=colors_f, alpha=0.85, edgecolor='black', lw=0.5)
if any(s > 0 for s in cs_stds):
    ax.errorbar(x_f, cs_means, yerr=cs_stds,
                fmt='none', color='black', capsize=4, lw=1.2, zorder=5)
# =============================================================================
# if len(x_f) >= 2:
#     z_cs = np.polyfit(x_f, cs_means, 1)
#     ax.plot(x_f, np.poly1d(z_cs)(x_f), color='black', lw=1.5, ls='-.',
#             zorder=6, label='Trend (linear)')
# =============================================================================
if len(x_f) >= 2:
    if COMPARE_MODE == 'ftmy_direct':
        # ── 연도별 추세선 ────────────────────────────────────────────
        for yr in sorted(set(years_f4)):
            idx = [i for i, y in enumerate(years_f4) if y == yr]
            if len(idx) < 2:
                continue
            xs = [x_f[i] for i in idx]
            ys = [cs_means[i] for i in idx]
            clr = YEAR_COLORS_F4.get(yr, ['#888888'] * len(SSP_ORDER_F4))[-1]
            z_cs = np.polyfit(xs, ys, 1)
            tx = np.linspace(min(xs), max(xs), 50)
            ax.plot(tx, np.poly1d(z_cs)(tx), color=clr, lw=2, ls='-.',
                    marker='o', markevery=[0, -1], markersize=6,
                    zorder=6, label=f'{yr} trend')
    else:
        z_cs = np.polyfit(x_f, cs_means, 1)
        ax.plot(x_f, np.poly1d(z_cs)(x_f), color='black', lw=1.5, ls='-.',
                zorder=6, label='Trend (linear)')
ax.axhline(baseline_cs, color='gray', lw=2, ls='--',
           label=f'Baseline TMYx ({baseline_cs} days/yr)')
ax.set_xticks(x_f)
ax.set_xticklabels(labels_f, rotation=45, ha='right', fontsize= tick_size)
ax.set_ylabel('Extreme Cold Days per Year', fontsize = axis_font_size)
ax.set_title('Cold Snap', fontsize = subtitle_size)
ax.legend(fontsize=legend_size)
ax.grid(alpha=0.3, axis='y')

# =============================================================================
# # ── (1,0) HW 변화량 (Baseline = 0) ───────────────────────────────────
# ax = axes4[1, 0]
# bar_colors_hw = ['#F44336' if v >= 0 else '#2196F3' for v in delta_hw]
# ax.bar(x_f, delta_hw, color=bar_colors_hw, alpha=0.85,
#        edgecolor='black', lw=0.5)
# if any(s > 0 for s in hw_stds):
#     ax.errorbar(x_f, delta_hw, yerr=hw_stds,
#                 fmt='none', color='black', capsize=4, lw=1.2, zorder=5)
# ax.axhline(0, color='gray', lw=2, ls='--', label='Baseline (Δ = 0)')
# ax.set_xticks(x_f)
# ax.set_xticklabels(labels_f, rotation=45, ha='right', fontsize=8)
# ax.set_ylabel('Δ Extreme Hot Days per Year\n(Future − Baseline)')
# ax.set_title('Heat Wave — Change from Baseline\n'
#              '(Red = Increase  /  Blue = Decrease)')
# ax.legend(fontsize=9); ax.grid(alpha=0.3, axis='y')
# 
# # ── (1,1) CS 변화량 (Baseline = 0) ───────────────────────────────────
# ax = axes4[1, 1]
# bar_colors_cs = ['#2196F3' if v >= 0 else '#F44336' for v in delta_cs]
# ax.bar(x_f, delta_cs, color=bar_colors_cs, alpha=0.85,
#        edgecolor='black', lw=0.5)
# if any(s > 0 for s in cs_stds):
#     ax.errorbar(x_f, delta_cs, yerr=cs_stds,
#                 fmt='none', color='black', capsize=4, lw=1.2, zorder=5)
# ax.axhline(0, color='gray', lw=2, ls='--', label='Baseline (Δ = 0)')
# ax.set_xticks(x_f)
# ax.set_xticklabels(labels_f, rotation=45, ha='right', fontsize=8)
# ax.set_ylabel('Δ Extreme Cold Days per Year\n(Future − Baseline)')
# ax.set_title('Cold Snap — Change from Baseline\n'
#              '(Blue = Increase  /  Red = Decrease)')
# ax.legend(fontsize=9); ax.grid(alpha=0.3, axis='y')
# 
# =============================================================================
plt.tight_layout()
plt.savefig(result_dir + 'Fig4_extreme_event_frequency.png',
            dpi=300, bbox_inches='tight')
plt.show()


# ── 5. CSV 저장 ───────────────────────────────────────────────────────
df_freq = pd.DataFrame({
    'Scenario'          : labels_f,
    'HW (days/yr)'      : np.round(hw_means, 1),
    'HW std'            : np.round(hw_stds, 1),
    'HW Δ (days/yr)'    : np.round(delta_hw, 1),
    'CS (days/yr)'      : np.round(cs_means, 1),
    'CS std'            : np.round(cs_stds, 1),
    'CS Δ (days/yr)'    : np.round(delta_cs, 1),
})
baseline_row = pd.DataFrame([{
    'Scenario'       : 'Baseline (TMYx)',
    'HW (days/yr)'   : baseline_hw, 'HW std': 0, 'HW Δ (days/yr)': 0,
    'CS (days/yr)'   : baseline_cs, 'CS std': 0, 'CS Δ (days/yr)': 0,
}])
pd.concat([baseline_row, df_freq], ignore_index=True).to_csv(
    result_dir + 'extreme_event_frequency.csv', index=False)

print(f'\n[Fig4] 완료 → {result_dir}')
print('  Fig4_extreme_event_frequency.png')
print('  extreme_event_frequency.csv')