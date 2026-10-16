"""
Measure 5: Replace HVAC system to GSHP (Residential + Office)
"""

import io
import math
import os
import re
import glob
from eppy.modeleditor import IDF


script_dir = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.join(script_dir, "..", "..", "Original_model")

IDD_PATH = r"C:\EnergyPlusV25-1-0\Energy+.idd"

INPUT_DIRS = [
    os.path.join(MODEL_ROOT, "residential", "system_ashp"),  # residential
    os.path.join(MODEL_ROOT, "office"),            # office
]
OUTPUT_DIR = os.path.join(script_dir, "..", "NewModel5")
OUTPUT_PREFIX = "NewModel5"


# residential
RES = {
    "always_on": "always_avail",
    "cooling_coil": "GSHP Cooling Coil_unit1",
    "heating_coil": "GSHP Heating Coil_unit1",
    "clg_capacity": "autosize",            
    "clg_sensible_capacity": "autosize",   
    "clg_cop": 7.007757577,
    "htg_capacity": "autosize",            
    "htg_cop": 3.167053691,
    "clg_rated_ewt": 25.0,
    "htg_rated_ewt": 0.0,
    "coil_air_flow": "autosize",           
    "coil_water_flow": "autosize",         
    "pump": {"Design_Pump_Head": 50000, "Design_Power_Consumption": "autosize"},  
    "loop_sizing": ("Condenser", 30.0, 5.5),   # Sizing:Plant for autosize 
    "ghe_layout": (4, 1, 6.0), # 4 bore holes
    "ghe_layout_by_cz": {"6": (6, 1, 6.0), "7": (6, 1, 6.0), "8": (8, 1, 6.0)}, # use different number of boreholes by location
    "ghe_flow_per_borehole": 0.0003,           # m3/s
    # use different medium water -> propylene glycol
    "loop_glycol": ("PropyleneGlycol", 0.3),
    "loop_min_temp": -10,
}
RES_TANK = {                                   
    "Tank_Volume": 0.30283288,
    "Heater_1_Capacity": 4500,
    "Uniform_Skin_Loss_Coefficient_per_Unit_Area_to_Ambient_Temperature": 0.232135950478784,
    "Number_of_Nodes": 6,
}
RES_TANK_ZONE = "garage1"                      
HPWH_TYPE = "WaterHeater:HeatPump:WrappedCondenser"

# office
AHU_LIST = ["bot", "mid", "top"]
OFF = {
    "always_on": "Always_On",
    "chw_supply_temp": 7.0, "chw_delta_t": 5.0,
    "hw_supply_temp": 45.0, "hw_delta_t": 11.0,
    "ghe_setpoint": 22.0, "ghe_exit_temp": 30.0, "ghe_delta_t": 5.5,
    "pump_head": 179352,
    "ghe_nx": 6, "ghe_ny": 6, "ghe_design_flow": 0.01344,
}

# water heater
DHW = {
    "loop_offset": 5.0,      # setpoint + 5 °C
    "backup_offset": 5.0,    # setpoint − 5 °C
    "target_margin": 1.0,    # use when temperature is lower than target temperature
    "cold_start": 14.44,     # tank indirect water heating recovery temperature
}

RES_DHW_PUMP_HEAD = 50000    # Pa, residential water heating loop pump spec.

# ground temperature by location 

EPW_DIR = os.path.join(MODEL_ROOT, "weather")
GROUND_BY_CITY = {
}
GROUND_DEFAULT = dict(t_avg=13.0, amp=10.0, phase=17.3, deep=[13.0] * 12)

# g-function
SOIL = {
    "residential": dict(k=0.692626, rho=1500.0, cp=1563.34, heat_cap=2347000),
    "office":      dict(k=1.8, rho=2500.0, cp=880.0, heat_cap=2.2e6),
}

BOREHOLE = {
    "residential": dict(top=1, length=76.2, dia=0.127016, grout_k=0.692626, grout_cp=3900000,
                        pipe_k=0.391312, pipe_cp=1542000, pipe_od=0.0266667,
                        pipe_t=0.00241285, utube=0.051225),
    "office":      dict(top=1.0, length=76.2, dia=0.1143, grout_k=1.0, grout_cp=3.9e6,
                        pipe_k=0.4, pipe_cp=1.542e6, pipe_od=0.0267,
                        pipe_t=0.00243, utube=0.0521),
}
GFUNC = {   # (ln(t/ts), g) if pre-calculated g-function is used
    "office": [
        (-15.2996, 1.0000), (-14.2010, 1.0220), (-13.2154, 1.0637), (-12.2310, 1.1518),
        (-11.2447, 1.3351), (-10.2599, 1.6762), (-9.2740, 2.2237), (-8.2864, 3.0029),
        (-7.8000, 3.3956), (-7.2000, 3.9044), (-6.5000, 4.5555), (-5.9000, 5.1530),
        (-5.2000, 5.9527), (-4.5000, 6.8860), (-3.9630, 7.6857), (-3.2700, 8.9150),
        (-2.8640, 9.7095), (-2.5770, 10.2610), (-2.1720, 11.1280), (-1.8840, 11.7440),
        (-1.1910, 13.3190), (-0.4970, 14.8670), (0.1960, 16.3650), (0.8900, 17.7870),
        (1.5840, 19.0900), (2.2780, 20.2200), (2.9720, 21.1310), (3.6650, 21.8030)],
}

# climate location
CLIMATE_ZONES = {"Miami": "1A", "Tampa": "2A", "Tucson": "2B",
    "Atlanta": "3A", "ElPaso": "3B", "SanDiego": "3C",
    "NewYork": "4A", "Albuquerque": "4B", "Seattle": "4C",
    "Buffalo": "5A", "Denver": "5B", "PortAngeles": "5C",
    "Rochester": "6A", "GreatFalls": "6B", "InternationalFalls": "7",
    "Duluth": "7", "Fairbanks": "8"}

FOUNDATIONS = {"slab": "Slab", "crawlspace": "Crawlspace",
               "unheatedbsmt": "UnheatedBsmt", "heatedbsmt": "HeatedBsmt"}



def load_clean_idf(path: str) -> IDF:
    with open(path, "r", encoding="latin-1") as f:
        records = re.split(r"(;)", f.read())
    cleaned, i = [], 0
    while i < len(records):
        chunk = records[i]
        obj_type = next((ln.strip().split(",")[0].strip()
                         for ln in chunk.splitlines()
                         if ln.strip() and not ln.strip().startswith("!")), "")
        if re.search(r"[ \[\]()]", obj_type) or obj_type.lower() == "output:preprocessormessage":
            print(f"    [clean] remove records: '{obj_type[:60]}'")
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
    """create object: curve, list."""
    kw = dict(fields)
    if name is not None:
        kw["Name"] = name
    obj = idf.newidfobject(obj_type.upper(), **kw)
    if values is not None:
        start = 2 if name is not None else 1
        obj.obj[start:] = list(values)
    return obj


def ensure_type_limits(idf: IDF, name: str, numeric="Continuous") -> None:
    if not get_object(idf, "ScheduleTypeLimits", name):
        add(idf, "ScheduleTypeLimits", name, Numeric_Type=numeric)


def constant_schedule(idf: IDF, name: str, value, limits="") -> str:
    if not get_object(idf, "Schedule:Compact", name):
        add(idf, "Schedule:Compact", name, Schedule_Type_Limits_Name=limits,
            values=[limits, "Through: 12/31", "For: AllDays", "Until: 24:00", value])
    return name


def retarget(idf: IDF, old_type: str, old_name: str, new_type: str, new_name: str) -> int:
    """change old to new type"""
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


