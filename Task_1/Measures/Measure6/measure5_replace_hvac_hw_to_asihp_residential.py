"""
convert_hp_to_asihp.py
======================
Converts a residential EnergyPlus IDF from air-to-air HP + AFN to an
Integrated Air-Source Heat Pump (ASIHP) system using Eppy.


What this script does
---------------------
Step 1  Remove all AirflowNetwork objects
Step 2  Remove old HP equipment (single-speed coils, WrappedCondenser HPWH,
        stratified tank, zone exhaust fan, old air loop + branches)
Step 3  Modify surviving objects (Water Heater Branch, PlantEquipmentList,
        ZoneHVAC:EquipmentList, ZoneHVAC:EquipmentConnections)
Step 4  Transplant 46 ASIHP objects from the target IDF
Step 5  Update Sizing:System air loop name
Step 6  Add DHW demand-side bypass pipe + update BranchList/Splitter/Mixer
Step 7  Stability patches:
          - HPWH min inlet air temperature → blank (no cold-weather cutoff)
          - Tank Element Control Logic → Simultaneous (prevents freeze cascade)
          - HPWH capacity/COP curve minimum output → 0.0 (prevents negative
            extrapolation below 0°C wet-bulb that causes −170°C crash)
"""

import argparse
import sys
import os
from eppy import modeleditor
from eppy.modeleditor import IDF


# ═════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════

def remove_all(idf, obj_type):
    """Remove every object of a given type."""
    key = obj_type.upper()
    objs = idf.idfobjects[key][:]
    for obj in objs:
        idf.removeidfobject(obj)
    return len(objs)


def remove_named(idf, obj_type, name):
    """Remove the first object of obj_type whose Name matches (case-insensitive)."""
    key = obj_type.upper()
    for obj in idf.idfobjects[key]:
        if obj.Name.upper() == name.upper():
            idf.removeidfobject(obj)
            return True
    print(f"  WARNING: {obj_type} '{name}' not found — skipping")
    return False


def get_named(idf, obj_type, name):
    """Return first object matching name (case-insensitive), or None."""
    for obj in idf.idfobjects[obj_type.upper()]:
        try:
            if obj.Name.upper() == name.upper():
                return obj
        except AttributeError:
            pass
    return None


def transplant_all(src_idf, dst_idf, obj_type, only_names=None):
    """
    Copy all objects of obj_type from src_idf to dst_idf.
    If only_names is given, copy only objects whose Name is in the list.
    """
    key = obj_type.upper()
    copied = 0
    for obj in src_idf.idfobjects[key]:
        name = getattr(obj, "Name", "")
        if only_names and name.upper() not in [n.upper() for n in only_names]:
            continue
        dst_idf.copyidfobject(obj)
        copied += 1
    return copied


# ═════════════════════════════════════════════════════════════════════════
# MAIN CONVERSION
# ═════════════════════════════════════════════════════════════════════════

