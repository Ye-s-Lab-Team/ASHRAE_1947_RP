"""
Measure 2 simpler version

1. set the power outage date
2. design the power outage schedule (Schedule:Compact)
3. apply it for the equipments, HVAC, and hot water system

Power outage date
- Summer outage: 7/16 - 7/18
- Winter outage: 12/16-12/18

Referenced model
- Residential: Residential building model with electric resistance heating
- Office: Medium office building model with electric resistance heating (outcome model from the measure 1 operation)

"""

# import libraries
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import copy
from matplotlib import dates
from matplotlib.dates import DayLocator, HourLocator,DateFormatter
import matplotlib.ticker as ticker
from matplotlib.ticker import FormatStrFormatter
from eppy import modeleditor
from eppy.modeleditor import IDF
import sys


#%% data path

pathnameto_eppy = '../'
sys.path.append(pathnameto_eppy)

##### Windows OS
iddfile = "C:/EnergyPlusV25-1-0/Energy+.idd"
residential1 = "../Building_models/original_versiontrans/residential/resstd_IECC_2024/elec_heating/"

residf = "US+SF+CZ4A+elecres+slab+IECC_2024.idf"

# =============================================================================
# ##### mac OS
# iddfile = "/Applications/EnergyPlus-25-1-0/Energy+.idd"
# office1 = "../Building_models/original_versiontrans/mid_office/ASHRAE901_OfficeMedium_STD2022/"
# residential1 = "../Building_models/original_versiontrans/residential/resstd_IECC_2024/elec_heating/"
# midoffice = "ASHRAE901_OfficeMedium_STD2022_NewYork.idf"
# resid = "US+SF+CZ4A+elecres+slab+IECC_2024.idf"
# 
# =============================================================================

IDF.setiddname(iddfile)
res1 = IDF(residential1 + residf)



newpath_res = "../Task1/Measure2/Residential/"



#%% Define the power outage period

summer_outage_startdate = "7/16"
summer_outage_enddate = "7/18"

winter_outage_startdate = "12/16"
winter_outage_enddate = "12/18"

location = res1.idfobjects['Site:Location'][0].Name


table = location.maketrans({
    '=': '', 
    ',': '', 
    '%': '',
    '^': '',
    '&': ''
})

# print(location.translate(table))
location = location.translate(table)

newidf_res = newpath_res + "outage+res+" + location + '.idf'
newidf_off = newpath_off + "outage+off+" + location + '.idf'


#%% Check the field name: Schedule:Year

yearly_schedule = "Schedule:Year"
weekly_compact = 'Schedule:Week:Compact'


equipment_schedule_year = {
    "InteriorLighting":       "LightingProfileWeek",
    "InteriorLightingHE":     "LightingProfileWeek_EELighting",
    "Refrigerator":           "RefrigeratorWeek",
    "MiscPlugLoad":           "MiscPlugLoadWeek",
    "CookingRange":           "CookingRangeWeek",
    "ClothesWasher_equip_sch": "ClothesWasherWeek_equip_sch",
    "ClothesDryer":           "ClothesDryerWeek",
    "Dishwasher_equip_sch":   "DishwasherWeek_equip_sch",
}

#%% Setup the power outage schedule object 

outage_dayschedule = 'power outage_day'
outage_weekschedule = 'power outage_week'

#%% design the power outage schedule

def get_object_by_name(idf: IDF, obj_type: str, name: str):
    """
    Return the first eppy object of obj_type whose Name field matches
    (case-insensitive). Returns None if not found.
    """
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name.strip().lower() == name.strip().lower():
            return obj
    return None


def power_outage_day_schedule(idf: IDF) -> None:
    """
    Add a Schedule:Day:Hourly named 'power outage_day' with all 24 hours = 0.
    Skips creation if the object already exists (e.g. file was partially modified).
    """
    if get_object_by_name(idf, "Schedule:Day:Hourly", outage_dayschedule):
        print(f"  [skip] Schedule:Day:Hourly '{outage_dayschedule}' already exists.")
        return

    day_obj = idf.newidfobject("SCHEDULE:DAY:HOURLY")
    day_obj.Name = outage_dayschedule
    day_obj.Schedule_Type_Limits_Name = "Fraction"

    # eppy names hourly fields Hour_1 … Hour_24
    for hour in range(1, 25):
        setattr(day_obj, f"Hour_{hour}", 0)

    print(f"  [created] Schedule:Day:Hourly '{outage_dayschedule}'")




