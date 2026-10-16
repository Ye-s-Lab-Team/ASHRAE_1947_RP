"""
Measure 3: Power outage scenario (Residential/Office)
1. Residential 
    1) equipment, lighting Schedule:Year -> all-zero week schedule
    2) HVAC·DHW availability -> availability schedule

2. Office
    1) HVAC operation/lighting/equipment Schedule:Compact -> 0 during the power outage period
    2) Always_On schedule for HVAC equpment -> power outage availability schedule
    3) DHW plant pump -> stop during the power outage

3. exception
    1) AvailabilityManager:NightCycle  : turn on the fan if the temperature has increased over threshold 
                                            even though operation schedule is 0
    2) ElectricLoadCenter:Transformer  : loss is always occurred
    3) Pump                            : operate whenever the flow has detected
    4) PV inverter                     : Inverter:PVWatts -> Inverter:Simple
"""

import io
import os
import re
import glob
from datetime import date, timedelta
from eppy.modeleditor import IDF


script_dir = os.path.dirname(os.path.abspath(__file__))
model_root = os.path.join(script_dir, "..", "..", "Original_model")

IDD_PATH = r"C:\EnergyPlusV25-1-0\Energy+.idd"

INPUT_DIRS = [
    os.path.join(model_root, "residential", "system_electricity"),  # residential
    os.path.join(model_root, "..", "Measure1", "NewModel1"),            # office
]
OUTPUT_DIR = os.path.join(script_dir, "..", "NewModel3")
OUTPUT_PREFIX = "NewModel3"
OUTPUT_PREFIX = "NewModel3"

# power outage periods
OUTAGE_PERIODS = [
    ("7/16", "7/18"),    # summer
    ("12/16", "12/18"),  # winter
]

# power outage schedule name
AVAIL_SCH       = "PowerOutage_Avail"  # On/Off: normal 1, power outage 0
OUTAGE_DAY_SCH  = "PowerOutage_Day"    # 0 for all day
OUTAGE_WEEK_SCH = "PowerOutage_Week"   # all weekdays -> PowerOutage_Day

# residential buidling
RES_YEAR_SCHEDULES = [          # equipment, lighting
    "InteriorLighting",
    "InteriorLightingHE",
    "Refrigerator",
    "MiscPlugLoad",
    "CookingRange",
    "ClothesWasher_equip_sch",
    "Dishwasher_equip_sch",
    "ClothesDryer",
]

RES_HVAC_TARGETS = [            # (object type, name, field)
    ("AvailabilityManager:Scheduled",                  "System availability",              "Schedule_Name"),
    ("AirTerminal:SingleDuct:ConstantVolume:NoReheat", "ZoneDirectAir_unit1",              "Availability_Schedule_Name"),
    ("Coil:Cooling:DX:SingleSpeed",                    "DX Cooling Coil_unit1",            "Availability_Schedule_Name"),
    ("Fan:OnOff",                                      "Supply Fan_unit1",                 "Availability_Schedule_Name"),
    ("Fan:OnOff",                                      "Heat Pump Water Heater Fan_unit1", "Availability_Schedule_Name"),
    ("Fan:ZoneExhaust",                                "Zone Exhaust Fan_unit1",           "Availability_Schedule_Name"),
    ("AirLoopHVAC:UnitaryHeatCool",                    "ACandF_unit1",                     "Availability_Schedule_Name"),
    ("Coil:Heating:Electric",                          "Main electric heating coil_unit1", "Availability_Schedule_Name"),
    ("WaterHeater:HeatPump:WrappedCondenser",          "Water Heater_unit1",               "Availability_Schedule_Name"),
    ("PlantEquipmentOperationSchemes",                 "DHW Loop Operation_unit1",         "Control_Scheme_1_Schedule_Name"),
]

