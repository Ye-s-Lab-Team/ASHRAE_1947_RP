"""
Measure 6 — HVAC / 급탕을 공기열원 통합형 히트펌프(ASIHP)로 교체 (Residential + Office)
=====================================================================================
입력 폴더의 모든 IDF를 파일 이름으로 building type 판별 후 처리한다.

  Residential (US+SF+CZ..+hp+.. prototype) — RES['model'] = "integrated" (기본)
    • 기존 ASHP(AirLoopHVAC:UnitaryHeatPump:AirToAir) + 실내 HPWH → CoilSystem:IntegratedHeatPump:AirSource
        - ASIHP와 구성 코일 8개(SC·SH·DWH·SCWH·SCDWH·SHDWH, 10단 VS)·커브는 EnergyPlus 예제
          ASIHPMixedTank.idf에서 가져와 이름·노드를 이 모델에 맞게 바꾼다
        - 공기 루프의 HP 냉·난방 코일을 ASIHP로 교체 (공기 루프·AirflowNetwork·ERV·배기팬 유지)
        - 급탕: 기존 탱크 + 외기형 WaterHeater:HeatPump:PumpedCondenser (DX 코일 = ASIHP)
        - ASIHP는 autosize가 안 되므로 원본 모델을 EnergyPlus로 sizing만 실행해 기존 ASHP 용량·풍량 사용
    • ※ EnergyPlus 25.1 ASIHP 한계: 동시 모드(냉방+급탕 SCWH/SCDWH, 난방+급탕 SHDWH)의 급탕 열이
        탱크에 전달되지 않음 (EnergyPlus 예제 ASIHPMixedTank.idf도 같음: 연간 급탕 2,484 kWh 보고,
        탱크 수열 577 kWh). 급탕 에너지가 과대, 난방 미충족 시간이 크게 나올 수 있음.
      RES['model'] = "separate"로 바꾸면 ASIHP 구성 코일을 냉난방(UnitarySystem)과 급탕(외기형 HPWH)에
      따로 연결한 대안 모델로 만든다 (통합 운전 효과 미반영).

  Office (ASHRAE901_OfficeMedium… 원본 또는 Measure 1 결과)
    • EnergyPlus는 ASIHP를 단일 zone용 AirLoopHVAC:UnitaryHeatPump:AirToAir에만 허용 → 다중 zone
      VAV AHU에는 넣을 수 없어, 같은 ASIHP 구성 코일(ORNL COP·SHR)로 구성:
        - AHU(bot/mid/top): AirLoopHVAC:UnitarySystem (SetPoint 제어) + VS 냉방·VS 난방 코일,
          zone 난방은 기존 VAV 재열 코일
        - 급탕: 가스 WaterHeater:Mixed → 외기형 VS 히트펌프 급탕기(PumpedCondenser) + 전기 백업
        - 외기온도 기반 급기온도 EMS 제어 (원래 코드 Step 3)는 OFF['sat_reset']으로 선택 (기본 끔)

  공통
    • PV 인버터 Inverter:PVWatts → Inverter:Simple (Measure 1 baseline과 같은 PV 모델)

출력: OUTPUT_DIR/NewModel6_{building type}_{climate zone}_{city}.idf
"""

import io
import os
import re
import glob
import shutil
import tempfile
import subprocess
from eppy.modeleditor import IDF


# ═════════════════════════════════════════════════════════════════════════════
# 설정
# ═════════════════════════════════════════════════════════════════════════════


script_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.join(script_dir, "..", "..", "Original_model")

IDD_PATH = r"C:\EnergyPlusV25-1-0\Energy+.idd"

TEMPLATE_IDF = os.path.join(os.path.dirname(IDD_PATH), "ExampleFiles", "ASIHPMixedTank.idf")

ENERGYPLUS_EXE = os.path.join(os.path.dirname(IDD_PATH),
                              "energyplus.exe" if os.name == "nt" else "energyplus")

INPUT_DIRS = [
    os.path.join(MODEL_ROOT, "residential", "system_ashp"),  # residential
    os.path.join(MODEL_ROOT, "office"),            # office
]
OUTPUT_DIR = os.path.join(script_dir, "..", "NewModel6")
OUTPUT_PREFIX = "NewModel6"

# ── ASIHP 구성 코일 성능 (원래 코드의 ORNL 값, residential·office 공통) ───────────
ASIHP = {
    "num_speeds": 10,
    "speed_fractions": [0.20, 0.28, 0.36, 0.44, 0.52, 0.60, 0.70, 0.80, 0.90, 1.00],
    # 공간 냉방 (용량·풍량은 autosize, 아래 reference 값은 단별 비율·COP 정의용)
    "sc_cops": [4.23, 4.58, 4.76, 4.68, 4.55, 4.40, 4.21, 4.00, 3.85, 3.67],
    "sc_shrs": [0.80, 0.79, 0.78, 0.77, 0.77, 0.76, 0.76, 0.75, 0.75, 0.75],
    # reference 풍량은 EnergyPlus 예제 비율(냉방 1.7 m3/s / 32 kW ≈ 400 cfm/ton, 난방 1.7 / 35 kW).
    #   원래 코드 값(2.5 / 2.2 m3/s ≈ 270 cfm/ton)은 autosize된 코일 풍량이 시스템 풍량의 절반 정도로
    #   잡혀 용량·효율이 낮게 계산됐음
    "sc_ref_cap": 70_000.0, "sc_ref_flow": round(70_000 * 1.7 / 32_000, 4),
    # 공간 난방
    "sh_cops": [4.60, 4.78, 4.84, 4.78, 4.66, 4.50, 4.32, 4.11, 3.93, 3.50],
    "sh_ref_cap": 60_000.0, "sh_ref_flow": round(60_000 * 1.7 / 35_000, 4),
    "sh_min_oat": -17.78,              # 압축기 최저 외기온도 (residential은 기존 DX 코일 값 사용)
    "defrost_fraction": 0.058333,
    # 급탕 (외기형 히트펌프 급탕기)
    "dhw_cops": [4.50, 4.50, 4.40, 4.30, 4.20, 4.10, 3.90, 3.80, 3.70, 3.60],
    "dhw_cap": 5_000.0, "dhw_water_flow": 0.00025, "dhw_pump_power": 100.0,
    # 급탕 정격 조건 = 커브 기준 조건 (EnergyPlus 예제). 원래 코드 값 19.7 / 13.5 / 57.2 °C
    "dhw_rated_db": 29.44, "dhw_rated_wb": 22.22, "dhw_rated_water": 55.72,
    "dhw_air_per_watt": 0.2685 / 4000,  # 증발기 풍량 [m3/s per W] (EnergyPlus ASIHP 예제 비율)
    "hpwh_min_inlet_temp": -5.0,       # 급탕기 압축기 최저 외기온도 (비우면 기본값 10 °C)
}

# ── Residential: ASIHP (EnergyPlus 예제 ASIHPMixedTank.idf의 ASIHP·코일·커브 사용) ─────
RES = {
    # "integrated": CoilSystem:IntegratedHeatPump:AirSource 사용 (task description 방식, 기본)
    # "separate"  : ASIHP 구성 코일(VS 냉방·난방·급탕)을 냉난방과 급탕에 따로 연결
    #   ※ EnergyPlus 25.1 ASIHP는 동시 모드(냉방+급탕, 난방+급탕)의 급탕 열이 탱크에 전달되지 않음
    #     (EnergyPlus 예제 ASIHPMixedTank.idf도 같음) → 결과 해석 시 주의, 파일 상단 설명 참고
    "model": "integrated",
    "always_on": "always_avail",
    "hp_type": "AirLoopHVAC:UnitaryHeatPump:AirToAir",
    "hpwh_type": "WaterHeater:HeatPump:WrappedCondenser",
    "tank_element_logic": "Simultaneous",   # 히트펌프와 탱크 히터 동시 운전 허용
    # ASIHP 제어값 덮어쓰기 {필드: 값}. 비우면 EnergyPlus 예제 값 사용.
    #   참고 모델(v10) 값(SCWH 20/32 °C, WH 우선 26/30 °C, SHDWH 14,400 s)은 이 모델에서
    #   AirflowNetwork 행렬 오류로 중단되어 기본은 예제 값
    "ihp_controls": {},
    # 용량·풍량: ASIHP 코일은 EnergyPlus에서 autosize가 안 됨(급탕기가 공기 루프 sizing 전에
    #   ASIHP 크기를 물어봐서 음수로 계산 → Fatal). 원본 모델을 EnergyPlus로 sizing만 돌려
    #   기존 ASHP DX 코일의 autosize 결과를 넣는다. 실패하면 아래 값 사용
    #   (예제 값 32~35 kW / 1.7 m3/s는 상업용 규모라 쓰지 않음)
    "fallback_size": {"cooling_w": 7000.0, "heating_w": 7000.0, "air_flow": 0.35},
    # 급탕 성능 커브 최저 출력 0 (영하 습구온도에서 음수로 외삽되는 것 방지)
    "zero_floor_curves": ["HPWHHeatingCapFTemp", "HPWHHeatingCOPFTemp"],
}