def rename_references(idf: IDF, old_name: str, new_name: str) -> int:
    """change field name to new object field name"""
    n = 0
    for objs in idf.idfobjects.values():
        for obj in objs:
            for k in range(1, len(obj.obj)):
                if str(obj.obj[k]).strip().lower() == old_name.lower():
                    obj.obj[k] = new_name
                    n += 1
    return n


def replace_pvwatts_inverter(idf: IDF, availability_schedule: str = "") -> int:
    n = 0
    for old in list(idf.idfobjects["ELECTRICLOADCENTER:INVERTER:PVWATTS"]):
        name, eff = old.Name, old.Inverter_Efficiency or 0.96
        idf.removeidfobject(old)
        add(idf, "ElectricLoadCenter:Inverter:Simple", name,
            Availability_Schedule_Name=availability_schedule,
            Radiative_Fraction=0, Inverter_Efficiency=eff)
        n += 1
    return n


# ground temperature by location

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _read_epw_ground(path: str):
    """read from weather file"""
    with open(path, "r", encoding="latin-1") as f:
        for _ in range(8):
            line = f.readline()
            if line.upper().startswith("GROUND TEMPERATURES"):
                v = [x.strip() for x in line.strip().split(",")]
                n, out, i = int(v[1]), [], 2
                for _ in range(n):
                    depth = float(v[i])
                    out.append((depth, [float(t) for t in v[i + 4:i + 16]]))
                    i += 16
                return out
    return []


_SYNONYMS = {"international": "intl", "airport": "ap", "arpt": "ap", "aprt": "ap",
             "county": "co", "regional": "rgnl", "municipal": "muni"}


def _city_tokens(city: str) -> list:
    """'RochesterInternationalArpt' = ['rochester', 'intl', 'ap']"""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", str(city))
    return [_SYNONYMS.get(w.lower(), w.lower()) for w in words]


def _find_epw(city: str, state: str = ""):
    tokens = _city_tokens(city)
    if not tokens:
        return None
    scored = []
    for path in glob.glob(os.path.join(EPW_DIR, "**", "*.epw"), recursive=True):
        words = [_SYNONYMS.get(w, w) for w in re.split(r"[^a-z0-9]+", os.path.basename(path).lower())]
        joined = "".join(words)
        if tokens[0] not in joined:
            continue
        score = sum(t in words or t in joined for t in tokens)
        if state and state.lower() in words:                 
            score += 10
        scored.append((score, path))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    best = [p for sc, p in scored if sc == scored[0][0]]
    if len(best) > 1:
        print(f"  [warn] '{city}'has numerous epw files, use {os.path.basename(best[0])}"
              f"(list: {', '.join(os.path.basename(p) for p in best)})")
    return best[0]


def _ground_from_mains(idf: IDF):
    """
    estimate ground temperature based on the object
    """
    for wm in idf.idfobjects["SITE:WATERMAINSTEMPERATURE"]:
        try:
            t_avg = float(wm.Annual_Average_Outdoor_Air_Temperature)
            diff = float(wm.Maximum_Difference_In_Monthly_Average_Outdoor_Air_Temperatures)
        except (TypeError, ValueError):
            continue
        return dict(t_avg=round(t_avg, 2), amp=round(diff / 2, 2), phase=25.0,
                    deep=[round(t_avg, 2)] * 12, source="Site:WaterMainsTemperature")
    return None


def ground_profile(city: str, idf: IDF = None) -> dict:
    """
    ground temperature by city
    Site:WaterMainsTemperature in idf file, use default value
    """
    if city in GROUND_BY_CITY:
        g = {**GROUND_DEFAULT, **GROUND_BY_CITY[city]}
        return {**g, "source": "GROUND_BY_CITY"}

    state = ""
    if idf is not None and idf.idfobjects["SITE:LOCATION"]:
        m = re.search(r"_([A-Z]{2})_USA", str(idf.idfobjects["SITE:LOCATION"][0].Name))
        state = m.group(1) if m else ""
    path = _find_epw(city, state)
    depths = _read_epw_ground(path) if path else []
    if depths:
        shallow, deep = depths[0][1], depths[-1][1]
        t_min_month = shallow.index(min(shallow))            # 0 = Jan
        return dict(t_avg=round(sum(shallow) / 12, 2),
                    amp=round((max(shallow) - min(shallow)) / 2, 2),
                    phase=round(15 + 30.4 * t_min_month, 1),   # mid date 
                    deep=deep, source=os.path.basename(path))
    if path:
        print(f"  [warn] {os.path.basename(path)} does not have GROUND TEMPERATURES")

    g = _ground_from_mains(idf) if idf is not None else None
    if g:
        print(f"  [warn] '{city}' epw cannot find, use estimated value")
        return g

    print(f"  [warn] '{city}' ground temperature cannot be found, use default value "
          )
    return {**GROUND_DEFAULT, "source": "default"}


def set_deep_ground_temperature(idf: IDF, ground: dict) -> None:
    """Site:GroundTemperature:Deep = location value"""
    objs = idf.idfobjects["SITE:GROUNDTEMPERATURE:DEEP"]
    obj = objs[0] if objs else add(idf, "Site:GroundTemperature:Deep", None)
    obj.obj[1:] = [round(t, 2) for t in ground["deep"]]




def add_wwhp_curves(idf: IDF) -> None:
    """water to water heat pump EquationFit"""
    lim = [0, 100, 0, 100, 0, 100, 0, 100]
    for name, c in [
            ("GSHP_CoolCap_QuadLinear", [-1.52030596, 3.46625667, -1.32267797, 0.09395678, 0.038975504]),
            ("GSHP_CoolPwr_QuadLinear", [-8.59564386, 0.96265085, 8.69489229, 0.02501462, -0.20132665]),
            ("GSHP_HeatCap_QuadLinear", [-3.33491153, -0.51451946, 4.51592706, 0.01797107, 0.155797661]),
            ("GSHP_HeatPwr_QuadLinear", [-8.93121751, 8.57035762, 1.29660976, -0.21629222, 0.033862378])]:
        if not get_object(idf, "Curve:QuadLinear", name):
            add(idf, "Curve:QuadLinear", name, values=c + lim)


def add_wwhp_heating(idf: IDF, name: str, load: tuple, source: tuple, companion: str = "") -> None:
    """HeatPump:WaterToWater:EquationFit:Heating. load/source = (inlet node, outlet node)"""
    add_wwhp_curves(idf)
    add(idf, "HeatPump:WaterToWater:EquationFit:Heating", name,
        Load_Side_Inlet_Node_Name=load[0], Load_Side_Outlet_Node_Name=load[1],
        Source_Side_Inlet_Node_Name=source[0], Source_Side_Outlet_Node_Name=source[1],
        Reference_Load_Side_Flow_Rate="autosize", Reference_Source_Side_Flow_Rate="autosize",
        Reference_Heating_Capacity="autosize", Reference_Heating_Power_Consumption="autosize",
        Heating_Capacity_Curve_Name="GSHP_HeatCap_QuadLinear",
        Heating_Compressor_Power_Curve_Name="GSHP_HeatPwr_QuadLinear",
        Companion_Cooling_Heat_Pump_Name=companion)


def schedule_max(idf: IDF, name: str, default: float = 60.0) -> float:
    """max value of Schedule:Compact / Schedule:Constant (water heating setpoint reading purpose)"""
    obj = get_object(idf, "Schedule:Compact", name)
    if obj is not None:
        vals = []
        for v in obj.obj[3:]:
            for part in str(v).split(","):                    # 'Until 24:00,44'
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


