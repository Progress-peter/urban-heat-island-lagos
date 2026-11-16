# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3
#     name: python3
# ---

# %% [markdown]
# # Lagos Urban Heat Island, 2019–2025 (observed) → 2027, 2029 (projected)
#
# **Landsat 8/9 C2 L2 land surface temperature (LST) · Dynamic World built-up · 20 LGAs**
#
# | Epoch | Imagery window (dry season, December-centred) | Status |
# |---|---|---|
# | 2019 | 1 Nov 2019 – 29 Feb 2020 | observed (baseline) |
# | 2021 | 1 Nov 2021 – 28 Feb 2022 | observed |
# | 2023 | 1 Nov 2023 – 29 Feb 2024 | observed |
# | 2025 | 1 Nov 2025 – 28 Feb 2026 | observed |
# | 2027 | — | projected (scenarios) |
# | 2029 | — | projected (scenarios) |
#
# Key metric: **heat excess** = mean LST of an area − mean LST of vegetated land in Lagos State *in the same epoch*.
# Both terms share the same weather, so heat excess is comparable across years in a way raw LST is not.
#
# Run top to bottom in Google Colab. Output: `uhi_outputs.zip` → unzip into the repo root
# (fills `docs/data/` for the web map and `results/figures/` for the README).

# %% [markdown]
# ## 1. Configuration

# %%
EE_PROJECT = "your-ee-project-id"       # Earth Engine Cloud project (non-commercial)

EPOCHS = [
    {"id": "2019", "year": 2019, "start": "2019-11-01", "end": "2020-03-01", "label": "Dec 2019 (Nov–Feb)"},
    {"id": "2021", "year": 2021, "start": "2021-11-01", "end": "2022-03-01", "label": "Dec 2021 (Nov–Feb)"},
    {"id": "2023", "year": 2023, "start": "2023-11-01", "end": "2024-03-01", "label": "Dec 2023 (Nov–Feb)"},
    {"id": "2025", "year": 2025, "start": "2025-11-01", "end": "2026-03-01", "label": "Dec 2025 (Nov–Feb)"},
]
OBS_YEARS = [e["year"] for e in EPOCHS]
BASE_YEAR = OBS_YEARS[-1]                  # projections start from the latest observed epoch
PROJECTION_YEARS = [2027, 2029]
# Dynamic World built-up: annual mode for the calendar year of each epoch
DW_WINDOWS = {y: (f"{y}-01-01", f"{y + 1}-01-01") for y in OBS_YEARS}

MAX_SCENE_CLOUD = 40              # % scene cloud cover filter (pixel mask applied after)
MIN_CLEAR_OBS = 3                 # minimum clear observations per pixel
LST_VALID_RANGE = (10, 70)        # °C plausibility filter
SCALE = 30                        # m
COVERAGE_MIN_LGA = 0.30           # LGA-epoch rows with <30% valid land pixels are excluded from modelling
HOTSPOT_PERCENTILE = 90           # hotspot = heat excess >= baseline-epoch 90th percentile
BOOTSTRAP_N = 2000
SEED = 42
PNG_DIMENSIONS = 1600

VEG_REF = [1, 2, 4, 5]            # Dynamic World: trees, grass, crops, shrub & scrub (flooded veg excluded)
PAL_LST = ["313695", "4575b4", "74add1", "abd9e9", "fee090", "fdae61", "f46d43", "d73027", "a50026"]
PAL_DIV = ["2166ac", "67a9cf", "d1e5f0", "f7f7f7", "fddbc7", "ef8a62", "b2182b"]

# %% [markdown]
# ## 2. Setup

# %%
import json, os, shutil, datetime as dt
import numpy as np
import requests
import ee
import matplotlib.pyplot as plt

try:
    ee.Initialize(project=EE_PROJECT)
except Exception:
    ee.Authenticate()
    ee.Initialize(project=EE_PROJECT)

OUT = "uhi_outputs"
DATA = os.path.join(OUT, "docs", "data")
FIGS = os.path.join(OUT, "results", "figures")
os.makedirs(DATA, exist_ok=True); os.makedirs(FIGS, exist_ok=True)
FIRST, LAST = EPOCHS[0]["id"], EPOCHS[-1]["id"]

# %% [markdown]
# ## 3. Study area — Lagos State and LGAs (FAO GAUL 2015)

