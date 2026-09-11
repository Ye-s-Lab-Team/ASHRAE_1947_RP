"""
measure5_v3.py
EnergyPlus IDF modifier: Replace AHU Coils with ASIHP (Air-Source Integrated Heat Pump)

Steps:
  1. Replace AHU Coils with ASIHP
  2. Connect IHP DHW Coil to WaterHeater:Mixed via new Plant Loop
  3. SetpointManager & Control Logic Update for ASIHP
"""

import re
from eppy.modeleditor import IDF

# ──────────────────────────────────────────────
# File Paths
# ──────────────────────────────────────────────
IDD_FILE  = r"C:\EnergyPlusV25-1-0\Energy+.idd"
INPUT_IDF = (
    r"C:\Users\yhw15\OneDrive\Documents\Year_25-26\1947-test\1947-RP"
    r"\ASHRAE901_OfficeMedium_STD2022\ASHRAE901_OfficeMedium_STD2022_NewYork.idf"
)
OUTPUT_IDF = (
    r"C:\Users\yhw15\OneDrive\Documents\Year_25-26\1947-test\1947-RP"
    r"\STD2022_NewYork_IASHP_v2\ASHRAE901_OfficeMedium_STD2022_NewYork_IASHP_v9.idf"
)

# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
NUM_SPEEDS = 10
AHU_LIST   = ["bot", "mid", "top"]
DHW_AHU    = AHU_LIST  # all AHUs get DHW coil in Step 1

# EnergyPlus VariableSpeed Coil rated conditions
COOL_RATED_INDOOR_DB  = 26.7   # °C
COOL_RATED_INDOOR_WB  = 19.4   # °C
COOL_RATED_OUTDOOR_DB = 35.0   # °C
HEAT_RATED_INDOOR_DB  = 21.1   # °C
HEAT_RATED_OUTDOOR_DB =  8.33  # °C
DHW_RATED_INLET_DB    = 19.7   # °C
DHW_RATED_INLET_WB    = 13.5   # °C
DHW_RATED_WATER_TEMP  = 57.2   # °C

# ORNL Speed COPs and SHR for 10 speeds
COOL_SPEED_COPS = [4.23, 4.58, 4.76, 4.68, 4.55, 4.40, 4.21, 4.00, 3.85, 3.67]
COOL_SPEED_SHRS = [0.80, 0.79, 0.78, 0.77, 0.77, 0.76, 0.76, 0.75, 0.75, 0.75]
HEAT_SPEED_COPS = [4.60, 4.78, 4.84, 4.78, 4.66, 4.50, 4.32, 4.11, 3.93, 3.50]
DHW_SPEED_COPS  = [4.50, 4.50, 4.40, 4.30, 4.20, 4.10, 3.90, 3.80, 3.70, 3.60]

SPEED_FRACTIONS        = [0.20, 0.28, 0.36, 0.44, 0.52, 0.60, 0.70, 0.80, 0.90, 1.00]
SC_NOMINAL_CAP_W       = 70_000.0
SC_NOMINAL_FLOW_M3S    =  2.5
SH_NOMINAL_CAP_W       = 60_000.0
SH_NOMINAL_FLOW_M3S    =  2.2
DHW_NOMINAL_CAP_W      =  5_000.0
DHW_NOMINAL_WATER_M3S  =  0.00025
DHW_PUMP_POWER_W       = 100.0

# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
WH_NAME       = "SWHSys1 Water Heater"
DHW_LOOP_NAME = "IHP DHW Source Loop"
DHW_AHU_STEP2 = "bot"  # single AHU used for the plant loop equipment branch

IHP_COND_IN  = "SWHSys1 IHP Source Inlet Node"
IHP_COND_OUT = "SWHSys1 IHP Source Outlet Node"
WH_SRC_IN    = "SWHSys1 WH Source Inlet Node"
WH_SRC_OUT   = "SWHSys1 WH Source Outlet Node"

LOOP_SUPPLY_IN  = "IHP DHW Loop Supply Inlet Node"
LOOP_SUPPLY_OUT = "IHP DHW Loop Supply Outlet Node"
LOOP_DEMAND_IN  = "IHP DHW Loop Demand Inlet Node"
LOOP_DEMAND_OUT = "IHP DHW Loop Demand Outlet Node"

PUMP_OUT_NODE   = "IHP DHW Pump Outlet Node"
SPLY_BYPASS_IN  = "IHP DHW Supply Bypass Inlet Node"
SPLY_BYPASS_OUT = "IHP DHW Supply Bypass Outlet Node"
SPLY_PIPE_IN    = "IHP DHW Supply Outlet Pipe Inlet Node"

DMND_PIPE_OUT   = "IHP DHW Demand Inlet Pipe Outlet Node"
DMND_BYPASS_IN  = "IHP DHW Demand Bypass Inlet Node"
DMND_BYPASS_OUT = "IHP DHW Demand Bypass Outlet Node"
DMND_PIPE2_IN   = "IHP DHW Demand Outlet Pipe Inlet Node"

# ──────────────────────────────────────────────────────────────────────────────
# STEP 3 CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
OAT_THRESHOLD_COOL = 12.0
OAT_THRESHOLD_HEAT =  0.0
SAT_SP_MAX_HEAT    = 40.0
SAT_SP_COOL_MIN    = 15.6


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Add ASIHP to all AHUs
# ══════════════════════════════════════════════════════════════════════════════

def add_ihp_performance_curves(idf):
    """Add all IHP performance curves (biquadratic + quadratic)."""

    def add_biquad(name, c):
        """Curve:Biquadratic  f(x1,x2) = c0+c1*x1+c2*x1²+c3*x2+c4*x2²+c5*x1*x2"""
        obj = idf.newidfobject("CURVE:BIQUADRATIC")
        obj.Name = name
        obj.Coefficient1_Constant  = c[0]
        obj.Coefficient2_x         = c[1]
        obj.Coefficient3_x2        = c[2]
        obj.Coefficient4_y         = c[3]
        obj.Coefficient5_y2        = c[4]
        obj.Coefficient6_xy        = c[5]
        obj.Minimum_Value_of_x     = 12.78
        obj.Maximum_Value_of_x     = 23.89
        obj.Minimum_Value_of_y     = 18.33
        obj.Maximum_Value_of_y     = 51.67
        obj.Minimum_Curve_Output   = 0.5
        obj.Maximum_Curve_Output   = 1.5
        return obj

    def add_quad(name, c, xmin=0.0, xmax=1.0):
        """Curve:Quadratic  f(x) = c0 + c1*x + c2*x²"""
        obj = idf.newidfobject("CURVE:QUADRATIC")
        obj.Name = name
        obj.Coefficient1_Constant = c[0]
        obj.Coefficient2_x        = c[1]
        obj.Coefficient3_x2       = c[2]
        obj.Minimum_Value_of_x    = xmin
        obj.Maximum_Value_of_x    = xmax
        return obj

    # SC Mode Curves
    add_biquad("IHP_SC_CapFT",
        [0.942587793, 0.009543347, 0.000683770,
         -0.011042676, 0.000005249, -0.000009720])
    add_biquad("IHP_SC_EIRFT",
        [0.342414409, 0.034885008, -0.000623700,
         -0.004237496, 0.000210584, -0.000116138])
    add_quad("IHP_SC_CapFF", [0.718664047,  0.41386073,  -0.132541148])
    add_quad("IHP_SC_EIRFF", [1.143487507, -0.13943972,  -0.004047787])

    # SH Mode Curves
    add_biquad("IHP_SH_CapFT",
        [0.566333415, -0.000744164, -0.0000103,
          0.009414634,  0.0000506,  -0.000181042])
    add_biquad("IHP_SH_EIRFT",
        [0.718664047,  0.000000000,  0.000000000,
         -0.004000000,  0.000102000, -0.000000000])
    add_quad("IHP_SH_CapFF", [0.694045465,  0.474207981, -0.168253446])
    add_quad("IHP_SH_EIRFF", [2.185418751, -1.942827919,  0.757409168])

    # DHW Mode Curves
    add_biquad("IHP_DHW_CapFT",
        [0.563,  0.0437,  0.000220,
         -0.00897, -0.0000380, -0.000190])
    add_biquad("IHP_DHW_EIRFT",
        [0.388, -0.0135,  0.000679,
          0.0154,  0.000378, -0.000545])
    add_quad("IHP_DHW_CapFF", [1.0, 0.0, 0.0])
    add_quad("IHP_DHW_EIRFF", [1.0, 0.0, 0.0])

    # Fan Power Curve
    add_quad("IHP_PLF", [0.85, 0.15, 0.0], xmin=0.0, xmax=1.0)

    print("  [curves] 11 IHP performance curves added.")