def convert_tank_to_indirect(idf: IDF, tank_type: str, tank, src_in: str, src_out: str,
                             setpoint_schedule: str = None) -> float:
    """
    hot water tank has changed to indirect heating tank,
    water heating loop is connected to the source side.
    """
    stratified = tank_type.lower() == "waterheater:stratified"
    sp_field = "Heater_1_Setpoint_Temperature_Schedule_Name" if stratified \
        else "Setpoint_Temperature_Schedule_Name"
    sp_sch = setpoint_schedule or getattr(tank, sp_field)
    setpoint = schedule_max(idf, sp_sch)
    # adjust target setpoint -> if temperature is lower than the equipment target temperature
    targets = [schedule_max(idf, w.Target_Temperature_Schedule_Name, default=0)
               for w in idf.idfobjects["WATERUSE:EQUIPMENT"] if w.Target_Temperature_Schedule_Name]
    hottest = max(targets, default=0)
    if setpoint < hottest:
        need = hottest + DHW["target_margin"]
        print(f"    [ok] tank setpoint {setpoint:g} -> {need:g} °C (lower than equipment hot water target setpoint "
              f"{hottest:g} °C)")
        setpoint = need

    ensure_type_limits(idf, "Temperature")
    backup = constant_schedule(idf, f"{tank.Name} Backup Setpoint",
                               setpoint - DHW["backup_offset"], "Temperature")
    setattr(tank, sp_field, backup)
    if stratified:
        tank.Heater_2_Setpoint_Temperature_Schedule_Name = backup
    if str(tank.Heater_Fuel_Type).strip().lower() != "electricity":
        tank.Off_Cycle_Parasitic_Fuel_Consumption_Rate = 0
        tank.On_Cycle_Parasitic_Fuel_Consumption_Rate = 0
    tank.Heater_Fuel_Type = "Electricity"
    tank.Off_Cycle_Parasitic_Fuel_Type = tank.On_Cycle_Parasitic_Fuel_Type = "Electricity"

    tank.Source_Side_Inlet_Node_Name, tank.Source_Side_Outlet_Node_Name = src_in, src_out
    tank.Source_Side_Effectiveness = 1
    tank.Source_Side_Flow_Control_Mode = "StorageTank"
    tank.Indirect_Alternate_Setpoint_Temperature_Schedule_Name = ""
    print(f"    [ok] {tank_type} '{tank.Name}' -> indirect heating (setpoint {setpoint:g} °C, "
          f"electric back up heating {setpoint - DHW['backup_offset']:g} °C)")
    return setpoint


def add_dhw_heat_pump(idf: IDF, tank_type: str, tank, hp_name: str, pump: tuple,
                      op_schedule: str, setpoint_schedule: str = None) -> tuple:
    """
    tank -> indirect heating, WWHP for water heating + creating water heating loop
    """
    import math
    src_in, src_out = f"{tank.Name} Source Inlet Node", f"{tank.Name} Source Outlet Node"
    setpoint = convert_tank_to_indirect(idf, tank_type, tank, src_in, src_out, setpoint_schedule)
    loop_t = setpoint + DHW["loop_offset"]
    limit = float(tank.Maximum_Temperature_Limit or 0)
    if limit < loop_t + 5:
        tank.Maximum_Temperature_Limit = loop_t + 5

    # calculate delta T for loop design and flow rate of source side based on the recovery condition
    volume = float(tank.Tank_Volume)
    hours = float(tank.Indirect_Water_Heating_Recovery_Time or 1.5)
    t0 = DHW["cold_start"]
    log_ratio = math.log((loop_t - t0) / (loop_t - setpoint))
    flow = volume / (hours * 3600) * log_ratio               # m3/s
    delta_t = (setpoint - t0) / log_ratio                    # WWHP capacity = recovery Q
    tank.Source_Side_Design_Flow_Rate = round(flow, 7)

    load = (f"{hp_name} Load Inlet Node", f"{hp_name} Load Outlet Node")
    source = (f"{hp_name} Source Inlet Node", f"{hp_name} Source Outlet Node")
    add_wwhp_heating(idf, hp_name, load, source)
    hp = "HeatPump:WaterToWater:EquationFit:Heating"
    out = build_loop(idf, "DHW HP Loop", "PlantLoop", pump,
                     supply=[(hp, hp_name, *load)],
                     demand=[(tank_type, tank.Name, src_in, src_out)],
                     operation="HeatingLoad", op_schedule=op_schedule,
                     max_temp=loop_t + 15, min_temp=10,
                     sizing=("Heating", loop_t, round(delta_t, 2)))
    scheduled_setpoint(idf, out, loop_t, "DHW HP Loop")
    print(f"    + water WWHP '{hp_name}' (water heating loop {loop_t:g} °C, designed delta T {delta_t:.1f} °C, "
          f"tank {volume * 1000:.0f} L recovers {hours:g} h)")
    return (hp, hp_name, *source)


# GHX
def _ierf(x: float) -> float:
    return x * math.erf(x) - (1 - math.exp(-x * x)) / math.sqrt(math.pi)


def _fls(d: float, t: float, H: float, D: float, alpha: float, n: int = 400) -> float:
    """fls response: average bore hole length, distance d, time t [s] (Cimmino & Bernier eq.)"""
    a = 1 / math.sqrt(4 * alpha * t)
    v0, v1 = math.log(a), math.log(max(a * 1.0001, 8.0 / d))   # until s = e^v, exp(-d²s²) ≈ 0
    if v1 <= v0:
        return 0.0
    step, total = (v1 - v0) / n, 0.0
    for k in range(n + 1):                                      # Simpson
        s = math.exp(v0 + k * step)
        y = (2 * _ierf(H * s) + 2 * _ierf(H * s + 2 * D * s)
             - _ierf(2 * H * s + 2 * D * s) - _ierf(2 * D * s))
        total += math.exp(-d * d * s * s) * y / (H * s) * (1 if k in (0, n) else 4 if k % 2 else 2)
    return 0.5 * total * step / 3


def compute_gfunction(btype: str, layout: tuple) -> list:
    """
    bore hole design g-function
    """
    nx, ny, spacing = layout
    g, b = SOIL[btype], BOREHOLE[btype]
    H, D, rb = b["length"], b["top"], b["dia"] / 2
    alpha = g["k"] / g["heat_cap"]
    ts = H * H / (9 * alpha)
    pts = [(i * spacing, j * spacing) for i in range(nx) for j in range(ny)]
    pairs = {}                                                  # number of bore hole by distance
    for (x1, y1) in pts:
        for (x2, y2) in pts:
            d = round(math.hypot(x1 - x2, y1 - y2), 6) or rb
            pairs[d] = pairs.get(d, 0) + 1
    out = []
    for k in range(81):                                         # ln(t/ts) = −17 … +3
        lntts = -17 + 0.25 * k
        t = math.exp(lntts) * ts
        val = sum(c * _fls(d, t, H, D, alpha) for d, c in pairs.items()) / len(pts)
        out.append((round(lntts, 4), round(val, 5)))
    return out