# office building
OFFICE_COMPACT_SCHEDULES = [    # Schedule:Compact
    # HVAC operation
    "HVACOperationSchd",
    "MinOA_MotorizedDamper_Sched",
    # lighting, equipment
    "ltg_sch_office",
    "BLDG_EQUIP_SCH",
    "BLDG_ELEVATORS",
    "ELEV_LIGHT_FAN_SCH_ADD_DF",
    "Exterior_lighting_schedule_a",
    "Exterior_lighting_schedule_b_2016",
    "Exterior_lighting_schedule_c_2016",
]

OFFICE_REDIRECT_FROM  = "Always_On"
OFFICE_REDIRECT_TYPES = [       # if Availability_Schedule_Name is Always_On, change the schedule
    "AirTerminal:SingleDuct:VAV:Reheat",
    "Coil:Cooling:DX:TwoSpeed",
    "Coil:Heating:Electric",
    "CoilSystem:Cooling:DX",
]


# residential foundation types
FOUNDATIONS = {
    "slab":         "Slab",
    "crawlspace":   "Crawlspace",
    "unheatedbsmt": "UnheatedBsmt",
    "heatedbsmt":   "HeatedBsmt",
}

# climate locations
CLIMATE_ZONES = {"Miami": "1A", "Tampa": "2A", "Tucson": "2B",
    "Atlanta": "3A", "ElPaso": "3B", "SanDiego": "3C",
    "NewYork": "4A", "Albuquerque": "4B", "Seattle": "4C",
    "Buffalo": "5A", "Denver": "5B", "PortAngeles": "5C",
    "Rochester": "6A", "GreatFalls": "6B", "InternationalFalls": "7",
    "Duluth": "7", "Fairbanks": "8"}


# date, power outage period calculation

_YEAR = 2023                      # temporal year for date calculation
_JAN1, _DEC31 = date(_YEAR, 1, 1), date(_YEAR, 12, 31)
_OUTAGE = object()                # power outage marking


def _parse_md(text) -> date:
    """'7/16', 'Through: 7/16' text, date"""
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", str(text))
    if not m:
        raise ValueError(f"cannot read the date: {text!r}")
    return date(_YEAR, int(m.group(1)), int(m.group(2)))


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _parse_outages(periods):
    ranges = sorted((_parse_md(s), _parse_md(e)) for s, e in periods)
    for (s, e) in ranges:
        if s > e:
            raise ValueError(f"power outage starting date is later than end date: {_md(s)} – {_md(e)}")
    for (_, e1), (s2, _) in zip(ranges, ranges[1:]):
        if s2 <= e1:
            raise ValueError(f"power outage period is overlapped: ~{_md(e1)} / {_md(s2)}~")
    return ranges


OUTAGES = _parse_outages(OUTAGE_PERIODS)


def overlay_outages(segments):
    """
    overwrite power outage period
    """
    breaks = {end for end, _ in segments}
    for s, e in OUTAGES:
        if s > _JAN1:
            breaks.add(s - timedelta(days=1))
        breaks.add(e)

    result, start = [], _JAN1
    for end in sorted(b for b in breaks if b <= _DEC31):
        if any(s <= start and end <= e for s, e in OUTAGES):
            content = _OUTAGE
        else:
            content = next(c for seg_end, c in segments if seg_end >= end)

        if result and result[-1][2] is content:
            result[-1] = (result[-1][0], end, content)
        else:
            result.append((start, end, content))
        start = end + timedelta(days=1)
    return result



def load_clean_idf(path: str) -> IDF:
    """
    record cleaning
    """
    with open(path, "r", encoding="latin-1") as f:
        records = re.split(r"(;)", f.read())

    cleaned, i = [], 0
    while i < len(records):
        chunk = records[i]
        obj_type = next((ln.strip().split(",")[0].strip()
                         for ln in chunk.splitlines()
                         if ln.strip() and not ln.strip().startswith("!")), "")
        if re.search(r"[ \[\]()]", obj_type):
            print(f"    [clean] wrong record cleaned: '{obj_type[:60]}'")
            i += 2 if i + 1 < len(records) and records[i + 1] == ";" else 1
            continue
        cleaned.append(chunk)
        i += 1
    return IDF(io.StringIO("".join(cleaned)))