def power_outage_week_schedule(idf: IDF) -> None:
    """
    Add a Schedule:Week:Compact named 'elec_outage_zero_week' that maps
    every day type to 'power outage_day'.
    Skips creation if the object already exists.
    """
    if get_object_by_name(idf, "Schedule:Week:Compact", outage_weekschedule):
        print(f"  [skip] Schedule:Week:Compact '{outage_weekschedule}' already exists.")
        return

    week_obj = idf.newidfobject("SCHEDULE:WEEK:COMPACT")
    week_obj.Name = outage_weekschedule
    # DayType_List_1 / Schedule_Day_Name_1 covers every day type
    week_obj.DayType_List_1  = "For: AllDays"
    week_obj.ScheduleDay_Name_1 = outage_dayschedule

    print(f"  [created] Schedule:Week:Compact '{outage_weekschedule}'")
  






def apply_outage_to_year_schedule(idf: IDF, sched_name: str, orig_week: str, 
                                  summer_startdate, summer_enddate, winter_startdate, winter_enddate) -> None:
    """
    Modify a Schedule:Year object to introduce outage periods.

    Before (single segment):
        Week Name 1 = orig_week,  Start 1/1,  End 12/31

    After (five segments):
        Week Name 1 = orig_week,            Start day (MM/DD),   End 7/15   (normal)
        Week Name 2 = elec_outage_zero_week, Start (MM/DD),  End 7/18   (summer outage)
        Week Name 3 = orig_week,            Start (MM/DD),  End 12/15  (normal)
        Week Name 4 = elec_outage_zero_week, Start (MM/DD), End 12/18  (winter outage)
        Week Name 5 = orig_week,            Start (MM/DD), End 12/31  (normal)

    eppy field naming convention for Schedule:Year:
        Schedule_Week_Name_1, Start_Month_1, Start_Day_1, End_Month_1, End_Day_1
        Schedule_Week_Name_2, Start_Month_2, Start_Day_2, End_Month_2, End_Day_2
        ... (up to 53 segments supported by EnergyPlus)
        
    for future update: define time
    more segment for more power outage day simulation
    """
    obj = get_object_by_name(idf, "Schedule:Year", sched_name)
    if obj is None:
        print(f"  [WARNING] Schedule:Year '{sched_name}' not found — skipping.")
        return
    
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


    
    # Define the 5 segments as (week_name, start_month, start_day, end_month, end_day)
    segments = [
        (orig_week,      1,  1,  po_startmonth_summer, po_startday_summer-1),   # normal: Jan 1  – Jul 15
        (outage_weekschedule, po_startmonth_summer, po_startday_summer,  po_endmonth_summer, po_endday_summer),   # outage: Jul 16 – Jul 18
        (orig_week,      po_startmonth_summer, po_endday_summer+1, po_startmonth_winter, po_startday_winter-1),   # normal: Jul 19 – Dec 15
        (outage_weekschedule, po_startmonth_winter, po_startday_winter, po_endmonth_winter, po_endday_winter),  # outage: Dec 16 – Dec 18
        (orig_week,      po_endmonth_winter, po_endday_winter+1, 12, 31),  # normal: Dec 19 – Dec 31
    ]

    for i, (week, sm, sd, em, ed) in enumerate(segments, start=1):
        setattr(obj, f"ScheduleWeek_Name_{i}", week)
        setattr(obj, f"Start_Month_{i}", sm)
        setattr(obj, f"Start_Day_{i}", sd)
        setattr(obj, f"End_Month_{i}", em)
        setattr(obj, f"End_Day_{i}", ed)

    print(f"  [modified] Schedule:Year '{sched_name}' → 5 segments with outage weeks")


# =============================================================================
# HVAC schedule modification
# =============================================================================

outage_schedule = "power out schedule_compact"
original_schedule = 'always_avail'