def add_ground_heat_exchanger(idf: IDF, btype: str, name: str, inlet: str, outlet: str,
                              n_boreholes: int, design_flow: float, ground: dict,
                              layout: tuple = None) -> None:
    """
    vertical ground heat exchanger
      layout = (number of X axis bore holes, number of Y axis bore holes, distance m) -> calculate and use as ResponseFactor
      layout = None → GFUNC[btype] (use pre-calculated g-function)
    """
    g, b = SOIL[btype], BOREHOLE[btype]
    gt_name, props, rf = f"{name} Ground Temps", f"{name} Props", f"{name} g-functions"
    add(idf, "Site:GroundTemperature:Undisturbed:KusudaAchenbach", gt_name,
        Soil_Thermal_Conductivity=g["k"], Soil_Density=g["rho"], Soil_Specific_Heat=g["cp"],
        Average_Soil_Surface_Temperature=ground["t_avg"],
        Average_Amplitude_of_Surface_Temperature=ground["amp"],
        Phase_Shift_of_Minimum_Surface_Temperature=ground["phase"])
    add(idf, "GroundHeatExchanger:Vertical:Properties", props,
        Depth_of_Top_of_Borehole=b["top"], Borehole_Length=b["length"],
        Borehole_Diameter=b["dia"], Grout_Thermal_Conductivity=b["grout_k"],
        Grout_Thermal_Heat_Capacity=b["grout_cp"], Pipe_Thermal_Conductivity=b["pipe_k"],
        Pipe_Thermal_Heat_Capacity=b["pipe_cp"], Pipe_Outer_Diameter=b["pipe_od"],
        Pipe_Thickness=b["pipe_t"], UTube_Distance=b["utube"])
    system = dict(
        Inlet_Node_Name=inlet, Outlet_Node_Name=outlet, Design_Flow_Rate=design_flow,
        Undisturbed_Ground_Temperature_Model_Type="Site:GroundTemperature:Undisturbed:KusudaAchenbach",
        Undisturbed_Ground_Temperature_Model_Name=gt_name,
        Ground_Thermal_Conductivity=g["k"], Ground_Thermal_Heat_Capacity=g["heat_cap"])
    rb_over_h = (b["dia"] / 2) / b["length"]
    if layout:
        nx, ny, _ = layout
        n_boreholes = nx * ny
        gfunc = compute_gfunction(btype, layout)
    else:
        gfunc = GFUNC[btype]
    add(idf, "GroundHeatExchanger:ResponseFactors", rf,
        values=[props, n_boreholes, round(rb_over_h, 8)] + [v for pair in gfunc for v in pair])
    add(idf, "GroundHeatExchanger:System", name, **system,
        GHEVerticalResponseFactors_Object_Name=rf)
    print(f"    + GroundHeatExchanger:System '{name}' ({n_boreholes}boreholes × {b['length']} m, "
          f"ground {ground['t_avg']:.1f} ± {ground['amp']:.1f} °C)")


def build_loop(idf: IDF, name: str, kind: str, pump: tuple, supply: list, demand: list,
               operation: str, op_schedule: str, max_temp, min_temp,
               max_flow="autosize", volume="autosize", load_scheme="Optimal", sizing=None,
               glycol=None) -> str:
    n = lambda s: f"{name} {s}"
    s_in, s_out = n("Supply Inlet Node"), n("Supply Outlet Node")
    d_in, d_out = n("Demand Inlet Node"), n("Demand Outlet Node")

    ptype, pfields = pump
    pump_comp = (ptype, n("Pump"), s_in, n("Pump Outlet Node"))
    add(idf, ptype, pump_comp[1], Inlet_Node_Name=s_in, Outlet_Node_Name=pump_comp[3], **pfields)

    def side(label, inlet_comp, comps, outlet_node):
        pipes = [("Pipe:Adiabatic", n(f"{label} Bypass Pipe"),
                  n(f"{label} Bypass Inlet Node"), n(f"{label} Bypass Outlet Node")),
                 ("Pipe:Adiabatic", n(f"{label} Outlet Pipe"),
                  n(f"{label} Mixer Outlet Node"), outlet_node)]
        if inlet_comp[0] == "Pipe:Adiabatic":
            pipes.append(inlet_comp)
        for _, pname, i, o in pipes:
            add(idf, "Pipe:Adiabatic", pname, Inlet_Node_Name=i, Outlet_Node_Name=o)

        def branch(bname, comp):
            add(idf, "Branch", bname, values=[""] + list(comp))
            return bname

        b_in = branch(n(f"{label} Inlet Branch"), inlet_comp)
        b_mid = [branch(n(f"{label} {c[1]} Branch"), c) for c in comps]
        b_byp = branch(n(f"{label} Bypass Branch"), pipes[0])
        b_out = branch(n(f"{label} Outlet Branch"), pipes[1])
        bl, sp, mx, cl = (n(f"{label} Branches"), n(f"{label} Splitter"),
                          n(f"{label} Mixer"), n(f"{label} Connectors"))
        add(idf, "BranchList", bl, values=[b_in, *b_mid, b_byp, b_out])
        add(idf, "Connector:Splitter", sp, values=[b_in, *b_mid, b_byp])
        add(idf, "Connector:Mixer", mx, values=[b_out, *b_mid, b_byp])
        add(idf, "ConnectorList", cl, values=["Connector:Splitter", sp, "Connector:Mixer", mx])
        return bl, cl

    s_bl, s_cl = side("Supply", pump_comp, supply, s_out)
    d_inlet_pipe = ("Pipe:Adiabatic", n("Demand Inlet Pipe"), d_in, n("Demand Inlet Pipe Outlet Node"))
    d_bl, d_cl = side("Demand", d_inlet_pipe, demand, d_out)


    plant = kind == "PlantLoop"
    eq_list, op_name, schemes = n("Equipment List"), n(f"{operation} Operation"), n("Operation Schemes")
    add(idf, "PlantEquipmentList" if plant else "CondenserEquipmentList", eq_list,
        values=[v for c in supply for v in c[:2]])
    if operation == "Uncontrolled":
        add(idf, "PlantEquipmentOperation:Uncontrolled", op_name, Equipment_List_Name=eq_list)
    else:
        add(idf, f"PlantEquipmentOperation:{operation}", op_name,
            values=[0, 1e9, eq_list])
    add(idf, "PlantEquipmentOperationSchemes" if plant else "CondenserEquipmentOperationSchemes",
        schemes, values=[f"PlantEquipmentOperation:{operation}", op_name, op_schedule])

    fluid = dict(Fluid_Type="Water")
    if glycol:
        fluid_name = f"{name} {glycol[0]} {int(glycol[1] * 100)}%"
        add(idf, "FluidProperties:GlycolConcentration", fluid_name,
            Glycol_Type=glycol[0], Glycol_Concentration=glycol[1])
        fluid = dict(Fluid_Type="UserDefinedFluidType", User_Defined_Fluid_Type=fluid_name)
    common = dict(**fluid, Maximum_Loop_Temperature=max_temp,
                  Minimum_Loop_Temperature=min_temp, Maximum_Loop_Flow_Rate=max_flow,
                  Minimum_Loop_Flow_Rate=0, Demand_Side_Inlet_Node_Name=d_in,
                  Demand_Side_Outlet_Node_Name=d_out, Load_Distribution_Scheme=load_scheme)
    if plant:
        add(idf, "PlantLoop", name, **common,
            Plant_Equipment_Operation_Scheme_Name=schemes,
            Loop_Temperature_Setpoint_Node_Name=s_out, Plant_Loop_Volume=volume,
            Plant_Side_Inlet_Node_Name=s_in, Plant_Side_Outlet_Node_Name=s_out,
            Plant_Side_Branch_List_Name=s_bl, Plant_Side_Connector_List_Name=s_cl,
            Demand_Side_Branch_List_Name=d_bl, Demand_Side_Connector_List_Name=d_cl)
    else:
        add(idf, "CondenserLoop", name, **common,
            Condenser_Equipment_Operation_Scheme_Name=schemes,
            Condenser_Loop_Temperature_Setpoint_Node_Name=s_out, Condenser_Loop_Volume=volume,
            Condenser_Side_Inlet_Node_Name=s_in, Condenser_Side_Outlet_Node_Name=s_out,
            Condenser_Side_Branch_List_Name=s_bl, Condenser_Side_Connector_List_Name=s_cl,
            Condenser_Demand_Side_Branch_List_Name=d_bl,
            Condenser_Demand_Side_Connector_List_Name=d_cl)
    if sizing:
        add(idf, "Sizing:Plant", None, Plant_or_Condenser_Loop_Name=name, Loop_Type=sizing[0],
            Design_Loop_Exit_Temperature=sizing[1], Loop_Design_Temperature_Difference=sizing[2])
    print(f"    + {kind} '{name}' (supply: {', '.join(c[1] for c in supply)} / "
          f"demand: {', '.join(c[1] for c in demand)})")
    return s_out