# ── Office ───────────────────────────────────────────────────────────────────────
AHU_LIST = ["bot", "mid", "top"]
OFF = {
    "always_on": "Always_On",
    "tank_name": "SWHSys1 Water Heater",
    "backup_offset": 5.0,              # 탱크 가스→전기 백업 히터 setpoint = setpoint − 5 °C
    # 급기온도 EMS 제어 (원래 코드 Step 3): 외기 ≥ 12 °C → 원래 SPM, ≤ 0 °C → 40 °C, 그 사이 선형.
    #   기본 False — 다중 zone VAV에서 급기를 40 °C로 올리면 내부 zone(냉방 필요)이 과열되어
    #   Chicago 테스트에서 미충족 냉방 1,855 h (원본 249 h). 끄면 히트펌프가 AHU 급기를,
    #   VAV 재열 코일이 zone 난방을 담당 (원본과 같은 제어)
    "sat_reset": False,
    "oat_cool": 12.0, "oat_heat": 0.0, "sat_heat_max": 40.0, "sat_cool_min": 15.6,
}
ADD_OUTPUT_VARIABLES = True            # 히트펌프 확인용 Output:Variable (Hourly) 추가

# ── 도시 → 기후대 / 기초 형식 표기 ─────────────────────────────────────────────
CLIMATE_ZONES = {
    "HoChiMinh": "0A", "AbuDhabi": "0B",
    "Honolulu": "1A", "Miami": "1A", "NewDelhi": "1B",
    "Tampa": "2A", "Houston": "2A", "Tucson": "2B", "Phoenix": "2B",
    "Atlanta": "3A", "Memphis": "3A", "ElPaso": "3B", "LasVegas": "3B",
    "SanDiego": "3C", "SanFrancisco": "3C",
    "NewYork": "4A", "Baltimore": "4A", "Albuquerque": "4B",
    "Seattle": "4C", "Salem": "4C",
    "Buffalo": "5A", "Chicago": "5A", "Denver": "5B", "Boulder": "5B",
    "PortAngeles": "5C",
    "Rochester": "6A", "Minneapolis": "6A", "GreatFalls": "6B", "Helena": "6B",
    "InternationalFalls": "7", "Duluth": "7",
    "Fairbanks": "8",
}
FOUNDATIONS = {"slab": "Slab", "crawlspace": "Crawlspace",
               "unheatedbsmt": "UnheatedBsmt", "heatedbsmt": "HeatedBsmt"}


# ═════════════════════════════════════════════════════════════════════════════
# IDF 공통 유틸
# ═════════════════════════════════════════════════════════════════════════════

def load_clean_idf(path) -> IDF:
    """
    IDF 로드 전 정리:
      - 전처리기 경고 문장이 오브젝트처럼 들어간 레코드 제거
      - Output:PreprocessorMessage 제거 (예전 실행에서 남으면 EnergyPlus가 바로 Fatal)
    """
    with open(path, "r", encoding="latin-1") as f:
        records = re.split(r"(;)", f.read())
    cleaned, i = [], 0
    while i < len(records):
        chunk = records[i]
        obj_type = next((ln.strip().split(",")[0].strip()
                         for ln in chunk.splitlines()
                         if ln.strip() and not ln.strip().startswith("!")), "")
        if re.search(r"[ \[\]()]", obj_type) or obj_type.lower() == "output:preprocessormessage":
            print(f"    [clean] 레코드 제거: '{obj_type[:60]}'")
            i += 2 if i + 1 < len(records) and records[i + 1] == ";" else 1
            continue
        cleaned.append(chunk)
        i += 1
    return IDF(io.StringIO("".join(cleaned)))


def get_object(idf: IDF, obj_type: str, name: str):
    if not obj_type or not name:
        return None
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name.strip().lower() == name.strip().lower():
            return obj
    return None


def remove_object(idf: IDF, obj_type: str, name: str) -> bool:
    obj = get_object(idf, obj_type, name)
    if obj is None:
        return False
    idf.removeidfobject(obj)
    print(f"    - {obj_type} '{name}'")
    return True


def add(idf: IDF, obj_type: str, name=None, values=None, **fields):
    """오브젝트 생성. values를 주면 Name 다음 필드부터 순서대로 채운다(커브·리스트용)."""
    kw = dict(fields)
    if name is not None:
        kw["Name"] = name
    obj = idf.newidfobject(obj_type.upper(), **kw)
    if values is not None:
        start = 2 if name is not None else 1
        obj.obj[start:] = list(values)
    return obj


def set_field(obj, pattern: str, value) -> None:
    """필드 이름을 정규식으로 찾아 값 지정 (IDD의 이중 공백·대소문자 차이 무시)"""
    rx = re.compile(pattern, re.I)
    for f in obj.fieldnames:
        if rx.fullmatch(re.sub(r"_+", "_", f)):
            obj[f] = value
            return
    raise KeyError(f"{obj.key}: '{pattern}' 필드 없음")


def ensure_type_limits(idf: IDF, name: str, numeric="Continuous") -> None:
    if not get_object(idf, "ScheduleTypeLimits", name):
        add(idf, "ScheduleTypeLimits", name, Numeric_Type=numeric)


def constant_schedule(idf: IDF, name: str, value, limits="") -> str:
    if not get_object(idf, "Schedule:Compact", name):
        add(idf, "Schedule:Compact", name, Schedule_Type_Limits_Name=limits,
            values=[limits, "Through: 12/31", "For: AllDays", "Until: 24:00", value])
    return name


def schedule_max(idf: IDF, name: str, default: float = 60.0) -> float:
    """Schedule:Compact / Schedule:Constant의 최댓값 (급탕 setpoint 읽기용)"""
    obj = get_object(idf, "Schedule:Compact", name)
    if obj is not None:
        vals = []
        for v in obj.obj[3:]:
            for part in str(v).split(","):                    # 'Until 24:00,44' 형식도 처리
                try:
                    vals.append(float(part.strip()))
                except ValueError:
                    pass
        if vals:
            return max(vals)
    obj = get_object(idf, "Schedule:Constant", name)
    if obj is not None:
        return float(obj.Hourly_Value)
    return default


def retarget(idf: IDF, old_type: str, old_name: str, new_type: str, new_name: str) -> int:
    """(old_type, old_name)로 이어진 참조를 모두 (new_type, new_name)으로 교체"""
    n = 0
    for objs in idf.idfobjects.values():
        for obj in objs:
            v = obj.obj
            for k in range(1, len(v) - 1):
                if (str(v[k]).strip().lower() == old_type.lower()
                        and str(v[k + 1]).strip().lower() == old_name.lower()):
                    v[k], v[k + 1] = new_type, new_name
                    n += 1
    return n


def replace_pvwatts_inverter(idf: IDF, availability_schedule: str = "") -> int:
    """Inverter:PVWatts → 같은 이름·효율의 Inverter:Simple (Measure 1/3/4/5와 같은 함수)"""
    n = 0
    for old in list(idf.idfobjects["ELECTRICLOADCENTER:INVERTER:PVWATTS"]):
        name, eff = old.Name, old.Inverter_Efficiency or 0.96
        idf.removeidfobject(old)
        add(idf, "ElectricLoadCenter:Inverter:Simple", name,
            Availability_Schedule_Name=availability_schedule,
            Radiative_Fraction=0, Inverter_Efficiency=eff)
        n += 1
    return n


def remove_from_zone_equipment(idf: IDF, obj_type: str, name: str) -> None:
    """ZoneHVAC:EquipmentList에서 항목을 빼고 냉·난방 순서를 다시 매긴다."""
    for eql in idf.idfobjects["ZONEHVAC:EQUIPMENTLIST"]:
        head, rest = eql.obj[:3], eql.obj[3:]
        groups = [rest[i:i + 6] for i in range(0, len(rest), 6)]
        groups = [g + [""] * (6 - len(g)) for g in groups if str(g[0]).strip()]
        keep = [g for g in groups if not (str(g[0]).lower() == obj_type.lower()
                                          and str(g[1]).strip().lower() == name.lower())]
        if len(keep) == len(groups):
            continue
        for col in (2, 3):
            order = sorted(range(len(keep)), key=lambda i: float(keep[i][col] or 0))
            for rank, i in enumerate(order, start=1):
                keep[i][col] = rank
        eql.obj[:] = head + [v for g in keep for v in g]
        print(f"    - ZoneHVAC:EquipmentList '{eql.Name}'에서 '{name}' 제거")


def remove_orphan_nodes(idf: IDF, nodes) -> None:
    """삭제한 장비의 노드를 NodeList·OutdoorAir:NodeList·OutdoorAir:Node에서 제거
    (남은 장비가 아직 쓰는 노드는 그대로 둠, 빈 리스트는 삭제)"""
    nodes = {str(n).strip().lower() for n in nodes if str(n).strip()}
    lists = {"NODELIST", "OUTDOORAIR:NODELIST", "OUTDOORAIR:NODE"}
    for key, objs in idf.idfobjects.items():
        if key.upper() in lists:
            continue
        for obj in objs:
            for v in obj.obj[1:]:
                nodes.discard(str(v).strip().lower())
    if not nodes:
        return
    for oan in list(idf.idfobjects["OUTDOORAIR:NODE"]):
        if oan.Name.strip().lower() in nodes:
            idf.removeidfobject(oan)
            print(f"    - OutdoorAir:Node '{oan.Name}'")
    for kind in ("NODELIST", "OUTDOORAIR:NODELIST"):
        start = 2 if kind == "NODELIST" else 1
        for nl in list(idf.idfobjects[kind]):
            vals = [v for v in nl.obj[start:] if str(v).strip()]
            keep = [v for v in vals if str(v).strip().lower() not in nodes]
            if len(keep) == len(vals):
                continue
            print(f"    - {kind.title()}에서 노드 {len(vals) - len(keep)}개 제거")
            if keep:
                nl.obj[start:] = keep
                continue
            name = nl.Name if kind == "NODELIST" else None
            idf.removeidfobject(nl)
            if name:
                for objs in idf.idfobjects.values():
                    for obj in objs:
                        for k in range(2, len(obj.obj)):
                            if str(obj.obj[k]).strip().lower() == name.lower():
                                obj.obj[k] = ""
                print(f"    - 빈 NodeList '{name}' 삭제")


