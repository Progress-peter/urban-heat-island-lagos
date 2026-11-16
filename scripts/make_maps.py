"""Static cartographic maps for the README, built from the notebook's outputs in docs/data/.
Run from the repo root:  python scripts/make_maps.py   → results/maps/*.png
"""
import json, math, os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Polygon as MplPolygon, Patch
from matplotlib.collections import PatchCollection
from PIL import Image
from shapely.geometry import shape

D, OUT = "docs/data", "results/maps"
os.makedirs(OUT, exist_ok=True)
S = json.load(open(f"{D}/summary.json"))
P = json.load(open(f"{D}/projections.json"))
G = json.load(open(f"{D}/lga.geojson"))
(SOUTH, WEST), (NORTH, EAST) = S["bounds"]
EXTENT = [WEST, EAST, SOUTH, NORTH]
ASPECT = 1 / math.cos(math.radians((SOUTH + NORTH) / 2))   # equal-distance look at 6.5°N
CMAP = LinearSegmentedColormap.from_list("lst", ["#" + c for c in S["pal_lst"]])
CMAP_DIV = LinearSegmentedColormap.from_list("div", ["#" + c for c in S["pal_div"]])
YEARS = [e["id"] for e in S["epochs"]]
CREDIT = "Data: USGS Landsat 8/9 C2 L2 · Google Dynamic World · FAO GAUL 2015 · Analysis: Progress Peter Akpan"
plt.rcParams.update({"font.size": 8, "font.family": "DejaVu Sans"})

def polys(geom):
    g = shape(geom)
    parts = [g] if g.geom_type == "Polygon" else [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
    return [np.array(p.exterior.coords) for p in parts]

LGAS = [(f["properties"]["lga"], polys(f["geometry"]), shape(f["geometry"])) for f in G["features"]]

def frame(ax):
    ax.set_xlim(WEST, EAST); ax.set_ylim(SOUTH, NORTH); ax.set_aspect(ASPECT)
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#999"); s.set_linewidth(0.6)

def boundaries(ax, lw=0.4, color="#222"):
    for _, rings, _ in LGAS:
        for r in rings:
            ax.plot(r[:, 0], r[:, 1], color=color, lw=lw)

def scalebar(ax, km=20):
    deg = km / (111.32 * math.cos(math.radians((SOUTH + NORTH) / 2)))
    x0, y0 = WEST + 0.03, SOUTH + 0.025
    ax.plot([x0, x0 + deg], [y0, y0], color="k", lw=2, solid_capstyle="butt")
    ax.text(x0 + deg / 2, y0 + 0.012, f"{km} km", ha="center", va="bottom", fontsize=7)

def north(ax):
    ax.annotate("N", xy=(0.975, 0.93), xytext=(0.975, 0.76), xycoords="axes fraction",
                ha="center", va="center", fontsize=8, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1))

def raster(ax, name):
    ax.imshow(np.asarray(Image.open(f"{D}/{name}")), extent=EXTENT, interpolation="nearest", zorder=1)

# ---------- 1. Heat excess, four epochs ----------
lo, hi = S["excess_range"]
fig, axes = plt.subplots(4, 1, figsize=(10, 9.4))
for ax, y, e in zip(axes, YEARS, S["epochs"]):
    raster(ax, f"excess_{y}.png"); boundaries(ax); frame(ax)
    ax.set_title(f"Dec {y}   ·   SUHI intensity {e['suhi']:+.1f} °C   ·   hotspot area {e['hot_km2']:.0f} km²",
                 loc="left", fontsize=9, fontweight="bold")
scalebar(axes[-1]); north(axes[0])
cb = fig.colorbar(plt.cm.ScalarMappable(Normalize(lo, hi), CMAP), ax=axes, orientation="horizontal",
                  fraction=0.025, pad=0.02, aspect=50, extend="both")
cb.set_label("Heat excess (°C): land surface temperature minus mean LST of vegetated land, same season")
fig.suptitle("Lagos State surface heat, December dry season 2019–2025", fontsize=13, fontweight="bold", x=0.02, ha="left")
fig.text(0.02, 0.005, CREDIT, fontsize=6.5, color="#666")
fig.savefig(f"{OUT}/01_heat_excess_2019_2025.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---------- 2. Land surface temperature, latest epoch ----------
last = YEARS[-1]; lo2, hi2 = S["lst_range"]
fig, ax = plt.subplots(figsize=(10, 3.4))
raster(ax, f"lst_{last}.png"); boundaries(ax); frame(ax); scalebar(ax); north(ax)
for name, _, geom in LGAS:
    if geom.area > 0.004:
        pt = geom.representative_point()
        ax.text(pt.x, pt.y, name, fontsize=5.5, ha="center", va="center", color="#111",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.6), zorder=5)
cb = fig.colorbar(plt.cm.ScalarMappable(Normalize(lo2, hi2), CMAP), ax=ax, orientation="horizontal",
                  fraction=0.06, pad=0.03, aspect=50, extend="both")