def scheduled_setpoint(idf: IDF, node: str, temp: float, name: str) -> None:
    ensure_type_limits(idf, "Temperature")
    sch = constant_schedule(idf, f"{name} Temp Schedule", temp, "Temperature")
    add(idf, "SetpointManager:Scheduled", f"{name} Setpoint Manager",
        Control_Variable="Temperature", Schedule_Name=sch, Setpoint_Node_or_NodeList_Name=node)


# residential

def _remove_from_zone_equipment(idf: IDF, obj_type: str, name: str) -> None:
    """ZoneHVAC:EquipmentList -> remove and reorder"""
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
        print(f"    ZoneHVAC:EquipmentList: '{eql.Name}', '{name}' removed")


def _remove_nodes_from_nodelists(idf: IDF, nodes) -> None:
    """clean the node list"""
    nodes = {str(n).strip().lower() for n in nodes if str(n).strip()}
    lists = {"NODELIST", "OUTDOORAIR:NODELIST", "OUTDOORAIR:NODE"}
    for key, objs in idf.idfobjects.items():               # keep valid nodes
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
            print(f"    {kind.title()}: {len(vals) - len(keep)} nodes are removed")
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
                print(f"   empty NodeList '{name}' is deleted")


def _add_res_curves(idf: IDF) -> None:
    """
    WaterToAir HP performance curve modification
    """
    lim4 = [-100, 100, -100, 100, 0, 100, 0, 100]                  # w, x, y, z
    for name, c in [("GSHP_TotCoolCap", [-9.04579502522263, 10.7553480046802, -1.69937859691413, 0.737989300704241, 0]),
                    ("GSHP_CoolPow",    [-3.50303494439906, -1.06706985019601, 4.34837210589294, 1.02529280547194, 0]),
                    ("GSHP_HeatCap",    [-1.82449220450272, -3.31281616694594, 5.59306489123436, 0.858772212623984, 0]),
                    ("GSHP_HeatPow",    [-2.4442872924394, 0.934304727021879, 1.76364353708994, 0.775628762040029, 0])]:
        add(idf, "Curve:QuadLinear", name, values=c + lim4)
    add(idf, "Curve:QuintLinear", "GSHP_CoolSensCap",
        values=[-5.17921912653132, 17.0277143871191, -11.2617991739786, -0.929300603852594,
                0.72746963129094, 0, -100, 100, -100, 100, -100, 100, 0, 100, 0, 100])
    add(idf, "Curve:Quadratic", "GSHP_PLF", values=[0.75, 0.25, 0, 0, 1])


def res_hvac_to_gshp(idf: IDF) -> list:
    """
    AirToAir HP to WaterToAir HP
    """
    hp = next(iter(idf.idfobjects["AIRLOOPHVAC:UNITARYHEATPUMP:AIRTOAIR"]), None)
    if hp is None:
        print("    [warn] No AirLoopHVAC:UnitaryHeatPump:AirToAir => skip")
        return []
    old_clg = get_object(idf, hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name)
    old_htg = get_object(idf, hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name)
    keep = {f: getattr(hp, f) for f in (
        "Name", "Availability_Schedule_Name", "Air_Inlet_Node_Name", "Air_Outlet_Node_Name",
        "Controlling_Zone_or_Thermostat_Location", "Supply_Air_Fan_Object_Type",
        "Supply_Air_Fan_Name", "Supplemental_Heating_Coil_Object_Type",
        "Supplemental_Heating_Coil_Name", "Maximum_Supply_Air_Temperature_from_Supplemental_Heater",
        "Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation",
        "Fan_Placement", "Supply_Air_Fan_Operating_Mode_Schedule_Name")}
    clg_air = (old_clg.Air_Inlet_Node_Name, old_clg.Air_Outlet_Node_Name)
    htg_air = (old_htg.Air_Inlet_Node_Name, old_htg.Air_Outlet_Node_Name)
    old = [(hp.Cooling_Coil_Object_Type, hp.Cooling_Coil_Name),
           (hp.Heating_Coil_Object_Type, hp.Heating_Coil_Name)]

    idf.removeidfobject(hp)
    print(f"    - AirLoopHVAC:UnitaryHeatPump:AirToAir '{keep['Name']}'")
    for t, nm in old:
        remove_object(idf, t, nm)

    _add_res_curves(idf)
    clg_w = ("GSHP CoolC Water Inlet Node", "GSHP CoolC Water Outlet Node")
    htg_w = ("GSHP HeatC Water Inlet Node", "GSHP HeatC Water Outlet Node")
    add(idf, "Coil:Cooling:WaterToAirHeatPump:EquationFit", RES["cooling_coil"],
        Water_Inlet_Node_Name=clg_w[0], Water_Outlet_Node_Name=clg_w[1],
        Air_Inlet_Node_Name=clg_air[0], Air_Outlet_Node_Name=clg_air[1],
        Rated_Air_Flow_Rate=RES["coil_air_flow"], Rated_Water_Flow_Rate=RES["coil_water_flow"],
        Gross_Rated_Total_Cooling_Capacity=RES["clg_capacity"],
        Gross_Rated_Sensible_Cooling_Capacity=RES["clg_sensible_capacity"],
        Gross_Rated_Cooling_COP=RES["clg_cop"],
        Rated_Entering_Water_Temperature=RES["clg_rated_ewt"],
        Rated_Entering_Air_DryBulb_Temperature=27, Rated_Entering_Air_WetBulb_Temperature=19,
        Total_Cooling_Capacity_Curve_Name="GSHP_TotCoolCap",
        Sensible_Cooling_Capacity_Curve_Name="GSHP_CoolSensCap",
        Cooling_Power_Consumption_Curve_Name="GSHP_CoolPow",
        Part_Load_Fraction_Correlation_Curve_Name="GSHP_PLF",
        Nominal_Time_for_Condensate_Removal_to_Begin=0,
        Ratio_of_Initial_Moisture_Evaporation_Rate_and_Steady_State_Latent_Capacity=0,
        Maximum_Cycling_Rate=2.5, Latent_Capacity_Time_Constant=60, Fan_Delay_Time=60)
    add(idf, "Coil:Heating:WaterToAirHeatPump:EquationFit", RES["heating_coil"],
        Water_Inlet_Node_Name=htg_w[0], Water_Outlet_Node_Name=htg_w[1],
        Air_Inlet_Node_Name=htg_air[0], Air_Outlet_Node_Name=htg_air[1],
        Rated_Air_Flow_Rate=RES["coil_air_flow"], Rated_Water_Flow_Rate=RES["coil_water_flow"],
        Gross_Rated_Heating_Capacity=RES["htg_capacity"], Gross_Rated_Heating_COP=RES["htg_cop"],
        Rated_Entering_Water_Temperature=RES["htg_rated_ewt"], Rated_Entering_Air_DryBulb_Temperature=20,
        Ratio_of_Rated_Heating_Capacity_to_Rated_Cooling_Capacity=1,
        Heating_Capacity_Curve_Name="GSHP_HeatCap",
        Heating_Power_Consumption_Curve_Name="GSHP_HeatPow",
        Part_Load_Fraction_Correlation_Curve_Name="GSHP_PLF")

    oa_sensor = "GSHP Outdoor Air Sensor Node"
    add(idf, "OutdoorAir:Node", oa_sensor)
    add(idf, "AirLoopHVAC:UnitaryHeatPump:WaterToAir", keep.pop("Name"), **keep,
        Supply_Air_Flow_Rate="autosize",
        Heating_Coil_Object_Type="Coil:Heating:WaterToAirHeatPump:EquationFit",
        Heating_Coil_Name=RES["heating_coil"], Heating_Convergence=0.001,
        Cooling_Coil_Object_Type="Coil:Cooling:WaterToAirHeatPump:EquationFit",
        Cooling_Coil_Name=RES["cooling_coil"], Cooling_Convergence=0.001,
        Outdoor_DryBulb_Temperature_Sensor_Node_Name=oa_sensor)
    unit = idf.idfobjects["AIRLOOPHVAC:UNITARYHEATPUMP:WATERTOAIR"][-1].Name
    retarget(idf, "AirLoopHVAC:UnitaryHeatPump:AirToAir", unit,
             "AirLoopHVAC:UnitaryHeatPump:WaterToAir", unit)
    print(f"    + AirLoopHVAC:UnitaryHeatPump:WaterToAir '{unit}' "
          f"(cooling COP {RES['clg_cop']:.2f}, heating COP {RES['htg_cop']:.2f})")

    # add AFN
    new_coils = {old[0][1].lower(): ("Coil:Cooling:WaterToAirHeatPump:EquationFit", RES["cooling_coil"]),
                 old[1][1].lower(): ("Coil:Heating:WaterToAirHeatPump:EquationFit", RES["heating_coil"])}
    for afn in idf.idfobjects["AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:COIL"]:
        new = new_coils.get(afn.Coil_Name.strip().lower())
        if new:
            afn.Coil_Object_Type = new[0]
    for old_name, (_, new_name) in new_coils.items():
        n = rename_references(idf, old_name, new_name)
        print(f"    [ok] '{old_name}' into '{new_name}' (AFN component, linkage included)")

    return [("Coil:Cooling:WaterToAirHeatPump:EquationFit", RES["cooling_coil"], *clg_w),
            ("Coil:Heating:WaterToAirHeatPump:EquationFit", RES["heating_coil"], *htg_w)]


