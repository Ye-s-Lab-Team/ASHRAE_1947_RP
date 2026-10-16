"""
Measure 4 — Office HVAC를 비통합형(unintegrated) ASHP로 교체
=============================================================
입력 폴더의 IDF 중 office 모델만 처리한다. (residential hp prototype은 냉난방 ASHP +
별도 HPWH로 이미 unintegrated 구성이라 이 measure에서 변경하지 않는다.)

  Office (ASHRAE901_OfficeMedium… 원본 또는 Measure 1 결과)
    • AHU(bot/mid/top)마다 CoilSystem:Cooling:DX(TwoSpeed) + 난방 코일(Fuel 또는 Electric)
      → AirLoopHVAC:UnitarySystem
           ├ Coil:Cooling:DX:SingleSpeed   (COP 3.4)
           ├ Coil:Heating:DX:SingleSpeed   (COP 3.2, 압축기 차단 −8 °C)
           └ Coil:Heating:Electric 보조    (외기 −8 °C 이하에서만)
    • PV 인버터 Inverter:PVWatts → Inverter:Simple (Measure 1 baseline과 같은 PV 모델)

출력: OUTPUT_DIR/NewModel4_{building type}_{climate zone}_{city}.idf
"""

import io
import os
import re
import glob
from eppy.modeleditor import IDF


# ═════════════════════════════════════════════════════════════════════════════
# 설정
# ═════════════════════════════════════════════════════════════════════════════

script_dir = os.path.dirname(os.path.abspath(__file__))
model_root = os.path.join(script_dir, "..", "..", "Original_model")

IDD_PATH = r"C:\EnergyPlusV25-1-0\Energy+.idd"

INPUT_DIRS = [
    os.path.join(script_dir, "..", "..", "Original_model", "office"),# office
]
OUTPUT_DIR = os.path.join(script_dir, "..", "NewModel4")
OUTPUT_PREFIX = "NewModel4"

# ── Office: ASHP 사양 ────────────────────────────────────────────────────────────
AHU_LIST = ["bot", "mid", "top"]
ASHP = {
    "cooling_cop": 3.4,
    "heating_cop": 3.2,
    "min_oat_compressor": -8.0,     # 이하에서 압축기 정지
    "max_oat_supplemental": -8.0,   # 이하에서만 보조 전기히터 운전
    "max_oat_defrost": 5.0,
    "max_supply_air_temp": 50.0,
}

# ── 도시 → 기후대 (office 파일명에 기후대가 없을 때 사용) ───────────────────────
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

# ═════════════════════════════════════════════════════════════════════════════
# IDF 공통 유틸
# ═════════════════════════════════════════════════════════════════════════════

def load_clean_idf(path: str) -> IDF:
    """전처리기 경고 문장이 오브젝트처럼 들어간 레코드를 제거한 뒤 로드"""
    with open(path, "r", encoding="latin-1") as f:
        records = re.split(r"(;)", f.read())
    cleaned, i = [], 0
    while i < len(records):
        chunk = records[i]
        obj_type = next((ln.strip().split(",")[0].strip()
                         for ln in chunk.splitlines()
                         if ln.strip() and not ln.strip().startswith("!")), "")
        if re.search(r"[ \[\]()]", obj_type):
            print(f"    [clean] 잘못된 레코드 제거: '{obj_type[:60]}'")
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


def replace_pvwatts_inverter(idf: IDF, availability_schedule: str = "") -> int:
    """
    ElectricLoadCenter:Inverter:PVWatts → 같은 이름·같은 효율의 Inverter:Simple로 교체.
    Measure 1(baseline) / Measure 3과 같은 함수 — 모든 모델이 같은 PV 모델을 쓰도록 한다.
    """
    n = 0
    for old in list(idf.idfobjects["ELECTRICLOADCENTER:INVERTER:PVWATTS"]):
        name, eff = old.Name, old.Inverter_Efficiency or 0.96
        idf.removeidfobject(old)
        idf.newidfobject("ELECTRICLOADCENTER:INVERTER:SIMPLE", Name=name,
                         Availability_Schedule_Name=availability_schedule,
                         Radiative_Fraction=0, Inverter_Efficiency=eff)
        n += 1
    return n


