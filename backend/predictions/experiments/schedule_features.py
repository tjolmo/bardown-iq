"""Schedule, fatigue and travel features per (game, team).

Everything here depends only on the schedule (dates, teams and optionally the venue), so it is known before puck
drop and works the same for finished and upcoming games. Feed it every scheduled game (regular season and playoffs).
"""
import numpy as np
import pandas as pd

# home arena (lat, lon, standard-time UTC offset). Arena moves within a metro (NYI, ARI, DET) are ignored.
ARENAS = {
    "ANA": (33.8078, -117.8765, -8), "ARI": (33.5319, -112.2611, -7), "ATL": (33.7573, -84.3963, -5),
    "BOS": (42.3662, -71.0621, -5), "BUF": (42.8750, -78.8764, -5), "CAR": (35.8033, -78.7219, -5),
    "CBJ": (39.9692, -83.0061, -5), "CGY": (51.0374, -114.0519, -7), "CHI": (41.8807, -87.6742, -6),
    "COL": (39.7487, -105.0077, -7), "DAL": (32.7905, -96.8103, -6), "DET": (42.3411, -83.0553, -5),
    "EDM": (53.5469, -113.4979, -7), "FLA": (26.1584, -80.3256, -5), "LAK": (34.0430, -118.2673, -8),
    "MIN": (44.9448, -93.1010, -6), "MTL": (45.4961, -73.5693, -5), "NJD": (40.7336, -74.1711, -5),
    "NSH": (36.1592, -86.7785, -6), "NYI": (40.7117, -73.7258, -5), "NYR": (40.7505, -73.9934, -5),
    "OTT": (45.2969, -75.9272, -5), "PHI": (39.9012, -75.1720, -5), "PHX": (33.5319, -112.2611, -7),
    "PIT": (40.4394, -79.9892, -5), "SEA": (47.6221, -122.3540, -8), "SJS": (37.3328, -121.9012, -8),
    "STL": (38.6268, -90.2026, -6), "TBL": (27.9427, -82.4519, -5), "TOR": (43.6435, -79.3791, -5),
    "UTA": (40.7683, -111.9011, -7), "VAN": (49.2778, -123.1089, -8), "VGK": (36.1029, -115.1784, -8),
    "WPG": (49.8928, -97.1436, -6), "WSH": (38.8981, -77.0209, -5),
}
# neutral sites far from the home team's arena: Global Series, 2020 bubble hubs, Tahoe. Outdoor games in or near
# the home market are left at the home arena.
NEUTRAL_VENUES = {
    "Avicii Arena": (59.2936, 18.0831, 1), "Ericsson Globe": (59.2936, 18.0831, 1), "Globe Arena": (59.2936, 18.0831, 1),
    "Scandinavium": (57.7000, 11.9870, 1), "O2 Czech Republic": (50.1047, 14.4936, 1),
    "O2 Arena Berlin": (52.5052, 13.4434, 1), "PSD Bank Dome": (51.2617, 6.7331, 1),
    "Hartwall Areena": (60.2053, 24.9289, 2), "Hartwall Arena": (60.2053, 24.9289, 2),
    "Veikkaus Arena": (60.2053, 24.9289, 2), "Nokia Arena": (61.4936, 23.7700, 2),
    "Rogers Place": ARENAS["EDM"], "Scotiabank Arena": ARENAS["TOR"], "Edgewood Tahoe Resort": (38.9690, -119.9440, -8),
}
MAX_LEG_KM = 5000   # longest North American leg is ~4500 km; caps trips to Europe
MAX_TZ_SHIFT = 3
HOME_RADIUS_KM = 100
B2B_TRAVEL_KM = 50

SCHEDULE_FEATURE_COLUMNS = ["travel_km", "tz_shift", "travel_km_7d", "games_4d", "games_7d", "back_to_back",
                            "b2b_travel", "road_trip_game", "home_stand_game", "first_home_after_trip",
                            "prev_trip_len", "season_day"]

def _haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))

def _locate(codes: pd.Series) -> pd.DataFrame:
    return pd.DataFrame([ARENAS.get(c, (np.nan,) * 3) for c in codes], columns=["lat", "lon", "tz"], index=codes.index)