def get_object(idf: IDF, obj_type: str, name: str):
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name.strip().lower() == name.strip().lower():
            return obj
    return None


def ensure_type_limits(idf: IDF, name: str) -> None:
    """if ScheduleTypeLimits does not exist, create 0–1 range schedule (Fraction / On/Off)"""
    if get_object(idf, "ScheduleTypeLimits", name):
        return
    idf.newidfobject(
        "SCHEDULETYPELIMITS", Name=name,
        Lower_Limit_Value=0, Upper_Limit_Value=1,
        Numeric_Type="Discrete" if name.lower() == "on/off" else "Continuous",
    )


# schedule modification
def _write_compact(obj, overlaid, outage_value) -> None:
    fields = []
    for _, end, content in overlaid:
        fields.append(f"Through: {_md(end)}")
        fields += (["For: AllDays", "Until: 24:00", str(outage_value)]
                   if content is _OUTAGE else content)
    obj.obj[3:] = fields          # [class, Name, TypeLimits, Field_1, ...]


def apply_outage_to_compact(idf: IDF, name: str, outage_value=0) -> bool:
    """change Schedule:Compact to the outage schedule during the power outage period"""
    obj = get_object(idf, "Schedule:Compact", name)
    if obj is None:
        print(f"    [warn] Schedule:Compact '{name}' not exist")
        return False

    segments = []
    for field in (str(v).strip() for v in obj.obj[3:]):
        if not field:
            continue
        if field.lower().startswith("through"):
            segments.append((_parse_md(field), []))
        else:
            segments[-1][1].append(field)

    overlaid = overlay_outages(segments)
    _write_compact(obj, overlaid, outage_value)
    print(f"    [ok] Schedule:Compact '{name}' -> {len(overlaid)} period")
    return True


def apply_outage_to_year(idf: IDF, name: str) -> bool:
    """change Schedule:Year to OUTAGE_WEEK_SCH during the power outage"""
    obj = get_object(idf, "Schedule:Year", name)
    if obj is None:
        print(f"    [warn] Schedule:Year '{name}' not exist")
        return False

    vals = obj.obj[3:]            # [week, sm, sd, em, ed] repeat
    segments = [(date(_YEAR, int(vals[i + 3]), int(vals[i + 4])), str(vals[i]).strip())
                for i in range(0, len(vals) - 4, 5) if str(vals[i]).strip()]

    overlaid = overlay_outages(segments)
    fields = []
    for start, end, week in overlaid:
        fields += [OUTAGE_WEEK_SCH if week is _OUTAGE else week,
                   start.month, start.day, end.month, end.day]
    obj.obj[3:] = fields
    print(f"    [ok] Schedule:Year '{name}' → {len(overlaid)} period")
    return True


def create_avail_schedule(idf: IDF) -> None:
    """normal 1, power outage 0 On/Off availability schedule"""
    if get_object(idf, "Schedule:Compact", AVAIL_SCH):
        return
    ensure_type_limits(idf, "On/Off")
    obj = idf.newidfobject("SCHEDULE:COMPACT", Name=AVAIL_SCH,
                           Schedule_Type_Limits_Name="On/Off")
    always_on = [(_DEC31, ["For: AllDays", "Until: 24:00", "1"])]
    _write_compact(obj, overlay_outages(always_on), outage_value=0)
    print(f"    [ok] '{AVAIL_SCH}' created")


def create_outage_week(idf: IDF) -> None:
    """create day schedule (0 for 24 hours), week schedule (use day schedule during all week)"""
    ensure_type_limits(idf, "Fraction")
    if not get_object(idf, "Schedule:Day:Hourly", OUTAGE_DAY_SCH):
        idf.newidfobject("SCHEDULE:DAY:HOURLY", Name=OUTAGE_DAY_SCH,
                         Schedule_Type_Limits_Name="Fraction",
                         **{f"Hour_{h}": 0 for h in range(1, 25)})
    if not get_object(idf, "Schedule:Week:Compact", OUTAGE_WEEK_SCH):
        week = idf.newidfobject("SCHEDULE:WEEK:COMPACT", Name=OUTAGE_WEEK_SCH)
        week.obj[2:] = ["For: AllDays", OUTAGE_DAY_SCH]