# ═════════════════════════════════════════════════════════════════════════════
# Office — AHU 냉·난방 코일 → UnitarySystem(ASHP)
# ═════════════════════════════════════════════════════════════════════════════

def _add_curve(idf: IDF, curve_type: str, name: str, coeffs: list, limits: list) -> None:
    if get_object(idf, curve_type, name):
        return
    obj = idf.newidfobject(curve_type.upper(), Name=name)
    obj.obj[2:] = list(coeffs) + list(limits)        # 계수 → x/y 최소·최대 순서
    print(f"    + {curve_type} '{name}'")


def add_ashp_curves(idf: IDF) -> None:
    """ASHP 난방 성능 커브 (냉방은 기존 LgDXalt_* 커브 사용)"""
    xy = [5.0, 24.0, -20.0, 20.0]                     # x: 실내 건구, y: 외기 건구 (°C)
    _add_curve(idf, "Curve:Biquadratic", "ASHP_HTG_CapFT",
               [0.876825, -0.002955, -0.000058, 0.025335, 0.000196, -0.000043], xy)
    _add_curve(idf, "Curve:Biquadratic", "ASHP_HTG_EIRFT",
               [0.704658, 0.008767, 0.000625, -0.009037, 0.000738, -0.001025], xy)
    _add_curve(idf, "Curve:Biquadratic", "ASHP_HTG_DefrostEIRFT",
               [1.0, 0, 0, 0, 0, 0], xy)
    _add_curve(idf, "Curve:Cubic", "ASHP_HTG_CapFF",
               [0.694045465, 0.474207981, -0.180783882, 0.012530446], [0.5, 1.5])
    _add_curve(idf, "Curve:Cubic", "ASHP_HTG_EIRFF",
               [1.570774717, -0.914152018, 0.036729136, 0.306648166], [0.5, 1.5])
    _add_curve(idf, "Curve:Quadratic", "ASHP_HTG_PLF",
               [0.85, 0.15, 0.0], [0.0, 1.0])