def get_object(idf: IDF, obj_type: str, name: str):
    """
    Return the first eppy object whose class is obj_type and whose Name
    field matches (case-insensitive). Returns None if not found.
    """
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name.strip().lower() == name.strip().lower():
            return obj
    return None



def create_power_out_schedule(idf: IDF, summer_startdate, summer_enddate, winter_startdate, winter_enddate) -> None:
    """
    Add Schedule:Compact "power out schedule" (On/Off type) with 5 date
    segments that mirror "always_avail" (value = 1) outside the outage
    windows and drop to 0 inside them:

        Through: 7/15  → For: AllDays / Until: 24:00 / 1   (normal)
        Through: 7/18  → For: AllDays / Until: 24:00 / 0   (summer outage)
        Through: 12/15 → For: AllDays / Until: 24:00 / 1   (normal)
        Through: 12/18 → For: AllDays / Until: 24:00 / 0   (winter outage)
        Through: 12/31 → For: AllDays / Until: 24:00 / 1   (normal)

    eppy represents the data portion of a Schedule:Compact as Field_1,
    Field_2, ... Each group of four fields encodes one Through/For/Until/value
    row.  Five segments → 20 fields total.
    """
    if get_object(idf, "Schedule:Compact", outage_schedule):
        print(f"  [skip] '{outage_schedule}' already exists.")
        return

    # (through_date, value) — value = 0 during outage, 1 during normal
    segments = [
        (summer_startdate,  1),   # normal  Jan 1  – Jul 15
        (summer_enddate,  0),   # outage  Jul 16 – Jul 18
        (winter_startdate, 1),   # normal  Jul 19 – Dec 15
        (winter_enddate, 0),   # outage  Dec 16 – Dec 18
        ("12/31", 1),   # normal  Dec 19 – Dec 31
    ]

    # Build flat field list: [Through:date, For:AllDays, Until:24:00, val, ...]
    fields = []
    for through_date, value in segments:
        fields.append(f"Through: {through_date}")
        fields.append("For: AllDays")
        fields.append("Until: 24:00")
        fields.append(value)

    obj = idf.newidfobject("SCHEDULE:COMPACT")
    obj.Name                      = outage_schedule
    obj.Schedule_Type_Limits_Name = "On/Off"

    # Assign Field_1 … Field_20 via eppy's setattr convention
    for i, val in enumerate(fields, start=1):
        setattr(obj, f"Field_{i}", val)

    print(f"  [created] Schedule:Compact '{outage_schedule}'")
    print(f"5 segments: normal/outage/normal/outage/normal")
    print(f"Outage windows: Jul 16-18 and Dec 16-18 → value = 0")


# ===========================================================================
# Step 2 — Redirect each HVAC object
# ===========================================================================

def redirect_availability_manager(idf: IDF) -> None:
    """
    AvailabilityManager:Scheduled  →  "System availability"
    eppy field: Schedule_Name

    Drives AirLoopHVAC (Central System_unit1) availability via the
    AvailabilityManagerAssignmentList. Shutting this down during outage
    periods disables the entire central air loop.

    Note: this object uses "Schedule_Name", not "Availability_Schedule_Name"
    — confirmed from IDF field comment:  !- Schedule Name
    """
    obj = get_object(idf, "AvailabilityManager:Scheduled", "System availability")
    if obj is None:
        print("  [WARNING] AvailabilityManager:Scheduled 'System availability' not found.")
        return
    obj.Schedule_Name = outage_schedule
    print("  [modified] AvailabilityManager:Scheduled  'System availability'"
          "  →  Schedule_Name")


def redirect_air_terminal(idf: IDF) -> None:
    """
    AirTerminal:SingleDuct:ConstantVolume:NoReheat  →  "ZoneDirectAir_unit1"
    eppy field: Availability_Schedule_Name

    Distributes conditioned supply air from the central AHU to the living
    zone. Disabling it during the outage stops airflow to the zone.
    """
    obj = get_object(
        idf, "AirTerminal:SingleDuct:ConstantVolume:NoReheat", "ZoneDirectAir_unit1"
    )
    if obj is None:
        print("  [WARNING] AirTerminal 'ZoneDirectAir_unit1' not found.")
        return
    obj.Availability_Schedule_Name = outage_schedule
    print("  [modified] AirTerminal:SingleDuct:ConstantVolume:NoReheat"
          "  'ZoneDirectAir_unit1'  →  Availability_Schedule_Name")


