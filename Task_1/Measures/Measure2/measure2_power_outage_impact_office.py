"""
office_power_outage_fixed.py
============================
Applies a power outage scenario to the medium office building IDF:
    test_New_York-John_F_Kenn.idf

Modifies both HVAC availability schedules and electric load schedules.

Outage windows (edit OUTAGE_PERIODS at the top of this file to change):
    Summer : July 16 – July 18    (7/16 – 7/18)
    Winter : December 16 – Dec 18 (12/16 – 12/18)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUG FIX — "Slab thickness ... is not a valid Object Type"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Root cause:
    When EnergyPlus previously ran on the source IDF it may have written
    GroundHeatTransfer:Slab preprocessor warning messages back into the
    file as if they were IDF objects, e.g.:

        Slab thickness [0.100 m] reset to 0.122 m  for computational stability.,
            <field values...>;

    eppy reads and re-saves this text verbatim.  EnergyPlus then chokes
    when it tries to parse that sentence as an object type name.

Fix applied — load_clean_idf():
    Before handing the file to eppy the raw text is split into
    semicolon-delimited records.  Any record whose first non-comment
    token (the object type) contains spaces, brackets [ ], or parentheses
    — all of which are illegal in valid EnergyPlus type names — is silently
    dropped.  Every legitimate object is preserved unchanged.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS SCRIPT MODIFIES AND WHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SECTION A — HVAC operational schedules  (rebuilt in-place, 5 date segments)
─────────────────────────────────────────────────────────────────────────────
  HVACOperationSchd  [on/off]
      Referenced by:
        • Fan:VariableVolume × 3              (Availability_Schedule_Name)
          → PACU_VAV_bot/mid/top Fan
        • AvailabilityManager:NightCycle × 3  (Fan_Schedule_Name)
          → PACU_VAV_bot/mid/top Availability Manager
      Day pattern preserved: Weekdays 06:00–22:00 = 1, Saturday 06:00–18:00 = 1,
      all other times = 0.  Outage windows override to AllDays = 0.

  MinOA_MotorizedDamper_Sched  [fraction]
      Referenced by:
        • Controller:MechanicalVentilation × 3  (Availability_Schedule_Name)
          → PACU_VAV_bot/mid/top_DCV
      Controls DCV (demand-controlled ventilation) availability.
      Day pattern preserved; outage windows → 0.

SECTION B — HVAC component availability  (new schedule created + redirect)
─────────────────────────────────────────────────────────────────────────────
  ALWAYS_ON [Fraction, always = 1.0] is used by 44 objects:
    • AirTerminal:SingleDuct:VAV:Reheat × 15   → REDIRECT ✓
    • Coil:Cooling:DX:TwoSpeed          ×  3   → REDIRECT ✓
    • Coil:Heating:Electric (AHU)       ×  3   → REDIRECT ✓
    • Coil:Heating:Electric (reheat)    × 15   → REDIRECT ✓
    • CoilSystem:Cooling:DX             ×  3   → REDIRECT ✓  (39 total)
    • AvailabilityManager:NightCycle × 3  (Applicability_Schedule_Name)
          → DO NOT CHANGE — this field controls whether night-cycling
            logic is active at all; it must remain always-on so EnergyPlus
            can evaluate night-cycle decisions on normal operating days.
    • ElectricLoadCenter:Transformer × 1
          → DO NOT CHANGE — non-HVAC infrastructure; altering this would
            affect grid-connection energy accounting, not equipment operation.

  A new schedule "HVAC_OutageSch" (On/Off, = 1 normally, = 0 during outages)
  is created and the 39 powered HVAC components are redirected to it.

SECTION C — Electric load schedules  (rebuilt in-place, 5 date segments)
─────────────────────────────────────────────────────────────────────────────
  ltg_sch_office              → Lights × 15             (all interior zones)
  BLDG_EQUIP_SCH              → ElectricEquipment × 15  (all interior zones)
  BLDG_ELEVATORS              → ElectricEquipment × 1   (elevator)
  ELEV_LIGHT_FAN_SCH_ADD_DF   → ElectricEquipment × 1   (elevator lights/fan)
  Exterior_lighting_schedule_a      → Exterior:Lights × 1
  Exterior_lighting_schedule_b_2016 → Exterior:Lights × 1
  Exterior_lighting_schedule_c_2016 → Exterior:Lights × 1

Usage:
    python office_power_outage_fixed.py

Requirements:
    pip install eppy

EnergyPlus version: 25.1
"""

import re
import io
from eppy.modeleditor import IDF

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — edit these to match your environment and outage scenario
# ─────────────────────────────────────────────────────────────────────────────

