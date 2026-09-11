"""
Script to convert a residential HP IDF to Ground Source Heat Pump (GSHP) system.
Uses eppy to:
1. Remove all AirflowNetwork:* objects
2. Remove air-source HP system components
3. Add GSHP water-to-air heat pump system with condenser loop and ground heat exchanger
4. Add WaterHeater:Stratified with desuperheater (replaces WaterHeater:HeatPump:WrappedCondenser)

Usage:
    pip install eppy
    python convert_hp_to_gshp.py <input.idf> <output.idf>

Requires an EnergyPlus IDD file. Set IDD_PATH below or pass as argument.
"""

import sys
import os
from eppy import modeleditor
from eppy.modeleditor import IDF

# =============================================================================
# try:
#     from eppy.modeleditor import IDF
# except ImportError:
#     raise ImportError("eppy is required. Install with: pip install eppy")
# =============================================================================


# ──────────────────────────────────────────────
# CONFIGURATION — adjust paths as needed
# ──────────────────────────────────────────────
IDD_PATH = None  # e.g. r"C:\EnergyPlusV25-1-0\Energy+.idd"
# If None, eppy will try to find it automatically.

# All AirflowNetwork class names to remove
AFN_CLASSES = [
    "AIRFLOWNETWORK:SIMULATIONCONTROL",
    "AIRFLOWNETWORK:MULTIZONE:ZONE",
    "AIRFLOWNETWORK:MULTIZONE:SURFACE",
    "AIRFLOWNETWORK:MULTIZONE:SURFACE:EFFECTIVELEAKAGEAREA",
    "AIRFLOWNETWORK:MULTIZONE:COMPONENT:ZONEEXHAUSTFAN",
    "AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:LEAKAGERATIO",
    "AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:DUCT",
    "AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:FAN",
    "AIRFLOWNETWORK:DISTRIBUTION:COMPONENT:COIL",
    "AIRFLOWNETWORK:DISTRIBUTION:NODE",
    "AIRFLOWNETWORK:DISTRIBUTION:LINKAGE",
]

# Original air-source HP object classes to remove entirely
HP_CLASSES_TO_REMOVE = [
    "AIRLOOPHVAC:UNITARYHEATPUMP:AIRTOAIR",
    "COIL:COOLING:DX:SINGLESPEED",
    "COIL:HEATING:DX:SINGLESPEED",
    "COIL:WATERHEATING:AIRTOWATERHEATPUMP:WRAPPED",
    "WATERHEATER:HEATPUMP:WRAPPEDCONDENSER",
    "ZONEHVAC:OUTDOORAIRUNIT",
    "FAN:ZONEEXHAUST",
]


def remove_all_of_class(idf, classname):
    """Remove every object of a given IDD class from the IDF."""
    classname_upper = classname.upper()
    objs = idf.idfobjects.get(classname_upper, [])
    for obj in list(objs):
        idf.removeidfobject(obj)
    removed = len(objs)
    if removed:
        print(f"  Removed {removed} object(s) of class {classname}")


def remove_named_object(idf, classname, name):
    """Remove a specific named object."""
    classname_upper = classname.upper()
    objs = idf.idfobjects.get(classname_upper, [])
    for obj in list(objs):
        if obj.Name.strip().lower() == name.strip().lower():
            idf.removeidfobject(obj)
            print(f"  Removed {classname}: {name}")
            return True
    return False


def update_zone_equipment_list(idf):
    """
    Replace the ZoneHVAC:EquipmentList to remove HPWH and exhaust fan entries,
    keeping only the AirDistributionUnit with priority 1.
    """
    for eqlist in idf.idfobjects.get("ZONEHVAC:EQUIPMENTLIST", []):
        if "ZoneEquipment_unit1" in eqlist.Name:
            # Keep only Zone Equipment 1 (Air Distribution Unit), reset sequences
            eqlist["Zone_Equipment_1_Cooling_Sequence"] = 1
            eqlist["Zone_Equipment_1_Heating_or_No-Load_Sequence"] = 1
            # Blank out equipment 2 and 3 entries
            for field in [
                "Zone_Equipment_2_Object_Type",
                "Zone_Equipment_2_Name",
                "Zone_Equipment_2_Cooling_Sequence",
                "Zone_Equipment_2_Heating_or_No-Load_Sequence",
                "Zone_Equipment_2_Sequential_Cooling_Fraction_Schedule_Name",
                "Zone_Equipment_2_Sequential_Heating_Fraction_Schedule_Name",
                "Zone_Equipment_3_Object_Type",
                "Zone_Equipment_3_Name",
                "Zone_Equipment_3_Cooling_Sequence",
                "Zone_Equipment_3_Heating_or_No-Load_Sequence",
                "Zone_Equipment_3_Sequential_Cooling_Fraction_Schedule_Name",
                "Zone_Equipment_3_Sequential_Heating_Fraction_Schedule_Name",
            ]:
                try:
                    eqlist[field] = ""
                except Exception:
                    pass
            print("  Updated ZoneHVAC:EquipmentList: ZoneEquipment_unit1")