# %%
f_ng_lagos = ee.Filter.And(ee.Filter.eq("ADM0_NAME", "Nigeria"), ee.Filter.eq("ADM1_NAME", "Lagos"))
state = ee.FeatureCollection("FAO/GAUL/2015/level1").filter(f_ng_lagos)
lgas = ee.FeatureCollection("FAO/GAUL/2015/level2").filter(f_ng_lagos)
assert state.size().getInfo() == 1, "Lagos State not found in GAUL level1"
aoi = state.geometry()
bbox = aoi.bounds()
ring = bbox.coordinates().getInfo()[0]
BOUNDS = [[min(p[1] for p in ring), min(p[0] for p in ring)], [max(p[1] for p in ring), max(p[0] for p in ring)]]
LGAS = sorted(lgas.aggregate_array("ADM2_NAME").getInfo())
print(len(LGAS), "LGAs:", ", ".join(LGAS))

# %% [markdown]
# ## 4. Dynamic World land cover per epoch and a fixed land mask

# %%
def dw_label(year):
    a, b = DW_WINDOWS[year]
    return (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(aoi).filterDate(a, b)
            .select("label").reduce(ee.Reducer.mode()).toInt().rename("DW").clip(aoi))

DW = {y: dw_label(y) for y in OBS_YEARS}
# Land = not water in ANY epoch (fixed mask so lagoon-edge changes don't move the denominator)
LAND = ee.Image(1).clip(aoi)
for y in DW:
    LAND = LAND.And(DW[y].neq(0))
LAND = LAND.rename("land")

def built_of(y): return DW[y].eq(6).rename("built")
def vegref_of(y): return DW[y].remap(VEG_REF, [1] * len(VEG_REF), 0).rename("veg")

lga_area = (ee.Image.pixelArea().divide(1e6).updateMask(LAND)
            .reduceRegions(collection=lgas, reducer=ee.Reducer.sum(), scale=SCALE, tileScale=4)
            .map(lambda f: ee.Feature(None, {"lga": f.get("ADM2_NAME"), "km2": f.get("sum")})).getInfo())
LAND_KM2 = {f["properties"]["lga"]: f["properties"]["km2"] for f in lga_area["features"]}
print("Land area (km²):", round(sum(LAND_KM2.values())))

# %% [markdown]
# ## 5. Landsat 8/9 C2 L2 → LST (°C), NDVI; one median composite per epoch
# `LST = ST_B10 × 0.00341802 + 149.0 − 273.15`; QA_PIXEL bits 0–4 (fill, dilated cloud, cirrus, cloud, shadow) masked.
# Landsat 9 data begin in early 2022, so 2019 is Landsat 8 only and 2021 is mostly Landsat 8.

# %%
def prep(img):
    clear = img.select("QA_PIXEL").bitwiseAnd(0b11111).eq(0)
    lst = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
    sr = img.select(["SR_B4", "SR_B5"]).multiply(0.0000275).add(-0.2)
    ndvi = sr.normalizedDifference(["SR_B5", "SR_B4"]).rename("NDVI")
    ok = lst.gte(LST_VALID_RANGE[0]).And(lst.lte(LST_VALID_RANGE[1]))
    return lst.addBands(ndvi).updateMask(clear.And(ok)).copyProperties(img, ["system:time_start"])

def landsat(cid, e):
    return (ee.ImageCollection(cid).filterBounds(aoi).filterDate(e["start"], e["end"])
            .filter(ee.Filter.lt("CLOUD_COVER", MAX_SCENE_CLOUD)))

stat = (ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True))
RR = dict(geometry=aoi, scale=SCALE, maxPixels=1e10, tileScale=4)