IDD_PATH   = "C:/EnergyPlusV25-1-0/Energy+.idd"          # Windows
# IDD_PATH = "/usr/local/EnergyPlus-25-1-0/Energy+.idd"  # Linux / macOS

INPUT_IDF  = "test_New.York-John.F.Kenn.idf"
OUTPUT_IDF = "outage_off_New_York-John_F_Kennedy_Intl_AP_NY_USA_WMO744860_outage.idf"

# Outage windows as ((start_month, start_day), (end_month, end_day)) tuples.
# The day before each start date is calculated automatically for the normal
# segment boundary, so start_day must not be the 1st of a month.


summer_outage_startdate = "7/16"
summer_outage_enddate = "7/18"

winter_outage_startdate = "12/16"
winter_outage_enddate = "12/18"

# Power outage start: Summer
po_startmonth_summer = int(summer_outage_startdate.split("/")[0])
po_startday_summer = int(summer_outage_startdate.split("/")[1])


# Power outage end: Summer
po_endmonth_summer = int(summer_outage_enddate.split("/")[0])
po_endday_summer = int(summer_outage_enddate.split("/")[1])

# Power outage start: Winter
po_startmonth_winter = int(winter_outage_startdate.split("/")[0])
po_startday_winter = int(winter_outage_startdate.split("/")[1])

# Power outage end: Winter
po_endmonth_winter = int(winter_outage_enddate.split("/")[0])
po_endday_winter = int(winter_outage_enddate.split("/")[1])


OUTAGE_PERIODS = [
    ((po_startmonth_summer,  po_startday_summer), (po_endmonth_summer,  po_endday_summer)),   # summer outage: Jul 16 – Jul 18
    ((po_startmonth_winter, po_startday_winter), (po_endmonth_winter, po_endday_winter)),   # winter outage: Dec 16 – Dec 18
]

# Name for the new HVAC component availability schedule (Section B)
HVAC_OUTAGE_SCH = "HVAC_OutageSch"

# HVAC object types whose Availability_Schedule_Name is redirected from
# ALWAYS_ON → HVAC_OutageSch.  NightCycle and Transformer are excluded.
HVAC_REDIRECT_TYPES = [
    "AIRTERMINAL:SINGLEDUCT:VAV:REHEAT",
    "COIL:COOLING:DX:TWOSPEED",
    "COIL:HEATING:ELECTRIC",
    "COILSYSTEM:COOLING:DX",
]

# Section A: HVAC operational schedules rebuilt with outage windows
HVAC_OP_SCHEDULES = [
    "HVACOperationSchd",
    "MinOA_MotorizedDamper_Sched",
]

# Section C: electric load schedules rebuilt with outage windows
ELEC_SCHEDULES = [
    "ltg_sch_office",
    "BLDG_EQUIP_SCH",
    "BLDG_ELEVATORS",
    "ELEV_LIGHT_FAN_SCH_ADD_DF",
    "Exterior_lighting_schedule_a",
    "Exterior_lighting_schedule_b_2016",
    "Exterior_lighting_schedule_c_2016",
]


# ─────────────────────────────────────────────────────────────────────────────
# FIX — Pre-cleaner: strip preprocessor-injected invalid objects
# ─────────────────────────────────────────────────────────────────────────────

def _is_invalid_object_type(token: str) -> bool:
    """
    Return True if token looks like a preprocessor-injected message rather
    than a valid EnergyPlus object type name.

    Valid object type names contain only letters, digits, colons, underscores,
    and hyphens.  Any token containing spaces, brackets [ ], or parentheses
    is an invalid object type (i.e. a preprocessor warning that crept in).
    """
    return bool(re.search(r'[ \[\]()]', token))


def clean_idf_text(raw_text: str) -> str:
    """
    Remove any IDF records whose object type name is a preprocessor message.

    Strategy: split the raw text on semicolons to get individual records.
    For each record, find the first non-blank, non-comment line and extract
    the token before the first comma (the object type name).  If that token
    contains characters that are illegal in EnergyPlus object type names,
    discard the entire record (and its trailing semicolon).

    Returns the cleaned IDF text with all legitimate objects intact.
    """
    records = re.split(r'(;)', raw_text)
    cleaned = []
    i = 0
    while i < len(records):
        chunk = records[i]
        obj_type_token = None
        for line in chunk.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('!'):
                m = re.match(r'^([^,\n!]+)', stripped)
                if m:
                    obj_type_token = m.group(1).strip()
                break
        if obj_type_token and _is_invalid_object_type(obj_type_token):
            print(f"  [cleaned] Removed preprocessor-injected object: "
                  f"'{obj_type_token[:70]}'")
            i += 1
            if i < len(records) and records[i] == ';':
                i += 1  # skip the semicolon belonging to this bad record
            continue
        cleaned.append(chunk)
        i += 1
    return ''.join(cleaned)


