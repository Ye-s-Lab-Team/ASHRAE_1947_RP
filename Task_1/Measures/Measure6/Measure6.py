"""
EnergyPlus simulation and required metrics saving
"""

import os
import re
import glob
import math
import shutil
import subprocess
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from eppy.modeleditor import IDF

import EnergyPlus_Metrics as em


# Paths 
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TASK_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))      

ENERGYPLUS_DIR = r"C:\EnergyPlusV25-1-0"
EXE = ".exe" if os.name == "nt" else ""
ENERGYPLUS_EXE = os.path.join(ENERGYPLUS_DIR, "energyplus" + EXE)
EXPANDOBJECTS_EXE = os.path.join(ENERGYPLUS_DIR, "ExpandObjects" + EXE)
GROUND_DIR = os.path.join(ENERGYPLUS_DIR, "PreProcess", "GrndTempCalc")    # Slab, Basement preprocessor
IDD_PATH = os.path.join(ENERGYPLUS_DIR, "Energy+.idd")

# EnergyPlus idf files location
MODEL_DIRS = sorted(glob.glob(os.path.join(TASK_ROOT, "Measure*", "NewModel*")))
# Weather file location
WEATHER_ROOT = os.path.normpath(os.path.join(TASK_ROOT, "..", "Task2", "weather_files"))
RESULTS_ROOT = os.path.join(TASK_ROOT, "results")
RUN_LOG_CSV = os.path.join(RESULTS_ROOT, "run_log.csv")
FIXED_WEATHER_DIR = os.path.join(RESULTS_ROOT, "_fixed_weather")   # Leap year and empty data preprocessing

N_WORKERS = max(1, (os.cpu_count() or 2) - 1)               # parallel simulation
RUN_PREPROCESSORS = True    # ExpandObjects + Slab/Basement preprocessing, only for the residential building

MAX_DISTANCE_KM = 100.0     # weather file matching
LOG_ONLY = False            # True: run error file and logging without additional simulation 
SKIP_EXISTING = True        # skip the previous simulation (only succeeded)


# Weather file selection

def epw_location(path: str) -> dict:
    """the first line of the epw: LOCATION,city,state,country,source,WMO,lat,lon,tz,elev"""
    with open(path, "r", encoding="latin-1") as f:
        v = [x.strip() for x in f.readline().split(",")]
    return dict(path=path, city=v[1], state=v[2], lat=float(v[6]), lon=float(v[7]))


def idf_location(idf_path: str) -> dict:
    idf = IDF(idf_path)
    loc = idf.idfobjects["SITE:LOCATION"][0]
    return dict(name=loc.Name, lat=float(loc.Latitude), lon=float(loc.Longitude))