def _run_index(flag: pd.Series, block: pd.Series) -> pd.Series:
    """1-based position within each run of consecutive equal `flag` values inside `block` (team-season)."""
    run = (flag != flag.groupby(block).shift()).cumsum()
    return flag.groupby(run).cumcount() + 1

def schedule_features(games: pd.DataFrame) -> pd.DataFrame:
    """`games`: id, season, date (YYYYMMDD), home_team_tri_code, away_team_tri_code and optionally venue.
    Returns one row per (game_id, team) with SCHEDULE_FEATURE_COLUMNS plus is_home, season and date."""
    g = games[games["id"] // 10000 % 100 >= 2].copy()   # preseason games don't count
    g["dt"] = pd.to_datetime(g["date"].astype(str), format="%Y%m%d")
    loc = _locate(g["home_team_tri_code"])
    if "venue" in g:
        site = g["venue"].map(NEUTRAL_VENUES).dropna()
        loc.loc[site.index] = pd.DataFrame(site.tolist(), columns=loc.columns, index=site.index)
    g[["lat", "lon", "tz"]] = loc.astype(float)

    cols = ["id", "season", "date", "dt", "lat", "lon", "tz"]
    home = g[cols + ["home_team_tri_code"]].rename(columns={"home_team_tri_code": "team"}).assign(is_home=1)
    away = g[cols + ["away_team_tri_code"]].rename(columns={"away_team_tri_code": "team"}).assign(is_home=0)
    df = pd.concat([home, away], ignore_index=True).rename(columns={"id": "game_id"})
    df = df.sort_values(["team", "dt", "game_id"], kind="stable").reset_index(drop=True)

    own = _locate(df["team"])
    # playing in your own building, so neutral-site "home" games (bubble, Europe) count as road games
    df["at_home"] = (_haversine_km(df["lat"], df["lon"], own["lat"], own["lon"]) < HOME_RADIUS_KM).astype(int)
    block = df["team"] + df["season"].astype(str)
    first = block != block.shift()
    # each season's trip starts from the home arena
    prev_lat = df["lat"].shift().where(~first, own["lat"])
    prev_lon = df["lon"].shift().where(~first, own["lon"])
    prev_tz = df["tz"].shift().where(~first, own["tz"])
    df["travel_km"] = _haversine_km(prev_lat, prev_lon, df["lat"], df["lon"]).clip(upper=MAX_LEG_KM)
    df["tz_shift"] = (df["tz"] - prev_tz).clip(-MAX_TZ_SHIFT, MAX_TZ_SHIFT)

    # rolling windows over calendar days ending today, current game included ("3 in 4" -> games_4d == 3)
    roll = df.set_index("dt").groupby("team", sort=False)
    df["travel_km_7d"] = roll["travel_km"].rolling("7D").sum().to_numpy()
    df["games_4d"] = roll["travel_km"].rolling("4D").count().to_numpy()
    df["games_7d"] = roll["travel_km"].rolling("7D").count().to_numpy()

    gap = df["dt"].diff().dt.days.where(~first)
    df["back_to_back"] = (gap == 1).astype(int)
    df["b2b_travel"] = (df["back_to_back"].astype(bool) & (df["travel_km"] > B2B_TRAVEL_KM)).astype(int)

    stint = _run_index(df["at_home"], block)
    df["road_trip_game"] = stint.where(df["at_home"] == 0, 0)
    df["home_stand_game"] = stint.where(df["at_home"] == 1, 0)
    prev_stint = stint.groupby(block).shift().fillna(0)
    returning = (df["at_home"] == 1) & (df["at_home"].groupby(block).shift() == 0)
    df["first_home_after_trip"] = returning.astype(int)
    df["prev_trip_len"] = prev_stint.where(returning, 0).astype(int)

    start = df.groupby("season")["dt"].transform("min")
    df["season_day"] = (df["dt"] - start).dt.days
    return df[["game_id", "team", "season", "date", "is_home"] + SCHEDULE_FEATURE_COLUMNS]