def load_clean_idf(idf_path: str) -> IDF:
    """
    Load an IDF file into eppy after stripping any preprocessor-injected
    invalid objects from the raw text via clean_idf_text().
    """
    with open(idf_path, 'r', encoding='latin-1') as f:
        raw = f.read()
    cleaned = clean_idf_text(raw)
    return IDF(io.StringIO(cleaned))


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def set_idd(path: str) -> None:
    """Register the EnergyPlus IDD with eppy (call once per Python session)."""
    try:
        IDF.setiddname(path)
    except Exception:
        pass  # already registered — safe to ignore


def get_object(idf: IDF, obj_type: str, name: str):
    """
    Return the first eppy object whose class is obj_type and whose Name
    field matches (case-insensitive). Returns None if not found.
    """
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name.strip().lower() == name.strip().lower():
            return obj
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Schedule field helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_compact_data_fields(obj) -> list:
    """
    Return the flat list of populated data fields from a Schedule:Compact.

    eppy stores all field values in obj.fieldvalues as:
        [class_name, Name, TypeLimits, Field_1, Field_2, ...]
    This returns only the data portion (index 3 onward), dropping empty
    or None padding entries that eppy appends to fill the IDD maximum.
    """
    return [str(v).strip() for v in obj.fieldvalues[3:]
            if str(v).strip() not in ("", "None")]


def extract_inner_day_blocks(fields: list) -> list:
    """
    Strip the leading "Through: <date>" token from a Schedule:Compact field
    list and return everything that follows — i.e. the For:/Until:/value
    tokens that define the daily pattern inside that date segment.

    Input:  ["Through: 12/31", "For: Weekdays ...", "Until: 06:00", "0.0", ...]
    Output: ["For: Weekdays ...", "Until: 06:00", "0.0", ...]

    Only the first Through: token is stripped. This is correct for the
    schedules in this file, which all have a single "Through: 12/31" wrapper.
    """
    for i, field in enumerate(fields):
        if field.lower().startswith("through:"):
            return fields[i + 1:]
    return fields  # no Through: found — return unchanged


def build_outage_fields(inner_day_blocks: list, outage_value=0) -> list:
    """
    Build the full flat field list for a 5-segment outage Schedule:Compact.

    Normal periods replicate the original day pattern from inner_day_blocks.
    Outage windows replace all days with a constant outage_value.

    Date boundaries are derived from OUTAGE_PERIODS:

        Segment 1  Jan 1              – day before summer start   original pattern
        Segment 2  summer start       – summer end                AllDays = outage_value
        Segment 3  day after summer end – day before winter start original pattern
        Segment 4  winter start       – winter end                AllDays = outage_value
        Segment 5  day after winter end – Dec 31                  original pattern

    Parameters
    ----------
    inner_day_blocks : list
        For:/Until:/value tokens from the original single-segment schedule.
    outage_value : int or float
        Value to assign during outage periods (default 0).

    Returns
    -------
    list
        Flat list ready to be assigned to Field_1, Field_2, ... on a
        Schedule:Compact eppy object.
    """
    (sm, sd), (em, ed) = OUTAGE_PERIODS[0]   # summer
    (wm, wd), (fw, lw) = OUTAGE_PERIODS[1]   # winter

    pre_summer = f"{sm}/{sd - 1}"   # day before summer outage starts
    summer_end = f"{em}/{ed}"
    pre_winter = f"{wm}/{wd - 1}"   # day before winter outage starts
    winter_end = f"{fw}/{lw}"

    outage_block = ["For: AllDays", "Until: 24:00", str(outage_value)]

    fields  = [f"Through: {pre_summer}"]  + inner_day_blocks   # normal
    fields += [f"Through: {summer_end}"]  + outage_block        # summer outage
    fields += [f"Through: {pre_winter}"]  + inner_day_blocks   # normal
    fields += [f"Through: {winter_end}"]  + outage_block        # winter outage
    fields += ["Through: 12/31"]          + inner_day_blocks   # normal
    return fields


