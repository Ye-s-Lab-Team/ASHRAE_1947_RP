import re
from eppy.modeleditor import IDF

# paths and filenames
IDD_FILE   = r""
INPUT_IDF  = r""
OUTPUT_IDF = r""

IDF.setiddname(IDD_FILE)
idf = IDF(INPUT_IDF)
print("✓ IDF loaded")

AHU_LIST = ["bot", "mid", "top"]

# helper: curve builders
def _names(obj_type):
    return {c.Name for c in idf.idfobjects[obj_type]}

def biq(name, c1, c2, c3, c4, c5, c6, xmin, xmax, ymin, ymax):
    if name in _names("CURVE:BIQUADRATIC"):
        return
    c = idf.newidfobject("CURVE:BIQUADRATIC")
    c.Name = name
    c.Coefficient1_Constant = c1;  c.Coefficient2_x  = c2;  c.Coefficient3_x2 = c3
    c.Coefficient4_y        = c4;  c.Coefficient5_y2 = c5;  c.Coefficient6_xy = c6
    c.Minimum_Value_of_x = xmin;   c.Maximum_Value_of_x = xmax
    c.Minimum_Value_of_y = ymin;   c.Maximum_Value_of_y = ymax
    print(f"  + curve {name}")

def cub(name, c1, c2, c3, c4, xmin, xmax):
    if name in _names("CURVE:CUBIC"):
        return
    c = idf.newidfobject("CURVE:CUBIC")
    c.Name = name
    c.Coefficient1_Constant = c1;  c.Coefficient2_x  = c2
    c.Coefficient3_x2       = c3;  c.Coefficient4_x3 = c4
    c.Minimum_Value_of_x = xmin;   c.Maximum_Value_of_x = xmax
    print(f"  + curve {name}")

def quad(name, c1, c2, c3, xmin, xmax):
    if name in _names("CURVE:QUADRATIC"):
        return
    c = idf.newidfobject("CURVE:QUADRATIC")
    c.Name = name
    c.Coefficient1_Constant = c1;  c.Coefficient2_x = c2;  c.Coefficient3_x2 = c3
    c.Minimum_Value_of_x = xmin;   c.Maximum_Value_of_x = xmax
    print(f"  + curve {name}")


# STEP 1 – Performance curves
print("\nStep 1: Performance curves")

biq("ASHP_HTG_CapFT",
    0.876825, -0.002955, -0.000058, 0.025335, 0.000196, -0.000043,
    xmin=5.0, xmax=24.0, ymin=-20.0, ymax=20.0)          # [FIX-4] was 15.0

biq("ASHP_HTG_EIRFT",
    0.704658,  0.008767,  0.000625, -0.009037, 0.000738, -0.001025,
    xmin=5.0, xmax=24.0, ymin=-20.0, ymax=20.0)           # [FIX-4] was 15.0

cub("ASHP_HTG_CapFF", 0.694045465, 0.474207981, -0.180783882, 0.012530446, 0.5, 1.5)
cub("ASHP_HTG_EIRFF", 1.570774717, -0.914152018, 0.036729136, 0.306648166, 0.5, 1.5)
quad("ASHP_HTG_PLF",  0.85, 0.15, 0.0, 0.0, 1.0)

biq("ASHP_HTG_DefrostEIRFT",
    1.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    xmin=5.0, xmax=24.0, ymin=-20.0, ymax=20.0)


# STEP 2 – OutdoorAir:Node
print("\nStep 2: OutdoorAir:Node (CLG condenser only)")
existing_oa = {n.Name for n in idf.idfobjects["OUTDOORAIR:NODE"]}
for ahu in AHU_LIST:
    nm = f"PACU_VAV_{ahu} ASHP CLG Condenser Inlet Node"
    if nm not in existing_oa:
        n = idf.newidfobject("OUTDOORAIR:NODE")
        n.Name = nm
        print(f"  + {nm}")


# STEP 3 – Remove original Coil:Heating:Fuel
print("\nStep 3: Remove Coil:Heating:Fuel")
for ahu in AHU_LIST:
    nm = f"PACU_VAV_{ahu} Heating Coil"
    matches = [c for c in idf.idfobjects["COIL:HEATING:FUEL"] if c.Name == nm]
    if matches:
        idf.removeidfobject(matches[0])
        print(f"  - {nm}")