IM, E = {}, {}      # EE images and python results per epoch
for e in EPOCHS:
    c8, c9 = landsat("LANDSAT/LC08/C02/T1_L2", e), landsat("LANDSAT/LC09/C02/T1_L2", e)
    n8, n9 = c8.size().getInfo(), c9.size().getInfo()
    if n8 + n9 == 0:
        raise RuntimeError(f"{e['id']}: no Landsat scenes — widen the window or raise MAX_SCENE_CLOUD")
    col = c8.merge(c9).map(prep)
    obs = col.select("LST").count()
    comp = col.median().updateMask(obs.gte(MIN_CLEAR_OBS)).clip(aoi)
    lst = comp.select("LST").updateMask(LAND)
    ndvi = comp.select("NDVI").updateMask(LAND)
    built, veg = built_of(e["year"]), vegref_of(e["year"])

    cov = lst.mask().gt(0).updateMask(LAND).reduceRegion(ee.Reducer.mean(), **RR).values().get(0).getInfo()
    zone = built.add(veg.multiply(2)).selfMask().rename("zone")
    groups = lst.addBands(zone).reduceRegion(stat.group(groupField=1, groupName="zone"), **RR).get("groups").getInfo()
    zd = {g["zone"]: g for g in groups}
    if 1 not in zd or 2 not in zd:
        raise RuntimeError(f"{e['id']}: no valid built-up or vegetated pixels — coverage {cov:.0%}")
    u, r = zd[1], zd[2]
    IM[e["id"]] = {"lst": lst, "anom": lst.subtract(r["mean"]).rename("ANOM"), "ndvi": ndvi, "built": built}
    E[e["id"]] = {**e, "landsat8": n8, "landsat9": n9, "coverage": round(cov, 3),
                  "urban_mean": round(u["mean"], 2), "urban_std": round(u["stdDev"], 2),
                  "rural_mean": round(r["mean"], 2), "rural_std": round(r["stdDev"], 2),
                  "suhi": round(u["mean"] - r["mean"], 2)}
    flag = "  <-- LOW COVERAGE" if cov < 0.5 else ""
    print(f"{e['id']} {e['label']:<20} L8={n8:<3} L9={n9:<3} coverage={cov:5.1%}  "
          f"built={u['mean']:.2f}  veg={r['mean']:.2f}  SUHI={u['mean']-r['mean']:+.2f} °C{flag}")

# %% [markdown]
# ## 6. Hotspot threshold (fixed from the 2019 baseline) and map display ranges

# %%
pb = (IM[FIRST]["lst"].addBands(IM[FIRST]["anom"])
      .reduceRegion(ee.Reducer.percentile([2, HOTSPOT_PERCENTILE, 98]), **RR).getInfo())
T_ANOM = pb[f"ANOM_p{HOTSPOT_PERCENTILE}"]
LST_RANGE = [int(np.floor(pb["LST_p2"])), int(np.ceil(pb["LST_p98"]))]
ANOM_RANGE = [int(np.floor(pb["ANOM_p2"])), int(np.ceil(pb["ANOM_p98"]))]
print(f"Hotspot = heat excess ≥ {T_ANOM:.2f} °C; LST display {LST_RANGE}; heat-excess display {ANOM_RANGE}")

# %% [markdown]
# ## 7. LGA statistics and hotspot area for every epoch

# %%
LS = {}   # LS[epoch_id][lga] = dict of stats
for eid, im in IM.items():
    valid = im["lst"].mask().gt(0).updateMask(LAND).rename("coverage")
    hot = im["anom"].gte(T_ANOM)
    img = (im["lst"].rename("lst_mean").addBands(im["anom"].rename("heat_excess"))
           .addBands(im["ndvi"].rename("ndvi_mean"))
           .addBands(im["built"].updateMask(LAND).rename("built_share"))
           .addBands(valid).addBands(hot.unmask(0).updateMask(im["lst"].mask()).rename("hot_share")))
    fc = img.reduceRegions(collection=lgas, reducer=ee.Reducer.mean(), scale=SCALE, tileScale=4)
    # select() keeps only properties that exist (an LGA with no valid pixels has no mean)
    fc = fc.map(lambda f: f.select(
        ["ADM2_NAME", "lst_mean", "heat_excess", "ndvi_mean", "built_share", "coverage", "hot_share"], None, False))
    LS[eid] = {}
    for f in fc.getInfo()["features"]:
        p = f["properties"]
        LS[eid][p.pop("ADM2_NAME")] = {k: (None if p.get(k) is None else round(p[k], 4)) for k in
                                       ["lst_mean", "heat_excess", "ndvi_mean", "built_share", "coverage", "hot_share"]}
    km2 = (ee.Image.pixelArea().divide(1e6).updateMask(hot.selfMask())
           .reduceRegion(ee.Reducer.sum(), **RR).values().get(0).getInfo())
    E[eid]["hot_km2"] = round(km2 or 0, 1)
    low = [l for l, s in LS[eid].items() if (s["coverage"] or 0) < COVERAGE_MIN_LGA]
    print(f"{eid}: hotspot area {E[eid]['hot_km2']:.1f} km²; LGAs below coverage threshold: {low or 'none'}")