def redirect_cooling_coil(idf: IDF) -> None:
    """
    Coil:Cooling:DX:SingleSpeed  →  "DX Cooling Coil_unit1"
    eppy field: Availability_Schedule_Name

    Single-speed DX cooling coil inside the unitary heat-cool system.
    """
    obj = get_object(idf, "Coil:Cooling:DX:SingleSpeed", "DX Cooling Coil_unit1")
    if obj is None:
        print("  [WARNING] Coil:Cooling:DX:SingleSpeed 'DX Cooling Coil_unit1' not found.")
        return
    obj.Availability_Schedule_Name = outage_schedule
    print("  [modified] Coil:Cooling:DX:SingleSpeed"
          "  'DX Cooling Coil_unit1'  →  Availability_Schedule_Name")


def redirect_fans(idf: IDF) -> None:
    """
    Fan:OnOff  →  "Supply Fan_unit1"              (central AHU supply fan)
    Fan:OnOff  →  "Heat Pump Water Heater Fan_unit1" (HPWH evaporator fan)
    Fan:ZoneExhaust  →  "Zone Exhaust Fan_unit1"  (bathroom/kitchen exhaust)
    eppy field: Availability_Schedule_Name  (same for all three)
    """
    fans = [
        ("FAN:ONOFF",       "Supply Fan_unit1"),
        ("FAN:ONOFF",       "Heat Pump Water Heater Fan_unit1"),
        ("FAN:ZONEEXHAUST", "Zone Exhaust Fan_unit1"),
    ]
    for obj_type, name in fans:
        obj = get_object(idf, obj_type, name)
        if obj is None:
            print(f"  [WARNING] {obj_type} '{name}' not found.")
            continue
        obj.Availability_Schedule_Name = outage_schedule
        print(f"  [modified] {obj_type}  '{name}'  →  Availability_Schedule_Name")


def redirect_unitary_system(idf: IDF) -> None:
    """
    AirLoopHVAC:UnitaryHeatCool  →  "ACandF_unit1"
    eppy field: Availability_Schedule_Name

    Wraps the supply fan, DX cooling coil, and electric heating coil into a
    single AHU component on the central air loop.
    """
    obj = get_object(idf, "AirLoopHVAC:UnitaryHeatCool", "ACandF_unit1")
    if obj is None:
        print("  [WARNING] AirLoopHVAC:UnitaryHeatCool 'ACandF_unit1' not found.")
        return
    obj.Availability_Schedule_Name = outage_schedule
    print("  [modified] AirLoopHVAC:UnitaryHeatCool"
          "  'ACandF_unit1'  →  Availability_Schedule_Name")


def redirect_heating_coil(idf: IDF) -> None:
    """
    Coil:Heating:Electric  →  "Main electric heating coil_unit1"
    eppy field: Availability_Schedule_Name

    Electric resistance heating coil inside the unitary heat-cool system.

    Note: the IDF spells the class "Coil:Heating:electric" (lowercase 'e').
    EnergyPlus and eppy are both case-insensitive for class names, so
    "Coil:Heating:Electric" resolves correctly.
    """
    obj = get_object(
        idf, "Coil:Heating:Electric", "Main electric heating coil_unit1"
    )
    if obj is None:
        print("  [WARNING] Coil:Heating:Electric"
              " 'Main electric heating coil_unit1' not found.")
        return
    obj.Availability_Schedule_Name = outage_schedule
    print("  [modified] Coil:Heating:Electric"
          "  'Main electric heating coil_unit1'  →  Availability_Schedule_Name")


def redirect_water_heater(idf: IDF) -> None:
    """
    WaterHeater:HeatPump:WrappedCondenser  →  "Water Heater_unit1"
    eppy field: Availability_Schedule_Name

    Heat-pump water heater (HPWH). Disabling it cuts compressor operation.
    The HPWH fan is handled separately in redirect_fans().
    """
    obj = get_object(
        idf, "WaterHeater:HeatPump:WrappedCondenser", "Water Heater_unit1"
    )
    if obj is None:
        print("  [WARNING] WaterHeater:HeatPump:WrappedCondenser"
              " 'Water Heater_unit1' not found.")
        return
    obj.Availability_Schedule_Name = outage_schedule
    print("  [modified] WaterHeater:HeatPump:WrappedCondenser"
          "  'Water Heater_unit1'  →  Availability_Schedule_Name")