def rebuild_compact_schedule(idf: IDF, name: str) -> None:
    """
    Replace a Schedule:Compact in-place with the 5-segment outage version.

    1. Find the object by name; read its Schedule Type Limits and field list.
    2. Extract the inner day-pattern block (strips the Through: 12/31 header).
    3. Build the new 5-segment field list via build_outage_fields().
    4. Remove the old object from the IDF object list.
    5. Create a new Schedule:Compact with the same name, same type limits,
       and the rebuilt field list assigned to Field_1, Field_2, ...
    """
    obj = get_object(idf, "Schedule:Compact", name)
    if obj is None:
        print(f"  [WARNING] Schedule:Compact '{name}' not found — skipping.")
        return

    type_limits  = obj.Schedule_Type_Limits_Name.strip()
    orig_fields  = get_compact_data_fields(obj)
    inner_blocks = extract_inner_day_blocks(orig_fields)
    new_fields   = build_outage_fields(inner_blocks)

    idf.idfobjects["SCHEDULE:COMPACT"].remove(obj)

    new_obj = idf.newidfobject("SCHEDULE:COMPACT")
    new_obj.Name                      = name
    new_obj.Schedule_Type_Limits_Name = type_limits
    for i, val in enumerate(new_fields, start=1):
        setattr(new_obj, f"Field_{i}", val)

    print(f"  [rebuilt ] '{name}'  "
          f"({len(new_fields)} fields, type: {type_limits})")


# ─────────────────────────────────────────────────────────────────────────────
# Section B — create HVAC_OutageSch and redirect components
# ─────────────────────────────────────────────────────────────────────────────

def create_hvac_outage_schedule(idf: IDF) -> None:
    """
    Create Schedule:Compact "HVAC_OutageSch" (On/Off type):
        Normal periods → 1   (equipment available)
        Outage periods → 0   (equipment unavailable)

    On/Off is used (not Fraction) to match HVACOperationSchd's type and to
    serve as a clean binary availability flag for EnergyPlus components.

    Why a new schedule rather than modifying ALWAYS_ON?
    ALWAYS_ON is also used by two objects that must remain always active:
      • AvailabilityManager:NightCycle (Applicability_Schedule_Name)
            This field enables night-cycle logic to run. If set to 0, EnergyPlus
            will never allow the night-cycle manager to start fans for
            temperature recovery — even on non-outage days.
      • ElectricLoadCenter:Transformer (Availability_Schedule_Name)
            This is not HVAC equipment; modifying it changes how EnergyPlus
            accounts for grid electricity and is outside the scope of an
            HVAC/equipment outage scenario.
    Creating a new schedule isolates the change to the 39 powered HVAC
    components without affecting these two special-case objects.
    """
    if get_object(idf, "Schedule:Compact", HVAC_OUTAGE_SCH):
        print(f"  [skip    ] '{HVAC_OUTAGE_SCH}' already exists.")
        return

    inner_on   = ["For: AllDays", "Until: 24:00", "1"]
    new_fields = build_outage_fields(inner_on, outage_value=0)

    obj = idf.newidfobject("SCHEDULE:COMPACT")
    obj.Name                      = HVAC_OUTAGE_SCH
    obj.Schedule_Type_Limits_Name = "On/Off"
    for i, val in enumerate(new_fields, start=1):
        setattr(obj, f"Field_{i}", val)

    (sm, sd), (em, ed) = OUTAGE_PERIODS[0]
    (wm, wd), (fw, lw) = OUTAGE_PERIODS[1]
    print(f"  [created ] '{HVAC_OUTAGE_SCH}'  "
          f"(outage windows: {sm}/{sd}–{em}/{ed} and {wm}/{wd}–{fw}/{lw} → 0)")


def redirect_hvac_components(idf: IDF) -> None:
    """
    For every HVAC component in HVAC_REDIRECT_TYPES whose
    Availability_Schedule_Name is currently 'Always_On', switch it to
    HVAC_OutageSch.

    Total objects redirected (verified against the source IDF):
        AirTerminal:SingleDuct:VAV:Reheat  15
        Coil:Cooling:DX:TwoSpeed            3
        Coil:Heating:Electric              18  (15 zone reheat + 3 AHU)
        CoilSystem:Cooling:DX               3
        ───────────────────────────────────────
        Total                              39
    """
    total = 0
    for obj_type in HVAC_REDIRECT_TYPES:
        count = 0
        for obj in idf.idfobjects[obj_type]:
            if obj.Availability_Schedule_Name.strip().lower() == "always_on":
                obj.Availability_Schedule_Name = HVAC_OUTAGE_SCH
                count += 1
        if count:
            print(f"  [redirect] {count:2d} × {obj_type.title()} "
                  f"→ '{HVAC_OUTAGE_SCH}'")
            total += count
    print(f"  [redirect] {total} HVAC components redirected in total")