def node_fields(obj) -> list:
    """오브젝트의 공기 노드 필드 값들"""
    return [str(v) for f, v in zip(obj.fieldnames, obj.obj)
            if f.endswith("Node_Name") and str(v).strip()]


# ═════════════════════════════════════════════════════════════════════════════
# 공통 — 외기형 히트펌프 급탕기 (WaterHeater:HeatPump:PumpedCondenser)
# ═════════════════════════════════════════════════════════════════════════════

def add_outdoor_hpwh(idf: IDF, name: str, tank_type: str, tank, use_nodes: tuple,
                     coil_type: str, coil_name: str, cond_nodes: tuple, air_nodes: tuple,
                     setpoint_schedule: str, avail: str, water_flow, air_flow,
                     min_inlet_temp: float, element_logic: str, sensor: dict = None) -> None:
    """
    탱크(plant 연결 유지) + 외기 증발기 HPWH.
      use_nodes  : 탱크 use side (inlet, outlet) — 기존 급탕 loop branch 노드
      cond_nodes : HPWH 응축기 물 (inlet, outlet) = 탱크 source side (outlet, inlet)
      air_nodes  : (외기 흡입 = 팬 입구, 팬 출구 = 증발기 입구, 증발기 출구 = 배기)
    탱크를 가리키던 plant 참조(Branch·PlantEquipmentList)는 HPWH로 바꾼다.
    """
    n = retarget(idf, tank_type, tank.Name, "WaterHeater:HeatPump:PumpedCondenser", name)
    tank.Source_Side_Inlet_Node_Name, tank.Source_Side_Outlet_Node_Name = cond_nodes[1], cond_nodes[0]
    oa_in, fan_out, exhaust = air_nodes
    add(idf, "OutdoorAir:Node", oa_in)
    fan = f"{name} Fan"
    add(idf, "Fan:OnOff", fan, Availability_Schedule_Name=avail, Fan_Total_Efficiency=0.7,
        Pressure_Rise=100.0, Maximum_Flow_Rate=air_flow, Motor_Efficiency=0.9,
        Motor_In_Airstream_Fraction=1.0, Air_Inlet_Node_Name=oa_in, Air_Outlet_Node_Name=fan_out)
    hpwh = add(idf, "WaterHeater:HeatPump:PumpedCondenser", name,
               Availability_Schedule_Name=avail,
               Compressor_Setpoint_Temperature_Schedule_Name=setpoint_schedule,
               Dead_Band_Temperature_Difference=2.0,
               Condenser_Water_Inlet_Node_Name=cond_nodes[0],
               Condenser_Water_Outlet_Node_Name=cond_nodes[1],
               Condenser_Water_Flow_Rate=water_flow, Evaporator_Air_Flow_Rate=air_flow,
               Inlet_Air_Configuration="OutdoorAirOnly",
               Outdoor_Air_Node_Name=oa_in, Exhaust_Air_Node_Name=exhaust,
               Tank_Object_Type=tank_type, Tank_Name=tank.Name,
               Tank_Use_Side_Inlet_Node_Name=use_nodes[0],
               Tank_Use_Side_Outlet_Node_Name=use_nodes[1],
               DX_Coil_Object_Type=coil_type, DX_Coil_Name=coil_name,
               Minimum_Inlet_Air_Temperature_for_Compressor_Operation=min_inlet_temp,
               Compressor_Location="Outdoors",
               Fan_Object_Type="Fan:OnOff", Fan_Name=fan, Fan_Placement="BlowThrough",
               Parasitic_Heat_Rejection_Location="Outdoors",
               Tank_Element_Control_Logic=element_logic)
    for field, value in (sensor or {}).items():
        if value not in ("", None):
            hpwh[field] = value
    print(f"    + WaterHeater:HeatPump:PumpedCondenser '{name}' (DX 코일 {coil_type} '{coil_name}', "
          f"외기 증발기, 압축기 최저 외기 {min_inlet_temp:g} °C) — plant 참조 {n}곳 연결")


# ═════════════════════════════════════════════════════════════════════════════
# 공통 — ASIHP 구성 코일 (VS 냉방·VS 난방·VS 급탕, ORNL 성능)
# ═════════════════════════════════════════════════════════════════════════════

def asihp_curves(idf: IDF) -> None:
    """
    성능 커브 — EnergyPlus ASIHP 예제(ASIHPMixedTank.idf)의 커브. 정격 조건에서 출력 ≈ 1.
      (원래 코드의 커브는 냉방 용량 외에는 정격 조건 출력이 1이 아니었음: 난방 용량 0.60·EIR 0.69,
       급탕 용량 0.41·EIR 2.03 → 난방 용량 부족·COP 과대, 급탕 용량·COP 절반 이하로 계산됨)
    COP·SHR·단별 비율은 ORNL 값(ASIHP 설정) 그대로.
    """
    if get_object(idf, "Curve:Biquadratic", "ASIHP_CoolCapFT"):
        return
    biquad = [  # (이름, 계수 6개, x 범위, y 범위, 출력 범위)
        ("ASIHP_CoolCapFT", [0.766956, 0.0107756, -4.14703e-05, 0.00134961, -0.000261144, 0.000457488],
         (12.77778, 23.88889), (18.0, 46.11111), ("", "")),
        ("ASIHP_CoolEIRFT", [0.297145, 0.0430933, -0.000748766, 0.00597727, 0.000482112, -0.000956448],
         (12.77778, 23.88889), (18.0, 46.11111), ("", "")),
        ("ASIHP_HeatCapFT", [0.8529681407, -0.0004847169, -1.0693e-06, 0.0185542164, 8.72425e-05, -1.66868e-05],
         (17.78, 23.33), (-28.89, 17.22), (0.3799, 1.1896)),
        ("ASIHP_HeatEIRFT", [0.7077081462, 0.0148163478, 0.0002622589, -0.0113239622, 0.0002939277, -0.0003605284],
         (17.78, 23.33), (-28.89, 17.22), (0.8266, 2.0277)),
        # 급탕: x = 증발기 입구 공기 습구온도, y = 응축기 입구 수온
        ("ASIHP_WHCapFT", [0.369827, 0.043341, -0.00023, 0.000466, 2.6e-05, -0.00027], (0.0, 40.0), (20.0, 90.0), (0.0, "")),
        ("ASIHP_WHCOPFT", [1.19713, 0.077849, -1.6e-06, -0.02675, 0.000296, -0.00112], (0.0, 40.0), (20.0, 90.0), (0.0, "")),
    ]
    for name, c, x, y, out in biquad:
        add(idf, "Curve:Biquadratic", name, values=c + [x[0], x[1], y[0], y[1], out[0], out[1]])
    for name, c, lim in [("ASIHP_CoolCapFF", [0.8, 0.2, 0.0], (0.5, 1.5)),
                         ("ASIHP_CoolEIRFF", [1.156, -0.1816, 0.0256], (0.5, 1.5)),
                         ("ASIHP_HeatCapFF", [0.84, 0.16, 0.0], (0.5, 1.5)),
                         ("ASIHP_HeatEIRFF", [1.3824, -0.4336, 0.0512], (0.0, 1.0)),
                         ("ASIHP_PLF", [0.85, 0.15, 0.0], (0.0, 1.0)),
                         ("ASIHP_WHPLF", [0.75, 0.25, 0.0], (0.0, 1.0)),
                         ("ASIHP_Constant", [1.0, 0.0, 0.0], (0.0, 2.0))]:
        add(idf, "Curve:Quadratic", name, values=c + list(lim))


