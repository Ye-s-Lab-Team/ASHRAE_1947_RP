'''
Change HVAC and hot water system to unintegrated ASHP

Referenced prototype building models: medium office, residential-gas furnace, residential-hp
'''


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
office1 = "../Building_models/original_versiontrans/mid_office/ASHRAE901_OfficeMedium_STD2022/"
residential1 = "../Building_models/original_versiontrans/residential/resstd_IECC_2024/hp/"

midofficeidf = "ASHRAE901_OfficeMedium_STD2022_NewYork.idf"
residf = "US+SF+CZ4A+hp+slab+IECC_2024.idf"



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
# off1 = IDF(1 + midofficeidf)

# res_ref1 = IDF(refRes1 + refidf)


newpath = "../Task1/Measure3/"


#%% check the field name: residential

def measure3_residential(res1):
    
    # check the field name
    # define water heater related objects
    
    wh_mix = "WaterHeater:Mixed"
    wh_hp = "WaterHeater:HeatPump:WrappedCondenser" #need to change all of this object to mixed water heater
    wh_size = "WaterHeater:Sizing"
    wh_branch = "Branch"
    wh_plant = "PlantEquipmentList"
    
    
    # check the fieldnames
    
    wh_hp_obj = res1.idfobjects[wh_hp][0]
    wh_size_obj = res1.idfobjects[wh_size][0]
    wh_plant_obj = res1.idfobjects[wh_plant][0]
    
    wh_hp_fields = wh_hp_obj.fieldnames
    wh_size_fields = wh_size_obj.fieldnames
    wh_plant_fields = wh_plant_obj.fieldnames
    
    


    # add water heater(mixed) objects
    
    # add new water heater object
    new_wh = res1.newidfobject(wh_mix)
    
    # check the field name
    wh_mix_fields = res1.idfobjects[wh_mix][0].fieldnames
        
    # fill the object fields
    new_wh.Name = 'Water Heater_unit1'
    new_wh.Tank_Volume = '0.15141644'
    new_wh.Setpoint_Temperature_Schedule_Name = 'dhw_setpt'
    new_wh.Deadband_Temperature_Difference = '2'
    new_wh.Maximum_Temperature_Limit = '50'
    new_wh.Heater_Control_Type = 'Cycle'
    new_wh.Heater_Maximum_Capacity = 'autosize'
    new_wh.Heater_Minimum_Capacity = '0'
    new_wh.Heater_Ignition_Minimum_Flow_Rate = '0'
    new_wh.Heater_Fuel_Type = 'Electricity'
    new_wh.Heater_Thermal_Efficiency = '0.8'
    new_wh.Ambient_Temperature_Indicator = 'Zone'
    new_wh.Ambient_Temperature_Zone_Name = 'garage1'
    new_wh.Off_Cycle_Loss_Coefficient_to_Ambient_Temperature = '5.58332533E+00'
    new_wh.Off_Cycle_Loss_Fraction_to_Zone = '1'
    new_wh.On_Cycle_Loss_Coefficient_to_Ambient_Temperature = '5.58332533E+00'
    new_wh.On_Cycle_Loss_Fraction_to_Zone = '1'
    new_wh.Peak_Use_Flow_Rate = '0'
    new_wh.Use_Side_Inlet_Node_Name = 'Water Heater use inlet node_unit1'
    new_wh.Use_Side_Outlet_Node_Name = 'Water Heater use outlet node_unit1'
    new_wh.Use_Side_Effectiveness = '1'
    new_wh.Source_Side_Effectiveness = '1'
    new_wh.Use_Side_Design_Flow_Rate = 'autosize'
    new_wh.Source_Side_Design_Flow_Rate = '0'
    new_wh.Indirect_Water_Heating_Recovery_Time = '1.5'

    # add water heater sizing object
    
    # add new water heater object
    new_wh_size = res1.newidfobject(wh_size)
    
    # fill the object fields
    new_wh_size.WaterHeater_Name = 'Water Heater_unit1'
    new_wh_size.Design_Mode = 'ResidentialHUD-FHAMinimum'
    new_wh_size.Number_of_Bedrooms = '3'
    new_wh_size.Number_of_Bathrooms = '3'


    # change related objects
    
    # define related objects
    wh_plant_obj.Equipment_1_Object_Type = wh_mix
    
    branch = res1.idfobjects[wh_branch]
    
    print(branch)
    
    for b in range(len(branch)):
        if branch[b].Name == 'Water Heater Branch_unit1':
            # print('got it!')
            branch[b].Component_1_Object_Type = wh_mix
        else:
            pass

    # save idf file
    
    location = res1.idfobjects['Site:Location'][0].Name
    
    
    table = location.maketrans({
        '=': '', 
        ',': '', 
        '%': '',
        '^': '',
        '&': ''
    })
    
    print(location.translate(table))
    location = location.translate(table)
    
    
    res1_modified = res1.saveas(newpath + "test_" + location + '.idf')
    
    return(res1_modified)


#%% test

res1_modified = measure3_residential(res1)