# %% [markdown]
# ## 8. Trend model and scenario projections (2027, 2029)
#
# **Panel:** LGA × observed year (2019, 2021, 2023, 2025): heat excess and built-up share.
#
# **Model (LGA fixed effects):** heat_excess(i,t) = α_i + β·built_share(i,t) + γ·year + ε
# - β = warming from built-up expansion (°C per unit built-up share)
# - γ = background drift not explained by expansion (densification, tree loss inside built areas, materials)
#
# **Scenarios** from each LGA's 2025 level:
# - **S1 — growth continues:** built-up share keeps growing at the LGA's own 2019–2025 linear rate → Δ = β·Δbuilt + γ·Δt
# - **S2 — no further growth:** built-up frozen at 2025 → Δ = γ·Δt (only the observed background drift)
#
# **Uncertainty:** 2,000 cluster-bootstrap draws (resampling LGAs) → 95% intervals.
# **Validation (hindcast):** fit on 2019–2023 only, predict 2025, compare with observed 2025 and a no-change baseline.

# %%
# --- MODEL START ---
def ok(s, cov_min=0.30):
    return s is not None and s.get("heat_excess") is not None and (s.get("coverage") or 0) >= cov_min

def make_rows(LS, years, cov_min=0.30):
    """Panel rows {lga, year, he, built} for LGA-years passing the coverage threshold. LS keyed by str(year)."""
    rows = []
    for y in years:
        for lga, s in LS[str(y)].items():
            if ok(s, cov_min):
                rows.append({"lga": lga, "year": y, "he": s["heat_excess"], "built": s["built_share"]})
    return rows

def group(rows):
    g = {}
    for r in rows:
        g.setdefault(r["lga"], []).append(r)
    return g

def balanced(rows, n_years):
    keep = {l for l, rs in group(rows).items() if len(rs) == n_years}
    return [r for r in rows if r["lga"] in keep], sorted(keep)

def fit_fe(rows):
    """Within (fixed-effects) estimator. Returns (beta per unit built share, gamma per year)."""
    X, Y = [], []
    for rs in group(rows).values():
        if len(rs) < 2:
            continue
        b = np.array([r["built"] for r in rs]); t = np.array([r["year"] for r in rs], float)
        h = np.array([r["he"] for r in rs])
        X += list(zip(b - b.mean(), t - t.mean())); Y += list(h - h.mean())
    coef, *_ = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)
    return float(coef[0]), float(coef[1])

def growth_rates(rows):
    """Per-LGA OLS slope of built-up share on year (share per year)."""
    return {lga: float(np.polyfit([r["year"] for r in rs], [r["built"] for r in rs], 1)[0])
            for lga, rs in group(rows).items() if len(rs) >= 2}

def project(rows, beta, gamma, growth, base_year, years):
    out = {}
    for lga, rs in group(rows).items():
        base = next((r for r in rs if r["year"] == base_year), None)
        if base is None or lga not in growth:
            continue
        out[lga] = {}
        for Y in years:
            d = Y - base_year
            b_proj = min(1.0, max(0.0, base["built"] + growth[lga] * d))
            out[lga][Y] = {"S1": base["he"] + beta * (b_proj - base["built"]) + gamma * d,
                           "S2": base["he"] + gamma * d, "built_S1": b_proj}
    return out

def weighted(values, weights):
    k = [l for l in values if l in weights]
    w = np.array([weights[l] for l in k])
    return float(np.dot([values[l] for l in k], w) / w.sum())

def ci(a):
    return [round(float(np.percentile(a, 2.5)), 2), round(float(np.percentile(a, 97.5)), 2)]