# STEP 4 – Remove CoilSystem:Cooling:DX wrappers
print("\nStep 4: Remove CoilSystem:Cooling:DX wrappers")
for ahu in AHU_LIST:
    nm = f"PACU_VAV_{ahu} Cooling Coil"
    matches = [c for c in idf.idfobjects["COILSYSTEM:COOLING:DX"] if c.Name == nm]
    if matches:
        idf.removeidfobject(matches[0])
        print(f"  - CoilSystem: {nm}")


# STEP 4b – Remove orphaned inner Coil:Cooling:DX:TwoSpeed objects
print("\nStep 4b: Remove orphaned Coil:Cooling:DX:TwoSpeed")
for ahu in AHU_LIST:
    nm = f"PACU_VAV_{ahu} Cooling Coil"
    matches = [c for c in idf.idfobjects["COIL:COOLING:DX:TWOSPEED"] if c.Name == nm]
    if matches:
        idf.removeidfobject(matches[0])
        print(f"  - TwoSpeed coil: {nm}")


# STEP 4c – Delete orphaned SetpointManager:MixedAir that targeted
print("\nStep 4c: Remove orphaned CoolC SAT Managers")
for ahu in AHU_LIST:
    nm = f"PACU_VAV_{ahu}_CoolC SAT Manager"
    matches = [s for s in idf.idfobjects["SETPOINTMANAGER:MIXEDAIR"] if s.Name == nm]
    if matches:
        idf.removeidfobject(matches[0])
        print(f"  - {nm}")


# STEP 5 – Coil:Cooling:DX:SingleSpeed  (ASHP cooling, COP=3.4)
print("\nStep 5: Coil:Cooling:DX:SingleSpeed (COP=3.4)")
for ahu in AHU_LIST:
    us_name      = f"PACU_VAV_{ahu} Unitary ASHP"
    us_inlet     = f"PACU_VAV_{ahu}_OA-PACU_VAV_{ahu}_CoolCNode"
    clg_out_node = f"{us_name} Cooling Coil Air Outlet"

    name = f"PACU_VAV_{ahu} ASHP Cooling Coil"
    c = idf.newidfobject("COIL:COOLING:DX:SINGLESPEED")
    c.Name                          = name
    c.Availability_Schedule_Name    = "Always_On"
    c.Gross_Rated_Total_Cooling_Capacity = "AUTOSIZE"
    c.Gross_Rated_Sensible_Heat_Ratio    = "AUTOSIZE"
    c.Gross_Rated_Cooling_COP            = 3.4
    c.Rated_Air_Flow_Rate                = "AUTOSIZE"
    c.Air_Inlet_Node_Name                = us_inlet
    c.Air_Outlet_Node_Name               = clg_out_node
    c.Total_Cooling_Capacity_Function_of_Temperature_Curve_Name   = "LgDXalt_CapFT"
    c.Total_Cooling_Capacity_Function_of_Flow_Fraction_Curve_Name = "LgDXalt_CapFF"
    c.Energy_Input_Ratio_Function_of_Temperature_Curve_Name       = "LgDXalt_EIRFT"
    c.Energy_Input_Ratio_Function_of_Flow_Fraction_Curve_Name     = "LgDXalt_EIRFF"
    c.Part_Load_Fraction_Correlation_Curve_Name                   = "LgDXalt_PLR"
    c.Condenser_Air_Inlet_Node_Name = f"PACU_VAV_{ahu} ASHP CLG Condenser Inlet Node"
    c.Condenser_Type                = "AirCooled"
    c.Crankcase_Heater_Capacity     = 0.0
    c.Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation = 10.0
    print(f"  + {name}")