# identify building type and process by building type

def apply_grid_tied(idf: IDF) -> None:
    """processing exceptions which ignore the schedule"""
    print("processing exceptions (NightCycle / Transformer / Pump / PV)")

    # NightCycle: Applicability
    for obj in idf.idfobjects["AVAILABILITYMANAGER:NIGHTCYCLE"]:
        obj.Applicability_Schedule_Name = AVAIL_SCH
        print(f"    [ok] NightCycle '{obj.Name}' -> Applicability")

    # Transformer
    for obj in idf.idfobjects["ELECTRICLOADCENTER:TRANSFORMER"]:
        obj.Availability_Schedule_Name = AVAIL_SCH
        print(f"    [ok] Transformer '{obj.Name}'")

    # Pump
    for ptype in ("PUMP:CONSTANTSPEED", "PUMP:VARIABLESPEED"):
        for obj in idf.idfobjects[ptype]:
            sch = obj.Pump_Flow_Rate_Schedule_Name.strip()
            if sch:
                apply_outage_to_compact(idf, sch)
            else:
                obj.Pump_Flow_Rate_Schedule_Name = AVAIL_SCH
                print(f"    [ok] Pump '{obj.Name}' -> Flow Rate Schedule")

    # PV inverter
    for old in list(idf.idfobjects["ELECTRICLOADCENTER:INVERTER:PVWATTS"]):
        name, eff = old.Name, old.Inverter_Efficiency or 0.96
        idf.removeidfobject(old)
        idf.newidfobject("ELECTRICLOADCENTER:INVERTER:SIMPLE", Name=name,
                         Availability_Schedule_Name=AVAIL_SCH,
                         Radiative_Fraction=0, Inverter_Efficiency=eff)
        print(f"    [ok] Inverter:PVWatts '{name}' -> Inverter:Simple (efficiency {eff})")

    for itype in ("ELECTRICLOADCENTER:INVERTER:SIMPLE",
                  "ELECTRICLOADCENTER:INVERTER:FUNCTIONOFPOWER",
                  "ELECTRICLOADCENTER:INVERTER:LOOKUPTABLE"):
        for obj in idf.idfobjects[itype]:
            sch = obj.Availability_Schedule_Name.strip()
            if sch and sch.lower() not in ("always_on", AVAIL_SCH.lower()):
                apply_outage_to_compact(idf, sch)
            elif sch.lower() != AVAIL_SCH.lower():
                obj.Availability_Schedule_Name = AVAIL_SCH
                print(f"    [ok] Inverter '{obj.Name}' -> Availability")


def apply_residential(idf: IDF) -> None:
    print("equipment and lighting Schedule:Year")
    create_outage_week(idf)
    for name in RES_YEAR_SCHEDULES:
        apply_outage_to_year(idf, name)

    print("HVAC and DHW availability")
    create_avail_schedule(idf)
    for obj_type, name, field in RES_HVAC_TARGETS:
        obj = get_object(idf, obj_type, name)
        if obj is None:
            print(f"    [warn] {obj_type} '{name}' not exist")
            continue
        setattr(obj, field, AVAIL_SCH)
        print(f"    [ok] {obj_type} '{name}'")

    apply_grid_tied(idf)


def apply_office(idf: IDF) -> None:
    print("HVAC operation / lighting / equipment Schedule:Compact")
    for name in OFFICE_COMPACT_SCHEDULES:
        apply_outage_to_compact(idf, name)

    print("HVAC availability")
    create_avail_schedule(idf)
    total = 0
    for obj_type in OFFICE_REDIRECT_TYPES:
        n = 0
        for obj in idf.idfobjects[obj_type.upper()]:
            if obj.Availability_Schedule_Name.strip().lower() == OFFICE_REDIRECT_FROM.lower():
                obj.Availability_Schedule_Name = AVAIL_SCH
                n += 1
        if n:
            print(f"    [ok] {n:2d} × {obj_type}")
        total += n
    print(f"    {total} equipment changed in total")

    # DHW plant
    print("DHW plant operation")
    for obj in idf.idfobjects["PLANTEQUIPMENTOPERATIONSCHEMES"]:
        # obj.obj = [class, Name, (scheme type, scheme name, schedule) × N]
        for k in range(4, len(obj.obj), 3):
            if str(obj.obj[k]).strip():
                obj.obj[k] = AVAIL_SCH
        print(f"    [ok] PlantEquipmentOperationSchemes '{obj.Name}'")

    apply_grid_tied(idf)