def redirect_plant_operation(idf: IDF) -> None:
    """
    PlantEquipmentOperationSchemes  →  "DHW Loop Operation_unit1"
    eppy field: Control_Scheme_1_Schedule_Name

    Controls which plant equipment is dispatched on the DHW loop. Its schedule
    field is "Control Scheme 1 Schedule Name" in the IDF — eppy maps this to
    Control_Scheme_1_Schedule_Name. Setting this to the outage schedule
    prevents any DHW plant equipment from operating during outages.

    Note: this field name differs from all other objects above — it is NOT
    called "Availability_Schedule_Name".
    """
    obj = get_object(
        idf, "PlantEquipmentOperationSchemes", "DHW Loop Operation_unit1"
    )
    if obj is None:
        print("  [WARNING] PlantEquipmentOperationSchemes"
              " 'DHW Loop Operation_unit1' not found.")
        return
    obj.Control_Scheme_1_Schedule_Name = outage_schedule
    print("  [modified] PlantEquipmentOperationSchemes"
          "  'DHW Loop Operation_unit1'  →  Control_Scheme_1_Schedule_Name")


# ===========================================================================
# Verification
# ===========================================================================

def verify(idf: IDF) -> None:
    """
    Confirm:
      - "power out schedule" exists with 5 date segments including both
        outage windows.
      - All 10 HVAC objects now reference "power out schedule".
      - ZoneVentilation:DesignFlowRate still references "always_avail".
    """
    print(f"\n{'='*60}")
    print("VERIFICATION")
    print(f"{'='*60}")

    # --- Check outage schedule structure ---
    sched = get_object(idf, "Schedule:Compact", outage_schedule)
    if sched:
        # Read Field_1 … Field_20, collect only the Through: entries
        fields   = [str(getattr(sched, f"Field_{i}", "")).strip()
                    for i in range(1, 25)]
        throughs = [f for f in fields if f.lower().startswith("through:")]
        has_summer = any("7/18"  in t for t in throughs)
        has_winter = any("12/18" in t for t in throughs)
        ok = len(throughs) == 5 and has_summer and has_winter
        print(f"  [{'OK' if ok else 'ERROR'}]"
              f"  Schedule:Compact '{outage_schedule}'"
              f"  →  {len(throughs)} segments,"
              f"  summer outage = {'YES' if has_summer else 'NO'},"
              f"  winter outage = {'YES' if has_winter else 'NO'}")
    else:
        print(f"  [ERROR]  Schedule:Compact '{outage_schedule}' NOT FOUND")

    # --- Check each HVAC object ---
    # (obj_type, obj_name, eppy_field_attr)
    checks = [
        ("AvailabilityManager:Scheduled",
            "System availability",
            "Schedule_Name"),
        ("AirTerminal:SingleDuct:ConstantVolume:NoReheat",
            "ZoneDirectAir_unit1",
            "Availability_Schedule_Name"),
        ("Coil:Cooling:DX:SingleSpeed",
            "DX Cooling Coil_unit1",
            "Availability_Schedule_Name"),
        ("Fan:OnOff",
            "Supply Fan_unit1",
            "Availability_Schedule_Name"),
        ("Fan:OnOff",
            "Heat Pump Water Heater Fan_unit1",
            "Availability_Schedule_Name"),
        ("Fan:ZoneExhaust",
            "Zone Exhaust Fan_unit1",
            "Availability_Schedule_Name"),
        ("AirLoopHVAC:UnitaryHeatCool",
            "ACandF_unit1",
            "Availability_Schedule_Name"),
        ("Coil:Heating:Electric",
            "Main electric heating coil_unit1",
            "Availability_Schedule_Name"),
        ("WaterHeater:HeatPump:WrappedCondenser",
            "Water Heater_unit1",
            "Availability_Schedule_Name"),
        ("PlantEquipmentOperationSchemes",
            "DHW Loop Operation_unit1",
            "Control_Scheme_1_Schedule_Name"),
    ]

    for obj_type, name, field in checks:
        obj = get_object(idf, obj_type, name)
        if obj is None:
            print(f"  [ERROR]  {obj_type} '{name}' — NOT FOUND")
            continue
        current = getattr(obj, field, "").strip()
        ok = current.lower() == outage_schedule.lower()
        print(f"  [{'OK' if ok else 'ERROR'}]"
              f"  {obj_type}  '{name}'"
              f"  →  {field} = '{current}'")

    # --- ZoneVentilation must remain unchanged ---
    for obj in idf.idfobjects["ZONEVENTILATION:DESIGNFLOWRATE"]:
        current = obj.Schedule_Name.strip()
        ok = current.lower() == original_schedule.lower()
        print(f"  [{'OK' if ok else 'WARN — was changed!'}]"
              f"  ZoneVentilation '{obj.Name}'"
              f"  →  Schedule_Name = '{current}'"
              f"  (must remain '{original_schedule}')")