# STEP 6 – Coil:Heating:DX:SingleSpeed  (ASHP heating, COP=3.2)
print("\nStep 6: Coil:Heating:DX:SingleSpeed (COP=3.2)")
for ahu in AHU_LIST:
    us_name      = f"PACU_VAV_{ahu} Unitary ASHP"
    clg_out_node = f"{us_name} Cooling Coil Air Outlet"
    htg_out_node = f"{us_name} Heating Coil Air Outlet"

    name = f"PACU_VAV_{ahu} ASHP Heating Coil"
    c = idf.newidfobject("COIL:HEATING:DX:SINGLESPEED")
    c.Name                          = name
    c.Availability_Schedule_Name    = "Always_On"
    c.Gross_Rated_Heating_Capacity  = "AUTOSIZE"
    c.Gross_Rated_Heating_COP       = 3.2
    c.Rated_Air_Flow_Rate           = "AUTOSIZE"
    c.Air_Inlet_Node_Name           = clg_out_node
    c.Air_Outlet_Node_Name          = htg_out_node
    c.Heating_Capacity_Function_of_Temperature_Curve_Name           = "ASHP_HTG_CapFT"
    c.Heating_Capacity_Function_of_Flow_Fraction_Curve_Name         = "ASHP_HTG_CapFF"
    c.Energy_Input_Ratio_Function_of_Temperature_Curve_Name         = "ASHP_HTG_EIRFT"
    c.Energy_Input_Ratio_Function_of_Flow_Fraction_Curve_Name       = "ASHP_HTG_EIRFF"
    c.Part_Load_Fraction_Correlation_Curve_Name                     = "ASHP_HTG_PLF"
    c.Defrost_Energy_Input_Ratio_Function_of_Temperature_Curve_Name = "ASHP_HTG_DefrostEIRFT"
    c.Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation  = -8.0
    c.Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation     =  5.0
    c.Crankcase_Heater_Capacity     = 0.0
    c.Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation = 10.0
    c.Defrost_Strategy              = "ReverseCycle"
    c.Defrost_Control               = "Timed"
    c.Defrost_Time_Period_Fraction  = 0.058333
    c.Resistive_Defrost_Heater_Capacity = "AUTOSIZE"
    print(f"  + {name}")


# STEP 7 – Coil:Heating:Electric  (backup)
print("\nStep 7: Coil:Heating:Electric (backup)")
for ahu in AHU_LIST:
    us_name      = f"PACU_VAV_{ahu} Unitary ASHP"
    htg_out_node = f"{us_name} Heating Coil Air Outlet"
    us_outlet    = f"PACU_VAV_{ahu}_HeatC-PACU_VAV_{ahu} FanNode"

    name = f"PACU_VAV_{ahu} Backup Electric Coil"
    c = idf.newidfobject("COIL:HEATING:ELECTRIC")
    c.Name                           = name
    c.Availability_Schedule_Name     = "Always_On"
    c.Efficiency                     = 1.0
    c.Nominal_Capacity               = "AUTOSIZE"
    c.Air_Inlet_Node_Name            = htg_out_node
    c.Air_Outlet_Node_Name           = us_outlet
    c.Temperature_Setpoint_Node_Name = us_outlet
    print(f"  + {name}")


# STEP 8 – AirLoopHVAC:UnitarySystem
print("\nStep 8: AirLoopHVAC:UnitarySystem")
for ahu in AHU_LIST:
    name      = f"PACU_VAV_{ahu} Unitary ASHP"
    us_inlet  = f"PACU_VAV_{ahu}_OA-PACU_VAV_{ahu}_CoolCNode"
    us_outlet = f"PACU_VAV_{ahu}_HeatC-PACU_VAV_{ahu} FanNode"

    u = idf.newidfobject("AIRLOOPHVAC:UNITARYSYSTEM")
    u.Name                        = name
    u.Control_Type                = "SetPoint"
    u.Availability_Schedule_Name  = "Always_On"
    u.Air_Inlet_Node_Name         = us_inlet
    u.Air_Outlet_Node_Name        = us_outlet

    u.Cooling_Coil_Object_Type              = "Coil:Cooling:DX:SingleSpeed"
    u.Cooling_Coil_Name                     = f"PACU_VAV_{ahu} ASHP Cooling Coil"
    u.Cooling_Supply_Air_Flow_Rate_Method   = "SupplyAirFlowRate"
    u.Cooling_Supply_Air_Flow_Rate          = "AUTOSIZE"

    u.Heating_Coil_Object_Type              = "Coil:Heating:DX:SingleSpeed"
    u.Heating_Coil_Name                     = f"PACU_VAV_{ahu} ASHP Heating Coil"
    u.Heating_Supply_Air_Flow_Rate_Method   = "SupplyAirFlowRate"
    u.Heating_Supply_Air_Flow_Rate          = "AUTOSIZE"

    u.Supplemental_Heating_Coil_Object_Type = "Coil:Heating:Electric"
    u.Supplemental_Heating_Coil_Name        = f"PACU_VAV_{ahu} Backup Electric Coil"
    u.Maximum_Supply_Air_Temperature        = 50.0
    # Backup electric only activates when OAT ≤ −8 °C (below HP compressor cutout)
    u.Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation = -8.0

    u.No_Load_Supply_Air_Flow_Rate_Method   = "SupplyAirFlowRate"
    u.No_Load_Supply_Air_Flow_Rate          = "AUTOSIZE"
    print(f"  + {name}")


