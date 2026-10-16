import os
import re
import glob
from eppy.modeleditor import IDF


# IECC Climate locations
CLIMATE_ZONES = {"Miami": "1A", "Tampa": "2A", "Tucson": "2B",
    "Atlanta": "3A", "ElPaso": "3B", "SanDiego": "3C",
    "NewYork": "4A", "Albuquerque": "4B", "Seattle": "4C",
    "Buffalo": "5A", "Denver": "5B", "PortAngeles": "5C",
    "Rochester": "6A", "GreatFalls": "6B", "InternationalFalls": "7",
    "Duluth": "7", "Fairbanks": "8"}


def replace_pvwatts_inverter(idf, availability_schedule=""):
    """
    ElectricLoadCenter:Inverter:PVWatts -> Inverter:Simple.
    to simulate power outage scenario in Measure 2 (Model 3).
    PVWatt inverter does not support availability schedule,
    so it cannot be turned off in power outage scenario.
    Apply the same inverter model to Measure 1 and Measure 2 model.
      - New model 1       : availability_schedule="" (always available)
      - New model 3 : availability_schedule="PowerOutage_Avail"
    """
    n = 0
    for old in list(idf.idfobjects["ELECTRICLOADCENTER:INVERTER:PVWATTS"]):
        name, eff = old.Name, old.Inverter_Efficiency or 0.96
        idf.removeidfobject(old)
        idf.newidfobject("ELECTRICLOADCENTER:INVERTER:SIMPLE", Name=name,
                         Availability_Schedule_Name=availability_schedule,
                         Radiative_Fraction=0, Inverter_Efficiency=eff)
        n += 1
    return n

def run_measure1(input_dir, iddfile, output_dir="NewModel1"):
    """
    Change all Coil:Heating:Fuel objects into Coil:Heating:Electric in input_dir,
    modified idf file will be named as 
    'NewModel1_{building type}_{climate zone}_{city}.idf' and saved in output_dir."""
    
    coil_gas = "Coil:Heating:Fuel"
    coil_elec = "Coil:Heating:Electric"

    IDF.setiddname(iddfile)
    os.makedirs(output_dir, exist_ok=True)

    idf_files = sorted(glob.glob(os.path.join(input_dir, "*.idf")))
    if not idf_files:
        print(f"No idf file: {input_dir}")
        return []

    saved = []
    for path in idf_files:
        fname = os.path.basename(path)

        # extract building type and city from the file name
        m = re.match(r"^ASHRAE901_(?P<btype>[^_]+)_STD\d+_(?P<city>.+)\.idf$", fname, re.I)
        if not m:
            print(f"[skip] different file naming format: {fname}")
            continue
        btype, city = m.group("btype"), m.group("city")
        cz = CLIMATE_ZONES.get(city, "CZunknown")
        if cz == "CZunknown":
            print(f"[warn] no climate location in the list: {city}, add to CLIMATE_ZONES")

        idf = IDF(path)
        gas_coils = list(idf.idfobjects[coil_gas])
        if not gas_coils:
            print(f"[skip] no {coil_gas} : {fname}")
            continue

        # refer existing electricity coil efficiency (1.0, if no referrable value exist)
        elec_existing = idf.idfobjects[coil_elec]
        efficiency = elec_existing[0].Efficiency if elec_existing else 1.0
        if efficiency in ("", None):
            efficiency = 1.0

        # create electricity heating coil and change gas coil objects into electricity coil
        gas_names = set()
        for g in gas_coils:
            gas_names.add(g.Name.upper())
            idf.newidfobject(
                coil_elec,
                Name=g.Name,
                Availability_Schedule_Name=g.Availability_Schedule_Name,
                Efficiency=efficiency,
                Nominal_Capacity=g.Nominal_Capacity,
                Air_Inlet_Node_Name=g.Air_Inlet_Node_Name,
                Air_Outlet_Node_Name=g.Air_Outlet_Node_Name,
                Temperature_Setpoint_Node_Name=g.Temperature_Setpoint_Node_Name,
            )

        # Change all objects connected to gas coil objects
        n_ref = 0
        for objs in idf.idfobjects.values():
            for obj in objs:
                vals = obj.obj
                for k in range(1, len(vals) - 1):
                    if (isinstance(vals[k], str) and vals[k].upper() == coil_gas.upper()
                            and str(vals[k + 1]).upper() in gas_names):
                        vals[k] = coil_elec
                        n_ref += 1

        # delete gas coils
        for g in gas_coils:
            idf.removeidfobject(g)
        
        # change PV inverter
        n_inv = replace_pvwatts_inverter(idf)

        # save modified idf file
        out_path = os.path.join(output_dir, f"NewModel1_{btype}_{cz}_{city}.idf")
        idf.saveas(out_path)
        saved.append(out_path)
        print(f"[ok] {fname} → {os.path.basename(out_path)} "
              f"({len(gas_coils)} gas coils are replaced, edited {n_ref})")

    print(f"\nDone: {len(saved)}/{len(idf_files)} files are saved in {output_dir}")
    return saved


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_root = os.path.join(script_dir, "..", "..", "Original_model")
    run_measure1(
        input_dir=os.path.join(model_root, "office"),
        iddfile=r"C:\EnergyPlusV25-1-0\Energy+.idd",
        output_dir=os.path.join(script_dir, "..", "NewModel1"),)