def convert(original_path, target_path, idd_path, output_path):

    # ── Load IDF files ────────────────────────────────────────────────
    IDF.setiddname(idd_path)
    print(f"Loading original : {original_path}")
    idf = IDF(original_path)
    print(f"Loading target   : {target_path}")
    src = IDF(target_path)

    # ═══════════════════════════════════════════════════════════════════
    # STEP 1 — Remove all AirflowNetwork objects
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 1: Removing AirflowNetwork objects...")
    afn_types = [
        "AirflowNetwork:SimulationControl",
        "AirflowNetwork:MultiZone:Zone",
        "AirflowNetwork:MultiZone:Surface",
        "AirflowNetwork:MultiZone:Surface:EffectiveLeakageArea",
        "AirflowNetwork:MultiZone:Component:ZoneExhaustFan",
        "AirflowNetwork:Distribution:Node",
        "AirflowNetwork:Distribution:Component:Duct",
        "AirflowNetwork:Distribution:Component:Fan",
        "AirflowNetwork:Distribution:Component:Coil",
        "AirflowNetwork:Distribution:Component:LeakageRatio",
        "AirflowNetwork:Distribution:Linkage",
    ]
    total_afn = 0
    for t in afn_types:
        n = remove_all(idf, t)
        if n: print(f"  Removed {n:3d}  {t}")
        total_afn += n
    print(f"  Total AFN removed: {total_afn}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 2 — Remove old HP equipment
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 2: Removing old HP equipment...")
    to_remove = [
        # Old air-side HP
        ("AirLoopHVAC",                            "Central System_unit1"),
        ("AirLoopHVAC:UnitaryHeatPump:AirToAir",   "Heat Pump_unit1"),
        ("AirLoopHVAC:ReturnPath",                 "ReturnPath_unit1"),
        ("AirLoopHVAC:SupplyPath",                 "SupplyPath_unit1"),
        ("AirLoopHVAC:ZoneMixer",                  "Zone Return Air Mixer_unit1"),
        ("AirLoopHVAC:ZoneSplitter",               "Zone Supply Air Splitter_unit1"),
        ("Branch",                                  "Air Loop Main Branch_unit1"),
        ("BranchList",                             "Air Loop Branches_unit1"),
        ("Coil:Cooling:DX:SingleSpeed",            "DX Cooling Coil_unit1"),
        ("Coil:Heating:DX:SingleSpeed",            "Main DX Heating Coil_unit1"),
        # Old DHW
        ("WaterHeater:HeatPump:WrappedCondenser",  "Water Heater_unit1"),
        ("WaterHeater:Stratified",                 "Water Heater_Tank_unit1"),
        ("WaterHeater:Sizing",                     "Water Heater_Tank_unit1"),
        ("Coil:WaterHeating:AirToWaterHeatPump:Wrapped",
                                                   "Heat Pump Water Heater Evaporator_unit1"),
        # Zone exhaust fan
        ("Fan:ZoneExhaust",                        "Zone Exhaust Fan_unit1"),
        ("NodeList",                               "Zone Exhaust Node_List_unit1"),
        # Misc
        ("OutdoorAir:Node",                        "HPPlantAirInletNode_unit1"),
        ("Curve:Cubic",                            "HPACHeatCapFT"),
        ("Curve:Cubic",                            "HPACHeatEIRFT"),
        ("Sizing:System",                          "Central System_unit1"),
    ]
    for obj_type, name in to_remove:
        if remove_named(idf, obj_type, name):
            print(f"  Removed  {obj_type}: {name}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 3 — Modify surviving objects
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 3: Modifying surviving objects...")

    # 3a. Water Heater Branch: WrappedCondenser → PumpedCondenser
    branch = get_named(idf, "Branch", "Water Heater Branch_unit1")
    if branch:
        branch.Component_1_Object_Type = "WaterHeater:HeatPump:PumpedCondenser"
        branch.Component_1_Name        = "test_OutdoorHeatPumpWaterHeater"
        print("  Updated  Branch: Water Heater Branch_unit1")

    # 3b. PlantEquipmentList: same swap
    pel = get_named(idf, "PlantEquipmentList", "DHW Plant Equipment_unit1")
    if pel:
        pel.Equipment_1_Object_Type = "WaterHeater:HeatPump:PumpedCondenser"
        pel.Equipment_1_Name        = "test_OutdoorHeatPumpWaterHeater"
        print("  Updated  PlantEquipmentList: DHW Plant Equipment_unit1")

    # 3c. ZoneHVAC:EquipmentList:
    #     - swap HPWH type/name
    #     - remove ZoneExhaust entry (truncate to 2 equipment)
    eql = get_named(idf, "ZoneHVAC:EquipmentList", "ZoneEquipment_unit1")
    if eql:
        eql.Zone_Equipment_2_Object_Type = "WaterHeater:HeatPump:PumpedCondenser"
        eql.Zone_Equipment_2_Name        = "test_OutdoorHeatPumpWaterHeater"
        # Remove Zone Equipment 3 fields (Fan:ZoneExhaust) by blanking them
        for field in [
            "Zone_Equipment_3_Object_Type", "Zone_Equipment_3_Name",
            "Zone_Equipment_3_Cooling_Sequence",
            "Zone_Equipment_3_Heating_or_No-Load_Sequence",
            "Zone_Equipment_3_Sequential_Cooling_Fraction_Schedule_Name",
            "Zone_Equipment_3_Sequential_Heating_Fraction_Schedule_Name",
        ]:
            try:
                setattr(eql, field, "")
            except Exception:
                pass
        print("  Updated  ZoneHVAC:EquipmentList: ZoneEquipment_unit1")

    # 3d. ZoneHVAC:EquipmentConnections:
    #     - inlet node → test_Zone1Inlets (matches target NodeList)
    #     - exhaust node → blank (no ZoneExhaust fan)
    eqc = get_named(idf, "ZoneHVAC:EquipmentConnections", "living_unit1")
    if eqc:
        eqc.Zone_Air_Inlet_Node_or_NodeList_Name   = "test_Zone1Inlets"
        eqc.Zone_Air_Exhaust_Node_or_NodeList_Name = ""
        print("  Updated  ZoneHVAC:EquipmentConnections: living_unit1")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 4 — Transplant ASIHP objects from target
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 4: Transplanting ASIHP objects from target...")

    transplant_types = [
        # Singletons / global settings
        "HeatBalanceAlgorithm",
        "Site:GroundTemperature:BuildingSurface",
        # Schedules needed by ASIHP/HPWH
        ("Schedule:Compact", [
            "PlantHPWHSch", "HPWHTempSch", "OAFractionSched",
            "OutdoorAirAvailSched", "Hot Water Setpoint Temp Schedule",
            "Hot Water Demand Schedule",
        ]),
        ("Schedule:Constant", None),   # all 16 — they don't exist in original
        # HPWH outdoor fan
        ("Fan:OnOff", ["HPWHOutdoorFan"]),
        # Variable-speed coils
        "Coil:Cooling:DX:VariableSpeed",
        "Coil:Heating:DX:VariableSpeed",
        "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed",
        "CoilSystem:IntegratedHeatPump:AirSource",
        # New air loop
        ("AirLoopHVAC:UnitaryHeatPump:AirToAir", ["DXAC Heat Pump 1"]),
        "Controller:OutdoorAir",
        "AirLoopHVAC:ControllerList",
        ("AirLoopHVAC", ["Typical Terminal Reheat 1"]),
        "AirLoopHVAC:OutdoorAirSystem:EquipmentList",
        "AirLoopHVAC:OutdoorAirSystem",
        "OutdoorAir:Mixer",
        "AirLoopHVAC:ZoneSplitter",
        "AirLoopHVAC:SupplyPath",
        "AirLoopHVAC:ZoneMixer",
        "AirLoopHVAC:ReturnPath",
        ("Branch", ["test_Air Loop Main Branch_unit1"]),
        ("BranchList", ["test_Air Loop Branches"]),
        # Availability managers
        "AvailabilityManager:Scheduled",
        "AvailabilityManagerAssignmentList",
        # Nodes
        ("NodeList", ["test_OutsideAirInletNodes", "test_Zone1Inlets"]),
        ("OutdoorAir:Node", [
            "test_HPWHOutdoorTank OA Node",
            "test_HPOUTDOORAIRINLETNODE",
            "test_HPOutdoorAirOutletNode",
        ]),
        "OutdoorAir:NodeList",
        # DHW equipment
        "WaterHeater:Mixed",
        "WaterHeater:HeatPump:PumpedCondenser",
        # Performance curves
        ("Curve:Quadratic",   ["HPWHPLFFPLR"]),
        ("Curve:Biquadratic", ["HPACHeatCapFT", "HPACHeatEIRFT"]),
    ]

    for entry in transplant_types:
        if isinstance(entry, str):
            obj_type, only_names = entry, None
        else:
            obj_type, only_names = entry

        n = transplant_all(src, idf, obj_type, only_names)
        label = obj_type + (f" {only_names}" if only_names else " (all)")
        print(f"  Copied {n:2d}  {label}")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 5 — Sizing:System: re-add from original with updated airloop name
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 5: Re-adding Sizing:System with new air loop name...")
    # The original Sizing:System was removed in Step 2.
    # Recreate it using eppy newidfobject — copy all values, change Name.
    # Eppy field name for "AirLoop Name" in Sizing:System is "AirLoop_Name"
    idf_orig = IDF(original_path)   # re-read original to get the removed object
    ss_orig = None
    for obj in idf_orig.idfobjects["SIZING:SYSTEM"]:
        if obj.AirLoop_Name.upper() == "CENTRAL SYSTEM_UNIT1":
            ss_orig = obj
            break

    if ss_orig:
        new_ss = idf.newidfobject("Sizing:System")
        # Copy every field
        for field in ss_orig.fieldnames:
            try:
                setattr(new_ss, field, getattr(ss_orig, field))
            except Exception:
                pass
        new_ss.AirLoop_Name = "Typical Terminal Reheat 1"
        print("  Added    Sizing:System → Typical Terminal Reheat 1")
    else:
        print("  WARNING: Sizing:System not found in original")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 6 — DHW demand-side bypass pipe
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 6: Adding DHW demand-side bypass pipe...")

    BYPASS_PIPE        = "DHW Bypass Pipe_unit1"
    BYPASS_BRANCH      = "DHW Bypass Branch_unit1"
    BYPASS_PIPE_INLET  = "DHW Bypass Pipe Inlet Node_unit1"
    BYPASS_PIPE_OUTLET = "DHW Bypass Pipe Outlet Node_unit1"
    DHW_OUTLET_BRANCH  = "Mains Makeup Branch_unit1"

    # Pipe:Adiabatic
    pipe = idf.newidfobject("Pipe:Adiabatic")
    pipe.Name             = BYPASS_PIPE
    pipe.Inlet_Node_Name  = BYPASS_PIPE_INLET
    pipe.Outlet_Node_Name = BYPASS_PIPE_OUTLET
    print(f"  Added    Pipe:Adiabatic: {BYPASS_PIPE}")

    # Branch
    bp_branch = idf.newidfobject("Branch")
    bp_branch.Name                        = BYPASS_BRANCH
    bp_branch.Component_1_Object_Type     = "Pipe:Adiabatic"
    bp_branch.Component_1_Name            = BYPASS_PIPE
    bp_branch.Component_1_Inlet_Node_Name = BYPASS_PIPE_INLET
    bp_branch.Component_1_Outlet_Node_Name= BYPASS_PIPE_OUTLET
    print(f"  Added    Branch: {BYPASS_BRANCH}")

    # BranchList — insert bypass BEFORE the outlet branch (Mains Makeup)
    bl = get_named(idf, "BranchList", "DHW Demand Branches_unit1")
    if bl:
        # Find the outlet branch field and shift it one position right
        fields = [f for f in bl.fieldnames if f.startswith("Branch_")]
        # Collect current values
        values = [getattr(bl, f) for f in fields]
        # Find position of Mains Makeup (outlet — must stay last)
        outlet_idx = next(
            (i for i, v in enumerate(values) if DHW_OUTLET_BRANCH.upper() in v.upper()),
            len(values) - 1
        )
        # Insert bypass before outlet
        values.insert(outlet_idx, BYPASS_BRANCH)
        # Write back (eppy may have extra blank fields we can use)
        for idx, field in enumerate(fields):
            if idx < len(values):
                setattr(bl, field, values[idx])
            else:
                setattr(bl, field, "")
        print(f"  Updated  BranchList: DHW Demand Branches_unit1 (bypass before outlet)")

    # Connector:Splitter — add bypass as outlet branch
    splitter = get_named(idf, "Connector:Splitter", "DHW Demand Splitter_unit1")
    if splitter:
        fields = [f for f in splitter.fieldnames if "Outlet_Branch" in f]
        values = [getattr(splitter, f) for f in fields]
        # Find first empty slot
        placed = False
        for field in fields:
            if not getattr(splitter, field, "").strip():
                setattr(splitter, field, BYPASS_BRANCH)
                placed = True
                break
        if not placed:
            # Use newidfobject approach isn't possible for connectors — 
            # eppy should have enough spare fields; warn if not
            print("  WARNING: Splitter has no empty outlet branch field")
        else:
            print(f"  Updated  Connector:Splitter: DHW Demand Splitter_unit1")

    # Connector:Mixer — add bypass as inlet branch
    mixer = get_named(idf, "Connector:Mixer", "DHW Demand Mixer_unit1")
    if mixer:
        fields = [f for f in mixer.fieldnames if "Inlet_Branch" in f]
        placed = False
        for field in fields:
            if not getattr(mixer, field, "").strip():
                setattr(mixer, field, BYPASS_BRANCH)
                placed = True
                break
        if not placed:
            print("  WARNING: Mixer has no empty inlet branch field")
        else:
            print(f"  Updated  Connector:Mixer: DHW Demand Mixer_unit1")

    # ═══════════════════════════════════════════════════════════════════
    # STEP 7 — Stability patches
    # ═══════════════════════════════════════════════════════════════════
    print("\nStep 7: Applying stability patches...")

    # 7a. HPWH min inlet air temperature → blank
    hpwh = get_named(idf, "WaterHeater:HeatPump:PumpedCondenser",
                     "test_OutdoorHeatPumpWaterHeater")
    if hpwh:
        hpwh.Minimum_Inlet_Air_Temperature_for_Compressor_Operation = ""
        print("  Patched  HPWH min inlet air temp → blank")

    # 7b. Tank Element Control Logic → Simultaneous
    #     (prevents backup heater lockout when ASIHP is in SH mode)
    if hpwh:
        hpwh.Tank_Element_Control_Logic = "Simultaneous"
        print("  Patched  HPWH Tank Element Control Logic → Simultaneous")

    # 7c. Performance curve minimum output → 0.0
    #     Prevents capacity/COP curves from going negative at cold outdoor temps,
    #     which causes runaway node temperatures and fatal VS compressor crash.
    for curve_name in ["HPWHHeatingCapFTemp", "HPWHHeatingCOPFTemp"]:
        curve = get_named(idf, "Curve:Biquadratic", curve_name)
        if curve:
            curve.Minimum_Curve_Output = 0.0
            print(f"  Patched  Curve:Biquadratic {curve_name} min output → 0.0")

    # ═══════════════════════════════════════════════════════════════════
    # SAVE
    # ═══════════════════════════════════════════════════════════════════
    print(f"\nSaving → {output_path}")
    idf.saveas(output_path)
    lines = sum(1 for _ in open(output_path))
    size  = os.path.getsize(output_path) / 1024
    print(f"Done: {lines:,} lines, {size:.1f} KB")


# ═════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Convert HP IDF → ASIHP IDF using Eppy")
    parser.add_argument("--original", required=True,
                        help="Original air-to-air HP IDF")
    parser.add_argument("--target",   required=True,
                        help="Reference ASIHP target IDF")
    parser.add_argument("--idd",      required=True,
                        help="EnergyPlus IDD file (Energy+.idd)")
    parser.add_argument("--output",   required=True,
                        help="Output path for converted IDF")
    args = parser.parse_args()

    for p in [args.original, args.target, args.idd]:
        if not os.path.isfile(p):
            sys.exit(f"ERROR: file not found: {p}")

    convert(args.original, args.target, args.idd, args.output)


if __name__ == "__main__":
    main()