def add_vs_coils(idf: IDF, p: str, inlet: str, mid: str, outlet: str, min_oat=None) -> tuple:
    """ASIHP 공간 냉방·난방 코일 (10단 VS, 용량·풍량 autosize). 반환: (냉방 코일, 난방 코일) 이름"""
    asihp_curves(idf)
    n, fr = ASIHP["num_speeds"], ASIHP["speed_fractions"]
    sc = add(idf, "Coil:Cooling:DX:VariableSpeed", f"{p} VS Cooling Coil",
             Indoor_Air_Inlet_Node_Name=inlet, Indoor_Air_Outlet_Node_Name=mid,
             Number_of_Speeds=n, Nominal_Speed_Level=n,
             Gross_Rated_Total_Cooling_Capacity_At_Selected_Nominal_Speed_Level="autosize",
             Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level="autosize",
             Nominal_Time_for_Condensate_to_Begin_Leaving_the_Coil=1000.0,
             Initial_Moisture_Evaporation_Rate_Divided_by_SteadyState_AC_Latent_Capacity=1.5,
             Maximum_Cycling_Rate=2.5, Latent_Capacity_Time_Constant=60.0,
             Energy_Part_Load_Fraction_Curve_Name="ASIHP_PLF", Condenser_Type="AirCooled")
    for i in range(1, n + 1):
        f = fr[i - 1]
        set_field(sc, f"Speed_{i}_Reference_Unit_Gross_Rated_Total_Cooling_Capacity", round(ASIHP["sc_ref_cap"] * f, 2))
        set_field(sc, f"Speed_{i}_Reference_Unit_Gross_Rated_Sensible_Heat_Ratio", ASIHP["sc_shrs"][i - 1])
        set_field(sc, f"Speed_{i}_Reference_Unit_Gross_Rated_Cooling_COP", ASIHP["sc_cops"][i - 1])
        set_field(sc, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate", round(ASIHP["sc_ref_flow"] * f, 6))
        set_field(sc, f"Speed_{i}_Total_Cooling_Capacity_Function_of_Temperature_Curve_Name", "ASIHP_CoolCapFT")
        set_field(sc, f"Speed_{i}_Total_Cooling_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_CoolCapFF")
        set_field(sc, f"Speed_{i}_Energy_Input_Ratio_Function_of_Temperature_Curve_Name", "ASIHP_CoolEIRFT")
        set_field(sc, f"Speed_{i}_Energy_Input_Ratio_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_CoolEIRFF")

    sh = add(idf, "Coil:Heating:DX:VariableSpeed", f"{p} VS Heating Coil",
             Indoor_Air_Inlet_Node_Name=mid, Indoor_Air_Outlet_Node_Name=outlet,
             Number_of_Speeds=n, Nominal_Speed_Level=n,
             Rated_Heating_Capacity_At_Selected_Nominal_Speed_Level="autosize",
             Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level="autosize",
             Energy_Part_Load_Fraction_Curve_Name="ASIHP_PLF",
             Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation=ASIHP["sh_min_oat"] if min_oat is None else min_oat,
             Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation=5.0,
             Crankcase_Heater_Capacity=200.0,
             Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation=10.0,
             Defrost_Strategy="Resistive", Defrost_Control="Timed",
             Defrost_Time_Period_Fraction=ASIHP["defrost_fraction"])
    for i in range(1, n + 1):
        f = fr[i - 1]
        set_field(sh, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_Capacity", round(ASIHP["sh_ref_cap"] * f, 2))
        set_field(sh, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_COP", ASIHP["sh_cops"][i - 1])
        set_field(sh, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate", round(ASIHP["sh_ref_flow"] * f, 6))
        set_field(sh, f"Speed_{i}_Heating_Capacity_Function_of_Temperature_Curve_Name", "ASIHP_HeatCapFT")
        set_field(sh, f"Speed_{i}_(Total_)?Heating_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_HeatCapFF")
        set_field(sh, f"Speed_{i}_Energy_Input_Ratio_Function_of_Temperature_Curve_Name", "ASIHP_HeatEIRFT")
        set_field(sh, f"Speed_{i}_Energy_Input_Ratio_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_HeatEIRFF")
    return sc.Name, sh.Name


def add_vs_dhw_coil(idf: IDF, name: str) -> tuple:
    """
    ASIHP 급탕 코일 (10단 VS, 외기 증발기).
    반환: (코일 이름, 응축기 물 노드 (in, out), 공기 노드 (외기 흡입, 팬 출구, 배기), 증발기 풍량)
    """
    asihp_curves(idf)
    n, fr, cap = ASIHP["num_speeds"], ASIHP["speed_fractions"], ASIHP["dhw_cap"]
    air_flow = round(cap * ASIHP["dhw_air_per_watt"], 5)
    cond = (f"{name} Condenser Water Inlet Node", f"{name} Condenser Water Outlet Node")
    air = (f"{name} Outdoor Air Inlet Node", f"{name} Fan Outlet Node", f"{name} Outdoor Air Outlet Node")
    coil = add(idf, "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", f"{name} VS Coil",
               Number_of_Speeds=n, Nominal_Speed_Level=n, Rated_Water_Heating_Capacity=cap,
               Rated_Evaporator_Inlet_Air_DryBulb_Temperature=ASIHP["dhw_rated_db"],
               Rated_Evaporator_Inlet_Air_WetBulb_Temperature=ASIHP["dhw_rated_wb"],
               Rated_Condenser_Inlet_Water_Temperature=ASIHP["dhw_rated_water"],
               Rated_Evaporator_Air_Flow_Rate=air_flow,
               Rated_Condenser_Water_Flow_Rate=ASIHP["dhw_water_flow"],
               Evaporator_Fan_Power_Included_in_Rated_COP="No",
               Condenser_Pump_Power_Included_in_Rated_COP="No",
               Fraction_of_Condenser_Pump_Heat_to_Water=0.1,
               Evaporator_Air_Inlet_Node_Name=air[1], Evaporator_Air_Outlet_Node_Name=air[2],
               Condenser_Water_Inlet_Node_Name=cond[0], Condenser_Water_Outlet_Node_Name=cond[1],
               Crankcase_Heater_Capacity=0.0,
               Maximum_Ambient_Temperature_for_Crankcase_Heater_Operation=10.0,
               Evaporator_Air_Temperature_Type_for_Curve_Objects="WetBulbTemperature",
               Part_Load_Fraction_Correlation_Curve_Name="ASIHP_WHPLF")
    for i in range(1, n + 1):
        f = fr[i - 1]
        set_field(coil, f"Rated_Water_Heating_Capacity_at_Speed_{i}", round(cap * f, 2))
        set_field(coil, f"Rated_Water_Heating_COP_at_Speed_{i}", ASIHP["dhw_cops"][i - 1])
        set_field(coil, f"Rated_Sensible_Heat_Ratio_at_Speed_{i}", 0.85)
        set_field(coil, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate", round(air_flow * f, 6))
        set_field(coil, f"Speed_{i}_Reference_Unit_Rated_Water_Flow_Rate", round(ASIHP["dhw_water_flow"] * f, 8))
        set_field(coil, f"Speed_{i}_Reference_Unit_Water_Pump_Input_Power_At_Rated_Conditions",
                  round(ASIHP["dhw_pump_power"] * f, 2))
        set_field(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Temperature_Curve_Name", "ASIHP_WHCapFT")
        set_field(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_Constant")
        set_field(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Water_Flow_Fraction_Curve_Name", "ASIHP_Constant")
        set_field(coil, f"Speed_{i}_COP_Function_of_Temperature_Curve_Name", "ASIHP_WHCOPFT")
        set_field(coil, f"Speed_{i}_COP_Function_of_Air_Flow_Fraction_Curve_Name", "ASIHP_Constant")
        set_field(coil, f"Speed_{i}_COP_Function_of_Water_Flow_Fraction_Curve_Name", "ASIHP_Constant")

    return coil.Name, cond, air, air_flow


# ═════════════════════════════════════════════════════════════════════════════
# Residential — CoilSystem:IntegratedHeatPump:AirSource (ASIHP)
# ═════════════════════════════════════════════════════════════════════════════

def baseline_sizes(path: str, queries: dict) -> dict:
    """
    원본 IDF를 EnergyPlus로 sizing만 실행해서 eio의 autosize 결과를 읽는다.
      queries: {키: (컴포넌트 이름, eio 설명 일부)}  반환: {키: 값} (못 찾은 키는 빠짐)
    지중 전처리기(slab/basement)는 기상 파일이 필요하므로 이 sizing 실행에서만 일반 Ground로 대체.
    """
    if not os.path.isfile(ENERGYPLUS_EXE):
        print(f"    [warn] EnergyPlus 실행 파일 없음: {ENERGYPLUS_EXE}")
        return {}
    with open(path, "r", encoding="latin-1") as f:
        records = re.split(r"(;)", f.read())
    out, i = [], 0
    while i < len(records):
        first = next((ln.strip() for ln in records[i].splitlines()
                      if ln.strip() and not ln.strip().startswith("!")), "")
        head = first.split(",")[0].strip().lower()
        if head.startswith("groundheattransfer:") or head == "output:preprocessormessage" \
                or re.search(r"[ \[\]()]", head):
            i += 2
            continue
        out.append(records[i])
        i += 1
    text = "".join(out)
    text = re.sub(r"Ground(?:Slab|Basement)Preprocessor\w*\s*,(\s*(?:!-[^\n]*)?\n?\s*)[^,;!\n]*([,;])",
                  r"Ground,\1\2", text, flags=re.I)
    text = re.sub(r"SimulationControl,[^;]*;", "SimulationControl, Yes, Yes, No, No, No, No;",
                  text, count=1, flags=re.I)
    tmp = tempfile.mkdtemp(prefix="m6_sizing_")
    found = {}
    try:
        src = os.path.join(tmp, "sizing.idf")
        with open(src, "w", encoding="latin-1") as f:
            f.write(text)
        subprocess.run([ENERGYPLUS_EXE, "-d", tmp, "-i", IDF.getiddname(), src],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        eio = os.path.join(tmp, "eplusout.eio")
        if os.path.isfile(eio):
            with open(eio, "r", encoding="latin-1") as f:
                for line in f:
                    v = [x.strip() for x in line.split(",")]
                    if len(v) < 5 or v[0] != "Component Sizing Information":
                        continue
                    for key, (name, desc) in queries.items():
                        if v[2].lower() == name.lower() and desc.lower() in v[3].lower():
                            found[key] = float(v[4])
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return found


_TEMPLATE = None


def load_template() -> IDF:
    global _TEMPLATE
    if _TEMPLATE is None:
        if not os.path.isfile(TEMPLATE_IDF):
            raise FileNotFoundError(f"ASIHP 예제 파일 없음: {TEMPLATE_IDF} (TEMPLATE_IDF 경로 확인)")
        _TEMPLATE = IDF(TEMPLATE_IDF)
    return _TEMPLATE


IHP_ROLES = {   # 역할: (오브젝트 타입, 예제 ASIHPMixedTank.idf의 이름)
    "ihp": ("CoilSystem:IntegratedHeatPump:AirSource", "ASIHP1"),
    "sc": ("Coil:Cooling:DX:VariableSpeed", "Heat Pump ACDXCoil 1"),
    "sh": ("Coil:Heating:DX:VariableSpeed", "Heat Pump DX Heating Coil 1"),
    "dwh": ("Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", "HPWHOutdoorDXCoilVS"),
    "scwh": ("Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", "SCWHCoil1"),
    "scdwh_c": ("Coil:Cooling:DX:VariableSpeed", "SCDWHCoolCoil1"),
    "scdwh_w": ("Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", "SCDWHWHCoil1"),
    "shdwh_h": ("Coil:Heating:DX:VariableSpeed", "SHDWHHeatCoil1"),
    "shdwh_w": ("Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", "SHDWHWHCoil1"),
}


def copy_ihp_from_template(idf: IDF, node_map: dict, suffix: str) -> dict:
    """
    예제의 ASIHP + 구성 코일 8개 + 그 코일들이 쓰는 커브를 복사.
    이름: ASIHP는 'ASIHP{suffix}', 코일은 'ASIHP {예제 이름}{suffix}', 커브는 'ASIHP_{커브 이름}'.
    노드는 node_map(예제 노드 → 이 모델 노드)으로 교체. 반환: 역할 → 새 이름
    """
    tpl = load_template()
    src = {r: get_object(tpl, t, n) for r, (t, n) in IHP_ROLES.items()}
    missing = [IHP_ROLES[r][1] for r, o in src.items() if o is None]
    if missing:
        raise ValueError(f"예제에 ASIHP 오브젝트가 없음: {missing}")
    curve_index = {o.Name.lower(): o for k, objs in tpl.idfobjects.items()
                   if k.startswith("CURVE:") for o in objs}
    rename = {n.lower(): f"ASIHP {n}{suffix}" for _, n in IHP_ROLES.values()}
    rename[IHP_ROLES["ihp"][1].lower()] = f"ASIHP{suffix}"
    curves = {}
    for o in src.values():
        for v in o.obj[2:]:
            key = str(v).strip().lower()
            if key in curve_index:
                curves[key] = curve_index[key]
    for key, c in curves.items():
        rename[key] = f"ASIHP_{c.Name}"
        if not get_object(idf, c.key, rename[key]):
            new = idf.copyidfobject(c)
            new.Name = rename[key]
            if c.Name in RES["zero_floor_curves"]:
                new.Minimum_Curve_Output = 0.0          # 영하 습구온도에서 음수 외삽 방지
    lookup = {**{k.lower(): v for k, v in node_map.items()}, **rename}
    for r in IHP_ROLES:
        new = idf.copyidfobject(src[r])
        for k in range(1, len(new.obj)):
            v = str(new.obj[k]).strip().lower()
            if v in lookup:
                new.obj[k] = lookup[v]
            elif k > 1 and new.fieldnames[k].endswith("Node_Name") and v:
                raise ValueError(f"예제 노드 '{new.obj[k]}'의 대응 노드가 node_map에 없음")
    print(f"    + ASIHP + 구성 코일 8개 + 커브 {len(curves)}개 ({os.path.basename(TEMPLATE_IDF)})")
    return {r: rename[n.lower()] for r, (_, n) in IHP_ROLES.items()}


def remove_old_hpwh(idf: IDF, hpwh) -> dict:
    """실내 공기형 HPWH(WrappedCondenser) 삭제 (본체·증발기 코일·팬·공기 노드). 반환: 보관 정보"""
    keep = dict(name=hpwh.Name, setpoint=hpwh.Compressor_Setpoint_Temperature_Schedule_Name,
                use=(hpwh.Tank_Use_Side_Inlet_Node_Name, hpwh.Tank_Use_Side_Outlet_Node_Name),
                sensor={f: getattr(hpwh, f, "") for f in (
                    "Control_Sensor_1_Height_In_Stratified_Tank", "Control_Sensor_1_Weight",
                    "Control_Sensor_2_Height_In_Stratified_Tank")})
    old_air = [getattr(hpwh, f, "") for f in (
        "Air_Inlet_Node_Name", "Air_Outlet_Node_Name", "Outdoor_Air_Node_Name",
        "Exhaust_Air_Node_Name", "Inlet_Air_Mixer_Node_Name", "Outlet_Air_Splitter_Node_Name")]
    parts = [(hpwh.DX_Coil_Object_Type, hpwh.DX_Coil_Name), (hpwh.Fan_Object_Type, hpwh.Fan_Name)]
    for t, nm in parts:
        o = get_object(idf, t, nm)
        old_air += node_fields(o) if o is not None else []
    remove_from_zone_equipment(idf, RES["hpwh_type"], keep["name"])
    idf.removeidfobject(hpwh)
    print(f"    - {RES['hpwh_type']} '{keep['name']}'")
    for t, nm in parts:
        remove_object(idf, t, nm)
    remove_orphan_nodes(idf, old_air)
    n = retarget(idf, RES["hpwh_type"], keep["name"], "WaterHeater:HeatPump:PumpedCondenser", keep["name"])
    print(f"    [ok] plant 참조 {n}곳 → WaterHeater:HeatPump:PumpedCondenser '{keep['name']}'")
    return keep


def res_to_asihp(idf: IDF, src_path: str = None) -> None:
    hp = next(iter(idf.idfobjects[RES["hp_type"].upper()]), None)
    hpwh = next(iter(idf.idfobjects[RES["hpwh_type"].upper()]), None)
    if hp is None or hpwh is None:
        print(f"    [warn] {RES['hp_type']} 또는 {RES['hpwh_type']} 없음 — 건너뜀")
        return
    tank = get_object(idf, hpwh.Tank_Object_Type, hpwh.Tank_Name)
    old_clg = get_object(idf, hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name)
    old_htg = get_object(idf, hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name)
    if tank is None or old_clg is None or old_htg is None:
        print("    [warn] 탱크 또는 기존 DX 코일을 찾지 못함 — 건너뜀")
        return
    if old_clg.Air_Outlet_Node_Name.lower() != old_htg.Air_Inlet_Node_Name.lower():
        print("    [warn] 냉방 코일 출구 ≠ 난방 코일 입구 — 노드 연결 확인 필요")
    suffix = re.search(r"(_unit\d+)$", hp.Name)
    suffix = suffix.group(1) if suffix else ""

    # 1) 용량·풍량: ASIHP는 autosize가 안 되므로 원본 DX 코일의 sizing 결과 사용
    sizes = baseline_sizes(src_path, {
        "cooling_w": (old_clg.Name, "Total Cooling Capacity"),
        "heating_w": (old_htg.Name, "Heating Capacity"),
        "air_flow": (old_clg.Name, "Air Flow Rate")}) if src_path else {}
    if len(sizes) == 3:
        print(f"    [ok] 원본 ASHP sizing 결과 사용: 냉방 {sizes['cooling_w']:.0f} W, "
              f"난방 {sizes['heating_w']:.0f} W, 풍량 {sizes['air_flow']:.3f} m3/s")
    else:
        sizes = RES["fallback_size"]
        print(f"    [warn] 원본 sizing 실패 → RES['fallback_size'] 사용 ({sizes})")

    # 2) 기존 HPWH 삭제
    keep = remove_old_hpwh(idf, hpwh)

    # 3) ASIHP + 구성 코일 (예제 노드 → 이 모델 노드)
    cond = (f"ASIHP Condenser Water Inlet Node{suffix}", f"ASIHP Condenser Water Outlet Node{suffix}")
    air = (f"ASIHP Outdoor Air Inlet Node{suffix}", f"ASIHP Outdoor Fan Outlet Node{suffix}",
           f"ASIHP Outdoor Air Outlet Node{suffix}")
    names = copy_ihp_from_template(idf, {
        "DX Cooling Coil Air Inlet Node": old_clg.Air_Inlet_Node_Name,
        "Heating Coil Air Inlet Node": old_clg.Air_Outlet_Node_Name,
        "SuppHeating Coil Air Inlet Node": old_htg.Air_Outlet_Node_Name,
        "HPOutdoorWaterInletNode": cond[0], "HPOutdoorWaterOutletNode": cond[1],
        "HPOutdoorAirInletNode": air[0], "HPOutdoorFanAirOutletNode": air[1],
        "HPOutdoorAirOutletNode": air[2]}, suffix)
    ihp = get_object(idf, "CoilSystem:IntegratedHeatPump:AirSource", names["ihp"])
    for field, value in RES["ihp_controls"].items():
        ihp[field] = value
    for r in ("sc", "scdwh_c"):
        c = get_object(idf, "Coil:Cooling:DX:VariableSpeed", names[r])
        c.Gross_Rated_Total_Cooling_Capacity_At_Selected_Nominal_Speed_Level = round(sizes["cooling_w"], 1)
        c.Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level = round(sizes["air_flow"], 5)
    for r in ("sh", "shdwh_h"):
        c = get_object(idf, "Coil:Heating:DX:VariableSpeed", names[r])
        c.Rated_Heating_Capacity_At_Selected_Nominal_Speed_Level = round(sizes["heating_w"], 1)
        c.Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level = round(sizes["air_flow"], 5)
        # 압축기 최저 외기온도·제상은 기존 DX 난방 코일 값 (baseline과 같은 조건)
        for f in ("Defrost_Energy_Input_Ratio_Function_of_Temperature_Curve_Name",
                  "Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation",
                  "Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation",
                  "Defrost_Strategy", "Defrost_Control", "Defrost_Time_Period_Fraction",
                  "Resistive_Defrost_Heater_Capacity"):
            v = getattr(old_htg, f, "")
            if str(v).strip():
                c[f] = v
        if not str(getattr(old_htg, "Resistive_Defrost_Heater_Capacity", "")).strip():
            c.Resistive_Defrost_Heater_Capacity = 0     # 예제 20 kW (상업용 규모) 제거

    # 4) 공기 루프의 HP 냉·난방 코일 → ASIHP, AFN 코일 컴포넌트·Linkage는 실제 VS 코일로
    old = [(hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name, "Coil:Cooling:DX:VariableSpeed", names["sc"]),
           (hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name, "Coil:Heating:DX:VariableSpeed", names["sh"])]
    hp.Cooling_Coil_Object_Type = hp.Heating_Coil_Object_Type = "CoilSystem:IntegratedHeatPump:AirSource"
    hp.Cooling_Coil_Name = hp.Heating_Coil_Name = ihp.Name
    for t, nm, new_t, new_nm in old:
        remove_object(idf, t, nm)
        for afn in idf.idfobjects["AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:COIL"]:
            if afn.Coil_Name.strip().lower() == nm.lower():
                afn.Coil_Name, afn.Coil_Object_Type = new_nm, new_t
        for link in idf.idfobjects["AIRFLOWNETWORK:DISTRIBUTION:LINKAGE"]:
            if link.Component_Name.strip().lower() == nm.lower():
                link.Component_Name = new_nm
    print(f"    [ok] {RES['hp_type']} '{hp.Name}' 냉·난방 코일 → ASIHP '{ihp.Name}' (AFN 연결 유지)")

    # 5) 급탕: 기존 탱크 + 외기형 PumpedCondenser (DX 코일 = ASIHP)
    dwh = get_object(idf, "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", names["dwh"])
    stratified = tank.key.upper() == "WATERHEATER:STRATIFIED"
    add_outdoor_hpwh(
        idf, keep["name"], "WaterHeater:Stratified" if stratified else "WaterHeater:Mixed", tank,
        keep["use"], "CoilSystem:IntegratedHeatPump:AirSource", ihp.Name, cond, air,
        keep["setpoint"], RES["always_on"],
        water_flow=dwh.Rated_Condenser_Water_Flow_Rate, air_flow=dwh.Rated_Evaporator_Air_Flow_Rate,
        min_inlet_temp=ASIHP["hpwh_min_inlet_temp"], element_logic=RES["tank_element_logic"],
        sensor=keep["sensor"] if stratified else None)
    print(f"    [ok] 급탕 setpoint '{keep['setpoint']}' ({schedule_max(idf, keep['setpoint']):g} °C), "
          f"탱크 '{tank.Name}' 유지")


# ── 대안 (RES['model'] = "separate"): ASIHP 구성 코일을 냉난방·급탕에 분리 연결 ─────────
#   EnergyPlus ASIHP의 동시 모드 급탕 열 미전달 문제를 피하는 방식 (통합 운전 효과는 미반영)

def sep_space_coils(idf: IDF, src_path: str = None) -> None:
    """
    AirToAir HP(단일속도 DX) → 같은 이름·노드·팬·보조 히터의 AirLoopHVAC:UnitarySystem(Load 제어)
    + ASIHP VS 냉방·난방 코일. 공기 루프·AFN은 유지.
      ※ AirToAir HP에 VS 코일을 그대로 넣으면 실온이 setpoint보다 계속 약 0.4 °C 낮게 제어되고
        (Chicago 미충족 난방 약 4,000 h) 가끔 'VS WSHP unit compressor speed calculation failed'
        Fatal이 나서 UnitarySystem으로 바꾼다.
    """
    hp = next(iter(idf.idfobjects[RES["hp_type"].upper()]), None)
    if hp is None:
        print(f"    [warn] {RES['hp_type']} 없음 — 냉난방 교체 생략")
        return
    old_clg = get_object(idf, hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name)
    old_htg = get_object(idf, hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name)
    if old_clg is None or old_htg is None:
        print("    [warn] 기존 DX 코일을 찾지 못함 — 냉난방 교체 생략")
        return
    if old_clg.Air_Outlet_Node_Name.lower() != old_htg.Air_Inlet_Node_Name.lower():
        print("    [warn] 냉방 코일 출구 ≠ 난방 코일 입구 — 노드 연결 확인 필요")

    # 1) ASIHP VS 코일 (기존 DX 코일과 같은 노드, 압축기 최저 외기온도·제상은 기존 난방 코일 값)
    min_oat = old_htg.Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation
    sc, sh = add_vs_coils(idf, hp.Name, old_clg.Air_Inlet_Node_Name, old_clg.Air_Outlet_Node_Name,
                          old_htg.Air_Outlet_Node_Name,
                          min_oat=min_oat if str(min_oat).strip() else None)
    sh_obj = get_object(idf, "Coil:Heating:DX:VariableSpeed", sh)
    for f in ("Defrost_Energy_Input_Ratio_Function_of_Temperature_Curve_Name",
              "Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation",
              "Defrost_Strategy", "Defrost_Control", "Defrost_Time_Period_Fraction",
              "Resistive_Defrost_Heater_Capacity"):
        v = getattr(old_htg, f, "")
        if str(v).strip():
            sh_obj[f] = v

    # 2) 보조 전기히터 용량 = 원본 AirToAir HP의 autosize 결과
    supp = get_object(idf, hp.Supplemental_Heating_Coil_Object_Type, hp.Supplemental_Heating_Coil_Name)
    if supp is not None and str(getattr(supp, "Nominal_Capacity", "")).lower() == "autosize" and src_path:
        cap = baseline_sizes(src_path, {"supp": (supp.Name, "Nominal Capacity")}).get("supp")
        if cap:
            supp.Nominal_Capacity = round(cap, 1)
            print(f"    [ok] 보조 히터 '{supp.Name}' 용량 {cap:.0f} W (원본 sizing 결과)")
        else:
            print("    [warn] 원본 sizing 실패 → 보조 히터 autosize 유지 (히트펌프 난방 용량과 같게 잡힘)")

    # 3) AirToAir HP → UnitarySystem
    old = [(hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name, "Coil:Cooling:DX:VariableSpeed", sc),
           (hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name, "Coil:Heating:DX:VariableSpeed", sh)]
    unit = add(idf, "AirLoopHVAC:UnitarySystem", None, Control_Type="Load",
               Controlling_Zone_or_Thermostat_Location=hp.Controlling_Zone_or_Thermostat_Location,
               Dehumidification_Control_Type="None",
               Availability_Schedule_Name=hp.Availability_Schedule_Name,
               Air_Inlet_Node_Name=hp.Air_Inlet_Node_Name, Air_Outlet_Node_Name=hp.Air_Outlet_Node_Name,
               Supply_Fan_Object_Type=hp.Supply_Air_Fan_Object_Type, Supply_Fan_Name=hp.Supply_Air_Fan_Name,
               Fan_Placement=hp.Fan_Placement,
               Supply_Air_Fan_Operating_Mode_Schedule_Name=hp.Supply_Air_Fan_Operating_Mode_Schedule_Name,
               Heating_Coil_Object_Type=old[1][2], Heating_Coil_Name=sh, DX_Heating_Coil_Sizing_Ratio=1.0,
               Cooling_Coil_Object_Type=old[0][2], Cooling_Coil_Name=sc, Use_DOAS_DX_Cooling_Coil="No",
               Supplemental_Heating_Coil_Object_Type=hp.Supplemental_Heating_Coil_Object_Type,
               Supplemental_Heating_Coil_Name=hp.Supplemental_Heating_Coil_Name,
               Cooling_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
               Cooling_Supply_Air_Flow_Rate=hp.Cooling_Supply_Air_Flow_Rate,
               Heating_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
               Heating_Supply_Air_Flow_Rate=hp.Heating_Supply_Air_Flow_Rate,
               No_Load_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
               No_Load_Supply_Air_Flow_Rate=hp.No_Load_Supply_Air_Flow_Rate or 0,
               Maximum_Supply_Air_Temperature=hp.Maximum_Supply_Air_Temperature_from_Supplemental_Heater,
               Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation=
               hp.Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation)
    unit_name = hp.Name
    idf.removeidfobject(hp)
    unit.Name = unit_name
    n = retarget(idf, RES["hp_type"], unit_name, "AirLoopHVAC:UnitarySystem", unit_name)

    # 4) 기존 DX 코일 삭제, AFN 코일 컴포넌트·Linkage를 새 VS 코일로
    for t, nm, new_t, new_nm in old:
        remove_object(idf, t, nm)
        for afn in idf.idfobjects["AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:COIL"]:
            if afn.Coil_Name.strip().lower() == nm.lower():
                afn.Coil_Name, afn.Coil_Object_Type = new_nm, new_t
        for link in idf.idfobjects["AIRFLOWNETWORK:DISTRIBUTION:LINKAGE"]:
            if link.Component_Name.strip().lower() == nm.lower():
                link.Component_Name = new_nm
    print(f"    [ok] {RES['hp_type']} '{unit_name}' → AirLoopHVAC:UnitarySystem (참조 {n}곳) "
          f"+ VS 냉방 '{sc}' / VS 난방 '{sh}' (10단, autosize, AFN 연결 유지)")


def sep_dhw(idf: IDF) -> None:
    """실내 공기형 HPWH(WrappedCondenser) → ASIHP 급탕 코일의 외기형 PumpedCondenser HPWH (탱크 유지)"""
    hpwh = next(iter(idf.idfobjects[RES["hpwh_type"].upper()]), None)
    if hpwh is None:
        print(f"    [warn] {RES['hpwh_type']} 없음 — 급탕 교체 생략")
        return
    tank = get_object(idf, hpwh.Tank_Object_Type, hpwh.Tank_Name)
    if tank is None:
        print("    [warn] HPWH 탱크를 찾지 못함 — 급탕 교체 생략")
        return

    # 1) 기존 HPWH 정보 보관 후 삭제 (본체·증발기 코일·팬·공기 노드)
    keep = dict(name=hpwh.Name, setpoint=hpwh.Compressor_Setpoint_Temperature_Schedule_Name,
                use=(hpwh.Tank_Use_Side_Inlet_Node_Name, hpwh.Tank_Use_Side_Outlet_Node_Name))
    sensor = {f: getattr(hpwh, f, "") for f in (
        "Control_Sensor_1_Height_In_Stratified_Tank", "Control_Sensor_1_Weight",
        "Control_Sensor_2_Height_In_Stratified_Tank")}
    old_air = [getattr(hpwh, f, "") for f in (
        "Air_Inlet_Node_Name", "Air_Outlet_Node_Name", "Outdoor_Air_Node_Name",
        "Exhaust_Air_Node_Name", "Inlet_Air_Mixer_Node_Name", "Outlet_Air_Splitter_Node_Name")]
    parts = [(hpwh.DX_Coil_Object_Type, hpwh.DX_Coil_Name), (hpwh.Fan_Object_Type, hpwh.Fan_Name)]
    for t, nm in parts:
        o = get_object(idf, t, nm)
        old_air += node_fields(o) if o is not None else []
    remove_from_zone_equipment(idf, RES["hpwh_type"], keep["name"])
    idf.removeidfobject(hpwh)
    print(f"    - {RES['hpwh_type']} '{keep['name']}'")
    for t, nm in parts:
        remove_object(idf, t, nm)
    remove_orphan_nodes(idf, old_air)
    n = retarget(idf, RES["hpwh_type"], keep["name"], "WaterHeater:HeatPump:PumpedCondenser", keep["name"])

    # 2) ASIHP 급탕 코일 + 외기형 HPWH (기존 탱크, 기존 압축기 setpoint)
    coil, cond, air, air_flow = add_vs_dhw_coil(idf, keep["name"])
    stratified = tank.key.upper() == "WATERHEATER:STRATIFIED"
    add_outdoor_hpwh(
        idf, keep["name"], "WaterHeater:Stratified" if stratified else "WaterHeater:Mixed", tank,
        keep["use"], "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", coil, cond, air,
        keep["setpoint"], RES["always_on"], water_flow=ASIHP["dhw_water_flow"], air_flow=air_flow,
        min_inlet_temp=ASIHP["hpwh_min_inlet_temp"], element_logic=RES["tank_element_logic"],
        sensor=sensor if stratified else None)
    print(f"    [ok] plant 참조 {n}곳 → PumpedCondenser, 급탕 setpoint '{keep['setpoint']}' "
          f"({schedule_max(idf, keep['setpoint']):g} °C), 탱크 '{tank.Name}' 유지")


def res_outputs(idf: IDF) -> None:
    ihp = ("Integrated Heat Pump Electricity Rate", "Integrated Heat Pump Air Heating Rate",
           "Integrated Heat Pump Air Total Cooling Rate", "Integrated Heat Pump Water Heating Rate")
    common = ("Cooling Coil Total Cooling Rate", "Heating Coil Heating Rate",
              "Water Heater Source Side Heat Transfer Rate", "Water Heater Use Side Outlet Temperature")
    for var in (ihp if RES["model"] != "separate" else ()) + common:
        add(idf, "Output:Variable", None, Key_Value="*", Variable_Name=var, Reporting_Frequency="Hourly")


def apply_residential(idf: IDF, src_path: str = None) -> None:
    if RES["model"] == "separate":
        print("  ── 냉난방: 단일속도 ASHP → ASIHP 구성 VS 냉·난방 코일 (UnitarySystem, 분리 모델)")
        sep_space_coils(idf, src_path)
        print("  ── 급탕: 실내 공기형 HPWH → ASIHP 구성 VS 급탕 코일의 외기형 HPWH")
        sep_dhw(idf)
    else:
        print("  ── 냉난방 + 급탕: ASHP + HPWH → ASIHP (CoilSystem:IntegratedHeatPump:AirSource)")
        res_to_asihp(idf, src_path)
    if ADD_OUTPUT_VARIABLES:
        res_outputs(idf)


# ═════════════════════════════════════════════════════════════════════════════
# Office — VS 공기열원 히트펌프 AHU + 외기형 VS 히트펌프 급탕기
# ═════════════════════════════════════════════════════════════════════════════

def office_ahu_to_vs_hp(idf: IDF, ahu: str) -> set:
    """AHU 냉·난방 코일 → UnitarySystem(VS 냉방 + VS 난방). 반환: 삭제한 코일의 커브 이름"""
    p = f"PACU_VAV_{ahu}"
    branch = get_object(idf, "Branch", f"{p} Air Loop Main Branch")
    if branch is None:
        print(f"    [warn] '{p} Air Loop Main Branch' 없음 — 건너뜀")
        return set()
    oa_out = f"{p}_OA-{p}_CoolCNode"
    mid = f"{p}_CoolC-{p}_HeatCNode"          # 냉방 코일 출구 (기존 CoolC SAT Manager setpoint)
    fan_in = f"{p}_HeatC-{p} FanNode"         # 난방 코일 출구 (기존 HeatC MixedAir Manager setpoint)
    fan_out = f"{p} Supply Equipment Outlet Node"

    # 1) 기존 DX 냉방(CoilSystem + TwoSpeed) + 난방 코일(Fuel 또는 Measure 1의 Electric)
    tw = get_object(idf, "Coil:Cooling:DX:TwoSpeed", f"{p} Cooling Coil")
    curves = {str(v).strip() for v in (tw.obj[2:] if tw else []) if str(v).startswith("LgDX")}
    remove_object(idf, "CoilSystem:Cooling:DX", f"{p} Cooling Coil")
    remove_object(idf, "Coil:Cooling:DX:TwoSpeed", f"{p} Cooling Coil")
    if not remove_object(idf, "Coil:Heating:Fuel", f"{p} Heating Coil"):
        remove_object(idf, "Coil:Heating:Electric", f"{p} Heating Coil")
    for node in (f"{p}_CoolC Cond OA node", f"{p}_CoolCOA Ref node"):
        remove_object(idf, "OutdoorAir:Node", node)

    # 2) VS 코일 + UnitarySystem (팬 포함, 코일 출구 노드 이름은 기존과 같게 → 기존 SPM 그대로 사용)
    sc, sh = add_vs_coils(idf, p, oa_out, mid, fan_in)
    us = f"{p} ASHP UnitarySystem"
    add(idf, "AirLoopHVAC:UnitarySystem", us, Control_Type="SetPoint",
        Dehumidification_Control_Type="None", Availability_Schedule_Name=OFF["always_on"],
        Air_Inlet_Node_Name=oa_out, Air_Outlet_Node_Name=fan_out,
        Supply_Fan_Object_Type="Fan:VariableVolume", Supply_Fan_Name=f"{p} Fan",
        Fan_Placement="DrawThrough", Supply_Air_Fan_Operating_Mode_Schedule_Name=OFF["always_on"],
        Heating_Coil_Object_Type="Coil:Heating:DX:VariableSpeed", Heating_Coil_Name=sh,
        DX_Heating_Coil_Sizing_Ratio=1.0,
        Cooling_Coil_Object_Type="Coil:Cooling:DX:VariableSpeed", Cooling_Coil_Name=sc,
        Use_DOAS_DX_Cooling_Coil="No", Minimum_Supply_Air_Temperature=2.0,
        Cooling_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate", Cooling_Supply_Air_Flow_Rate="autosize",
        Heating_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate", Heating_Supply_Air_Flow_Rate="autosize",
        No_Load_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate", No_Load_Supply_Air_Flow_Rate="autosize",
        Maximum_Supply_Air_Temperature=50.0,
        Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation=21.0)

    # 3) Branch: OA system → UnitarySystem (팬은 UnitarySystem 안)
    branch.obj[3:] = branch.obj[3:7] + ["AirLoopHVAC:UnitarySystem", us, oa_out, fan_out]
    print(f"  ── AHU '{p}' → UnitarySystem (VS 냉방 {ASIHP['num_speeds']}단 + VS 난방 {ASIHP['num_speeds']}단)")
    return curves


def office_sat_control(idf: IDF) -> None:
    """
    외기온도 기반 급기온도 EMS (원래 코드 Step 3, OFF['sat_reset']=True일 때만):
      ※ 원래 코드는 Sizing:System 난방 급기온도도 40 °C로 바꿨는데, 그러면 VAV 재열 코일 용량이
        0 W로 sizing되어 zone 난방이 안 됨 → 여기서는 Sizing:System을 바꾸지 않음
      외기 ≥ oat_cool → 원래 SPM(Warmest) 그대로 / ≤ oat_heat → sat_heat_max / 사이는 선형.
      UnitarySystem(SetPoint)은 각 코일 출구 setpoint으로 운전하므로 급기 출구뿐 아니라
      냉방·난방 코일 출구 노드에도 같은 값을 준다 (원래 코드는 급기 출구에만 줘서 코일이 반응하지 않았음).
    """
    add(idf, "EnergyManagementSystem:Sensor", "IHP_OAT",
        OutputVariable_or_OutputMeter_Index_Key_Name="Environment",
        OutputVariable_or_OutputMeter_Name="Site Outdoor Air Drybulb Temperature")
    add(idf, "EnergyManagementSystem:GlobalVariable", None, Erl_Variable_1_Name="IHP_SAT_Target")
    acts = []
    for ahu in AHU_LIST:
        p = f"PACU_VAV_{ahu}"
        for tag, node in (("SAT", f"{p} Supply Equipment Outlet Node"),
                          ("CC", f"{p}_CoolC-{p}_HeatCNode"),
                          ("HC", f"{p}_HeatC-{p} FanNode")):
            name = f"IHP_{tag}_SP_{ahu.upper()}"
            add(idf, "EnergyManagementSystem:Actuator", name,
                Actuated_Component_Unique_Name=node, Actuated_Component_Type="System Node Setpoint",
                Actuated_Component_Control_Type="Temperature Setpoint")
            acts.append(name)
    o = OFF
    lines = [f"IF IHP_OAT >= {o['oat_cool']}", "SET IHP_SAT_Target = NULL",
             f"ELSEIF IHP_OAT <= {o['oat_heat']}", f"SET IHP_SAT_Target = {o['sat_heat_max']}",
             "ELSE",
             f"SET IHP_SAT_Target = {o['sat_cool_min']} + ({o['sat_heat_max']} - {o['sat_cool_min']}) * "
             f"({o['oat_cool']} - IHP_OAT) / ({o['oat_cool']} - {o['oat_heat']})",
             "ENDIF"] + [f"SET {a} = IHP_SAT_Target" for a in acts]
    add(idf, "EnergyManagementSystem:Program", "IHP_SAT_Control", values=lines)
    add(idf, "EnergyManagementSystem:ProgramCallingManager", "IHP_SAT_Control_Manager",
        EnergyPlus_Model_Calling_Point="AfterPredictorAfterHVACManagers", Program_Name_1="IHP_SAT_Control")
    print(f"  ── EMS 급기온도 제어 (외기 ≤ {o['oat_heat']:g} °C → {o['sat_heat_max']:g} °C, "
          f"≥ {o['oat_cool']:g} °C → 기존 SPM)")


def office_dhw(idf: IDF) -> None:
    """가스 WaterHeater:Mixed → 전기 백업 탱크 + 외기형 VS 히트펌프 급탕기"""
    tank = get_object(idf, "WaterHeater:Mixed", OFF["tank_name"])
    if tank is None:
        print(f"    [warn] WaterHeater:Mixed '{OFF['tank_name']}' 없음 — 급탕 교체 생략")
        return
    setpoint_sch = tank.Setpoint_Temperature_Schedule_Name
    setpoint = schedule_max(idf, setpoint_sch)
    ensure_type_limits(idf, "Temperature")
    tank.Setpoint_Temperature_Schedule_Name = constant_schedule(
        idf, f"{tank.Name} Backup Setpoint", setpoint - OFF["backup_offset"], "Temperature")
    if str(tank.Heater_Fuel_Type).strip().lower() != "electricity":
        tank.Off_Cycle_Parasitic_Fuel_Consumption_Rate = 0     # 가스 파일럿·연도 손실 제거
        tank.On_Cycle_Parasitic_Fuel_Consumption_Rate = 0
    tank.Heater_Fuel_Type = "Electricity"
    tank.Heater_Thermal_Efficiency = 1.0
    tank.Off_Cycle_Parasitic_Fuel_Type = tank.On_Cycle_Parasitic_Fuel_Type = "Electricity"

    name = "SWHSys1 HP Water Heater"
    coil, cond, air, air_flow = add_vs_dhw_coil(idf, name)
    add_outdoor_hpwh(idf, name, "WaterHeater:Mixed", tank,
                     (tank.Use_Side_Inlet_Node_Name, tank.Use_Side_Outlet_Node_Name),
                     "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed", coil, cond, air,
                     setpoint_sch, OFF["always_on"], water_flow=ASIHP["dhw_water_flow"],
                     air_flow=air_flow, min_inlet_temp=ASIHP["hpwh_min_inlet_temp"],
                     element_logic="MutuallyExclusive")
    print(f"    [ok] '{tank.Name}' 가스 → 전기 백업 ({setpoint - OFF['backup_offset']:g} °C), "
          f"히트펌프 setpoint {setpoint:g} °C, 용량 {ASIHP['dhw_cap'] / 1000:g} kW")


def _remove_unused_curves(idf: IDF, names) -> None:
    for name in names:
        used = any(str(v).strip().lower() == name.lower()
                   for objs in idf.idfobjects.values() for o in objs for v in o.obj[2:])
        if not used:
            for t in ("Curve:Biquadratic", "Curve:Quadratic"):
                remove_object(idf, t, name)


def office_outputs(idf: IDF) -> None:
    for key, var in [("*", "Cooling Coil Total Cooling Rate"), ("*", "Cooling Coil Electricity Rate"),
                     ("*", "Heating Coil Heating Rate"), ("*", "Heating Coil Electricity Rate"),
                     ("*", "Water Heater Heat Pump Water Heating Rate"),
                     ("*", "Water Heater Heating Rate"),
                     ("*", "Site Outdoor Air Drybulb Temperature")]:
        add(idf, "Output:Variable", None, Key_Value=key, Variable_Name=var, Reporting_Frequency="Hourly")
    for ahu in AHU_LIST:
        node = f"PACU_VAV_{ahu} Supply Equipment Outlet Node"
        for var in ("System Node Temperature", "System Node Setpoint Temperature"):
            add(idf, "Output:Variable", None, Key_Value=node, Variable_Name=var, Reporting_Frequency="Hourly")


def apply_office(idf: IDF) -> None:
    curves = set()
    for ahu in AHU_LIST:
        curves |= office_ahu_to_vs_hp(idf, ahu)
    _remove_unused_curves(idf, curves)
    if OFF["sat_reset"]:
        office_sat_control(idf)
    print("  ── 급탕: 가스 탱크 → 외기형 VS 히트펌프 급탕기 + 전기 백업")
    office_dhw(idf)
    if ADD_OUTPUT_VARIABLES:
        office_outputs(idf)


# ═════════════════════════════════════════════════════════════════════════════
# 파일명 → building type / 기후대 / 도시
# ═════════════════════════════════════════════════════════════════════════════

def detect_building_type(fname: str):
    """파일 이름으로 building type 판별 → 'residential' / 'office' / None"""
    low = fname.lower()
    if "office" in low:
        return "office"
    if low.startswith("us+") or "+sf+" in low or "+mf+" in low or "residential" in low:
        return "residential"
    return None


def _city_from_site(idf: IDF) -> str:
    """Site:Location 이름에서 도시명만 추출. 예) 'Miami Intl Ap FL USA ...' → 'Miami'"""
    name = idf.idfobjects["SITE:LOCATION"][0].Name
    name = re.split(r"[-_,]|\b(?:Intl|Int'l|AP|Ap|Arpt|Airport|TMY\d*|WMO)\b", name)[0]
    words = [w for w in re.findall(r"[A-Za-z]+", name) if not (w.isupper() and len(w) <= 3)]
    return "".join(w[0].upper() + w[1:] for w in words) or "Unknown"


def name_parts(fname: str, idf: IDF, btype: str):
    """(building type, climate zone, city) 반환. 형식을 모르면 None"""
    if btype == "residential":
        tokens = [t.lower() for t in os.path.splitext(fname)[0].split("+")]
        cz = re.search(r"CZ(\d[ABC]?)", fname, re.I)
        kind = "SF" if "sf" in tokens else "MF" if "mf" in tokens else ""
        foundation = next((FOUNDATIONS[t] for t in tokens if t in FOUNDATIONS), None)
        btype_name = f"Residential{kind}" + (f"-{foundation}" if foundation else "")
        return btype_name, cz.group(1).upper() if cz else "CZunknown", _city_from_site(idf)

    m = re.match(r"^NewModel\d+_(?P<bt>[^_]+)_(?P<cz>[^_]+)_(?P<city>.+)\.idf$", fname, re.I)
    if m:
        return m.group("bt"), m.group("cz"), m.group("city")
    m = re.match(r"^ASHRAE901_(?P<bt>[^_]+)_STD\d+_(?P<city>.+)\.idf$", fname, re.I)
    if m:
        city = m.group("city")
        return m.group("bt"), CLIMATE_ZONES.get(city, "CZunknown"), city
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 실행
# ═════════════════════════════════════════════════════════════════════════════

def run_measure6(input_dirs=INPUT_DIRS, output_dir=OUTPUT_DIR, idd_path=IDD_PATH):
    if IDF.getiddname() is None:
        IDF.setiddname(idd_path)
    os.makedirs(output_dir, exist_ok=True)

    paths = sorted({p for d in input_dirs for p in glob.glob(os.path.join(d, "*.idf"))})
    if not paths:
        print(f"[!] IDF 파일이 없습니다: {input_dirs}")
        return []

    saved, used_names = [], set()
    for path in paths:
        fname = os.path.basename(path)
        btype = detect_building_type(fname)
        if btype is None:
            print(f"\n[skip] building type을 알 수 없음: {fname}")
            continue

        print(f"\n[{btype}] {fname}")
        idf = load_clean_idf(path)
        parts = name_parts(fname, idf, btype)
        if parts is None:
            print(f"  [skip] 파일명 형식이 다름: {fname}")
            continue
        if parts[1] == "CZunknown":
            print(f"  [warn] 기후대를 찾지 못함 → CLIMATE_ZONES에 '{parts[2]}' 추가 필요")

        if btype == "residential":
            apply_residential(idf, path)
        else:
            apply_office(idf)

        n_inv = replace_pvwatts_inverter(idf)
        if n_inv:
            print(f"  ── PV 인버터 {n_inv}개 → Inverter:Simple (baseline과 동일)")

        stem = f"{OUTPUT_PREFIX}_" + "_".join(parts)
        out_name, k = f"{stem}.idf", 2
        while out_name in used_names:
            out_name, k = f"{stem}_{k}.idf", k + 1
        if k > 2:
            print(f"  [warn] 이름 중복 → '{out_name}'로 저장")
        used_names.add(out_name)

        out_path = os.path.join(output_dir, out_name)
        idf.saveas(out_path)
        saved.append(out_path)
        print(f"  [saved] {out_name}")

    print(f"\n완료: {len(saved)}/{len(paths)}개 저장 → {output_dir}")
    return saved


if __name__ == "__main__":
    run_measure6()