def distance_km(a: dict, b: dict) -> float:
    """haversine: distance between two locations (from idf and from epw)"""
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def weather_groups(root: str) -> dict:
    """
    grouping by location
    """
    groups = {}
    for path in sorted(glob.glob(os.path.join(root, "**", "*.epw"), recursive=True)):
        rel = os.path.relpath(path, root).split(os.sep)
        wtype = rel[0] if len(rel) > 1 else os.path.basename(root)
        loc = epw_location(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        m = re.match(r"^\d+-(.+)_[^_]+$", stem)           
        variant = m.group(1) if m else wtype
        key = wtype if variant == wtype else f"{wtype}/{variant}"
        groups.setdefault(key, []).append(loc)
    return groups


def fix_epw_blanks(epw_path: str) -> tuple:
    """
    proximate interpolation: fill in the nearest value
    """
    with open(epw_path, encoding="latin-1") as f:
        lines = f.read().splitlines()
    header, data = lines[:8], [l.split(",") for l in lines[8:] if l.strip()]
    blanks = [(i, j) for i, row in enumerate(data) for j, v in enumerate(row) if j > 5 and v.strip() == ""]
    if not blanks:
        return epw_path, ""
    for i, j in blanks:
        later = (data[k][j] for k in range(i + 1, len(data)) if data[k][j].strip())
        earlier = (data[k][j] for k in range(i - 1, -1, -1) if data[k][j].strip())
        data[i][j] = next(later, None) or next(earlier, "")
    rel = os.path.relpath(epw_path, WEATHER_ROOT)
    fixed = os.path.join(FIXED_WEATHER_DIR, rel)
    os.makedirs(os.path.dirname(fixed), exist_ok=True)
    with open(fixed, "w", encoding="latin-1", newline="\r\n") as f:
        f.write("\n".join(header + [",".join(r) for r in data]) + "\n")
    hours = sorted({i for i, _ in blanks})
    return fixed, f"{len(blanks)} blanks were interpolated, ({len(hours)} hours, first row: {','.join(data[hours[0]][:4])})"


def pick_weather(site: dict, epws: list) -> tuple:
    """the distance from the nearest weather file location (km)))"""
    best = min(epws, key=lambda e: distance_km(site, e))
    return best, distance_km(site, best)


# Run EnergyPlus

def finished_ok(run_dir: str) -> bool:
    end = os.path.join(run_dir, "eplusout.end")
    return os.path.isfile(end) and "Successfully" in open(end, encoding="latin-1").read()


def _run(cmd: list, cwd: str, log_name: str) -> None:
    with open(os.path.join(cwd, log_name), "w") as log:
        subprocess.run(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)


def write_epw_without_leap_day(epw_path: str, dst: str) -> None:
    """
    writing epw copy without leap day for preprocessor running
    """
    with open(epw_path, encoding="latin-1") as f:
        lines = f.read().splitlines()
    data = [l for l in lines[8:] if l.strip()]
    if len(data) > 8760:
        data = [l for l in data if l.split(",")[1:3] != ["2", "29"]]
    with open(dst, "w", encoding="latin-1", newline="\r\n") as f:
        f.write("\n".join(lines[:8] + data) + "\n")


def run_preprocessors(idf_path: str, epw_path: str, run_dir: str) -> str:
    shutil.copy(idf_path, os.path.join(run_dir, "in.idf"))
    shutil.copy(IDD_PATH, os.path.join(run_dir, "Energy+.idd"))
    _run([EXPANDOBJECTS_EXE], run_dir, "expandobjects.log")
    expanded = os.path.join(run_dir, "expanded.idf")
    text = open(expanded if os.path.isfile(expanded) else idf_path, encoding="latin-1").read()

    ground = [("GHTIn.idf", "Slab", "SlabGHT.idd", "SLABSurfaceTemps.TXT"),
              ("BasementGHTIn.idf", "Basement", "BasementGHT.idd", "EPObjects.TXT")]
    for ght_in, prog, idd, result in ground:
        if not os.path.isfile(os.path.join(run_dir, ght_in)):
            continue
        shutil.copy(os.path.join(GROUND_DIR, idd), os.path.join(run_dir, idd))
        if prog == "Basement":
            write_epw_without_leap_day(epw_path, os.path.join(run_dir, "in.epw"))
        else:
            shutil.copy(epw_path, os.path.join(run_dir, "in.epw"))
        _run([os.path.join(GROUND_DIR, prog + EXE)], run_dir, f"{prog.lower()}.log")
        out = os.path.join(run_dir, result)
        if not os.path.isfile(out):
            raise RuntimeError(f"{prog} preprocessing failed. check ({prog.lower()}.log)")
        result_text = open(out, encoding="latin-1").read()
        if "OtherSideCoefficients" not in result_text:            # preprocessor run, but no result
            tail = open(os.path.join(run_dir, f"{prog.lower()}.log"), encoding="latin-1").read().strip()
            raise RuntimeError(f"{prog} no boundary condition in preprocessing results. check {prog.lower()}.log: "
                               f"{' / '.join(tail.splitlines()[-3:])}")
        text += "\n\n" + result_text
    if os.path.isfile(os.path.join(run_dir, "in.epw")):
        os.remove(os.path.join(run_dir, "in.epw"))        # delete the copy of epw

    sim_idf = os.path.join(run_dir, "sim.idf")
    with open(sim_idf, "w", encoding="latin-1") as f:
        f.write(text)
    return sim_idf


HARMLESS_SEVERE = ("SetDXCoilAirLoopNumber",)   # severe error in AFN + VS coil (does not affact the result)


def _message(lines: list, i: int) -> str:
    """ith error line + following error description '**   ~~~   **'"""
    msg = [re.split(r"\*\*\s*(?:Fatal|Severe|Warning)\s*\*\*", lines[i], maxsplit=1)[-1].strip()]
    for line in lines[i + 1:i + 4]:
        if "~~~" not in line:
            break
        msg.append(line.split("~~~", 1)[1].strip(" *"))
    return " | ".join(m for m in msg if m)[:300]


def err_summary(run_dir: str) -> dict:
    """
    eplusout.err 
    the number of warning, severe, Fatal message. the first severe, the most repeated error
    (EnergyPlus message: '**  Fatal  **', '** Severe  **', '** Warning **')
    """
    err = os.path.join(run_dir, "eplusout.err")
    if not os.path.isfile(err):
        return dict(warnings=None, severe=None, fatal="no eplusout.err", first_severe="", top_warning="")
    lines = open(err, encoding="latin-1").read().splitlines()
    kind = lambda l: (re.search(r"\*\*\s*(Fatal|Severe|Warning)\s*\*\*", l) or [None, None])[1]

    fatal = next((_message(lines, i) for i, l in enumerate(lines) if kind(l) == "Fatal"), "")
    first_severe = next((_message(lines, i) for i, l in enumerate(lines)
                         if kind(l) == "Severe" and not any(h in l for h in HARMLESS_SEVERE)), "")
    counts = {}
    for i, l in enumerate(lines):
        if kind(l) == "Warning":
            key = re.sub(r"\d+(\.\d+)?", "#", _message(lines, i).split(" | ")[0])[:120]   # considering as the same error if only the number is different
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            rep = re.search(r"occurred\s+(\d+)\s+total times", nxt)                   # repeated warning summary
            counts[key] = counts.get(key, 0) + (int(rep.group(1)) if rep else 1)
    top = max(counts.items(), key=lambda kv: kv[1]) if counts else None

    m = None
    for line in reversed(lines):
        m = re.search(r"(\d+) Warning; (\d+) Severe Errors", line)
        if m:
            break
    return dict(warnings=int(m.group(1)) if m else None, severe=int(m.group(2)) if m else None,
                fatal=fatal, first_severe=first_severe,
                top_warning=f"[{top[1]} times] {top[0]}" if top else "")


def run_energyplus(idf_path: str, epw_path: str, run_dir: str) -> dict:
    t0 = time.time()
    try:
        sim_idf = run_preprocessors(idf_path, epw_path, run_dir) if RUN_PREPROCESSORS else idf_path
        _run([ENERGYPLUS_EXE, "-w", epw_path, "-d", run_dir, "-r", sim_idf], run_dir, "run.log")
        info = err_summary(run_dir)
        info["status"] = "ok" if finished_ok(run_dir) else "FAILED"
    except Exception as e:                                    # preprocessor, exe file issue, etc. 
        info = dict(status="FAILED", warnings=None, severe=None, fatal=str(e)[:300],
                    first_severe="", top_warning="")
    info["minutes"] = round((time.time() - t0) / 60, 1)
    return info


def describe(info: dict) -> str:
    if info["status"] == "ok":
        return f"ok ({info['minutes']} min, warning {info['warnings']}, severe {info['severe']})"
    if info["status"] == "skipped":
        return "skipped (previously run)"
    return f"FAILED — {(info['fatal'] or info['first_severe'])[:150]}"


def save_run_log(rows: list) -> None:
    """run log CSV"""
    cols = ["time", "weather", "measure", "model", "status", "minutes", "warnings", "severe",
            "fatal", "first_severe", "top_warning", "epw", "epw_distance_km", "epw_note", "run_dir"]
    pd.DataFrame(rows).reindex(columns=cols).to_csv(RUN_LOG_CSV, index=False, encoding="utf-8-sig")




# main
def main():
    if IDF.getiddname() is None:
        IDF.setiddname(IDD_PATH)

    idfs = sorted(p for d in MODEL_DIRS for p in glob.glob(os.path.join(d, "*.idf")))
    groups = weather_groups(WEATHER_ROOT)
    print(f"({len(MODEL_DIRS)} model folders): " + ", ".join(os.path.relpath(d, TASK_ROOT) for d in MODEL_DIRS))
    print(f"{WEATHER_ROOT} weather file folders")
    if not idfs or not groups:
        print(f" {len(idfs)} idf files, {len(groups)} epw groups — check the file exist"
              f"\n    (TASK_ROOT = {TASK_ROOT})")
        return
    print(f" {len(idfs)}idf files × {len(groups)} weather file groups: "
          + ", ".join(f"{g} ({len(e)} cities)" for g, e in groups.items()) + "\n")

    # check epw files for data failure
    fixed_epw = {}
    for epws in groups.values():
        for e in epws:
            fixed_epw[e["path"]] = fix_epw_blanks(e["path"])
    notes = {p: n for p, (_, n) in fixed_epw.items() if n}
    if notes:
        print(f" {len(notes)} data failures, use interpolated file)")
        for p, n in notes.items():
            print(f"   {os.path.relpath(p, WEATHER_ROOT)}: {n}")
        print()

    # run list
    jobs = []
    sites = {p: idf_location(p) for p in idfs}
    for group, epws in groups.items():
        print(f"── {group}")
        for idf_path in idfs:
            stem = os.path.splitext(os.path.basename(idf_path))[0]
            epw, km = pick_weather(sites[idf_path], epws)
            flag = "" if km <= MAX_DISTANCE_KM else f"  [warn] {km:.0f} additional epw is needed"
            print(f"   {stem:<55} ← {os.path.basename(epw['path'])} ({km:.0f} km){flag}")
            jobs.append(dict(weather=group, src=idf_path, epw=fixed_epw[epw["path"]][0],
                             epw_note=fixed_epw[epw["path"]][1], km=round(km, 1),
                             run_dir=os.path.join(RESULTS_ROOT, *group.split("/"), stem)))

    def log_row(job, info):
        return dict(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), weather=job["weather"],
                    measure=os.path.relpath(os.path.dirname(job["src"]), TASK_ROOT),
                    model=os.path.basename(job["run_dir"]), epw=os.path.basename(job["epw"]),
                    epw_distance_km=job["km"], epw_note=job["epw_note"], run_dir=job["run_dir"], **info)

    if LOG_ONLY:                                                 
        rows = [log_row(j, dict(status="ok" if finished_ok(j["run_dir"]) else "FAILED",
                                **err_summary(j["run_dir"])))
                for j in jobs if os.path.isdir(j["run_dir"])]
        save_run_log(rows)
        print(f"\n[saved] {RUN_LOG_CSV}  ({sum(r['status'] == 'FAILED' for r in rows)})")
        return

    # gathering the required matrics
    os.makedirs(RESULTS_ROOT, exist_ok=True)
    log_rows, todo = [], []
    for job in jobs:
        if SKIP_EXISTING and finished_ok(job["run_dir"]):
            log_rows.append(log_row(job, dict(status="skipped", **err_summary(job["run_dir"]))))
            continue
        os.makedirs(job["run_dir"], exist_ok=True)
        job["run_idf"] = os.path.join(job["run_dir"], os.path.basename(job["src"]))
        em.prepare_idf(job["src"], job["run_idf"])
        todo.append(job)
    print(f"\n {len(todo)} files ({len(jobs)} were already done, skip {len(todo)} files), {N_WORKERS} in parallel \n")

    # parallel simulation running
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(run_energyplus, j["run_idf"], j["epw"], j["run_dir"]): j for j in todo}
        for i, f in enumerate(as_completed(futures), 1):
            job, info = futures[f], f.result()
            print(f"  [{i}/{len(todo)}] {job['weather']}/{os.path.basename(job['run_dir'])}: {describe(info)}")
            log_rows.append(log_row(job, info))
            save_run_log(log_rows)
    save_run_log(log_rows)
    n_fail = sum(r["status"] == "FAILED" for r in log_rows)
    print(f"\n[saved] {RUN_LOG_CSV}  ({n_fail} failed)")

    # save matrics
    long_rows = []
    for group in groups:
        dirs = {os.path.basename(j["run_dir"]): j["run_dir"] for j in jobs
                if j["weather"] == group and finished_ok(j["run_dir"])}
        if not dirs:
            continue
        table = em.metrics_table(dirs)
        label = group.replace("/", "_")
        out = os.path.join(RESULTS_ROOT, *group.split("/"), f"metrics_{label}.csv")
        table.to_csv(out, encoding="utf-8-sig")
        print(f"\n[saved] {out}")
        long = table.reset_index().melt(id_vars="index", var_name="model", value_name="value")
        long.insert(0, "weather", group)
        long_rows.append(long.rename(columns={"index": "metric"}))
    if long_rows:
        out = os.path.join(RESULTS_ROOT, "metrics_all.csv")
        pd.concat(long_rows).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"[saved] {out}")


if __name__ == "__main__":
    main()