# ─────────────────────────────────────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────────────────────────────────────

def _verify_compact(idf: IDF, name: str) -> None:
    """Print a one-line pass/fail check for a rebuilt Schedule:Compact."""
    obj = get_object(idf, "Schedule:Compact", name)
    if obj is None:
        print(f"  [MISSING ] '{name}'")
        return

    fields   = get_compact_data_fields(obj)
    throughs = [f for f in fields if f.lower().startswith("through:")]

    (sm, sd), (em, ed) = OUTAGE_PERIODS[0]
    (wm, wd), (fw, lw) = OUTAGE_PERIODS[1]
    expected = {
        f"through: {sm}/{sd - 1}",
        f"through: {em}/{ed}",
        f"through: {wm}/{wd - 1}",
        f"through: {fw}/{lw}",
        "through: 12/31",
    }
    actual = {t.lower() for t in throughs}
    ok = (len(throughs) == 5) and (expected == actual)
    print(f"  [{'OK    ' if ok else 'ERROR '}] '{name}'  "
          f"— {len(throughs)} segments: {throughs}")


def verify(idf: IDF) -> None:
    """Run a full verification pass confirming all expected changes."""
    print(f"\n{'='*68}")
    print("VERIFICATION")
    print(f"{'='*68}")

    print("\n  A — HVAC operational schedules:")
    for name in HVAC_OP_SCHEDULES:
        _verify_compact(idf, name)

    print(f"\n  B — '{HVAC_OUTAGE_SCH}' schedule:")
    _verify_compact(idf, HVAC_OUTAGE_SCH)

    print(f"\n  B — HVAC component redirections → '{HVAC_OUTAGE_SCH}':")
    for obj_type in HVAC_REDIRECT_TYPES:
        n = sum(1 for obj in idf.idfobjects[obj_type]
                if obj.Availability_Schedule_Name.strip().lower()
                == HVAC_OUTAGE_SCH.lower())
        print(f"    {n:2d} × {obj_type.title()}")

    print("\n  B — objects that must keep ALWAYS_ON (must be unchanged):")
    nc_ok = all(
        obj.Applicability_Schedule_Name.strip().lower() == "always_on"
        for obj in idf.idfobjects["AVAILABILITYMANAGER:NIGHTCYCLE"]
        if hasattr(obj, "Applicability_Schedule_Name")
        and obj.Applicability_Schedule_Name.strip()
    )
    print(f"    AvailabilityManager:NightCycle Applicability: "
          f"{'OK — still Always_On' if nc_ok else 'ERROR — was changed!'}")

    tr = get_object(idf, "ElectricLoadCenter:Transformer", "Transformer 1")
    if tr:
        tr_ok = tr.Availability_Schedule_Name.strip().lower() == "always_on"
        print(f"    ElectricLoadCenter:Transformer:            "
              f"{'OK — still Always_On' if tr_ok else 'ERROR — was changed!'}")

    print("\n  C — Electric load schedules:")
    for name in ELEC_SCHEDULES:
        _verify_compact(idf, name)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run(idf_path: str, out_path: str) -> None:
    print(f"\n{'='*68}")
    print(f"INPUT : {idf_path}")
    print(f"OUTPUT: {out_path}")
    for (sm, sd), (em, ed) in OUTAGE_PERIODS:
        print(f"OUTAGE: {sm}/{sd} – {em}/{ed}")
    print(f"{'='*68}")

    # Load through the pre-cleaner to strip any preprocessor-injected objects
    print("\n--- Pre-cleaning IDF (stripping preprocessor artifacts) ---")
    idf = load_clean_idf(idf_path)

    # ── Section A: HVAC operational schedules ─────────────────────────────
    print("\n─── A: HVAC operational schedules ───────────────────────────────────")
    for name in HVAC_OP_SCHEDULES:
        rebuild_compact_schedule(idf, name)

    # ── Section B: HVAC component availability ────────────────────────────
    print("\n─── B: HVAC component availability ──────────────────────────────────")
    create_hvac_outage_schedule(idf)
    redirect_hvac_components(idf)

    # ── Section C: Electric load schedules ────────────────────────────────
    print("\n─── C: Electric equipment & lighting schedules ──────────────────────")
    for name in ELEC_SCHEDULES:
        rebuild_compact_schedule(idf, name)

    # ── Verify then save ───────────────────────────────────────────────────
    verify(idf)
    idf.saveas(out_path)
    print(f"\n[saved] {out_path}\n")


if __name__ == "__main__":
    set_idd(IDD_PATH)
    run(INPUT_IDF, OUTPUT_IDF)
