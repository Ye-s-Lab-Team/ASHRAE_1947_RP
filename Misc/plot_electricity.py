import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os

CSV_FILE = 'Measure5_winter_residential.csv'
# '/Users/harry/Downloads/Measure3_winter_residential.csv'   
# filename path, following the format "Measure3_[winter/summer]_[office/residential].csv"

basename = os.path.basename(CSV_FILE).lower()
if "summer" in basename:
    season = "Summer"
elif "winter" in basename:
    season = "Winter"
else:
    season = "Winter/Summer"

if "office" in basename:
    building_type = "Office"
elif "residential" in basename:
    building_type = "Residential"
else:
    building_type = "Building"

title = f"{season} season electricity consumption ({building_type})"
# title = f"{season} season HVAC energy consumption ({building_type})"


df = pd.read_csv(CSV_FILE)

df.columns = df.columns.str.strip()

x      = df["Date/Time"]
y_orig = df["Original"] #for measures
# y_orig = df["Electricity"] #for model 2
# labelname_elec = 'Electricity'
y_mod  = df["Measure 5 modified"] #for measures
labelname = "Measure 5 modified"

# y_mod  = df["Natural gas"] #for model 2
# labelname_gas = "Natural Gas"

plt.rcParams["font.family"]      = "Times New Roman"
plt.rcParams["font.size"]        = 18
plt.rcParams["axes.titlesize"]   = 18
plt.rcParams["axes.labelsize"]   = 15
plt.rcParams["xtick.labelsize"]  = 13
plt.rcParams["ytick.labelsize"]  = 13
plt.rcParams["legend.fontsize"]  = 15

fig, ax = plt.subplots(figsize=(11.1, 6.5), dpi=300)

ax.plot(x, y_orig, color="#1500FF", linewidth=1.5,
        label='Original', marker = 'o', markersize = 3)
ax.plot(x, y_mod,  color="#FF0000", linewidth=1.5,
        label=labelname, marker = 'D', markersize = 3)
# ax.plot(x, y_mod,  color="#FF0000", linewidth=1.5,
#         label=labelname_gas, marker = 'D', markersize = 3)

ax.set_title(title, pad=14)
ax.set_ylabel("HVAC Energy consumption [MJ]")
ax.set_xlabel("")

# except m2
# ax.set_xticks(range(0, len(x)))
# ax.set_xticklabels(x, rotation = -45, ha="left")
# plt.margins(x=0.01)

#for m2
step = max(1, len(x) // 20)  # show ~20 labels max
ax.set_xticks(range(0, len(x), step))
ax.set_xticklabels([x[i] for i in range(0, len(x), step)], rotation=-45, ha = 'left')


y_all = pd.concat([y_orig, y_mod])
y_min, y_max = 0, y_all.max()
margin = (y_max - y_min) * 0.08
ax.set_ylim(y_min, y_max + margin)

ax.grid(axis="y", linestyle="--", alpha=0.7)

ax.yaxis.set_major_formatter(ticker.FuncFormatter(
    lambda val, _: f"{val:,.0f}"))

ax.legend(
    loc="upper center",
    bbox_to_anchor=(0.5, -0.30),
    ncol=2,
    frameon=False,
    handlelength=2.2,
    columnspacing=2.5,
)

plt.tight_layout()

out_name = os.path.splitext(CSV_FILE)[0] + "_plot.png"
plt.savefig(out_name, dpi=300, bbox_inches="tight")
plt.show()