def add_gshp_system(idf):
    """Add all GSHP-related objects to the IDF."""

    print("\n--- Adding GSHP system objects ---")

    # ── Schedules ──────────────────────────────────────────────────────────────
    idf.newidfobject(
        "SCHEDULE:COMPACT",
        Name="DesuperheaterSched",
        Schedule_Type_Limits_Name="",
        Field_1="Through: 12/31",
        Field_2="For: AllDays",
        Field_3="Until: 24:00",
        Field_4="1",
    )
    idf.newidfobject(
        "SCHEDULE:CONSTANT",
        Name="DesuperheaterTempSch",
        Schedule_Type_Limits_Name="Temperature",
        Hourly_Value=60.0,
    )

    # ── Site: Ground Temperatures ──────────────────────────────────────────────
    idf.newidfobject(
        "SITE:GROUNDTEMPERATURE:BUILDINGSURFACE",
        January_Ground_Temperature=19.527,
        February_Ground_Temperature=19.502,
        March_Ground_Temperature=19.536,
        April_Ground_Temperature=19.598,
        May_Ground_Temperature=20.002,
        June_Ground_Temperature=21.640,
        July_Ground_Temperature=22.225,
        August_Ground_Temperature=22.375,
        September_Ground_Temperature=21.449,
        October_Ground_Temperature=20.121,
        November_Ground_Temperature=19.691,
        December_Ground_Temperature=19.549,
    )
    idf.newidfobject(
        "SITE:GROUNDTEMPERATURE:DEEP",
        January_Deep_Ground_Temperature=13.0,
        February_Deep_Ground_Temperature=13.0,
        March_Deep_Ground_Temperature=13.0,
        April_Deep_Ground_Temperature=13.0,
        May_Deep_Ground_Temperature=13.0,
        June_Deep_Ground_Temperature=13.0,
        July_Deep_Ground_Temperature=13.0,
        August_Deep_Ground_Temperature=13.0,
        September_Deep_Ground_Temperature=13.0,
        October_Deep_Ground_Temperature=13.0,
        November_Deep_Ground_Temperature=13.0,
        December_Deep_Ground_Temperature=13.0,
    )
    idf.newidfobject(
        "SITE:GROUNDTEMPERATURE:UNDISTURBED:KUSUDAACHENBACH",
        Name="test_vertical ground heat exchanger ground temps",
        Soil_Thermal_Conductivity=0.692626,
        Soil_Density=1500.0,
        Soil_Specific_Heat=1563.34,
        Average_Soil_Surface_Temperature=13.0,
        Amplitude_of_Soil_Surface_Temperature=10.0,
        Phase_Shift_of_Minimum_Soil_Surface_Temperature=17.3,
    )
    idf.newidfobject(
        "SITE:WATERMAINSTEMPERATURE",
        Calculation_Method="CorrelationFromWeatherFile",
    )

    # ── Curves ─────────────────────────────────────────────────────────────────
    # WaterToAir HP performance curves
    idf.newidfobject(
        "CURVE:QUADLINEAR",
        Name="test_TotCoolCapCurve",
        Coefficient1_Constant=-1.68436773,
        Coefficient2_w=4.93320639,
        Coefficient3_x=-2.31448099,
        Coefficient4_y=0.0514554796,
        Coefficient5_z=0.0208644436,
        Minimum_Value_of_w=-100,
        Maximum_Value_of_w=100,
        Minimum_Value_of_x=-100,
        Maximum_Value_of_x=100,
        Minimum_Value_of_y=0,
        Maximum_Value_of_y=100,
        Minimum_Value_of_z=0,
        Maximum_Value_of_z=100,
        Minimum_Curve_Output=0,
        Maximum_Curve_Output=38,
    )
    idf.newidfobject(
        "CURVE:QUADLINEAR",
        Name="test_CoolPowCurve",
        Coefficient1_Constant=-4.315757,
        Coefficient2_w=0.641814878,
        Coefficient3_x=4.26562885,
        Coefficient4_y=0.137969989,
        Coefficient5_z=-0.0513551465,
        Minimum_Value_of_w=-100,
        Maximum_Value_of_w=100,
        Minimum_Value_of_x=-100,
        Maximum_Value_of_x=100,
        Minimum_Value_of_y=0,
        Maximum_Value_of_y=100,
        Minimum_Value_of_z=0,
        Maximum_Value_of_z=100,
        Minimum_Curve_Output=0,
        Maximum_Curve_Output=38,
    )
    idf.newidfobject(
        "CURVE:QUADLINEAR",
        Name="test_HeatCapCurve",
        Coefficient1_Constant=-3.577354,
        Coefficient2_w=-0.62877328,
        Coefficient3_x=4.70460223,
        Coefficient4_y=0.0,
        Coefficient5_z=0.0,
        Minimum_Value_of_w=-100,
        Maximum_Value_of_w=100,
        Minimum_Value_of_x=-100,
        Maximum_Value_of_x=100,
        Minimum_Value_of_y=0,
        Maximum_Value_of_y=100,
        Minimum_Value_of_z=0,
        Maximum_Value_of_z=100,
        Minimum_Curve_Output=0,
        Maximum_Curve_Output=38,
    )
    idf.newidfobject(
        "CURVE:QUADLINEAR",
        Name="test_HeatPowCurve",
        Coefficient1_Constant=-7.10933262,
        Coefficient2_w=-0.48073498,
        Coefficient3_x=8.61905648,
        Coefficient4_y=0.0,
        Coefficient5_z=0.0,
        Minimum_Value_of_w=-100,
        Maximum_Value_of_w=100,
        Minimum_Value_of_x=-100,
        Maximum_Value_of_x=100,
        Minimum_Value_of_y=0,
        Maximum_Value_of_y=100,
        Minimum_Value_of_z=0,
        Maximum_Value_of_z=100,
        Minimum_Curve_Output=0,
        Maximum_Curve_Output=38,
    )
    idf.newidfobject(
        "CURVE:QUINTLINEAR",
        Name="test_CoolSensCapCurve",
        Coefficient1_Constant=2.24209455,
        Coefficient2_v=7.28936345,
        Coefficient3_w=-14.7818754,
        Coefficient4_x=7.31628578,
        Coefficient5_y=0.0,
        Coefficient6_z=0.0,
        Minimum_Value_of_v=-100,
        Maximum_Value_of_v=100,
        Minimum_Value_of_w=-100,
        Maximum_Value_of_w=100,
        Minimum_Value_of_x=-100,
        Maximum_Value_of_x=100,
        Minimum_Value_of_y=0,
        Maximum_Value_of_y=100,
        Minimum_Value_of_z=0,
        Maximum_Value_of_z=100,
        Minimum_Curve_Output=0,
        Maximum_Curve_Output=38,
    )
    idf.newidfobject(
        "CURVE:QUADRATIC",
        Name="test_HPACCOOLPLFFPLR",
        Coefficient1_Constant=0.85,
        Coefficient2_x=0.15,
        Coefficient3_x2=0.0,
        Minimum_Value_of_x=0.0,
        Maximum_Value_of_x=1.0,
    )
    idf.newidfobject(
        "CURVE:QUADRATIC",
        Name="test_HPACHEATPLFFPLR",
        Coefficient1_Constant=0.85,
        Coefficient2_x=0.15,
        Coefficient3_x2=0.0,
        Minimum_Value_of_x=0.0,
        Maximum_Value_of_x=1.0,
    )
    idf.newidfobject(
        "CURVE:BIQUADRATIC",
        Name="test_HEffFTemp",
        Coefficient1_Constant=0.9,
        Coefficient2_x=0.005,
        Coefficient3_x2=0.0,
        Coefficient4_y=0.0,
        Coefficient5_y2=0.0,
        Coefficient6_xy=0.0,
        Minimum_Value_of_x=10.0,
        Maximum_Value_of_x=50.0,
        Minimum_Value_of_y=20.0,
        Maximum_Value_of_y=35.0,
    )

    # ── GSHP Coils ─────────────────────────────────────────────────────────────
    idf.newidfobject(
        "COIL:COOLING:WATERTOAIRHEATPUMP:EQUATIONFIT",
        Name="test_Sys 1 Heat Pump Cooling Mode",
        Water_Inlet_Node_Name="test_sys1 water to air heat pump source side 1 inlet node",
        Water_Outlet_Node_Name="test_sys1 water to air heat pump source side1 outlet node",
        Air_Inlet_Node_Name="test_Sys 1 Cooling Coil Air Inlet Node",
        Air_Outlet_Node_Name="test_Sys 1 Heating Coil Air Inlet Node",
        Rated_Air_Flow_Rate=1,
        Rated_Water_Flow_Rate=0.00165,
        Gross_Rated_Total_Cooling_Capacity=23125.6,
        Gross_Rated_Sensible_Cooling_Capacity=16267.06,
        Gross_Rated_Cooling_COP=7.007757577,
        Rated_Entering_Water_Temperature=30,
        Rated_Entering_Air_DryBulb_Temperature=27,
        Rated_Entering_Air_WetBulb_Temperature=19,
        Total_Cooling_Capacity_Curve_Name="test_TotCoolCapCurve",
        Sensible_Cooling_Capacity_Curve_Name="test_CoolSensCapCurve",
        Cooling_Power_Consumption_Curve_Name="test_CoolPowCurve",
        Part_Load_Fraction_Correlation_Curve_Name="test_HPACCOOLPLFFPLR",
        Nominal_Time_for_Condensate_Removal_to_Begin=0,
        Ratio_of_Initial_Moisture_Evaporation_Rate_and_Steady_State_Latent_Capacity=0,
        Maximum_Cycling_Rate=2.5,
        Latent_Capacity_Time_Constant=60,
        Fan_Delay_Time=60,
    )
    idf.newidfobject(
        "COIL:HEATING:WATERTOAIRHEATPUMP:EQUATIONFIT",
        Name="test_Sys 1 Heat Pump Heating Mode",
        Water_Inlet_Node_Name="test_Sys 1 Water to Air Heat Pump Source Side2 Inlet Node",
        Water_Outlet_Node_Name="test_Sys 1 Water to Air Heat Pump Source Side2 Outlet Node",
        Air_Inlet_Node_Name="test_Sys 1 Heating Coil Air Inlet Node",
        Air_Outlet_Node_Name="test_Sys 1 SuppHeating Coil Air Inlet Node",
        Rated_Air_Flow_Rate=1,
        Rated_Water_Flow_Rate=0.00165,
        Gross_Rated_Heating_Capacity=19156.73,
        Gross_Rated_Heating_COP=3.167053691,
        Rated_Entering_Water_Temperature=20,
        Rated_Entering_Air_DryBulb_Temperature=20,
        Ratio_of_Rated_Heating_Capacity_to_Rated_Cooling_Capacity=1,
        Heating_Capacity_Curve_Name="test_HeatCapCurve",
        Heating_Power_Consumption_Curve_Name="test_HeatPowCurve",
        Part_Load_Fraction_Correlation_Curve_Name="test_HPACHEATPLFFPLR",
    )

    # ── Desuperheater & Stratified Water Heater ─────────────────────────────────
    idf.newidfobject(
        "COIL:WATERHEATING:DESUPERHEATER",
        Name="test_WaterHeatingCoil",
        Availability_Schedule_Name="DesuperheaterSched",
        Setpoint_Temperature_Schedule_Name="DesuperheaterTempSch",
        Dead_Band_Temperature_Difference=4,
        Rated_Heat_Reclaim_Recovery_Efficiency=0.25,
        Rated_Inlet_Water_Temperature=50,
        Rated_Outdoor_Air_Temperature=35,
        Maximum_Inlet_Water_Temperature_for_Heat_Reclaim=50,
        Heat_Reclaim_Efficiency_Function_of_Temperature_Curve_Name="test_HEffFTemp",
        Water_Inlet_Node_Name="test_WaterHeatingCoilInletNode",
        Water_Outlet_Node_Name="test_WaterHeatingCoilOutletNode",
        Tank_Object_Type="WaterHeater:Stratified",
        Tank_Name="Water Heater_Tank_unit1",
        Heating_Source_Object_Type="Coil:Cooling:WaterToAirHeatPump:EquationFit",
        Heating_Source_Name="test_Sys 1 Heat Pump Cooling Mode",
        Water_Flow_Rate=0.0001,
        Water_Pump_Power=25,
        Fraction_of_Pump_Heat_to_Water=0.2,
        OnCycle_Parasitic_Electric_Load=10,
        OffCycle_Parasitic_Electric_Load=10,
    )
    idf.newidfobject(
        "WATERHEATER:STRATIFIED",
        Name="Water Heater_Tank_unit1",
        EndUse_Subcategory="Water Heater",
        Tank_Volume=0.30283288,
        Tank_Height=1.594,
        Tank_Shape="VerticalCylinder",
        Maximum_Temperature_Limit=51,
        Heater_Priority_Control="MasterSlave",
        Heater_1_Setpoint_Temperature_Schedule_Name="dhw_setpt_hpwh",
        Heater_1_Deadband_Temperature_Difference=2,
        Heater_1_Capacity=4500,
        Heater_1_Height=1.129,
        Heater_2_Setpoint_Temperature_Schedule_Name="dhw_setpt_hpwh",
        Heater_2_Deadband_Temperature_Difference=2,
        Heater_2_Capacity=0,
        Heater_2_Height=0.266,
        Heater_Fuel_Type="electricity",
        Heater_Thermal_Efficiency=1,
        Off_Cycle_Parasitic_Fuel_Consumption_Rate=8.3,
        Off_Cycle_Parasitic_Fuel_Type="Electricity",
        Off_Cycle_Parasitic_Heat_Fraction_to_Tank=0,
        Off_Cycle_Parasitic_Height=1,
        On_Cycle_Parasitic_Fuel_Consumption_Rate=8.3,
        On_Cycle_Parasitic_Fuel_Type="Electricity",
        On_Cycle_Parasitic_Heat_Fraction_to_Tank=0,
        On_Cycle_Parasitic_Height=1,
        Ambient_Temperature_Indicator="Zone",
        Ambient_Temperature_Zone_Name="garage1",
        Uniform_Skin_Loss_Coefficient_per_Unit_Area_to_Ambient_Temperature=0.232135950478784,
        Skin_Loss_Fraction_to_Zone=1,
        Off_Cycle_Flue_Loss_Fraction_to_Zone=1,
        Use_Side_Inlet_Node_Name="Water Heater use inlet node_unit1",
        Use_Side_Outlet_Node_Name="Water Heater use outlet node_unit1",
        Use_Side_Effectiveness=1,
        Use_Side_Inlet_Height=0,
        Use_Side_Outlet_Height="autocalculate",
        Source_Side_Inlet_Node_Name="test_WaterHeatingCoilOutletNode",
        Source_Side_Outlet_Node_Name="test_WaterHeatingCoilInletNode",
        Source_Side_Effectiveness=1,
        Source_Side_Inlet_Height=0.7,
        Source_Side_Outlet_Height=0,
        Inlet_Mode="Fixed",
        Use_Side_Design_Flow_Rate="autosize",
        Source_Side_Design_Flow_Rate="autosize",
        Indirect_Water_Heating_Recovery_Time=1.5,
        Number_of_Nodes=6,
    )

    # ── Unitary WaterToAir HP ──────────────────────────────────────────────────
    idf.newidfobject(
        "AIRLOOPHVAC:UNITARYHEATPUMP:WATERTOAIR",
        Name="test_Water-To-Air Heat Pump Unit 1",
        Availability_Schedule_Name="always_avail",
        Air_Inlet_Node_Name="test_Sys 1 Mixed Air Node",
        Air_Outlet_Node_Name="test_Sys 1 Air Loop Outlet Node_unit1",
        Supply_Air_Flow_Rate="autosize",
        Controlling_Zone_or_Thermostat_Location="living_unit1",
        Supply_Air_Fan_Object_Type="Fan:OnOff",
        Supply_Air_Fan_Name="test_Supply Fan_unit1",
        Heating_Coil_Object_Type="Coil:Heating:WaterToAirHeatPump:EquationFit",
        Heating_Coil_Name="test_Sys 1 Heat Pump Heating Mode",
        Heating_Convergence=0.001,
        Cooling_Coil_Object_Type="Coil:Cooling:WaterToAirHeatPump:EquationFit",
        Cooling_Coil_Name="test_Sys 1 Heat Pump Cooling Mode",
        Cooling_Convergence=0.001,
        Supplemental_Heating_Coil_Object_Type="Coil:Heating:Electric",
        Supplemental_Heating_Coil_Name="Supp Heating Coil_unit1",
        Maximum_Supply_Air_Temperature_from_Supplemental_Heater="autosize",
        Maximum_Outdoor_DryBulb_Temperature_for_Supplemental_Heater_Operation=21,
        Outdoor_DryBulb_Temperature_Sensor_Node_Name="test_Sys 1 Outside Air Inlet Node",
        Fan_Placement="BlowThrough",
        Supply_Air_Fan_Operating_Mode_Schedule_Name="fan_cycle",
    )

    # ── Outdoor Air Controller & System ────────────────────────────────────────
    idf.newidfobject(
        "CONTROLLER:OUTDOORAIR",
        Name="test_OA Controller 1",
        Relief_Air_Outlet_Node_Name="test_Sys 1 Relief Air Outlet Node",
        Return_Air_Node_Name="test_Sys 1 Outdoor Air Mixer Inlet Node",
        Mixed_Air_Node_Name="test_Sys 1 Mixed Air Node",
        Actuator_Node_Name="test_Sys 1 Outside Air Inlet Node",
        Minimum_Outdoor_Air_Flow_Rate=0.1,
        Maximum_Outdoor_Air_Flow_Rate=1,
        Economizer_Control_Type="NoEconomizer",
        Economizer_Control_Action_Type="ModulateFlow",
        Lockout_Type="NoLockout",
        Minimum_Limit_Type="FixedMinimum",
        Minimum_Outdoor_Air_Schedule_Name="OAFractionSched",
    )
    idf.newidfobject(
        "AIRLOOPHVAC:CONTROLLERLIST",
        Name="test_OA Sys 1 Controllers",
        Controller_1_Object_Type="Controller:OutdoorAir",
        Controller_1_Name="test_OA Controller 1",
    )
    idf.newidfobject(
        "OUTDOORAIR:MIXER",
        Name="test_OA Mixing Box 1",
        Mixed_Air_Node_Name="test_Sys 1 Mixed Air Node",
        Outdoor_Air_Stream_Node_Name="test_Sys 1 Outside Air Inlet Node",
        Relief_Air_Stream_Node_Name="test_Sys 1 Relief Air Outlet Node",
        Return_Air_Stream_Node_Name="test_Sys 1 Outdoor Air Mixer Inlet Node",
    )
    idf.newidfobject(
        "AIRLOOPHVAC:OUTDOORAIRSYSTEM:EQUIPMENTLIST",
        Name="test_OA Sys 1 Equipment",
        Component_1_Object_Type="OutdoorAir:Mixer",
        Component_1_Name="test_OA Mixing Box 1",
    )
    idf.newidfobject(
        "AIRLOOPHVAC:OUTDOORAIRSYSTEM",
        Name="test_OA Sys 1",
        Controller_List_Name="test_OA Sys 1 Controllers",
        Outdoor_Air_Equipment_List_Name="test_OA Sys 1 Equipment",
    )

    # ── AirLoopHVAC ────────────────────────────────────────────────────────────
    idf.newidfobject(
        "AIRLOOPHVAC",
        Name="test_WAHP package single zone 1",
        Availability_Manager_List_Name="test_Heat Pump 1 Avail List",
        Design_Supply_Air_Flow_Rate=1,
        Branch_List_Name="test_Sys 1 Air Loop Branches",
        Supply_Side_Inlet_Node_Name="test_Sys 1 Outdoor Air Mixer Inlet Node",
        Demand_Side_Outlet_Node_Name="test_Sys 1 Return Air Mixer Outlet",
        Demand_Side_Inlet_Node_Names="test_Sys 1 Zone Equipment Inlet Node",
        Supply_Side_Outlet_Node_Names="test_Sys 1 Air Loop Outlet Node_unit1",
    )

    # ── ZoneSplitter / SupplyPath ───────────────────────────────────────────────
    idf.newidfobject(
        "AIRLOOPHVAC:ZONESPLITTER",
        Name="test_Sys 1 Zone Supply Air Splitter",
        Inlet_Node_Name="test_Sys 1 Zone Equipment Inlet Node",
        Outlet_1_Node_Name="test_Zone Inlet Node_unit1 ATInlet",
    )
    idf.newidfobject(
        "AIRLOOPHVAC:SUPPLYPATH",
        Name="test_Sys 1 HeatPumpSupplyPath",
        Supply_Air_Path_Inlet_Node_Name="test_Sys 1 Zone Equipment Inlet Node",
        Component_1_Object_Type="AirLoopHVAC:ZoneSplitter",
        Component_1_Name="test_Sys 1 Zone Supply Air Splitter",
    )

    # ── NodeLists & OutdoorAir:NodeList ────────────────────────────────────────
    idf.newidfobject(
        "NODELIST",
        Name="test_Sys 1 OutsideAirInletNodes",
        Node_1_Name="test_Sys 1 Outside Air Inlet Node",
    )
    idf.newidfobject(
        "NODELIST",
        Name="test_Zone1Inlets",
        Node_1_Name="test_Zone Inlet Node_unit1",
    )
    idf.newidfobject(
        "OUTDOORAIR:NODELIST",
        Node_or_NodeList_Name_1="test_Sys 1 OutsideAirInletNodes",
    )

    # ── Pump ConstantSpeed for Condenser Loop ───────────────────────────────────
    idf.newidfobject(
        "PUMP:CONSTANTSPEED",
        Name="test_Cond Circ Pump",
        Inlet_Node_Name="test_Condenser Supply Inlet Node",
        Outlet_Node_Name="test_Condenser Pump Outlet Node",
        Design_Flow_Rate=0.0099,
        Design_Pump_Head=50000,
        Design_Power_Consumption=600,
        Motor_Efficiency=0.87,
        Fraction_of_Motor_Inefficiencies_to_Fluid_Stream=0,
        Pump_Control_Type="Continuous",
    )

    # ── Ground Heat Exchanger ──────────────────────────────────────────────────
    idf.newidfobject(
        "GROUNDHEATEXCHANGER:VERTICAL:PROPERTIES",
        Name="test_Vertical Ground Heat Exchanger Props",
        Depth_of_Top_of_Borehole=1,
        Borehole_Length=76.2,
        Borehole_Diameter=0.127016,
        Grout_Thermal_Conductivity=0.692626,
        Grout_Thermal_Heat_Capacity=3900000,
        Pipe_Thermal_Conductivity=0.391312,
        Pipe_Thermal_Heat_Capacity=1542000,
        Pipe_Outer_Diameter=0.0266667,
        Pipe_Thickness=0.00241285,
        UTube_Distance=0.051225,
    )

    ghe_rf = idf.newidfobject(
        "GROUNDHEATEXCHANGER:RESPONSEFACTORS",
        Name="test_Vertical Ground Heat Exchanger g-functions",
        GHEVerticalProperties_Object_Name="test_Vertical Ground Heat Exchanger Props",
        Number_of_Boreholes=120,
        GFunction_Reference_Ratio=0.0005,
    )
    # g-function pairs
    g_lnTTs = [
        -15.2996, -14.201, -13.2202, -12.2086, -11.1888, -10.1816,
        -9.1815, -8.6809, -8.5, -7.8, -7.2, -6.5, -5.9, -5.2,
        -4.5, -3.963, -3.27, -2.864, -2.577, -2.171, -1.884, -1.191,
        -0.497, -0.274, -0.051, 0.196, 0.419, 0.642, 0.873, 1.112,
        1.335, 1.679, 2.028, 2.275, 3.003,
    ]
    g_vals = [
        -0.348322, 0.022208, 0.412345, 0.867498, 1.357839, 1.852024,
        2.345656, 2.593958, 2.679, 3.023, 3.32, 3.681, 4.071, 4.828,
        6.253, 7.894, 11.82, 15.117, 18.006, 22.887, 26.924, 38.004,
        49.919, 53.407, 56.632, 59.825, 62.349, 64.524, 66.412, 67.993,
        69.162, 70.476, 71.361, 71.79, 72.511,
    ]
    for i, (lnTTs, gv) in enumerate(zip(g_lnTTs, g_vals), 1):
        try:
            ghe_rf[f"gFunction_Ln_T_Ts_Value_{i}"] = lnTTs
            ghe_rf[f"gFunction_g_Value_{i}"] = gv
        except Exception:
            pass

    idf.newidfobject(
        "GROUNDHEATEXCHANGER:SYSTEM",
        Name="test_Vertical Ground Heat Exchanger",
        Inlet_Node_Name="test_GHE Inlet Node",
        Outlet_Node_Name="test_GHE Outlet Node",
        Design_Flow_Rate=0.0033,
        Undisturbed_Ground_Temperature_Model_Type="Site:GroundTemperature:Undisturbed:KusudaAchenbach",
        Undisturbed_Ground_Temperature_Model_Name="test_vertical ground heat exchanger ground temps",
        Ground_Thermal_Conductivity=0.692626,
        Ground_Thermal_Heat_Capacity=2347000,
        GHEVerticalResponseFactors_Object_Name="test_Vertical Ground Heat Exchanger g-functions",
        gFunction_Calculation_Method="UHFcalc",
    )

    # ── Condenser Loop Pipes & Branches ────────────────────────────────────────
    for name, inlet, outlet in [
        ("test_Condenser Supply Side Bypass",   "test_Cond Supply Bypass Inlet Node",         "test_Cond Supply Bypass Outlet Node"),
        ("test_Condenser Supply Outlet",         "test_Condenser Supply Exit Pipe Inlet Node", "test_Condenser Supply Outlet Node"),
        ("test_Condenser Demand Inlet Pipe",     "test_Condenser Demand Inlet Node",           "test_Condenser Demand Entrance Pipe Outlet Node"),
        ("test_Condenser Demand Side Bypass",    "test_Cond Demand Bypass Inlet Node",         "test_Cond Demand Bypass Outlet Node"),
        ("test_Condenser Demand Outlet Pipe",    "test_Condenser Demand Exit Pipe Inlet Node", "test_Condenser Demand Outlet Node"),
    ]:
        idf.newidfobject(
            "PIPE:ADIABATIC",
            Name=name,
            Inlet_Node_Name=inlet,
            Outlet_Node_Name=outlet,
        )

    # Condenser loop branches
    idf.newidfobject(
        "BRANCH",
        Name="test_Sys 1 Air Loop Main Branch",
        Component_1_Object_Type="AirLoopHVAC:OutdoorAirSystem",
        Component_1_Name="test_OA Sys 1",
        Component_1_Inlet_Node_Name="test_Sys 1 Outdoor Air Mixer Inlet Node",
        Component_1_Outlet_Node_Name="test_Sys 1 Mixed Air Node",
        Component_2_Object_Type="AirLoopHVAC:UnitaryHeatPump:WaterToAir",
        Component_2_Name="test_Water-To-Air Heat Pump Unit 1",
        Component_2_Inlet_Node_Name="test_Sys 1 Mixed Air Node",
        Component_2_Outlet_Node_Name="test_Sys 1 Air Loop Outlet Node_unit1",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Sys 1 Gshp Cooling Condenser Branch",
        Component_1_Object_Type="Coil:Cooling:WaterToAirHeatPump:EquationFit",
        Component_1_Name="test_Sys 1 Heat Pump Cooling Mode",
        Component_1_Inlet_Node_Name="test_sys1 water to air heat pump source side 1 inlet node",
        Component_1_Outlet_Node_Name="test_sys1 water to air heat pump source side1 outlet node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Sys 1 Gshp Heating Condenser Branch ",
        Component_1_Object_Type="Coil:Heating:WaterToAirHeatPump:EquationFit",
        Component_1_Name="test_Sys 1 Heat Pump Heating Mode",
        Component_1_Inlet_Node_Name="test_Sys 1 Water to Air Heat Pump Source Side2 Inlet Node",
        Component_1_Outlet_Node_Name="test_Sys 1 Water to Air Heat Pump Source Side2 Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Demand Bypass Branch",
        Component_1_Object_Type="Pipe:Adiabatic",
        Component_1_Name="test_Condenser Demand Side Bypass",
        Component_1_Inlet_Node_Name="test_Cond Demand Bypass Inlet Node",
        Component_1_Outlet_Node_Name="test_Cond Demand Bypass Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Demand Outlet Branch",
        Component_1_Object_Type="Pipe:Adiabatic",
        Component_1_Name="test_Condenser Demand Outlet Pipe",
        Component_1_Inlet_Node_Name="test_Condenser Demand Exit Pipe Inlet Node",
        Component_1_Outlet_Node_Name="test_Condenser Demand Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Supply Inlet Branch",
        Component_1_Object_Type="Pump:ConstantSpeed",
        Component_1_Name="test_Cond Circ Pump",
        Component_1_Inlet_Node_Name="test_Condenser Supply Inlet Node",
        Component_1_Outlet_Node_Name="test_Condenser Pump Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Supply GHE Branch",
        Component_1_Object_Type="GroundHeatExchanger:System",
        Component_1_Name="test_Vertical Ground Heat Exchanger",
        Component_1_Inlet_Node_Name="test_GHE Inlet Node",
        Component_1_Outlet_Node_Name="test_GHE Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Supply Bypass Branch",
        Component_1_Object_Type="Pipe:Adiabatic",
        Component_1_Name="test_Condenser Supply Side Bypass",
        Component_1_Inlet_Node_Name="test_Cond Supply Bypass Inlet Node",
        Component_1_Outlet_Node_Name="test_Cond Supply Bypass Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Supply Outlet Branch",
        Component_1_Object_Type="Pipe:Adiabatic",
        Component_1_Name="test_Condenser Supply Outlet",
        Component_1_Inlet_Node_Name="test_Condenser Supply Exit Pipe Inlet Node",
        Component_1_Outlet_Node_Name="test_Condenser Supply Outlet Node",
    )
    idf.newidfobject(
        "BRANCH",
        Name="test_Condenser Demand Inlet Branch ",
        Component_1_Object_Type="Pipe:Adiabatic",
        Component_1_Name="test_Condenser Demand Inlet Pipe",
        Component_1_Inlet_Node_Name="test_Condenser Demand Inlet Node",
        Component_1_Outlet_Node_Name="test_Condenser Demand Entrance Pipe Outlet Node",
    )

    # BranchLists
    idf.newidfobject(
        "BRANCHLIST",
        Name="test_Sys 1 Air Loop Branches",
        Branch_1_Name="test_Sys 1 Air Loop Main Branch",
    )
    idf.newidfobject(
        "BRANCHLIST",
        Name="test_Condenser Supply Side Branches",
        Branch_1_Name="test_Condenser Supply Inlet Branch",
        Branch_2_Name="test_Condenser Supply GHE Branch",
        Branch_3_Name="test_Condenser Supply Bypass Branch",
        Branch_4_Name="test_Condenser Supply Outlet Branch",
    )
    idf.newidfobject(
        "BRANCHLIST",
        Name="test_Condenser Demand Side Branches",
        Branch_1_Name="test_Condenser Demand Inlet Branch ",
        Branch_2_Name="test_Sys 1 Gshp Cooling Condenser Branch",
        Branch_3_Name="test_Sys 1 Gshp Heating Condenser Branch ",
        Branch_4_Name="test_Condenser Demand Bypass Branch",
        Branch_5_Name="test_Condenser Demand Outlet Branch",
    )

    # Connector:Splitters
    idf.newidfobject(
        "CONNECTOR:SPLITTER",
        Name="test_Condenser Demand Spliter",
        Inlet_Branch_Name="test_Condenser Demand Inlet Branch ",
        Outlet_Branch_1_Name="test_Sys 1 Gshp Cooling Condenser Branch",
        Outlet_Branch_2_Name="test_Sys 1 Gshp Heating Condenser Branch ",
        Outlet_Branch_3_Name="test_Condenser Demand Bypass Branch",
    )
    idf.newidfobject(
        "CONNECTOR:SPLITTER",
        Name="test_Condenser Supply Splitter",
        Inlet_Branch_Name="test_Condenser Supply Inlet Branch",
        Outlet_Branch_1_Name="test_Condenser Supply GHE Branch",
        Outlet_Branch_2_Name="test_Condenser Supply Bypass Branch",
    )

    # Connector:Mixers
    idf.newidfobject(
        "CONNECTOR:MIXER",
        Name="test_Condenser Demand Mixer",
        Outlet_Branch_Name="test_Condenser Demand Outlet Branch",
        Inlet_Branch_1_Name="test_Sys 1 Gshp Cooling Condenser Branch",
        Inlet_Branch_2_Name="test_Sys 1 Gshp Heating Condenser Branch ",
        Inlet_Branch_3_Name="test_Condenser Demand Bypass Branch",
    )
    idf.newidfobject(
        "CONNECTOR:MIXER",
        Name="test_Condenser Supply Mixer",
        Outlet_Branch_Name="test_Condenser Supply Outlet Branch",
        Inlet_Branch_1_Name="test_Condenser Supply GHE Branch",
        Inlet_Branch_2_Name="test_Condenser Supply Bypass Branch",
    )

    # ConnectorLists
    idf.newidfobject(
        "CONNECTORLIST",
        Name="test_Condenser Supply Side Connectors",
        Connector_1_Object_Type="Connector:Splitter",
        Connector_1_Name="test_Condenser Supply Splitter",
        Connector_2_Object_Type="Connector:Mixer",
        Connector_2_Name="test_Condenser Supply Mixer",
    )
    idf.newidfobject(
        "CONNECTORLIST",
        Name="test_Condenser Demand Side Connectors",
        Connector_1_Object_Type="Connector:Splitter",
        Connector_1_Name="test_Condenser Demand Spliter",
        Connector_2_Object_Type="Connector:Mixer",
        Connector_2_Name="test_Condenser Demand Mixer",
    )

    # ── CondenserLoop ──────────────────────────────────────────────────────────
    idf.newidfobject(
        "CONDENSERLOOP",
        Name="test_Water Source Heat Pump Condenser Loop",
        Fluid_Type="Water",
        Condenser_Equipment_Operation_Scheme_Name="test_Tower Loop Operation",
        Condenser_Loop_Temperature_Setpoint_Node_Name="test_Condenser Supply Outlet Node",
        Maximum_Loop_Temperature=80,
        Minimum_Loop_Temperature=10,
        Maximum_Loop_Flow_Rate=0.0099,
        Minimum_Loop_Flow_Rate=0,
        Condenser_Loop_Volume="autocalculate",
        Condenser_Side_Inlet_Node_Name="test_Condenser Supply Inlet Node",
        Condenser_Side_Outlet_Node_Name="test_Condenser Supply Outlet Node",
        Condenser_Side_Branch_List_Name="test_Condenser Supply Side Branches",
        Condenser_Side_Connector_List_Name="test_Condenser Supply Side Connectors",
        Demand_Side_Inlet_Node_Name="test_Condenser Demand Inlet Node",
        Demand_Side_Outlet_Node_Name="test_Condenser Demand Outlet Node",
        Condenser_Demand_Side_Branch_List_Name="test_Condenser Demand Side Branches",
        Condenser_Demand_Side_Connector_List_Name="test_Condenser Demand Side Connectors",
        Load_Distribution_Scheme="SequentialLoad",
    )

    # ── CondenserEquipment ─────────────────────────────────────────────────────
    idf.newidfobject(
        "CONDENSEREQUIPMENTLIST",
        Name="test_All Towers",
        Equipment_1_Object_Type="GroundHeatExchanger:System",
        Equipment_1_Name="test_Vertical Ground Heat Exchanger",
    )
    idf.newidfobject(
        "PLANTEQUIPMENTOPERATION:UNCONTROLLED",
        Name="test_Year Round Tower",
        Equipment_List_Name="test_All Towers",
    )
    idf.newidfobject(
        "CONDENSEREQUIPMENTOPERATIONSCHEMES",
        Name="test_Tower Loop Operation",
        Control_Scheme_1_Object_Type="PlantEquipmentOperation:Uncontrolled",
        Control_Scheme_1_Name="test_Year Round Tower",
        Control_Scheme_1_Schedule_Name="always_avail",
    )

    # ── AvailabilityManager entries ────────────────────────────────────────────
    idf.newidfobject(
        "AVAILABILITYMANAGER:SCHEDULED",
        Name="Heat Pump 1 Avail",
        Schedule_Name="always_avail",
    )
    idf.newidfobject(
        "AVAILABILITYMANAGERASSIGNMENTLIST",
        Name="test_Heat Pump 1 Avail List",
        Availability_Manager_1_Object_Type="AvailabilityManager:Scheduled",
        Availability_Manager_1_Name="Heat Pump 1 Avail",
    )

    # ── SetpointManager:FollowGroundTemperature ────────────────────────────────
    idf.newidfobject(
        "SETPOINTMANAGER:FOLLOWGROUNDTEMPERATURE",
        Name="test_MyCondenserControl",
        Control_Variable="Temperature",
        Reference_Ground_Temperature_Object_Type="Site:GroundTemperature:Deep",
        Offset_Temperature_Difference=0,
        Maximum_Setpoint_Temperature=80,
        Minimum_Setpoint_Temperature=10,
        Setpoint_Node_or_NodeList_Name="test_Condenser Supply Outlet Node",
    )

    # ── AirTerminal & ADU ──────────────────────────────────────────────────────
    idf.newidfobject(
        "AIRTERMINAL:SINGLEDUCT:CONSTANTVOLUME:NOREHEAT",
        Name="ZoneDirectAir_unit1",
        Availability_Schedule_Name="always_avail",
        Air_Inlet_Node_Name="test_Zone Inlet Node_unit1 ATInlet",
        Air_Outlet_Node_Name="test_Zone Inlet Node_unit1",
        Maximum_Air_Flow_Rate="autosize",
    )

    print("  All GSHP objects added.")