def convert_ahu_to_ashp(idf: IDF, ahu: str) -> None:
    p = f"PACU_VAV_{ahu}"
    us_name   = f"{p} Unitary ASHP"
    us_inlet  = f"{p}_OA-{p}_CoolCNode"
    us_outlet = f"{p}_HeatC-{p} FanNode"
    clg_out   = f"{us_name} Cooling Coil Air Outlet"
    htg_out   = f"{us_name} Heating Coil Air Outlet"
    supply_out = f"{p} Supply Equipment Outlet Node"
    cond_node = f"{p} ASHP CLG Condenser Inlet Node"

    branch = get_object(idf, "Branch", f"{p} Air Loop Main Branch")
    if branch is None:
        print(f"    [warn] '{p} Air Loop Main Branch' 없음 — 건너뜀")
        return
    print(f"  ── AHU '{p}'")

    # 1) 기존 냉·난방 코일 삭제 (난방은 Measure 1 전이면 Fuel, 후면 Electric)
    remove_object(idf, "CoilSystem:Cooling:DX", f"{p} Cooling Coil")
    remove_object(idf, "Coil:Cooling:DX:TwoSpeed", f"{p} Cooling Coil")
    if not remove_object(idf, "Coil:Heating:Fuel", f"{p} Heating Coil"):
        remove_object(idf, "Coil:Heating:Electric", f"{p} Heating Coil")
    remove_object(idf, "SetpointManager:MixedAir", f"{p}_CoolC SAT Manager")

    # 2) 냉방 코일 응축기 외기 노드
    if not get_object(idf, "OutdoorAir:Node", cond_node):
        idf.newidfobject("OUTDOORAIR:NODE", Name=cond_node)

    # 3) ASHP 코일 3개
    idf.newidfobject(
        "COIL:COOLING:DX:SINGLESPEED",
        Name=f"{p} ASHP Cooling Coil",
        Availability_Schedule_Name="Always_On",
        Gross_Rated_Total_Cooling_Capacity="AUTOSIZE",
        Gross_Rated_Sensible_Heat_Ratio="AUTOSIZE",
        Gross_Rated_Cooling_COP=ASHP["cooling_cop"],
        Rated_Air_Flow_Rate="AUTOSIZE",
        Air_Inlet_Node_Name=us_inlet,
        Air_Outlet_Node_Name=clg_out,
        Total_Cooling_Capacity_Function_of_Temperature_Curve_Name="LgDXalt_CapFT",
        Total_Cooling_Capacity_Function_of_Flow_Fraction_Curve_Name="LgDXalt_CapFF",
        Energy_Input_Ratio_Function_of_Temperature_Curve_Name="LgDXalt_EIRFT",
        Energy_Input_Ratio_Function_of_Flow_Fraction_Curve_Name="LgDXalt_EIRFF",
        Part_Load_Fraction_Correlation_Curve_Name="LgDXalt_PLR",
        Condenser_Air_Inlet_Node_Name=cond_node,
        Condenser_Type="AirCooled",
        Crankcase_Heater_Capacity=0.0,
        Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation=10.0,
    )
    idf.newidfobject(
        "COIL:HEATING:DX:SINGLESPEED",
        Name=f"{p} ASHP Heating Coil",
        Availability_Schedule_Name="Always_On",
        Gross_Rated_Heating_Capacity="AUTOSIZE",
        Gross_Rated_Heating_COP=ASHP["heating_cop"],
        Rated_Air_Flow_Rate="AUTOSIZE",
        Air_Inlet_Node_Name=clg_out,
        Air_Outlet_Node_Name=htg_out,
        Heating_Capacity_Function_of_Temperature_Curve_Name="ASHP_HTG_CapFT",
        Heating_Capacity_Function_of_Flow_Fraction_Curve_Name="ASHP_HTG_CapFF",
        Energy_Input_Ratio_Function_of_Temperature_Curve_Name="ASHP_HTG_EIRFT",
        Energy_Input_Ratio_Function_of_Flow_Fraction_Curve_Name="ASHP_HTG_EIRFF",
        Part_Load_Fraction_Correlation_Curve_Name="ASHP_HTG_PLF",
        Defrost_Energy_Input_Ratio_Function_of_Temperature_Curve_Name="ASHP_HTG_DefrostEIRFT",
        Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation=ASHP["min_oat_compressor"],
        Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation=ASHP["max_oat_defrost"],
        Crankcase_Heater_Capacity=0.0,
        Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation=10.0,
        Defrost_Strategy="ReverseCycle",
        Defrost_Control="Timed",
        Defrost_Time_Period_Fraction=0.058333,
        Resistive_Defrost_Heater_Capacity="AUTOSIZE",
    )
    idf.newidfobject(
        "COIL:HEATING:ELECTRIC",
        Name=f"{p} Backup Electric Coil",
        Availability_Schedule_Name="Always_On",
        Efficiency=1.0,
        Nominal_Capacity="AUTOSIZE",
        Air_Inlet_Node_Name=htg_out,
        Air_Outlet_Node_Name=us_outlet,
        Temperature_Setpoint_Node_Name=us_outlet,
    )

    # 4) UnitarySystem (setpoint 제어)
    idf.newidfobject(
        "AIRLOOPHVAC:UNITARYSYSTEM",
        Name=us_name,
        Control_Type="SetPoint",
        Availability_Schedule_Name="Always_On",
        Air_Inlet_Node_Name=us_inlet,
        Air_Outlet_Node_Name=us_outlet,
        Heating_Coil_Object_Type="Coil:Heating:DX:SingleSpeed",
        Heating_Coil_Name=f"{p} ASHP Heating Coil",
        Cooling_Coil_Object_Type="Coil:Cooling:DX:SingleSpeed",
        Cooling_Coil_Name=f"{p} ASHP Cooling Coil",
        Supplemental_Heating_Coil_Object_Type="Coil:Heating:Electric",
        Supplemental_Heating_Coil_Name=f"{p} Backup Electric Coil",
        Cooling_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
        Cooling_Supply_Air_Flow_Rate="AUTOSIZE",
        Heating_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
        Heating_Supply_Air_Flow_Rate="AUTOSIZE",
        No_Load_Supply_Air_Flow_Rate_Method="SupplyAirFlowRate",
        No_Load_Supply_Air_Flow_Rate="AUTOSIZE",
        Maximum_Supply_Air_Temperature=ASHP["max_supply_air_temp"],
        Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation=ASHP["max_oat_supplemental"],
    )
    print(f"    + UnitarySystem '{us_name}' (냉방 COP {ASHP['cooling_cop']}, "
          f"난방 COP {ASHP['heating_cop']}, 보조 전기히터)")

    # 5) DX 코일 출구 setpoint (UnitarySystem setpoint 제어용)
    for sp_name, node in [(f"{p}_ASHP_CoolC SAT Manager", clg_out),
                          (f"{p}_ASHP_HeatC MixedAir Manager", htg_out)]:
        idf.newidfobject(
            "SETPOINTMANAGER:MIXEDAIR",
            Name=sp_name,
            Control_Variable="Temperature",
            Reference_Setpoint_Node_Name=supply_out,
            Fan_Inlet_Node_Name=us_outlet,
            Fan_Outlet_Node_Name=supply_out,
            Setpoint_Node_or_NodeList_Name=node,
        )

    # 6) Branch: OA System → UnitarySystem → Fan
    oa = branch.obj[3:7]                            # 1번 컴포넌트(OA system) 유지
    branch.obj[3:] = oa + [
        "AirLoopHVAC:UnitarySystem", us_name, us_inlet, us_outlet,
        "Fan:VariableVolume", f"{p} Fan", us_outlet, supply_out,
    ]
    print(f"    [ok] Branch '{branch.Name}' → OA / UnitarySystem / Fan")