# ===========================================================================
# Main pipeline
# ===========================================================================

def run(idf_path: str, out_path: str) -> None:
    print(f"\n{'='*60}")
    print(f"INPUT:  {idf_path}")
    print(f"OUTPUT: {out_path}")
    print(f"{'='*60}")

    idf = IDF(idf_path)

    # Step 1 — build the outage schedule
    print("\n--- Step 1: Create 'power out schedule' ---")
    create_power_out_schedule(idf)

    # Step 2 — redirect every HVAC object
    print("\n--- Step 2: Redirect HVAC availability schedules ---")
    redirect_availability_manager(idf)
    redirect_air_terminal(idf)
    redirect_cooling_coil(idf)
    redirect_fans(idf)
    redirect_unitary_system(idf)
    redirect_heating_coil(idf)
    redirect_water_heater(idf)
    redirect_plant_operation(idf)

    # Step 3 — verify in-memory then save
    verify(idf)

    idf.saveas(out_path)
    print(f"\n[saved]  {out_path}")

def apply_residential_outage(idf_file, new_filepath_filename, summer_startdate, summer_enddate, winter_startdate, winter_enddate) -> None:
    """
    Full pipeline for the residential IDF file.
    Adds outage day/week schedules and rewrites all target Schedule:Year objects.
    """
    print(f"\n{'='*60}")
    print(f"RESIDENTIAL FILE: {idf_file}")
    print(f"{'='*60}")

    idf = idf_file

    # Step 1: Create the all-zero day schedule
    print("\n--- Step 1: Zero day schedule ---")
    power_outage_day_schedule(idf)

    # Step 2: Create the all-zero week schedule
    print("\n--- Step 2: Zero week schedule ---")
    power_outage_week_schedule(idf)

    # Step 3: Modify each target Schedule:Year
    print("\n--- Step 3: Modify Schedule:Year objects ---")
    for sched_name, orig_week in equipment_schedule_year.items():
        apply_outage_to_year_schedule(idf, sched_name, orig_week, summer_startdate, summer_enddate, 
                                      winter_startdate, winter_enddate)

    
# =============================================================================
#     HVAC schedule change
# =============================================================================
    
    # Step 1 — build the outage schedule
    print("\n--- Step 1: Create 'power out schedule' ---")
    create_power_out_schedule(idf, summer_startdate, summer_enddate, winter_startdate, winter_enddate)
    
    # Step 2 — redirect every HVAC object
    print("\n--- Step 2: Redirect HVAC availability schedules ---")
    redirect_availability_manager(idf)
    redirect_air_terminal(idf)
    redirect_cooling_coil(idf)
    redirect_fans(idf)
    redirect_unitary_system(idf)
    redirect_heating_coil(idf)
    redirect_water_heater(idf)
    redirect_plant_operation(idf)
    
    
    res1_modified = res1.saveas(new_filepath_filename)

    # return(res1_modified)
    print(f"\n[saved] {new_filepath_filename}")

#%% test

# res1_poweroutage = apply_residential_outage(res1, newidf_res, 7/16, 7/18, 12/16, 12/18)