def res_dhw_to_wwhp(idf: IDF):
    """
    HPWH -> Stratified tank changed to indirect + water heating WWHP.
    """
    hpwh = next(iter(idf.idfobjects[HPWH_TYPE.upper()]), None)
    if hpwh is None:
        print("    [warn] no HPWH: skip")
        return None
    tank = get_object(idf, hpwh.Tank_Object_Type, hpwh.Tank_Name)
    if tank is None or hpwh.Tank_Object_Type.lower() != "waterheater:stratified":
        print("    [warn] HPWH type is not WaterHeater:Stratified : skip")
        return None
    name = hpwh.Name
    parts = [(hpwh.DX_Coil_Object_Type, hpwh.DX_Coil_Name), (hpwh.Fan_Object_Type, hpwh.Fan_Name)]
    air_nodes = [getattr(hpwh, f, "") for f in (
        "Air_Inlet_Node_Name", "Air_Outlet_Node_Name", "Outdoor_Air_Node_Name",
        "Exhaust_Air_Node_Name", "Inlet_Air_Mixer_Node_Name", "Outlet_Air_Splitter_Node_Name")]
    for t, nm in parts:
        comp = get_object(idf, t, nm)
        if comp is not None:
            air_nodes += [str(v) for k, v in zip(comp.objls, comp.obj)
                          if k.endswith("Node_Name") and "Air" in k]
    # compressor setpoint
    tank_setpoint = hpwh.Compressor_Setpoint_Temperature_Schedule_Name

    # delete HPWH components
    _remove_from_zone_equipment(idf, HPWH_TYPE, name)
    idf.removeidfobject(hpwh)
    print(f"    - {HPWH_TYPE} '{name}'")
    for t, nm in parts:
        remove_object(idf, t, nm)
    _remove_nodes_from_nodelists(idf, air_nodes)

    # water tank spec.
    for field, value in RES_TANK.items():
        setattr(tank, field, value)
    if get_object(idf, "Zone", RES_TANK_ZONE):
        tank.Ambient_Temperature_Indicator, tank.Ambient_Temperature_Zone_Name = "Zone", RES_TANK_ZONE
    n = retarget(idf, HPWH_TYPE, name, "WaterHeater:Stratified", tank.Name)
    print(f"    [ok] plant 참조 {n}곳 → WaterHeater:Stratified '{tank.Name}'")

    # water pump + water heating loop 
    pump = ("Pump:VariableSpeed", dict(
        Design_Maximum_Flow_Rate="autosize", Design_Pump_Head=RES_DHW_PUMP_HEAD,
        Design_Power_Consumption="autosize", Motor_Efficiency=0.87,
        Fraction_of_Motor_Inefficiencies_to_Fluid_Stream=0,
        Coefficient_1_of_the_Part_Load_Performance_Curve=0,
        Coefficient_2_of_the_Part_Load_Performance_Curve=1,
        Coefficient_3_of_the_Part_Load_Performance_Curve=0,
        Coefficient_4_of_the_Part_Load_Performance_Curve=0,
        Design_Minimum_Flow_Rate=0, Pump_Control_Type="Intermittent"))
    return add_dhw_heat_pump(idf, "WaterHeater:Stratified", tank, "GSHP DHW HP_unit1",
                             pump, RES["always_on"], setpoint_schedule=tank_setpoint)


def ghe_layout_for(cz: str) -> tuple:
    """bore hole layout by location"""
    digit = re.match(r"\d+", str(cz))
    return RES["ghe_layout_by_cz"].get(digit.group(0) if digit else "", RES["ghe_layout"])


def res_ground_loop(idf: IDF, demand: list, ground: dict) -> None:
    """GHX condenser loop (heating and cooling coil + water heating WWHP source side)"""
    if not idf.idfobjects["SITE:GROUNDTEMPERATURE:BUILDINGSURFACE"]:   # original value, only in unavailable case
        add(idf, "Site:GroundTemperature:BuildingSurface", None,
            values=[19.527, 19.502, 19.536, 19.598, 20.002, 21.640,
                    22.225, 22.375, 21.449, 20.121, 19.691, 19.549])
    set_deep_ground_temperature(idf, ground)

    ghe = ("GroundHeatExchanger:System", "GSHP Vertical GHE", "GSHP GHE Inlet Node", "GSHP GHE Outlet Node")
    layout = ghe_layout_for(ground.get("cz", ""))
    nx, ny, _ = layout
    add_ground_heat_exchanger(idf, "residential", ghe[1], ghe[2], ghe[3], nx * ny,
                              round(nx * ny * RES["ghe_flow_per_borehole"], 6), ground,
                              layout=layout)
    out = build_loop(
        idf, "GSHP Condenser Loop", "CondenserLoop",
        pump=("Pump:ConstantSpeed", dict(Design_Flow_Rate="autosize", Motor_Efficiency=0.87,
                                         Fraction_of_Motor_Inefficiencies_to_Fluid_Stream=0,
                                         Pump_Control_Type="Continuous", **RES["pump"])),
        supply=[ghe], demand=demand,
        operation="Uncontrolled", op_schedule=RES["always_on"],
        max_temp=80, min_temp=RES["loop_min_temp"], max_flow="autosize",
        volume="autocalculate", load_scheme="SequentialLoad", sizing=RES["loop_sizing"],
        glycol=RES["loop_glycol"])
    add(idf, "SetpointManager:FollowGroundTemperature", "GSHP Condenser Loop Setpoint Manager",
        Control_Variable="Temperature",
        Reference_Ground_Temperature_Object_Type="Site:GroundTemperature:Deep",
        Offset_Temperature_Difference=0, Maximum_Setpoint_Temperature=80,
        Minimum_Setpoint_Temperature=RES["loop_min_temp"], Setpoint_Node_or_NodeList_Name=out)


