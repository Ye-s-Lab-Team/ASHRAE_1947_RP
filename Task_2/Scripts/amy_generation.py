'''
AMY Generation pipeline
1. check all location and year amy data is available
2. check how many lines are missed to set up 'max_missimg_amy_rows' parameter
3. loop the year and location
'''

# import library
import pandas as pd
import numpy as np
import diyepw

#%% define path

main = 'C:/Users/kkuio/OneDrive/바탕 화면/AMY/source/'
epw_saving = "C:/Users/kkuio/OneDrive/바탕 화면/AMY/AMY_epw"

#%% setup parameters

start_year = 1995
end_year = 2024+1
default = 9999

#%% weather station setup

data = {'climate_loc': ['1A', '2A', '2B', '3A', '3B', '3C', '4A', '4B', '4C',
                        '5A', '5B', '5C', '6A', '6B', '7', '8'], 
        'city': ['Miami', 'Tampa', 'Tucson', 'Atlanta', 'ElPaso', 'SanDiego', 
                 'NewYork', 'Albuquerque', 'Seattle', 'Buffalo', 'Denver',  
                 'PortAngeles', 'Rochester', 'GreatFalls', 'InternationalFalls', 
                 'Fairbank'],
        'weather_station': [722020, 747880, 722745, 722190, 722700, 722904, 
                            744860, 723650, 727930, 725280, 724695, 727885, 
                            726440, 727750, 727470, 702610]}
location = pd.DataFrame(data)

#%% analyze the file is suitable for AMY EPW generation
# need to check how many lines are missing
# set the max_missing_any_rows parameter as this maximum missing rows

analysis_result = {}
total_missing = np.zeros(len(location))
max_missing = np.zeros(len(location))


for y in range(start_year, end_year):
    for i in range(len(location)):
        # print(location['city'][i])
        temp = diyepw.analyze_noaa_isd_lite_file(main + location['city'][i]+'/'+ str(location['weather_station'][i])+'-'+str(y) + '.gz', compression='gzip')
        total_missing[i] = temp.get('total_rows_missing')
        max_missing[i] = temp.get('max_consec_rows_missing')
        analysis_result[f"missing_data_{y}"] = pd.concat([location, pd.DataFrame(total_missing, columns=['total_rows_missing']), pd.DataFrame(max_missing, columns=['max_consec_rows_missing'])], axis = 1)
        

#%% work on a single file AMY generation

# loop location
for i in range(len(location)):
    loc = location['weather_station'][i]
    city = location['city'][i]
    for year in range(start_year, end_year):
        print(year, city)
        tot_missing = analysis_result[f"missing_data_{year}"].loc[i, 'total_rows_missing']
        max_missing = analysis_result[f"missing_data_{year}"].loc[i, 'max_consec_rows_missing']
        # AMY generation
        diyepw.create_amy_epw_file(loc, year, max_missing_amy_rows=default, max_records_to_impute = default, 
                                   allow_downloads = True, amy_epw_dir=epw_saving)


'''
        wmo_index: int,
        year: int,
        *,
        max_records_to_interpolate: int = 6,
        max_records_to_impute: int = 48,
        max_missing_amy_rows: int = 700,
        amy_epw_dir: str = None,
        tmy_epw_dir: str = None,
        amy_dir: str = None,
        amy_files: Tuple[str, str] = None,
        allow_downloads: bool = False
'''