# STEP 9 – SetpointManager:MixedAir for the two new DX coil outlets
print("\nStep 9: [FIX-1] SetpointManager:MixedAir for DX coil outlets")
for ahu in AHU_LIST:
    us_name      = f"PACU_VAV_{ahu} Unitary ASHP"
    clg_out_node = f"{us_name} Cooling Coil Air Outlet"
    htg_out_node = f"{us_name} Heating Coil Air Outlet"
    fan_inlet    = f"PACU_VAV_{ahu}_HeatC-PACU_VAV_{ahu} FanNode"
    supply_out   = f"PACU_VAV_{ahu} Supply Equipment Outlet Node"

    sp_clg = idf.newidfobject("SETPOINTMANAGER:MIXEDAIR")
    sp_clg.Name                           = f"PACU_VAV_{ahu}_ASHP_CoolC SAT Manager"
    sp_clg.Control_Variable               = "Temperature"
    sp_clg.Reference_Setpoint_Node_Name   = supply_out
    sp_clg.Fan_Inlet_Node_Name            = fan_inlet
    sp_clg.Fan_Outlet_Node_Name           = supply_out
    sp_clg.Setpoint_Node_or_NodeList_Name = clg_out_node
    print(f"  + {sp_clg.Name}")

    sp_htg = idf.newidfobject("SETPOINTMANAGER:MIXEDAIR")
    sp_htg.Name                           = f"PACU_VAV_{ahu}_ASHP_HeatC MixedAir Manager"
    sp_htg.Control_Variable               = "Temperature"
    sp_htg.Reference_Setpoint_Node_Name   = supply_out
    sp_htg.Fan_Inlet_Node_Name            = fan_inlet
    sp_htg.Fan_Outlet_Node_Name           = supply_out
    sp_htg.Setpoint_Node_or_NodeList_Name = htg_out_node
    print(f"  + {sp_htg.Name}")


# STEP 10 – Rewrite Branch: OA System → UnitarySystem → Fan
print("\nStep 10: Update Branch definitions")
for ahu in AHU_LIST:
    bname = f"PACU_VAV_{ahu} Air Loop Main Branch"
    matches = [b for b in idf.idfobjects["BRANCH"] if b.Name == bname]
    if not matches:
        print(f"  ! Branch not found: {bname}")
        continue
    b = matches[0]
    b.Component_2_Object_Type      = "AirLoopHVAC:UnitarySystem"
    b.Component_2_Name             = f"PACU_VAV_{ahu} Unitary ASHP"
    b.Component_2_Inlet_Node_Name  = f"PACU_VAV_{ahu}_OA-PACU_VAV_{ahu}_CoolCNode"
    b.Component_2_Outlet_Node_Name = f"PACU_VAV_{ahu}_HeatC-PACU_VAV_{ahu} FanNode"
    b.Component_3_Object_Type      = "Fan:VariableVolume"
    b.Component_3_Name             = f"PACU_VAV_{ahu} Fan"
    b.Component_3_Inlet_Node_Name  = f"PACU_VAV_{ahu}_HeatC-PACU_VAV_{ahu} FanNode"
    b.Component_3_Outlet_Node_Name = f"PACU_VAV_{ahu} Supply Equipment Outlet Node"
    b.Component_4_Object_Type      = ""
    b.Component_4_Name             = ""
    b.Component_4_Inlet_Node_Name  = ""
    b.Component_4_Outlet_Node_Name = ""
    print(f"  ✓ {bname}")


# Save
idf.saveas(OUTPUT_IDF)
print(f"\nIDF saved → {OUTPUT_IDF}")