def apply_residential(idf: IDF, ground: dict) -> None:
    print("  heating and cooling: ASHP -> GSHP")
    demand = res_hvac_to_gshp(idf)
    if not demand:
        return
    print("  water heating: HPWH -> indirect heating tank + water heating WWHP")
    dhw_src = res_dhw_to_wwhp(idf)
    if dhw_src:
        demand.append(dhw_src)
    print("  GHX loop")
    res_ground_loop(idf, demand, ground)


# office

def office_ahu_to_water_coils(idf: IDF, ahu: str) -> dict:
    p = f"PACU_VAV_{ahu}"
    branch = get_object(idf, "Branch", f"{p} Air Loop Main Branch")
    if branch is None:
        print(f"    [warn] no '{p} Air Loop Main Branch': skip")
        return {}
    oa_out = f"{p}_OA-{p}_CoolCNode"
    mid    = f"{p}_CoolC-{p}_HeatCNode"
    fan_in = f"{p}_HeatC-{p} FanNode"
    fan_out = f"{p} Supply Equipment Outlet Node"

    # delete DX system
    tw = get_object(idf, "Coil:Cooling:DX:TwoSpeed", f"{p} Cooling Coil")
    curves = {str(v).strip() for v in (tw.obj[2:] if tw else []) if str(v).startswith("LgDX")}
    remove_object(idf, "CoilSystem:Cooling:DX", f"{p} Cooling Coil")
    remove_object(idf, "Coil:Cooling:DX:TwoSpeed", f"{p} Cooling Coil")
    if not remove_object(idf, "Coil:Heating:Fuel", f"{p} Heating Coil"):
        remove_object(idf, "Coil:Heating:Electric", f"{p} Heating Coil")
    for node in (f"{p}_CoolC Cond OA node", f"{p}_CoolCOA Ref node"):
        remove_object(idf, "OutdoorAir:Node", node)

    # CW/HW coil
    cw, hw = f"{p} CW Cooling Coil", f"{p} HW Heating Coil"
    cw_w = (f"{p} CoolC Water Inlet Node", f"{p} CoolC Water Outlet Node")
    hw_w = (f"{p} HeatC Water Inlet Node", f"{p} HeatC Water Outlet Node")
    add(idf, "Coil:Cooling:Water", cw, Availability_Schedule_Name=OFF["always_on"],
        Design_Water_Flow_Rate="autosize", Design_Air_Flow_Rate="autosize",
        Design_Inlet_Water_Temperature="autosize", Design_Inlet_Air_Temperature="autosize",
        Design_Outlet_Air_Temperature="autosize", Design_Inlet_Air_Humidity_Ratio="autosize",
        Design_Outlet_Air_Humidity_Ratio="autosize",
        Water_Inlet_Node_Name=cw_w[0], Water_Outlet_Node_Name=cw_w[1],
        Air_Inlet_Node_Name=oa_out, Air_Outlet_Node_Name=mid,
        Type_of_Analysis="SimpleAnalysis", Heat_Exchanger_Configuration="CrossFlow")
    add(idf, "Coil:Heating:Water", hw, Availability_Schedule_Name=OFF["always_on"],
        UFactor_Times_Area_Value="autosize", Maximum_Water_Flow_Rate="autosize",
        Water_Inlet_Node_Name=hw_w[0], Water_Outlet_Node_Name=hw_w[1],
        Air_Inlet_Node_Name=mid, Air_Outlet_Node_Name=fan_in,
        Performance_Input_Method="UFactorTimesAreaAndDesignWaterFlowRate",
        Rated_Capacity="autosize", Rated_Inlet_Water_Temperature=45.0,
        Rated_Inlet_Air_Temperature=16.6, Rated_Outlet_Water_Temperature=35.0,
        Rated_Outlet_Air_Temperature=32.2, Rated_Ratio_for_Air_and_Water_Convection=0.5)

    # water flow mass controller
    ctrls = []
    for cname, action, sensor, actuator in [(f"{p} CW CoolC Controller", "Reverse", mid, cw_w[0]),
                                            (f"{p} HW HeatC Controller", "Normal", fan_in, hw_w[0])]:
        add(idf, "Controller:WaterCoil", cname, Control_Variable="Temperature", Action=action,
            Actuator_Variable="Flow", Sensor_Node_Name=sensor, Actuator_Node_Name=actuator,
            Controller_Convergence_Tolerance="autosize", Maximum_Actuated_Flow="autosize",
            Minimum_Actuated_Flow=0.0)
        ctrls += ["Controller:WaterCoil", cname]
    cl = f"{p}_Water_Coil_Controllers"
    add(idf, "AirLoopHVAC:ControllerList", cl, values=ctrls)
    loop = get_object(idf, "AirLoopHVAC", p)
    if loop is not None:
        loop.Controller_List_Name = cl

    # update branch
    branch.obj[3:] = branch.obj[3:7] + [
        "Coil:Cooling:Water", cw, oa_out, mid,
        "Coil:Heating:Water", hw, mid, fan_in,
        "Fan:VariableVolume", f"{p} Fan", fan_in, fan_out,
    ]
    print(f"  AHU'{p}' -> CW / HW coil + Controller:WaterCoil")
    return {"cw": ("Coil:Cooling:Water", cw, *cw_w), "hw": ("Coil:Heating:Water", hw, *hw_w),
            "curves": curves}


def _remove_unused_curves(idf: IDF, names) -> None:
    for name in names:
        used = any(str(v).strip().lower() == name.lower()
                   for objs in idf.idfobjects.values() for o in objs for v in o.obj[2:])
        if not used:
            for t in ("Curve:Biquadratic", "Curve:Quadratic"):
                remove_object(idf, t, name)