def run_projection(LS, LAND_KM2, obs_years, proj_years, B=2000, seed=42, cov_min=0.30):
    base_year = obs_years[-1]
    rows, lgas_ok = balanced(make_rows(LS, obs_years, cov_min), len(obs_years))
    beta, gamma = fit_fe(rows)
    growth = growth_rates(rows)
    point = project(rows, beta, gamma, growth, base_year, proj_years)

    rng = np.random.default_rng(seed)
    g = group(rows)
    draws = {"beta": [], "gamma": [], "agg": {Y: {"S1": [], "S2": []} for Y in proj_years},
             "lga": {l: {Y: {"S1": [], "S2": []} for Y in proj_years} for l in lgas_ok}}
    for _ in range(B):
        sample = rng.choice(lgas_ok, size=len(lgas_ok), replace=True)
        boot = [{**r, "lga": f"{l}#{k}"} for k, l in enumerate(sample) for r in g[l]]
        try:
            b_, g_ = fit_fe(boot)
        except np.linalg.LinAlgError:
            continue
        draws["beta"].append(b_); draws["gamma"].append(g_)
        pr = project(rows, b_, g_, growth, base_year, proj_years)
        for Y in proj_years:
            for s in ("S1", "S2"):
                draws["agg"][Y][s].append(weighted({l: pr[l][Y][s] for l in pr}, LAND_KM2))
                for l in pr:
                    draws["lga"][l][Y][s].append(pr[l][Y][s])

    observed = [{"year": y, "he": round(weighted({r["lga"]: r["he"] for r in rows if r["year"] == y}, LAND_KM2), 2)}
                for y in obs_years]
    base = {r["lga"]: r for r in rows if r["year"] == base_year}
    return {
        "obs_years": list(obs_years), "base_year": base_year, "proj_years": list(proj_years),
        "n_lgas": len(lgas_ok), "lgas": lgas_ok, "bootstrap_draws": len(draws["beta"]),
        "beta_per_10pp": round(beta * 0.1, 3), "beta_per_10pp_ci": [round(v * 0.1, 3) for v in ci(draws["beta"])],
        "gamma_per_yr": round(gamma, 3), "gamma_per_yr_ci": ci(draws["gamma"]),
        "aggregate": {"observed": observed,
                      **{s: [{"year": Y, "he": round(weighted({l: point[l][Y][s] for l in point}, LAND_KM2), 2),
                              "ci": ci(draws["agg"][Y][s])} for Y in proj_years] for s in ("S1", "S2")}},
        "lga": {l: {"he_base": round(base[l]["he"], 2), "built_base": round(base[l]["built"], 4),
                    "growth_pp_per_yr": round(growth[l] * 100, 2),
                    **{str(Y): {"S1": round(point[l][Y]["S1"], 2), "S1_ci": ci(draws["lga"][l][Y]["S1"]),
                                "S2": round(point[l][Y]["S2"], 2), "S2_ci": ci(draws["lga"][l][Y]["S2"]),
                                "built_S1": round(point[l][Y]["built_S1"], 4)} for Y in proj_years}}
                for l in point},
    }

def hindcast(LS, LAND_KM2, obs_years, cov_min=0.30):
    """Fit on all but the last observed epoch, predict the last one; compare with a no-change baseline."""
    train_years, target = obs_years[:-1], obs_years[-1]
    rows, lgas_ok = balanced(make_rows(LS, obs_years, cov_min), len(obs_years))
    train = [r for r in rows if r["year"] in train_years]
    beta, gamma = fit_fe(train)
    growth = growth_rates(train)
    last = {r["lga"]: r for r in train if r["year"] == train_years[-1]}
    obs = {r["lga"]: r for r in rows if r["year"] == target}
    d = target - train_years[-1]
    pred_model = {l: last[l]["he"] + beta * growth[l] * d + gamma * d for l in lgas_ok}
    pred_naive = {l: last[l]["he"] for l in lgas_ok}
    def metrics(p):
        e = np.array([p[l] - obs[l]["he"] for l in lgas_ok])
        return {"mae": round(float(np.abs(e).mean()), 2), "bias": round(float(e.mean()), 2),
                "aggregate_error": round(weighted(p, LAND_KM2) - weighted({l: obs[l]["he"] for l in lgas_ok}, LAND_KM2), 2)}
    return {"n_lgas": len(lgas_ok), "trained_on": list(train_years), "predicted": target,
            "model": metrics(pred_model), "no_change_baseline": metrics(pred_naive)}
# --- MODEL END ---