def apply_office(idf: IDF) -> None:
    print("  ── ASHP 난방 커브")
    add_ashp_curves(idf)
    for ahu in AHU_LIST:
        convert_ahu_to_ashp(idf, ahu)


# ═════════════════════════════════════════════════════════════════════════════
# 파일명 → building type / 기후대 / 도시
# ═════════════════════════════════════════════════════════════════════════════

def detect_building_type(fname: str):
    """파일 이름으로 building type 판별 → 'residential' / 'office' / None
    (이 measure는 office만 변경하고 residential은 건너뛴다)"""
    low = fname.lower()
    if "office" in low:
        return "office"
    if low.startswith("us+") or "+sf+" in low or "+mf+" in low or "residential" in low:
        return "residential"
    return None


def name_parts(fname: str):
    """office 파일명 → (building type, climate zone, city). 형식을 모르면 None"""
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

def run_measure4(input_dirs=INPUT_DIRS, output_dir=OUTPUT_DIR, idd_path=IDD_PATH):
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
        if btype != "office":
            reason = ("residential — 이미 unintegrated ASHP, 변경 없음"
                      if btype == "residential" else "building type을 알 수 없음")
            print(f"\n[skip] {fname} ({reason})")
            continue

        parts = name_parts(fname)
        if parts is None:
            print(f"\n[skip] 파일명 형식이 다름: {fname}")
            continue

        print(f"\n[office] {fname}")
        idf = load_clean_idf(path)
        if parts[1] == "CZunknown":
            print(f"  [warn] 기후대를 찾지 못함 → CLIMATE_ZONES에 '{parts[2]}' 추가 필요")

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

    print(f"\n완료: office {len(saved)}개 저장 → {output_dir}")
    return saved


if __name__ == "__main__":
    run_measure4()