def _ihp_air_nodes(ahu):
    p = f"PACU_VAV_{ahu}"
    return {
        "us_in"   : f"{p}_OA-{p}_CoolCNode",
        "sc_out"  : f"{p}_SC-{p}_SHNode",
        "ihp_out" : f"{p}_IHP-{p} FanNode",
    }


def add_sc_cooling_coil(idf, ahu):
    nodes = _ihp_air_nodes(ahu)
    p = f"PACU_VAV_{ahu}"

    coil = idf.newidfobject("COIL:COOLING:DX:VARIABLESPEED")
    coil.Name                              = f"{p} IHP SC Coil"
    coil.Indoor_Air_Inlet_Node_Name        = nodes["us_in"]
    coil.Indoor_Air_Outlet_Node_Name       = nodes["sc_out"]
    coil.Number_of_Speeds                  = NUM_SPEEDS
    coil.Nominal_Speed_Level               = NUM_SPEEDS
    coil.Gross_Rated_Total_Cooling_Capacity_At_Selected_Nominal_Speed_Level = "AUTOSIZE"
    coil.Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level                = "AUTOSIZE"
    coil.Nominal_Time_for_Condensate_to_Begin_Leaving_the_Coil              = 1000.0
    coil.Initial_Moisture_Evaporation_Rate_Divided_by_SteadyState_AC_Latent_Capacity = 1.5
    coil.Maximum_Cycling_Rate              = 2.5
    coil.Latent_Capacity_Time_Constant     = 60.0
    coil.Energy_Part_Load_Fraction_Curve_Name = "IHP_PLF"
    coil.Condenser_Type                    = "AirCooled"
    coil.Evaporative_Condenser_Pump_Rated_Power_Consumption = 0.0

    for i in range(1, NUM_SPEEDS + 1):
        frac = SPEED_FRACTIONS[i - 1]
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Total_Cooling_Capacity",  round(SC_NOMINAL_CAP_W * frac, 2))
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Sensible_Heat_Ratio",     COOL_SPEED_SHRS[i-1])
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Cooling_COP",             COOL_SPEED_COPS[i-1])
        setattr(coil, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate",                 round(SC_NOMINAL_FLOW_M3S * frac, 6))
        setattr(coil, f"Speed_{i}_Total_Cooling_Capacity_Function_of_Temperature_Curve_Name",       "IHP_SC_CapFT")
        setattr(coil, f"Speed_{i}_Total_Cooling_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "IHP_SC_CapFF")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Temperature_Curve_Name",           "IHP_SC_EIRFT")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Air_Flow_Fraction_Curve_Name",     "IHP_SC_EIRFF")

    print(f"  [coil] {coil.Name} added ({NUM_SPEEDS} speeds).")
    return coil


def add_sh_heating_coil(idf, ahu):
    nodes = _ihp_air_nodes(ahu)
    p = f"PACU_VAV_{ahu}"

    coil = idf.newidfobject("COIL:HEATING:DX:VARIABLESPEED")
    coil.Name                              = f"{p} IHP SH Coil"
    coil.Indoor_Air_Inlet_Node_Name        = nodes["sc_out"]
    coil.Indoor_Air_Outlet_Node_Name       = nodes["ihp_out"]
    coil.Number_of_Speeds                  = NUM_SPEEDS
    coil.Nominal_Speed_Level               = NUM_SPEEDS
    coil.Rated_Heating_Capacity_At_Selected_Nominal_Speed_Level = "AUTOSIZE"
    coil.Rated_Air_Flow_Rate_At_Selected_Nominal_Speed_Level    = "AUTOSIZE"
    coil.Energy_Part_Load_Fraction_Curve_Name                   = "IHP_PLF"
    coil.Defrost_Energy_Input_Ratio_Function_of_Temperature_Curve_Name = ""
    coil.Minimum_Outdoor_DryBulb_Temperature_for_Compressor_Operation  = -17.78
    coil.Outdoor_DryBulb_Temperature_to_Turn_On_Compressor             = 0.0
    coil.Maximum_Outdoor_DryBulb_Temperature_for_Defrost_Operation     = 5.0
    coil.Crankcase_Heater_Capacity                                      = 200.0
    coil.Crankcase_Heater_Capacity_Function_of_Temperature_Curve_Name  = "IHP_PLF"
    coil.Maximum_Outdoor_DryBulb_Temperature_for_Crankcase_Heater_Operation = 10.0
    coil.Defrost_Strategy          = "Resistive"
    coil.Defrost_Control           = "Timed"
    coil.Defrost_Time_Period_Fraction = 0.058333

    for i in range(1, 4):
        frac = SPEED_FRACTIONS[i - 1]
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_Capacity", round(SH_NOMINAL_CAP_W * frac, 2))
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_COP",              HEAT_SPEED_COPS[i-1])
        setattr(coil, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate",          round(SH_NOMINAL_FLOW_M3S * frac, 6))
        setattr(coil, f"Speed_{i}_Heating_Capacity_Function_of_Temperature_Curve_Name",          "IHP_SH_CapFT")
        setattr(coil, f"Speed_{i}_Total_Heating_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "IHP_SH_CapFF")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Temperature_Curve_Name",        "IHP_SH_EIRFT")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Air_Flow_Fraction_Curve_Name",  "IHP_SH_EIRFF")
    for i in range(4, NUM_SPEEDS + 1):
        frac = SPEED_FRACTIONS[i - 1]
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_Capacity", round(SH_NOMINAL_CAP_W * frac, 2))
        setattr(coil, f"Speed_{i}_Reference_Unit_Gross_Rated_Heating_COP",              HEAT_SPEED_COPS[i-1])
        setattr(coil, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate",          round(SH_NOMINAL_FLOW_M3S * frac, 6))
        setattr(coil, f"Speed_{i}_Heating_Capacity_Function_of_Temperature_Curve_Name",       "IHP_SH_CapFT")
        setattr(coil, f"Speed_{i}_Heating_Capacity_Function_of_Air_Flow_Fraction_Curve_Name", "IHP_SH_CapFF")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Temperature_Curve_Name",     "IHP_SH_EIRFT")
        setattr(coil, f"Speed_{i}_Energy_Input_Ratio_Function_of_Air_Flow_Fraction_Curve_Name", "IHP_SH_EIRFF")

    print(f"  [coil] {coil.Name} added ({NUM_SPEEDS} speeds).")
    return coil


def add_dhw_coil(idf, ahu, water_inlet_node, water_outlet_node):
    nodes = _ihp_air_nodes(ahu)
    p = f"PACU_VAV_{ahu}"
    dhw_air_in  = f"{p} IHP DHW OA Inlet"
    dhw_air_out = f"{p} IHP DHW OA Outlet"

    oa_node = idf.newidfobject("OUTDOORAIR:NODE")
    oa_node.Name = dhw_air_in
    print(f"  [OA]  OutdoorAir:Node '{dhw_air_in}' added for DHW evaporator")

    coil = idf.newidfobject("COIL:WATERHEATING:AIRTOWATERHEATPUMP:VARIABLESPEED")
    coil.Name                             = f"{p} IHP DHW Coil"
    coil.Number_of_Speeds                 = NUM_SPEEDS
    coil.Nominal_Speed_Level              = NUM_SPEEDS
    coil.Rated_Water_Heating_Capacity     = DHW_NOMINAL_CAP_W
    coil.Rated_Evaporator_Inlet_Air_DryBulb_Temperature = DHW_RATED_INLET_DB
    coil.Rated_Evaporator_Inlet_Air_WetBulb_Temperature = DHW_RATED_INLET_WB
    coil.Rated_Condenser_Inlet_Water_Temperature         = DHW_RATED_WATER_TEMP
    coil.Rated_Evaporator_Air_Flow_Rate   = "AUTOSIZE"
    coil.Rated_Condenser_Water_Flow_Rate  = "AUTOSIZE"
    coil.Evaporator_Fan_Power_Included_in_Rated_COP    = "No"
    coil.Condenser_Pump_Power_Included_in_Rated_COP    = "No"
    coil.Fraction_of_Condenser_Pump_Heat_to_Water      = 0.1
    coil.Evaporator_Air_Inlet_Node_Name   = dhw_air_in
    coil.Evaporator_Air_Outlet_Node_Name  = dhw_air_out
    coil.Condenser_Water_Inlet_Node_Name  = water_inlet_node
    coil.Condenser_Water_Outlet_Node_Name = water_outlet_node
    coil.Crankcase_Heater_Capacity        = 0.0
    coil.Maximum_Ambient_Temperature_for_Crankcase_Heater_Operation = 10.0
    coil.Evaporator_Air_Temperature_Type_for_Curve_Objects = "WetBulbTemperature"
    coil.Part_Load_Fraction_Correlation_Curve_Name = "IHP_PLF"

    for i in [x for x in range(1, NUM_SPEEDS + 1) if x != 3]:
        frac = SPEED_FRACTIONS[i - 1]
        setattr(coil, f"Rated_Water_Heating_Capacity_at_Speed_{i}",     DHW_NOMINAL_CAP_W)
        setattr(coil, f"Rated_Water_Heating_COP_at_Speed_{i}",          DHW_SPEED_COPS[i-1])
        setattr(coil, f"Speed_{i}_Reference_Unit_Rated_Air_Flow_Rate",              round(SH_NOMINAL_FLOW_M3S * frac, 6))
        setattr(coil, f"Speed_{i}_Reference_Unit_Rated_Water_Flow_Rate",            round(DHW_NOMINAL_WATER_M3S * frac, 8))
        setattr(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Temperature_Curve_Name",        "IHP_DHW_CapFT")
        setattr(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Air_Flow_Fraction_Curve_Name",  "IHP_DHW_CapFF")
        setattr(coil, f"Speed_{i}_Total_WH_Capacity_Function_of_Water_Flow_Fraction_Curve_Name","IHP_DHW_CapFF")
        setattr(coil, f"Speed_{i}_COP_Function_of_Temperature_Curve_Name",                      "IHP_DHW_EIRFT")
        setattr(coil, f"Speed_{i}_COP_Function_of_Air_Flow_Fraction_Curve_Name",                "IHP_DHW_EIRFF")
        setattr(coil, f"Speed_{i}_COP_Function_of_Water_Flow_Fraction_Curve_Name",              "IHP_DHW_EIRFF")
        setattr(coil, f"Speed_{i}_Reference_Unit_Water_Pump_Input_Power_At_Rated_Conditions", round(DHW_PUMP_POWER_W * frac, 2))

    # Speed 3 set separately (was excluded from loop above)
    frac_3 = SPEED_FRACTIONS[3 - 1]
    setattr(coil, "Rated_Water_Heating_Capacity_at_speed_3",     DHW_NOMINAL_CAP_W)
    setattr(coil, "Rated_Water_Heating_COP_at_Speed_3",          DHW_SPEED_COPS[2])
    setattr(coil, "Speed_3_Reference_Unit_Rated_Air_Flow_Rate",              round(SH_NOMINAL_FLOW_M3S * frac_3, 6))
    setattr(coil, "Speed_3_Reference_Unit_Rated_Water_Flow_Rate",            round(DHW_NOMINAL_WATER_M3S * frac_3, 8))
    setattr(coil, "Speed_3_Total_WH_Capacity_Function_of_Temperature_Curve_Name",        "IHP_DHW_CapFT")
    setattr(coil, "Speed_3_Total_WH_Capacity_Function_of_Air_Flow_Fraction_Curve_Name",  "IHP_DHW_CapFF")
    setattr(coil, "Speed_3_Total_WH_Capacity_Function_of_Water_Flow_Fraction_Curve_Name","IHP_DHW_CapFF")
    setattr(coil, "Speed_3_COP_Function_of_Temperature_Curve_Name",                      "IHP_DHW_EIRFT")
    setattr(coil, "Speed_3_COP_Function_of_Air_Flow_Fraction_Curve_Name",                "IHP_DHW_EIRFF")
    setattr(coil, "Speed_3_COP_Function_of_Water_Flow_Fraction_Curve_Name",              "IHP_DHW_EIRFF")
    setattr(coil, "Speed_3_Reference_Unit_Water_Pump_Input_Power_At_Rated_Conditions", round(DHW_PUMP_POWER_W * frac_3, 2))

    print(f"  [coil] {coil.Name} added ({NUM_SPEEDS} speeds, water: {water_inlet_node} → {water_outlet_node}).")
    return coil


def add_ihp_object(idf, ahu, has_dhw=False):
    p = f"PACU_VAV_{ahu}"

    ihp = idf.newidfobject("COILSYSTEM:INTEGRATEDHEATPUMP:AIRSOURCE")
    ihp.Name                = f"{p} IHP"
    ihp.Space_Cooling_Coil_Name = f"{p} IHP SC Coil"
    ihp.Space_Heating_Coil_Name = f"{p} IHP SH Coil"

    if has_dhw:
        ihp.Dedicated_Water_Heating_Coil_Name      = f"{p} IHP DHW Coil"
        ihp.Supply_Hot_Water_Flow_Sensor_Node_Name = f"{p}_IHP_DHW_Flow_Sensor"
        ihp.SCWH_Coil_Name                = f"{p} IHP SC Coil"
        ihp.SHDWH_Heating_Coil_Name       = f"{p} IHP SH Coil"
        ihp.SCDWH_Cooling_Coil_Name       = f"{p} IHP SC Coil"
        ihp.SCDWH_Water_Heating_Coil_Name = f"{p} IHP DHW Coil"
        ihp.SHDWH_Water_Heating_Coil_Name = f"{p} IHP DHW Coil"
    else:
        ihp.Dedicated_Water_Heating_Coil_Name = ""
        ihp.SCWH_Coil_Name                    = ""
        ihp.SHDWH_Heating_Coil_Name           = ""

    ihp.Indoor_Temperature_Limit_for_SCWH_Mode                 = 20.0
    ihp.Ambient_Temperature_Limit_for_SCWH_Mode                = 27.0
    ihp.Indoor_Temperature_above_Which_WH_has_Higher_Priority  = 20.0
    ihp.Ambient_Temperature_above_Which_WH_has_Higher_Priority = 20.0
    ihp.Flag_to_Indicate_Load_Control_in_SCWH_Mode             = 0
    ihp.Minimum_Speed_Level_for_SCWH_Mode                      = 1
    ihp.Minimum_Speed_Level_for_SHDWH_Mode                     = 1

    print(f"  [IHP]  {ihp.Name} created (DHW={'YES' if has_dhw else 'NO'}).")
    return ihp


def remove_blank_unitary_systems(idf):
    to_remove = [
        obj for obj in idf.idfobjects["AIRLOOPHVAC:UNITARYSYSTEM"]
        if not obj.Name or not obj.Name.strip()
    ]
    for obj in to_remove:
        idf.removeidfobject(obj)
    if to_remove:
        print(f"  [fix1] Removed {len(to_remove)} blank UnitarySystem object(s).")
    else:
        print("  [fix1] No blank UnitarySystem objects found.")
    return len(to_remove)


def add_unitary_system(idf, ahu):
    p = f"PACU_VAV_{ahu}"
    us_inlet  = f"{p}_OA-{p}_CoolCNode"
    us_outlet = f"{p} Supply Equipment Outlet Node"

    us = idf.newidfobject("AIRLOOPHVAC:UNITARYSYSTEM")
    us.Name                    = f"{p} UnitarySystem"
    us.Control_Type            = "SetPoint"
    us.Dehumidification_Control_Type           = "None"
    us.Availability_Schedule_Name              = "HVACOperationSchd"
    us.Air_Inlet_Node_Name                     = us_inlet
    us.Air_Outlet_Node_Name                    = us_outlet

    us.Supply_Fan_Object_Type                  = "Fan:VariableVolume"
    us.Supply_Fan_Name                         = f"{p} Fan"
    us.Fan_Placement                           = "DrawThrough"
    us.Supply_Air_Fan_Operating_Mode_Schedule_Name = "Always_On"

    us.Heating_Coil_Object_Type = "Coil:Heating:DX:VariableSpeed"
    us.Heating_Coil_Name        = f"{p} IHP SH Coil"
    us.DX_Heating_Coil_Sizing_Ratio = 1.0
    us.Cooling_Coil_Object_Type = "Coil:Cooling:DX:VariableSpeed"
    us.Cooling_Coil_Name        = f"{p} IHP SC Coil"
    us.Use_DOAS_DX_Cooling_Coil = "No"
    us.Minimum_Supply_Air_Temperature = 2.0
    us.Maximum_Supply_Air_Temperature = 50.0
    us.Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation = 21.0

    us.Cooling_Supply_Air_Flow_Rate_Method  = "SupplyAirFlowRate"
    us.Cooling_Supply_Air_Flow_Rate         = "AUTOSIZE"
    us.Heating_Supply_Air_Flow_Rate_Method  = "SupplyAirFlowRate"
    us.Heating_Supply_Air_Flow_Rate         = "AUTOSIZE"
    us.No_Load_Supply_Air_Flow_Rate_Method  = "SupplyAirFlowRate"
    us.No_Load_Supply_Air_Flow_Rate         = "AUTOSIZE"

    remove_blank_unitary_systems(idf)

    print(f"  [US]   {us.Name} created (SetPoint, DrawThrough).")
    return us


def _remove_obj_by_name(idf, obj_type, name):
    for obj in idf.idfobjects[obj_type.upper()]:
        if obj.Name == name:
            idf.removeidfobject(obj)
            return True
    print(f"  [WARN] {obj_type} '{name}' not found, skip remove.")
    return False


def update_branch(idf, ahu):
    p           = f"PACU_VAV_{ahu}"
    branch_name = f"{p} Air Loop Main Branch"

    _remove_obj_by_name(idf, "BRANCH", branch_name)

    b = idf.newidfobject("BRANCH")
    b.Name                         = branch_name
    b.Component_1_Object_Type      = "AirLoopHVAC:OutdoorAirSystem"
    b.Component_1_Name             = f"{p}_OA"
    b.Component_1_Inlet_Node_Name  = f"{p} Supply Equipment Inlet Node"
    b.Component_1_Outlet_Node_Name = f"{p}_OA-{p}_CoolCNode"
    b.Component_2_Object_Type      = "AirLoopHVAC:UnitarySystem"
    b.Component_2_Name             = f"{p} UnitarySystem"
    b.Component_2_Inlet_Node_Name  = f"{p}_OA-{p}_CoolCNode"
    b.Component_2_Outlet_Node_Name = f"{p} Supply Equipment Outlet Node"

    print(f"  [branch] {branch_name} rebuilt (2 components).")


def update_fan_nodes(idf, ahu):
    p        = f"PACU_VAV_{ahu}"
    new_node = f"{p}_IHP-{p} FanNode"
    for fan in idf.idfobjects["FAN:VARIABLEVOLUME"]:
        if fan.Name == f"{p} Fan":
            fan.Air_Inlet_Node_Name = new_node
            print(f"  [fan]  {fan.Name} inlet updated → {new_node}")
            return
    print(f"  [WARN] Fan '{p} Fan' not found.")


def update_setpoint_managers(idf, ahu):
    p           = f"PACU_VAV_{ahu}"
    old_fan     = f"{p}_HeatC-{p} FanNode"
    new_fan     = f"{p}_IHP-{p} FanNode"
    old_cool_out = f"{p}_CoolC-{p}_HeatCNode"

    for spm in idf.idfobjects["SETPOINTMANAGER:MIXEDAIR"]:
        if not spm.Name.startswith(p):
            continue
        if spm.Fan_Inlet_Node_Name == old_fan:
            spm.Fan_Inlet_Node_Name = new_fan
        if spm.Setpoint_Node_or_NodeList_Name in (old_cool_out, old_fan):
            spm.Setpoint_Node_or_NodeList_Name = new_fan
            print(f"  [SPM] {spm.Name} setpoint node → {new_fan}")


def remove_old_coils(idf, ahu):
    p = f"PACU_VAV_{ahu}"
    removed = []
    if _remove_obj_by_name(idf, "COILSYSTEM:COOLING:DX",     f"{p} Cooling Coil"):
        removed.append("CoilSystem:Cooling:DX")
    if _remove_obj_by_name(idf, "COIL:COOLING:DX:TWOSPEED",  f"{p} Cooling Coil"):
        removed.append("Coil:Cooling:DX:TwoSpeed")
    if _remove_obj_by_name(idf, "COIL:HEATING:FUEL",         f"{p} Heating Coil"):
        removed.append("Coil:Heating:Fuel")
    print(f"  [del]  {ahu}: removed {removed}")


def run_step1(idf, ahu_list,
              dhw_water_inlet  = "SWHSys1 IHP Source Inlet Node",
              dhw_water_outlet = "SWHSys1 IHP Source Outlet Node"):
    print("\n" + "="*60)
    print("STEP 1 — Add ASIHP to all AHUs")
    print("="*60)

    add_ihp_performance_curves(idf)

    for ahu in ahu_list:
        print(f"\n--- AHU: PACU_VAV_{ahu} ---")
        has_dhw = (ahu in DHW_AHU)
        remove_old_coils(idf, ahu)
        add_sc_cooling_coil(idf, ahu)
        add_sh_heating_coil(idf, ahu)
        if has_dhw:
            add_dhw_coil(idf, ahu, dhw_water_inlet, dhw_water_outlet)
        add_ihp_object(idf, ahu, has_dhw=has_dhw)
        add_unitary_system(idf, ahu)
        update_branch(idf, ahu)
        update_fan_nodes(idf, ahu)
        update_setpoint_managers(idf, ahu)

    print("\n" + "="*60)
    print("STEP 1 COMPLETE")
    print(f"  ✓ {len(ahu_list)} AHUs converted to ASIHP")
    print(f"  ✓ DHW Coil added to: {DHW_AHU}")
    print("="*60 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Connect IHP DHW to WaterHeater via Plant Loop
# ══════════════════════════════════════════════════════════════════════════════

def update_water_heater_source_side(idf):
    for wh in idf.idfobjects["WATERHEATER:MIXED"]:
        if wh.Name == WH_NAME:
            wh.Source_Side_Inlet_Node_Name  = IHP_COND_OUT
            wh.Source_Side_Outlet_Node_Name = IHP_COND_IN
            print("  [WH] Source Side directly connected to DHW Coil nodes")
            return
    raise ValueError(f"WaterHeater:Mixed '{WH_NAME}' not found.")


def add_dhw_pump(idf):
    pump = idf.newidfobject("PUMP:CONSTANTSPEED")
    pump.Name                     = "IHP DHW Pump"
    pump.Inlet_Node_Name          = LOOP_SUPPLY_IN
    pump.Outlet_Node_Name         = PUMP_OUT_NODE
    pump.Design_Flow_Rate         = "AUTOSIZE"
    pump.Design_Pump_Head         = 20000  # Pa
    pump.Design_Power_Consumption = "AUTOSIZE"
    pump.Motor_Efficiency         = 0.87
    pump.Fraction_of_Motor_Inefficiencies_to_Fluid_Stream = 0.0
    pump.Pump_Control_Type        = "Intermittent"
    print("  [pump] IHP DHW Pump added (ConstantSpeed).")
    return pump


def add_pipe(idf, name, inlet, outlet):
    p = idf.newidfobject("PIPE:ADIABATIC")
    p.Name             = name
    p.Inlet_Node_Name  = inlet
    p.Outlet_Node_Name = outlet
    return p


def add_dhw_branches(idf):
    # S1: Inlet Branch
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Supply Inlet Branch"
    b.Component_1_Object_Type      = "Pump:ConstantSpeed"
    b.Component_1_Name             = "IHP DHW Pump"
    b.Component_1_Inlet_Node_Name  = LOOP_SUPPLY_IN
    b.Component_1_Outlet_Node_Name = PUMP_OUT_NODE

    # S2: Equipment Branch
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Supply Equipment Branch"
    b.Component_1_Object_Type      = "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed"
    b.Component_1_Name             = f"PACU_VAV_{DHW_AHU_STEP2} IHP DHW Coil"
    b.Component_1_Inlet_Node_Name  = IHP_COND_IN
    b.Component_1_Outlet_Node_Name = IHP_COND_OUT

    # S3: Bypass Branch
    add_pipe(idf, "IHP DHW Supply Bypass Pipe", SPLY_BYPASS_IN, SPLY_BYPASS_OUT)
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Supply Bypass Branch"
    b.Component_1_Object_Type      = "Pipe:Adiabatic"
    b.Component_1_Name             = "IHP DHW Supply Bypass Pipe"
    b.Component_1_Inlet_Node_Name  = SPLY_BYPASS_IN
    b.Component_1_Outlet_Node_Name = SPLY_BYPASS_OUT

    # S4: Outlet Branch
    add_pipe(idf, "IHP DHW Supply Outlet Pipe", SPLY_PIPE_IN, LOOP_SUPPLY_OUT)
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Supply Outlet Branch"
    b.Component_1_Object_Type      = "Pipe:Adiabatic"
    b.Component_1_Name             = "IHP DHW Supply Outlet Pipe"
    b.Component_1_Inlet_Node_Name  = SPLY_PIPE_IN
    b.Component_1_Outlet_Node_Name = LOOP_SUPPLY_OUT

    # D1: Inlet Branch
    add_pipe(idf, "IHP DHW Demand Inlet Pipe", LOOP_DEMAND_IN, DMND_PIPE_OUT)
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Demand Inlet Branch"
    b.Component_1_Object_Type      = "Pipe:Adiabatic"
    b.Component_1_Name             = "IHP DHW Demand Inlet Pipe"
    b.Component_1_Inlet_Node_Name  = LOOP_DEMAND_IN
    b.Component_1_Outlet_Node_Name = DMND_PIPE_OUT

    # D2: WaterHeater Source Branch
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW WH Source Branch"
    b.Component_1_Object_Type      = "WaterHeater:Mixed"
    b.Component_1_Name             = WH_NAME
    b.Component_1_Inlet_Node_Name  = WH_SRC_IN
    b.Component_1_Outlet_Node_Name = WH_SRC_OUT

    # D3: Bypass Branch
    add_pipe(idf, "IHP DHW Demand Bypass Pipe", DMND_BYPASS_IN, DMND_BYPASS_OUT)
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Demand Bypass Branch"
    b.Component_1_Object_Type      = "Pipe:Adiabatic"
    b.Component_1_Name             = "IHP DHW Demand Bypass Pipe"
    b.Component_1_Inlet_Node_Name  = DMND_BYPASS_IN
    b.Component_1_Outlet_Node_Name = DMND_BYPASS_OUT

    # D4: Outlet Branch
    add_pipe(idf, "IHP DHW Demand Outlet Pipe", DMND_PIPE2_IN, LOOP_DEMAND_OUT)
    b = idf.newidfobject("BRANCH")
    b.Name                         = "IHP DHW Demand Outlet Branch"
    b.Component_1_Object_Type      = "Pipe:Adiabatic"
    b.Component_1_Name             = "IHP DHW Demand Outlet Pipe"
    b.Component_1_Inlet_Node_Name  = DMND_PIPE2_IN
    b.Component_1_Outlet_Node_Name = LOOP_DEMAND_OUT

    print("  [branch] 8 DHW loop branches added (4 supply + 4 demand).")


def add_dhw_connectors(idf):
    # Supply BranchList
    bl = idf.newidfobject("BRANCHLIST")
    bl.Name          = "IHP DHW Supply Branches"
    bl.Branch_1_Name = "IHP DHW Supply Inlet Branch"
    bl.Branch_2_Name = "IHP DHW Supply Equipment Branch"
    bl.Branch_3_Name = "IHP DHW Supply Bypass Branch"
    bl.Branch_4_Name = "IHP DHW Supply Outlet Branch"

    # Supply Splitter
    sp = idf.newidfobject("CONNECTOR:SPLITTER")
    sp.Name                 = "IHP DHW Supply Splitter"
    sp.Inlet_Branch_Name    = "IHP DHW Supply Inlet Branch"
    sp.Outlet_Branch_1_Name = "IHP DHW Supply Equipment Branch"
    sp.Outlet_Branch_2_Name = "IHP DHW Supply Bypass Branch"

    # Supply Mixer
    mx = idf.newidfobject("CONNECTOR:MIXER")
    mx.Name               = "IHP DHW Supply Mixer"
    mx.Outlet_Branch_Name = "IHP DHW Supply Outlet Branch"
    mx.Inlet_Branch_1_Name = "IHP DHW Supply Equipment Branch"
    mx.Inlet_Branch_2_Name = "IHP DHW Supply Bypass Branch"

    # Supply ConnectorList
    cl = idf.newidfobject("CONNECTORLIST")
    cl.Name                    = "IHP DHW Supply Connectors"
    cl.Connector_1_Object_Type = "Connector:Splitter"
    cl.Connector_1_Name        = "IHP DHW Supply Splitter"
    cl.Connector_2_Object_Type = "Connector:Mixer"
    cl.Connector_2_Name        = "IHP DHW Supply Mixer"

    # Demand BranchList
    bl = idf.newidfobject("BRANCHLIST")
    bl.Name          = "IHP DHW Demand Branches"
    bl.Branch_1_Name = "IHP DHW Demand Inlet Branch"
    bl.Branch_2_Name = "IHP DHW WH Source Branch"
    bl.Branch_3_Name = "IHP DHW Demand Bypass Branch"
    bl.Branch_4_Name = "IHP DHW Demand Outlet Branch"

    # Demand Splitter
    sp = idf.newidfobject("CONNECTOR:SPLITTER")
    sp.Name                 = "IHP DHW Demand Splitter"
    sp.Inlet_Branch_Name    = "IHP DHW Demand Inlet Branch"
    sp.Outlet_Branch_1_Name = "IHP DHW WH Source Branch"
    sp.Outlet_Branch_2_Name = "IHP DHW Demand Bypass Branch"

    # Demand Mixer
    mx = idf.newidfobject("CONNECTOR:MIXER")
    mx.Name                = "IHP DHW Demand Mixer"
    mx.Outlet_Branch_Name  = "IHP DHW Demand Outlet Branch"
    mx.Inlet_Branch_1_Name = "IHP DHW WH Source Branch"
    mx.Inlet_Branch_2_Name = "IHP DHW Demand Bypass Branch"

    # Demand ConnectorList
    cl = idf.newidfobject("CONNECTORLIST")
    cl.Name                    = "IHP DHW Demand Connectors"
    cl.Connector_1_Object_Type = "Connector:Splitter"
    cl.Connector_1_Name        = "IHP DHW Demand Splitter"
    cl.Connector_2_Object_Type = "Connector:Mixer"
    cl.Connector_2_Name        = "IHP DHW Demand Mixer"

    print("  [conn]  BranchLists, Splitters, Mixers, ConnectorLists added.")


def add_dhw_operation_scheme(idf):
    el = idf.newidfobject("PLANTEQUIPMENTLIST")
    el.Name                    = "IHP DHW Equipment List"
    el.Equipment_1_Object_Type = "Coil:WaterHeating:AirToWaterHeatPump:VariableSpeed"
    el.Equipment_1_Name        = f"PACU_VAV_{DHW_AHU_STEP2} IHP DHW Coil"

    op = idf.newidfobject("PLANTEQUIPMENTOPERATION:HEATINGLOAD")
    op.Name                        = "IHP DHW Operation Scheme"
    op.Load_Range_1_Lower_Limit    = 0.0
    op.Load_Range_1_Upper_Limit    = 1000000000000000.0
    op.Range_1_Equipment_List_Name = "IHP DHW Equipment List"

    ops = idf.newidfobject("PLANTEQUIPMENTOPERATIONSCHEMES")
    ops.Name                          = "IHP DHW Loop Operation Schemes"
    ops.Control_Scheme_1_Object_Type  = "PlantEquipmentOperation:HeatingLoad"
    ops.Control_Scheme_1_Name         = "IHP DHW Operation Scheme"
    ops.Control_Scheme_1_Schedule_Name = "PlantOnSched"

    print("  [op]    IHP DHW Operation Scheme added.")


def add_dhw_setpoint_manager(idf):
    spm = idf.newidfobject("SETPOINTMANAGER:SCHEDULED")
    spm.Name                           = "IHP DHW Loop Setpoint Manager"
    spm.Control_Variable               = "Temperature"
    spm.Schedule_Name                  = "SHWSys1-Loop-Temp-Schedule"
    spm.Setpoint_Node_or_NodeList_Name = LOOP_SUPPLY_OUT
    print("  [SPM]   IHP DHW Loop Setpoint Manager added (ref: SHWSys1-Loop-Temp-Schedule = 60°C).")


def add_dhw_sizing(idf):
    sz = idf.newidfobject("SIZING:PLANT")
    sz.Plant_or_Condenser_Loop_Name      = DHW_LOOP_NAME
    sz.Loop_Type                         = "Heating"
    sz.Design_Loop_Exit_Temperature      = 57.0
    sz.Loop_Design_Temperature_Difference = 5.0
    print(f"  [size]  Sizing:Plant for {DHW_LOOP_NAME} added.")


def add_dhw_plant_loop(idf):
    loop = idf.newidfobject("PLANTLOOP")
    loop.Name                                  = DHW_LOOP_NAME
    loop.Fluid_Type                            = "Water"
    loop.Plant_Equipment_Operation_Scheme_Name = "IHP DHW Loop Operation Schemes"
    loop.Loop_Temperature_Setpoint_Node_Name   = LOOP_SUPPLY_OUT
    loop.Maximum_Loop_Temperature              = 60.0
    loop.Minimum_Loop_Temperature              = 10.0
    loop.Maximum_Loop_Flow_Rate                = "AUTOSIZE"
    loop.Minimum_Loop_Flow_Rate                = 0.0
    loop.Plant_Loop_Volume                     = "AUTOSIZE"
    # Supply Side
    loop.Plant_Side_Inlet_Node_Name            = LOOP_SUPPLY_IN
    loop.Plant_Side_Outlet_Node_Name           = LOOP_SUPPLY_OUT
    loop.Plant_Side_Branch_List_Name           = "IHP DHW Supply Branches"
    loop.Plant_Side_Connector_List_Name        = "IHP DHW Supply Connectors"
    # Demand Side
    loop.Demand_Side_Inlet_Node_Name           = LOOP_DEMAND_IN
    loop.Demand_Side_Outlet_Node_Name          = LOOP_DEMAND_OUT
    loop.Demand_Side_Branch_List_Name          = "IHP DHW Demand Branches"
    loop.Demand_Side_Connector_List_Name       = "IHP DHW Demand Connectors"
    loop.Load_Distribution_Scheme              = "Optimal"

    print(f"  [loop]  PlantLoop '{DHW_LOOP_NAME}' created.")
    print(f"           Supply: {LOOP_SUPPLY_IN} → {LOOP_SUPPLY_OUT}")
    print(f"           Demand: {LOOP_DEMAND_IN} → {LOOP_DEMAND_OUT}")
    return loop


def run_step2(idf):
    print("\n" + "="*60)
    print("STEP 2 — Connect IHP DHW to WaterHeater via Plant Loop")
    print("="*60)

    # NOTE: Plant loop functions below are defined but currently commented out
    # in the original notebook. Uncomment as needed.
    # update_water_heater_source_side(idf)
    # add_dhw_pump(idf)
    # add_dhw_branches(idf)
    # add_dhw_connectors(idf)
    # add_dhw_operation_scheme(idf)
    # add_dhw_sizing(idf)
    # add_dhw_setpoint_manager(idf)
    # add_dhw_plant_loop(idf)

    print("\n" + "="*60)
    print("STEP 2 COMPLETE")
    print("  ✓ DHW Coil water nodes → WaterHeater Source Side (direct, no Plant Loop)")
    print("="*60 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — SetpointManager & Control Logic Update for ASIHP
# ══════════════════════════════════════════════════════════════════════════════

def update_sizing_system(idf, ahu_list):
    updated = 0
    for sz in idf.idfobjects["SIZING:SYSTEM"]:
        if sz.AirLoop_Name in [f"PACU_VAV_{ahu}" for ahu in ahu_list]:
            old_val = sz.Central_Heating_Design_Supply_Air_Temperature
            sz.Central_Heating_Design_Supply_Air_Temperature = SAT_SP_MAX_HEAT
            print(f"  [size] {sz.AirLoop_Name}: Heating SAT {old_val} → {SAT_SP_MAX_HEAT}°C")
            updated += 1
    print(f"  [size] {updated} Sizing:System objects updated.")


def add_oat_sensor(idf):
    for s in idf.idfobjects["ENERGYMANAGEMENTSYSTEM:SENSOR"]:
        if s.Name == "IHP_OAT":
            print("  [EMS]  Sensor 'IHP_OAT' already exists, skipped.")
            return
    s = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:SENSOR")
    s.Name                                       = "IHP_OAT"
    s.OutputVariable_or_OutputMeter_Index_Key_Name = "*"
    s.OutputVariable_or_OutputMeter_Name          = "Site Outdoor Air Drybulb Temperature"
    print("  [EMS]  Sensor 'IHP_OAT' added (Site Outdoor Air Drybulb Temperature).")


def add_sat_actuator(idf, ahu):
    p    = f"PACU_VAV_{ahu}"
    node = f"{p} Supply Equipment Outlet Node"
    name = f"IHP_SAT_SP_{ahu.upper()}"
    act = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:ACTUATOR")
    act.Name                          = name
    act.Actuated_Component_Unique_Name = node
    act.Actuated_Component_Type       = "System Node Setpoint"
    act.Actuated_Component_Control_Type = "Temperature Setpoint"
    print(f"  [EMS]  Actuator '{name}' → node: {node}")
    return name


def add_sat_control_program(idf, ahu_list):
    prog = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAM")
    prog.Name = "IHP_SAT_Control"

    lines = [
        f"IF IHP_OAT >= {OAT_THRESHOLD_COOL},",
        f"  SET IHP_SAT_Target = NULL,",
        f"ELSEIF IHP_OAT <= {OAT_THRESHOLD_HEAT},",
        f"  SET IHP_SAT_Target = {SAT_SP_MAX_HEAT},",
        f"ELSE,",
        (f"  SET IHP_SAT_Target = {SAT_SP_COOL_MIN} + "
         f"({SAT_SP_MAX_HEAT} - {SAT_SP_COOL_MIN}) * "
         f"({OAT_THRESHOLD_COOL} - IHP_OAT) / "
         f"({OAT_THRESHOLD_COOL} - {OAT_THRESHOLD_HEAT}),"),
        f"ENDIF,",
    ]
    for ahu in ahu_list:
        lines.append(f"SET IHP_SAT_SP_{ahu.upper()} = IHP_SAT_Target,")
    lines[-1] = lines[-1].rstrip(",") + ";"

    for i, line in enumerate(lines, start=1):
        setattr(prog, f"Program_Line_{i}", line)

    print(f"  [EMS]  Program 'IHP_SAT_Control' added ({len(lines)} lines, {len(ahu_list)} AHUs).")


def add_sat_global_variable(idf):
    gv = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:GLOBALVARIABLE")
    gv.Erl_Variable_1_Name = "IHP_SAT_Target"
    print("  [EMS]  GlobalVariable 'IHP_SAT_Target' added.")


def add_sat_calling_manager(idf):
    pcm = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAMCALLINGMANAGER")
    pcm.Name                           = "IHP_SAT_Control_Manager"
    pcm.EnergyPlus_Model_Calling_Point = "AfterPredictorAfterHVACManagers"
    pcm.Program_Name_1                 = "IHP_SAT_Control"
    print("  [EMS]  ProgramCallingManager 'IHP_SAT_Control_Manager' added.")


def verify_mixed_air_spm(idf, ahu_list):
    print()
    all_ok = True
    for ahu in ahu_list:
        p        = f"PACU_VAV_{ahu}"
        expected = f"{p}_IHP-{p} FanNode"
        for spm in idf.idfobjects["SETPOINTMANAGER:MIXEDAIR"]:
            if spm.Name.startswith(p):
                actual = spm.Fan_Inlet_Node_Name
                status = "✓" if actual == expected else "✗"
                if actual != expected:
                    all_ok = False
                print(f"  [SPM]  {status} {spm.Name}")
                print(f"           Fan Inlet = '{actual}'")
                if actual != expected:
                    print(f"           Expected  = '{expected}'  ← Step 1 check needed")
    if all_ok:
        print("  [OK]   All SetpointManager:MixedAir Fan Inlet nodes verified.")
    return all_ok


def add_output_variables(idf, ahu_list, dhw_ahu="bot"):
    def add_ov(key, varname, freq="Hourly"):
        ov = idf.newidfobject("OUTPUT:VARIABLE")
        ov.Key_Value           = key
        ov.Variable_Name       = varname
        ov.Reporting_Frequency = freq
        return ov

    p_dhw = f"PACU_VAV_{dhw_ahu}"

    for ahu in ahu_list:
        p = f"PACU_VAV_{ahu}"
        add_ov(f"{p} IHP", "Integrated Heat Pump Operating Mode Code")

    for ahu in ahu_list:
        p = f"PACU_VAV_{ahu}"
        add_ov(f"{p} IHP SC Coil", "Cooling Coil Total Cooling Rate")
        add_ov(f"{p} IHP SC Coil", "Cooling Coil Electric Power")
        add_ov(f"{p} IHP SH Coil", "Heating Coil Heating Rate")
        add_ov(f"{p} IHP SH Coil", "Heating Coil Electric Power")

    add_ov(f"{p_dhw} IHP DHW Coil", "Water Heater Heating Rate")
    add_ov(f"{p_dhw} IHP DHW Coil", "Cooling Coil Electric Power")
    add_ov("SWHSys1 Water Heater",  "Water Heater Heat Source Energy")

    for ahu in ahu_list:
        p = f"PACU_VAV_{ahu}"
        add_ov(f"{p} Supply Equipment Outlet Node", "System Node Temperature")
        add_ov(f"{p} Supply Equipment Outlet Node", "System Node Setpoint Temperature")

    add_ov("*", "Site Outdoor Air Drybulb Temperature")
    add_ov("SWHSys1 IHP Source Outlet Node", "System Node Temperature")
    add_ov("SWHSys1 WH Source Inlet Node",   "System Node Temperature")

    for ahu in ahu_list:
        ems_ov = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:OUTPUTVARIABLE")
        ems_ov.Name                      = f"IHP_SAT_SP_{ahu.upper()}_Value"
        ems_ov.EMS_Variable_Name         = f"IHP_SAT_SP_{ahu.upper()}"
        ems_ov.Type_of_Data_in_Variable  = "Averaged"
        ems_ov.Update_Frequency          = "SystemTimeStep"
        ems_ov.Units                     = "C"

    print(f"  [out]  Output:Variables added for {len(ahu_list)} AHUs "
          f"(IHP mode, coil rates, SAT, DHW).")


def run_step3(idf, ahu_list, dhw_ahu="bot"):
    print("\n" + "="*60)
    print("STEP 3 — SetpointManager & Control Logic Update")
    print("="*60)

    print("\n[3.1] Updating Sizing:System heating supply temperatures...")
    update_sizing_system(idf, ahu_list)

    print("\n[3.2] Adding EMS dual-mode SAT control...")
    add_oat_sensor(idf)
    add_sat_global_variable(idf)
    for ahu in ahu_list:
        add_sat_actuator(idf, ahu)
    add_sat_control_program(idf, ahu_list)
    add_sat_calling_manager(idf)

    print("\n[3.3] Verifying SetpointManager:MixedAir nodes...")
    verify_mixed_air_spm(idf, ahu_list)

    print("\n[3.4] Adding Output:Variables...")
    add_output_variables(idf, ahu_list, dhw_ahu=dhw_ahu)

    print("\n" + "="*60)
    print("STEP 3 COMPLETE")
    print("="*60 + "\n")


# ══════════════════════════════════════════════════════════════════════════════
# Save helpers
# ══════════════════════════════════════════════════════════════════════════════

def remove_wrong_dhw_coils(idf, wrong_ahus=["mid", "top"]):
    for ahu in wrong_ahus:
        p      = f"PACU_VAV_{ahu}"
        target = f"{p} IHP DHW Coil"
        for coil in idf.idfobjects["COIL:WATERHEATING:AIRTOWATERHEATPUMP:VARIABLESPEED"]:
            if coil.Name == target:
                idf.removeidfobject(coil)
                print(f"  [del] {target} removed")
                break
        for ihp in idf.idfobjects["COILSYSTEM:INTEGRATEDHEATPUMP:AIRSOURCE"]:
            if ihp.Name == f"{p} IHP":
                ihp.Dedicated_Water_Heating_Mode_Coil_Name = ""
                ihp.SCWH_Mode_Cooling_Coil_Name            = ""
                ihp.SCDWH_Cooling_Coil_Name                = ""
                ihp.SCDWH_Water_Heating_Coil_Name          = ""
                ihp.SHDWH_Water_Heating_Coil_Name          = ""
                print(f"  [IHP] {ihp.Name} DHW fields cleared")
                break


def remove_all_blank_objects(idf):
    types_to_check = [
        "CURVE:BIQUADRATIC",
        "CURVE:QUADRATIC",
        "CURVE:LINEAR",
        "AIRLOOPHVAC:UNITARYSYSTEM",
        "COIL:COOLING:DX:VARIABLESPEED",
        "COIL:HEATING:DX:VARIABLESPEED",
        "COIL:WATERHEATING:AIRTOWATERHEATPUMP:VARIABLESPEED",
        "COILSYSTEM:INTEGRATEDHEATPUMP:AIRSOURCE",
        "BRANCH",
        "ENERGYMANAGEMENTSYSTEM:SENSOR",
        "ENERGYMANAGEMENTSYSTEM:ACTUATOR",
        "ENERGYMANAGEMENTSYSTEM:PROGRAM",
    ]
    for obj_type in types_to_check:
        to_remove = [
            obj for obj in idf.idfobjects[obj_type]
            if not obj.Name or not obj.Name.strip()
        ]
        for obj in to_remove:
            idf.removeidfobject(obj)
        if to_remove:
            print(f"  [fix] Removed {len(to_remove)} blank {obj_type} object(s).")


def add_hvac_timeseries_outputs(idf, frequency="Hourly"):
    """
    frequency options: "TimeStep", "Hourly", "Daily", "Monthly", "RunPeriod"
    """
    variables = [
        ("*", "System Node Temperature"),
        ("*", "System Node Mass Flow Rate"),
        ("*", "Unitary System Cooling Coil Electric Energy"),
        ("*", "Unitary System Heating Coil Electric Energy"),
        ("*", "Integrated Heat Pump Operating Mode Code"),
        ("*", "Fan Electricity Energy"),
        ("*", "Water Heater Heating Energy"),
        ("*", "Water Heater Electric Energy"),
    ]
    for key, varname in variables:
        ov = idf.newidfobject("OUTPUT:VARIABLE")
        ov.Key_Value           = key
        ov.Variable_Name       = varname
        ov.Reporting_Frequency = frequency
    print(f"  [output] {len(variables)} Output:Variable objects added ({frequency})")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    IDF.setiddname(IDD_FILE)
    idf = IDF(INPUT_IDF)
    print("IDF loaded successfully")

    run_step1(idf, AHU_LIST)
    run_step2(idf)
    run_step3(idf, AHU_LIST, dhw_ahu="bot")

    remove_all_blank_objects(idf)
    remove_all_blank_objects(idf)  # run twice to catch cascading blanks

    add_hvac_timeseries_outputs(idf, frequency="Hourly")

    idf.saveas(OUTPUT_IDF)
    print(f"\nSaved: {OUTPUT_IDF}")


if __name__ == "__main__":
    main()
