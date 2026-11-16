"""SYNTHETIC unit test of the projection model (no Earth Engine needed).
Builds a fake LGA panel with KNOWN beta and gamma and checks the fixed-effects model recovers them.
Run: python tests/test_model_synthetic.py"""
import os, re, json
import numpy as np

src = open(os.path.join(os.path.dirname(__file__), "..", "notebooks", "lagos_uhi_lst.py")).read()
exec(re.search(r"# --- MODEL START ---(.*)# --- MODEL END ---", src, re.S).group(1))

OBS, PROJ_Y = [2019, 2021, 2023, 2025], [2027, 2029]
BETA, GAMMA = 6.0, 0.08            # true: +0.6 °C per +10 pp built-up, +0.08 °C/yr drift
rng = np.random.default_rng(0)
lgas = [f"L{i}" for i in range(20)]
alpha = {l: rng.normal(2, 1.5) for l in lgas}
b0 = {l: rng.uniform(.1, .8) for l in lgas}
g = {l: rng.uniform(0, .02) for l in lgas}
LS = {str(y): {l: {"heat_excess": alpha[l] + BETA * (b0[l] + g[l] * (y - 2019)) + GAMMA * (y - 2019) + rng.normal(0, .1),
                   "built_share": b0[l] + g[l] * (y - 2019), "coverage": .9} for l in lgas} for y in OBS}
LS["2025"]["L3"]["coverage"] = 0.1          # low-coverage row → L3 must leave the balanced panel
KM2 = {l: 50.0 for l in lgas}

P = run_projection(LS, KM2, OBS, PROJ_Y, B=300)
H = hindcast(LS, KM2, OBS)
print("n_lgas:", P["n_lgas"], "| beta/10pp:", P["beta_per_10pp"], P["beta_per_10pp_ci"],
      "| gamma/yr:", P["gamma_per_yr"], P["gamma_per_yr_ci"])
print("aggregate:", json.dumps(P["aggregate"]))
print("hindcast:", json.dumps(H))

assert P["n_lgas"] == 19 and "L3" not in P["lga"]
assert P["base_year"] == 2025 and set(P["lga"]["L0"]) >= {"2027", "2029", "he_base"}
assert abs(P["beta_per_10pp"] - 0.6) < 0.25 and abs(P["gamma_per_yr"] - 0.08) < 0.05
assert P["beta_per_10pp_ci"][0] < 0.6 < P["beta_per_10pp_ci"][1]
assert P["aggregate"]["S1"][-1]["he"] >= P["aggregate"]["S2"][-1]["he"]
assert H["trained_on"] == [2019, 2021, 2023] and H["predicted"] == 2025
assert H["model"]["mae"] < H["no_change_baseline"]["mae"]
print("ALL CHECKS PASSED")