PROJ = run_projection(LS, LAND_KM2, OBS_YEARS, PROJECTION_YEARS, B=BOOTSTRAP_N, seed=SEED, cov_min=COVERAGE_MIN_LGA)
HIND = hindcast(LS, LAND_KM2, OBS_YEARS, cov_min=COVERAGE_MIN_LGA)
print(f"LGAs in balanced panel: {PROJ['n_lgas']}")
print(f"β = {PROJ['beta_per_10pp']:+.3f} °C per +10 pp built-up  (95% CI {PROJ['beta_per_10pp_ci']})")
print(f"γ = {PROJ['gamma_per_yr']:+.3f} °C/yr background drift   (95% CI {PROJ['gamma_per_yr_ci']})")
for k, v in PROJ["aggregate"].items():
    print(k, v)
print("Hindcast:", json.dumps(HIND, indent=1))

# %% [markdown]
# ## 9. Web-map overlays (PNG)

# %%
def save_thumb(img, name):
    url = img.getThumbURL({"region": bbox, "dimensions": PNG_DIMENSIONS, "format": "png", "crs": "EPSG:4326"})
    resp = requests.get(url, timeout=300); resp.raise_for_status()
    open(f"{DATA}/{name}", "wb").write(resp.content)
    print("saved", name, f"{len(resp.content)/1e6:.1f} MB")

for eid in IM:
    save_thumb(IM[eid]["lst"].visualize(min=LST_RANGE[0], max=LST_RANGE[1], palette=PAL_LST), f"lst_{eid}.png")
    save_thumb(IM[eid]["anom"].visualize(min=ANOM_RANGE[0], max=ANOM_RANGE[1], palette=PAL_LST), f"excess_{eid}.png")

save_thumb(IM[LAST]["anom"].subtract(IM[FIRST]["anom"]).visualize(min=-4, max=4, palette=PAL_DIV), "change.png")
# Hotspot persistence: 1 = hot in baseline only (cooled), 2 = new by latest, 3 = hot in both
hA, hB = IM[FIRST]["anom"].gte(T_ANOM), IM[LAST]["anom"].gte(T_ANOM)
persist = hA.add(hB.multiply(2)).selfMask().updateMask(IM[FIRST]["lst"].mask().And(IM[LAST]["lst"].mask()))
save_thumb(persist.visualize(min=1, max=3, palette=["4575b4", "fdae61", "a50026"]), "hotspots_change.png")
save_thumb(built_of(int(LAST)).And(built_of(int(FIRST)).Not()).selfMask().visualize(palette=["6a3d9a"]), "new_built.png")

# %% [markdown]
# ## 10. Save data for the web map

# %%
lga_geo = lgas.map(lambda f: ee.Feature(f.geometry().simplify(100), {"lga": f.get("ADM2_NAME")})).getInfo()
for f in lga_geo["features"]:
    f["properties"]["land_km2"] = round(LAND_KM2.get(f["properties"]["lga"], 0), 1)
json.dump({"type": "FeatureCollection", "features": lga_geo["features"]}, open(f"{DATA}/lga.geojson", "w"))

panel = [{"epoch": eid, "lga": l, **s} for eid in LS for l, s in LS[eid].items()]
json.dump(panel, open(f"{DATA}/lga_panel.json", "w"))
json.dump({**PROJ, "hindcast": HIND}, open(f"{DATA}/projections.json", "w"), indent=1)

summary = {
    "title": f"Lagos Urban Heat Island {OBS_YEARS[0]}–{OBS_YEARS[-1]}",
    "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "epochs": [E[e["id"]] for e in EPOCHS], "first": FIRST, "last": LAST,
    "hotspot": {"definition": f"heat excess ≥ {FIRST} p{HOTSPOT_PERCENTILE}", "threshold_c": round(T_ANOM, 2)},
    "lst_range": LST_RANGE, "excess_range": ANOM_RANGE, "change_range": [-4, 4],
    "pal_lst": PAL_LST, "pal_div": PAL_DIV, "coverage_min_lga": COVERAGE_MIN_LGA,
    "bounds": BOUNDS, "synthetic": False,
}
json.dump(summary, open(f"{DATA}/summary.json", "w"), indent=2)
print(json.dumps(summary["epochs"], indent=1))

# %% [markdown]
# ## 11. README figures

# %%
plt.rcParams.update({"figure.dpi": 150, "font.size": 9})
agg = PROJ["aggregate"]; P_LAST = str(PROJECTION_YEARS[-1])