def detect_building_type(fname: str):
    """detect building type using file name"""
    low = fname.lower()
    if "office" in low:
        return "office"
    if low.startswith("us+") or "+sf+" in low or "+mf+" in low or "residential" in low:
        return "residential"
    return None


def _city_from_site(idf: IDF) -> str:
    """extract city from Site:Location"""
    name = idf.idfobjects["SITE:LOCATION"][0].Name
    name = re.split(r"[-_,]|\b(?:Intl|Int'l|AP|Ap|Arpt|Airport|TMY\d*|WMO)\b", name)[0]
    words = [w for w in re.findall(r"[A-Za-z]+", name)
             if not (w.isupper() and len(w) <= 3)]          
    return "".join(w[0].upper() + w[1:] for w in words) or "Unknown"


def name_parts(fname: str, idf: IDF, btype: str):
    """(building type, climate zone, city), if unknown: None"""
    if btype == "residential":
        tokens = [t.lower() for t in os.path.splitext(fname)[0].split("+")]
        cz = re.search(r"CZ(\d[ABC]?)", fname, re.I)
        kind = "SF" if "sf" in tokens else "MF" if "mf" in tokens else ""
        foundation = next((FOUNDATIONS[t] for t in tokens if t in FOUNDATIONS), None)
        btype_name = f"Residential{kind}" + (f"-{foundation}" if foundation else "")
        return btype_name, cz.group(1).upper() if cz else "CZunknown", _city_from_site(idf)

    # office
    m = re.match(r"^NewModel\d+_(?P<bt>[^_]+)_(?P<cz>[^_]+)_(?P<city>.+)\.idf$", fname, re.I)
    if m:
        return m.group("bt"), m.group("cz"), m.group("city")
    m = re.match(r"^ASHRAE901_(?P<bt>[^_]+)_STD\d+_(?P<city>.+)\.idf$", fname, re.I)
    if m:
        city = m.group("city")
        return m.group("bt"), CLIMATE_ZONES.get(city, "CZunknown"), city
    return None


#run

def run_measure2(input_dirs=INPUT_DIRS, output_dir=OUTPUT_DIR, idd_path=IDD_PATH):
    if IDF.getiddname() is None:
        IDF.setiddname(idd_path)
    os.makedirs(output_dir, exist_ok=True)

    print("power outage period: " + ", ".join(f"{_md(s)}–{_md(e)}" for s, e in OUTAGES))

    paths = sorted({p for d in input_dirs for p in glob.glob(os.path.join(d, "*.idf"))})
    if not paths:
        print(f"[!] no idf file: {input_dirs}")
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
            print(f"  [warn] unknown climate zone -> update CLIMATE_ZONES by adding '{parts[2]}'")

        if btype == "residential":
            apply_residential(idf)
        else:
            apply_office(idf)

        # if same file name -> put number label 
        stem = f"{OUTPUT_PREFIX}_" + "_".join(parts)
        out_name, k = f"{stem}.idf", 2
        while out_name in used_names:
            out_name, k = f"{stem}_{k}.idf", k + 1
        if k > 2:
            print(f"  [warn] file name duplicated -> save as '{out_name}'")
        used_names.add(out_name)

        out_path = os.path.join(output_dir, out_name)
        idf.saveas(out_path)
        saved.append(out_path)
        print(f"  [saved] {out_name}")

    print(f"\nDone: {len(saved)}/{len(paths)} files generated -> {output_dir}")
    return saved


if __name__ == "__main__":
    run_measure2()