cb.set_label("Land surface temperature (°C), median of clear Landsat 8/9 scenes, Nov 2025 – Feb 2026")
ax.set_title(f"Land surface temperature, Lagos State, Dec {last}", loc="left", fontsize=12, fontweight="bold")
fig.text(0.01, -0.02, CREDIT, fontsize=6.5, color="#666")
fig.savefig(f"{OUT}/02_lst_{last}.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---------- 3. Change 2019 → 2025 and hotspot persistence ----------
first = YEARS[0]
fig, axes = plt.subplots(2, 1, figsize=(10, 5.6))
raster(axes[0], "change.png"); boundaries(axes[0]); frame(axes[0])
axes[0].set_title(f"Change in heat excess, Dec {first} → Dec {last}", loc="left", fontsize=10, fontweight="bold")
c0, c1 = S["change_range"]
cb = fig.colorbar(plt.cm.ScalarMappable(Normalize(c0, c1), CMAP_DIV), ax=axes[0], fraction=0.03, pad=0.01, extend="both")
cb.set_label("°C", rotation=0)
raster(axes[1], "hotspots_change.png"); boundaries(axes[1]); frame(axes[1])
axes[1].set_title(f"Heat hotspots (excess ≥ {S['hotspot']['threshold_c']:.1f} °C), {first} vs {last}",
                  loc="left", fontsize=10, fontweight="bold")
axes[1].legend(handles=[Patch(color="#a50026", label=f"Hot in {first} and {last}"),
                        Patch(color="#fdae61", label=f"New hotspot by {last}"),
                        Patch(color="#4575b4", label=f"Hot in {first} only")],
               loc="upper right", fontsize=7, frameon=True)
scalebar(axes[1]); north(axes[0])
fig.text(0.01, 0.0, CREDIT, fontsize=6.5, color="#666")
fig.savefig(f"{OUT}/03_change_and_hotspots.png", dpi=170, bbox_inches="tight"); plt.close(fig)

# ---------- 4. LGA choropleth: observed 2025 vs illustrative 2029 ----------
py = str(P["proj_years"][-1])
vals25 = {l: v["he_base"] for l, v in P["lga"].items()}
vals29 = {l: v[py]["S1"] for l, v in P["lga"].items()}
allv = list(vals25.values()) + list(vals29.values())
norm = Normalize(math.floor(min(allv)), math.ceil(max(allv)))
SMALL = sorted([name for name, _, geom in LGAS if geom.area <= 0.003],
               key=lambda n: -vals25.get(n, -99))          # numbered markers for LGAs too small to label
NUM = {n: i + 1 for i, n in enumerate(SMALL)}
fig, axes = plt.subplots(2, 1, figsize=(10, 5.2))
for ax, vals, title in ((axes[0], vals25, f"Observed, Dec {P['base_year']}"),
                        (axes[1], vals29, f"Projected {py}: 'if the 2019–2025 trend continues' (illustrative, see note)")):
    patches, colors = [], []
    for name, rings, geom in LGAS:
        for r in rings:
            patches.append(MplPolygon(r, closed=True))
            colors.append(CMAP(norm(vals[name])) if name in vals else (0.85, 0.85, 0.85, 1))
    ax.add_collection(PatchCollection(patches, facecolor=colors, edgecolor="white", lw=0.6))
    for name, _, geom in LGAS:
        pt = geom.representative_point()
        if name in NUM:
            ax.text(pt.x, pt.y, str(NUM[name]), fontsize=5.5, ha="center", va="center", fontweight="bold",
                    bbox=dict(boxstyle="circle,pad=0.15", fc="white", ec="#333", lw=0.4))
        elif name in vals:
            ax.text(pt.x, pt.y, f"{name}\n{vals[name]:+.1f}", fontsize=5.3, ha="center", va="center")
    key = "\n".join(f"{NUM[n]}  {n.replace('/ ', '-').replace('/', '-')}  " + (f"{vals[n]:+.1f}" if n in vals else "n/a") for n in SMALL)
    ax.text(1.005, 0.98, key, transform=ax.transAxes, fontsize=5.8, va="top", ha="left", family="DejaVu Sans Mono",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#bbb", lw=0.5))
    frame(ax); ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
scalebar(axes[1]); north(axes[0])
cb = fig.colorbar(plt.cm.ScalarMappable(norm, CMAP), ax=axes, fraction=0.025, pad=0.25)
cb.set_label("Mean heat excess per LGA (°C)")
H = P["hindcast"]
fig.suptitle("Heat excess by LGA: 2025 observed vs 2029 projection", fontsize=12, fontweight="bold", x=0.02, ha="left")
fig.text(0.01, -0.01, f"Note: the projection model did not beat a no-change baseline in its 2025 hindcast "
         f"(MAE {H['model']['mae']:.2f} vs {H['no_change_baseline']['mae']:.2f} °C), so 2029 values are illustrative, "
         f"not a forecast. Grey = excluded (low valid coverage).  " + CREDIT, fontsize=6.3, color="#555", wrap=True)
fig.savefig(f"{OUT}/04_lga_2025_vs_2029.png", dpi=170, bbox_inches="tight"); plt.close(fig)
print("maps written to", OUT, sorted(os.listdir(OUT)))