fig, ax = plt.subplots(figsize=(6.5, 3.6))
oy = [o["year"] for o in agg["observed"]]; oh = [o["he"] for o in agg["observed"]]
ax.plot(oy, oh, "-o", c="k", label="Observed")
for s, c, lab in (("S1", "#d73027", "S1 growth continues"), ("S2", "#4575b4", "S2 no further growth")):
    ys = [BASE_YEAR] + [p["year"] for p in agg[s]]; hs = [oh[-1]] + [p["he"] for p in agg[s]]
    lo = [oh[-1]] + [p["ci"][0] for p in agg[s]]; hi = [oh[-1]] + [p["ci"][1] for p in agg[s]]
    ax.plot(ys, hs, "--o", c=c, label=lab); ax.fill_between(ys, lo, hi, color=c, alpha=0.15)
ax.set_ylabel("Mean heat excess (°C)"); ax.set_xticks(OBS_YEARS + PROJECTION_YEARS)
ax.set_title("Lagos-wide surface heat excess: observed and projected"); ax.legend(fontsize=8); fig.tight_layout()
fig.savefig(f"{FIGS}/trend_projection.png")

fig, ax = plt.subplots(figsize=(6, 3.2))
ax.bar([E[e["id"]]["label"] for e in EPOCHS], [E[e["id"]]["suhi"] for e in EPOCHS], color="#d73027")
ax.set_ylabel("SUHI intensity (°C)\nbuilt-up − vegetated")
ax.set_title("Surface UHI intensity by epoch"); fig.tight_layout(); fig.savefig(f"{FIGS}/suhi_by_epoch.png")

lg = sorted(PROJ["lga"].items(), key=lambda kv: kv[1][P_LAST]["S1"])
fig, ax = plt.subplots(figsize=(6.5, 5.5)); yy = np.arange(len(lg))
ax.barh(yy - 0.27, [v["he_base"] for _, v in lg], 0.27, color="#999", label=f"{BASE_YEAR} observed")
ax.barh(yy, [v[P_LAST]["S2"] for _, v in lg], 0.27, color="#4575b4", label=f"{P_LAST} S2 no growth")
ax.barh(yy + 0.27, [v[P_LAST]["S1"] for _, v in lg], 0.27, color="#d73027", label=f"{P_LAST} S1 growth continues")
ax.set_yticks(yy, [k for k, _ in lg]); ax.set_xlabel("Heat excess (°C)"); ax.legend(fontsize=7, loc="lower right")
ax.set_title(f"LGA heat excess: {BASE_YEAR} and {P_LAST} scenarios"); fig.tight_layout()
fig.savefig(f"{FIGS}/lga_projection.png")

bl = sorted(LGAS, key=lambda l: (LS[LAST][l]["built_share"] or 0))
fig, ax = plt.subplots(figsize=(6.5, 5)); yy = np.arange(len(bl))
ax.barh(yy - 0.2, [(LS[FIRST][l]["built_share"] or 0) * 100 for l in bl], 0.4, color="#bbb", label=FIRST)
ax.barh(yy + 0.2, [(LS[LAST][l]["built_share"] or 0) * 100 for l in bl], 0.4, color="#6a3d9a", label=LAST)
ax.set_yticks(yy, bl); ax.set_xlabel("Built-up share of land (%) — Dynamic World"); ax.legend()
ax.set_title(f"Built-up expansion by LGA, {FIRST} → {LAST}"); fig.tight_layout(); fig.savefig(f"{FIGS}/built_by_lga.png")
plt.show()

# %% [markdown]
# ## 12. Package outputs and download

# %%
shutil.make_archive("uhi_outputs", "zip", OUT)
try:
    from google.colab import drive, files
    drive.mount("/content/drive")
    dest = "/content/drive/MyDrive/urban-heat-island-lagos"
    os.makedirs(dest, exist_ok=True)
    shutil.copy("uhi_outputs.zip", dest)
    for n in ("summary.json", "projections.json"):
        shutil.copy(f"{DATA}/{n}", dest)
    print("Saved to Google Drive:", dest)
    files.download("uhi_outputs.zip")
except ImportError:
    print("Zip written to", os.path.abspath("uhi_outputs.zip"))
print("ALL DONE")