def convert_hp_to_gshp(input_idf_path, output_idf_path, idd_path=None):
    """Main conversion function."""
    print(f"\n{'='*60}")
    print(f"Converting: {input_idf_path}")
    print(f"Output:     {output_idf_path}")
    print(f"{'='*60}\n")

    # ── Set up IDD ──────────────────────────────────────────────────────────────
    if idd_path:
        IDF.setiddname(idd_path)
    else:
        # Try common EnergyPlus install locations
        candidate_idds = [
            r"C:\EnergyPlusV25-1-0\Energy+.idd",
            r"C:\EnergyPlusV24-2-0\Energy+.idd",
            "/usr/local/EnergyPlus-25-1-0/Energy+.idd",
            "/usr/local/EnergyPlus-24-2-0/Energy+.idd",
            "/Applications/EnergyPlus-25-1-0/Energy+.idd",
        ]
        for candidate in candidate_idds:
            if os.path.exists(candidate):
                IDF.setiddname(candidate)
                print(f"Using IDD: {candidate}")
                break
        else:
            raise FileNotFoundError(
                "Could not find Energy+.idd automatically.\n"
                "Please set IDD_PATH at the top of the script or pass it as the third argument.\n"
                "Typical location: C:\\EnergyPlusV25-1-0\\Energy+.idd"
            )

    # ── Load IDF ────────────────────────────────────────────────────────────────
    idf = IDF(input_idf_path)
    print("IDF loaded successfully.\n")

    # ── Step 1: Remove all AirflowNetwork objects ──────────────────────────────
    print("--- Step 1: Removing AirflowNetwork objects ---")
    for cls in AFN_CLASSES:
        remove_all_of_class(idf, cls)

    # ── Step 2: Remove air-source HP HVAC objects ──────────────────────────────
    print("\n--- Step 2: Removing air-source HP objects ---")
    for cls in HP_CLASSES_TO_REMOVE:
        remove_all_of_class(idf, cls)

    # Also remove the WaterHeater:HeatPump:WrappedCondenser that references HP
    remove_all_of_class(idf, "WATERHEATER:HEATPUMP:WRAPPEDCONDENSER")
    remove_all_of_class(idf, "COIL:WATERHEATING:AIRTOWATERHEATPUMP:WRAPPED")

    # ── Step 3: Update ZoneHVAC:EquipmentList ─────────────────────────────────
    print("\n--- Step 3: Updating ZoneHVAC:EquipmentList ---")
    update_zone_equipment_list(idf)

    # ── Step 4: Remove HP-related AirLoopHVAC (old one) ──────────────────────
    print("\n--- Step 4: Removing old AirLoopHVAC (AirToAir HP) ---")
    remove_all_of_class(idf, "AIRLOOPHVAC:UNITARYHEATPUMP:AIRTOAIR")
    # Remove old standalone AirLoopHVAC object that used the AirToAir HP
    for loop in list(idf.idfobjects.get("AIRLOOPHVAC", [])):
        if "WAHP" not in loop.Name and "WaterToAir" not in loop.Name:
            idf.removeidfobject(loop)
            print(f"  Removed AirLoopHVAC: {loop.Name}")

    # Remove old AirLoopHVAC:ZoneSplitter and AirLoopHVAC:SupplyPath
    # (new ones will be added with updated node names)
    remove_all_of_class(idf, "AIRLOOPHVAC:ZONESPLITTER")
    remove_all_of_class(idf, "AIRLOOPHVAC:SUPPLYPATH")
    remove_all_of_class(idf, "AIRLOOPHVAC:ZONEMIXER")
    remove_all_of_class(idf, "AIRLOOPHVAC:RETURNPATH")

    # ── Step 5: Add GSHP system ────────────────────────────────────────────────
    add_gshp_system(idf)

    # ── Save ────────────────────────────────────────────────────────────────────
    idf.saveas(output_idf_path)
    print(f"\n{'='*60}")
    print(f"Conversion complete! Output saved to: {output_idf_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nUsage: python convert_hp_to_gshp.py <input.idf> <output.idf> [path/to/Energy+.idd]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    idd = sys.argv[3] if len(sys.argv) > 3 else IDD_PATH

    convert_hp_to_gshp(input_path, output_path, idd)