def office_add_plants(idf: IDF, coils: list, ground: dict) -> None:
    add_wwhp_curves(idf)

    clg_hp, htg_hp = "GSHP Cooling HP", "GSHP Heating HP"
    clg_load = ("HeatPump:WaterToWater:EquationFit:Cooling", clg_hp,
                "GSHP CoolHP Load Inlet Node", "GSHP CoolHP Load Outlet Node")
    htg_load = ("HeatPump:WaterToWater:EquationFit:Heating", htg_hp,
                "GSHP HeatHP Load Inlet Node", "GSHP HeatHP Load Outlet Node")
    clg_src = (clg_load[0], clg_hp, "GSHP CoolHP Source Inlet Node", "GSHP CoolHP Source Outlet Node")
    htg_src = (htg_load[0], htg_hp, "GSHP HeatHP Source Inlet Node", "GSHP HeatHP Source Outlet Node")
    for (t, nm, li, lo), (_, _, si, so), comp, kind in [
            (clg_load, clg_src, htg_hp, "Cooling"), (htg_load, htg_src, clg_hp, "Heating")]:
        add(idf, t, nm, Source_Side_Inlet_Node_Name=si, Source_Side_Outlet_Node_Name=so,
            Load_Side_Inlet_Node_Name=li, Load_Side_Outlet_Node_Name=lo,
            Reference_Load_Side_Flow_Rate="autosize", Reference_Source_Side_Flow_Rate="autosize",
            **{f"Companion_{'Heating' if kind == 'Cooling' else 'Cooling'}_Heat_Pump_Name": comp,
               f"Reference_{kind}_Capacity": "autosize",
               f"Reference_{kind}_Power_Consumption": "autosize",
               f"{kind}_Capacity_Curve_Name": f"GSHP_{'Cool' if kind == 'Cooling' else 'Heat'}Cap_QuadLinear",
               f"{kind}_Compressor_Power_Curve_Name": f"GSHP_{'Cool' if kind == 'Cooling' else 'Heat'}Pwr_QuadLinear"})
    print(f"    + HeatPump:WaterToWater:EquationFit '{clg_hp}' / '{htg_hp}'")

    vs_pump = ("Pump:VariableSpeed", dict(
        Design_Maximum_Flow_Rate="autosize", Design_Pump_Head=OFF["pump_head"],
        Design_Power_Consumption="autosize", Motor_Efficiency=0.9,
        Fraction_of_Motor_Inefficiencies_to_Fluid_Stream=0.0,
        Coefficient_1_of_the_Part_Load_Performance_Curve=0,
        Coefficient_2_of_the_Part_Load_Performance_Curve=1,
        Coefficient_3_of_the_Part_Load_Performance_Curve=0,
        Coefficient_4_of_the_Part_Load_Performance_Curve=0,
        Design_Minimum_Flow_Rate=0.0, Pump_Control_Type="Intermittent"))
    on = OFF["always_on"]

    out = build_loop(idf, "CHW Loop", "PlantLoop", vs_pump, [clg_load], [c["cw"] for c in coils],
                     "CoolingLoad", on, 25.0, 2.0,
                     sizing=("Cooling", OFF["chw_supply_temp"], OFF["chw_delta_t"]))
    scheduled_setpoint(idf, out, OFF["chw_supply_temp"], "CHW Loop")

    out = build_loop(idf, "HW Loop", "PlantLoop", vs_pump, [htg_load], [c["hw"] for c in coils],
                     "HeatingLoad", on, 60.0, 10.0,
                     sizing=("Heating", OFF["hw_supply_temp"], OFF["hw_delta_t"]))
    scheduled_setpoint(idf, out, OFF["hw_supply_temp"], "HW Loop")

    # water heating: gas WaterHeater:Mixed -> indirect heating tank + water heating WWHP
    ghe_demand = [clg_src, htg_src]
    print("  water heating: gas heating -> indirect heating tank + water heating WWHP")
    tanks = list(idf.idfobjects["WATERHEATER:MIXED"])
    if tanks:
        if len(tanks) > 1:
            print(f"    [warn] WaterHeater:Mixed {len(tanks)}: only change the first '{tanks[0].Name}'")
        ghe_demand.append(add_dhw_heat_pump(idf, "WaterHeater:Mixed", tanks[0],
                                            "GSHP DHW HP", vs_pump, on))
    else:
        print("    [warn] no WaterHeater:Mixed: skip")

    ghe = ("GroundHeatExchanger:System", "Vertical GHE System", "GHE HX Inlet Node", "GHE HX Outlet Node")
    add_ground_heat_exchanger(idf, "office", ghe[1], ghe[2], ghe[3],
                              OFF["ghe_nx"] * OFF["ghe_ny"], OFF["ghe_design_flow"], ground)
    out = build_loop(idf, "GHE Loop", "PlantLoop", vs_pump, [ghe], ghe_demand,
                     "Uncontrolled", on, 40.0, -5.0,
                     sizing=("Condenser", OFF["ghe_exit_temp"], OFF["ghe_delta_t"]))
    scheduled_setpoint(idf, out, OFF["ghe_setpoint"], "GHE Loop")


def apply_office(idf: IDF, ground: dict) -> None:
    coils = [c for c in (office_ahu_to_water_coils(idf, a) for a in AHU_LIST) if c]
    if not coils:
        return
    _remove_unused_curves(idf, set().union(*(c["curves"] for c in coils)))
    print("  ── CHW / HW / GHE loop")
    office_add_plants(idf, coils, ground)



def detect_building_type(fname: str):
    low = fname.lower()
    if "office" in low:
        return "office"
    if low.startswith("us+") or "+sf+" in low or "+mf+" in low or "residential" in low:
        return "residential"
    return None


def _city_from_site(idf: IDF) -> str:
    name = idf.idfobjects["SITE:LOCATION"][0].Name
    name = re.split(r"[-_,]|\b(?:Intl|Int'l|AP|Ap|Arpt|Airport|TMY\d*|WMO)\b", name)[0]
    words = [w for w in re.findall(r"[A-Za-z]+", name) if not (w.isupper() and len(w) <= 3)]
    return "".join(w[0].upper() + w[1:] for w in words) or "Unknown"


def name_parts(fname: str, idf: IDF, btype: str):
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


# run

def run_measure4(input_dirs=INPUT_DIRS, output_dir=OUTPUT_DIR, idd_path=IDD_PATH):
    if IDF.getiddname() is None:
        IDF.setiddname(idd_path)
    os.makedirs(output_dir, exist_ok=True)

    paths = sorted({p for d in input_dirs for p in glob.glob(os.path.join(d, "*.idf"))})
    if not paths:
        print(f"IDF file does not exist: {input_dirs}")
        return []

    saved, used_names = [], set()
    for path in paths:
        fname = os.path.basename(path)
        btype = detect_building_type(fname)
        if btype is None:
            print(f"\n[skip] unknown building type: {fname}")
            continue

        print(f"\n[{btype}] {fname}")
        idf = load_clean_idf(path)
        parts = name_parts(fname, idf, btype)
        if parts is None:
            print(f"  [skip] different file name format: {fname}")
            continue
        if parts[1] == "CZunknown":
            print(f"  [warn] unknown climate zone: update CLIMATE_ZONES, adding '{parts[2]}'")

        ground = {**ground_profile(parts[2], idf), "cz": parts[1]}
        print(f"  ground temperature: {ground['t_avg']:.1f} °C on average, {ground['amp']:.1f} °C difference, "
              f"min. {ground['phase']:.0f} (from {ground['source']})")
        if btype == "residential":
            apply_residential(idf, ground)
        else:
            apply_office(idf, ground)

        n_inv = replace_pvwatts_inverter(idf)
        if n_inv:
            print(f"  {n_inv} PV inverters are changed into Inverter:Simple")

        stem = f"{OUTPUT_PREFIX}_" + "_".join(parts)
        out_name, k = f"{stem}.idf", 2
        while out_name in used_names:
            out_name, k = f"{stem}_{k}.idf", k + 1
        if k > 2:
            print(f"  [warn] duplicated file name -> save as '{out_name}'")
        used_names.add(out_name)

        out_path = os.path.join(output_dir, out_name)
        idf.saveas(out_path)
        saved.append(out_path)
        print(f"  [saved] {out_name}")

    print(f"\nDone: {len(saved)}/{len(paths)}files saved in {output_dir}")
    return saved


if __name__ == "__main__":
    run_measure4()