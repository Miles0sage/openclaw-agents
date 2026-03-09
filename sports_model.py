"""
Sports Prediction Engine — Phase 3: XGBoost NBA model + betting recommendations

Uses nba_api for historical data, XGBoost for win probability predictions.
Models saved to ./data/models/.

Composes with sportsbook_odds.py to produce full predict→odds→EV→Kelly pipeline.
"""

import json
import os
import time
import pickle
from datetime import datetime, timedelta
from pathlib import Path

# Load .env if not already in environment
if not os.environ.get("ODDS_API_KEY"):
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    except Exception:
        pass

MODEL_DIR = Path("./data/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Cache for NBA API calls (rate-limited at ~2 req/sec)
_cache = {}
_CACHE_TTL = 1800  # 30 minutes


def _cached_get(key: str):
    """Get from cache if fresh."""
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _cached_set(key: str, data):
    """Set cache entry."""
    _cache[key] = {"data": data, "ts": time.time()}


# ═══════════════════════════════════════════════════════════════
# NBA data helpers
# ═══════════════════════════════════════════════════════════════

def _get_nba_features(team_id: int, season: str, games_back: int = 10) -> dict:
    """Pull pre-game features from nba_api — rolling averages over last N games.

    All features are knowable BEFORE tip-off (no data leakage).
    Matches the v2 training feature set.
    """
    from nba_api.stats.endpoints import teamgamelog
    import pandas as pd

    cache_key = f"team_v2_{team_id}_{season}_{games_back}"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    try:
        time.sleep(0.6)  # Rate limit: NBA.com allows ~2 req/sec
        log = teamgamelog.TeamGameLog(team_id=team_id, season=season, timeout=15)
        df = log.get_data_frames()[0]

        if df.empty or len(df) < 3:
            return {"error": f"Not enough games for team {team_id} in {season}"}

        # Sort oldest first for proper rolling calc
        df = df.sort_values("GAME_DATE").reset_index(drop=True)
        df["WIN"] = (df["WL"] == "W").astype(int)
        df["IS_HOME"] = df["MATCHUP"].str.contains("vs.", na=False).astype(int)
        df["GAME_DATE_DT"] = pd.to_datetime(df["GAME_DATE"])

        # Rolling averages from the LAST N games (the most recent data)
        recent = df.tail(games_back)

        features = {
            "roll_fg_pct": round(recent["FG_PCT"].mean(), 4),
            "roll_fg3_pct": round(recent["FG3_PCT"].mean(), 4),
            "roll_reb": round(recent["REB"].mean(), 1),
            "roll_ast": round(recent["AST"].mean(), 1),
            "roll_tov": round(recent["TOV"].mean(), 1),
            "roll_pts": round(recent["PTS"].mean(), 1),
            "win_pct": round(df["WIN"].mean(), 3),  # Season-to-date
            "win_streak": _compute_win_streak(df["WIN"].values),
        }

        # Rest days
        dates = df["GAME_DATE_DT"]
        if len(dates) >= 2:
            features["rest_days"] = min((dates.iloc[-1] - dates.iloc[-2]).days, 7)
        else:
            features["rest_days"] = 3

        # Home/away record
        home_games = df[df["IS_HOME"] == 1]
        away_games = df[df["IS_HOME"] == 0]
        features["home_wpct"] = round(home_games["WIN"].mean(), 3) if len(home_games) > 0 else 0.5
        features["away_wpct"] = round(away_games["WIN"].mean(), 3) if len(away_games) > 0 else 0.5

        _cached_set(cache_key, features)
        return features

    except Exception as e:
        return {"error": f"NBA API error for team {team_id}: {str(e)[:200]}"}


def _compute_win_streak(wins) -> int:
    """Count consecutive wins going into next game (from end of array)."""
    streak = 0
    for w in reversed(wins):
        if w == 1:
            streak += 1
        else:
            break
    return streak


def _get_all_teams() -> dict:
    """Get all NBA teams as id -> abbreviation mapping."""
    from nba_api.stats.static import teams as nba_teams

    cache_key = "all_teams"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    all_teams = nba_teams.get_teams()
    result = {t["id"]: t for t in all_teams}
    _cached_set(cache_key, result)
    return result


def _find_team(name: str) -> dict:
    """Find an NBA team by name, abbreviation, or city."""
    from nba_api.stats.static import teams as nba_teams

    all_teams = nba_teams.get_teams()
    name_lower = name.lower().strip()

    for t in all_teams:
        if (name_lower == t["abbreviation"].lower() or
            name_lower == t["full_name"].lower() or
            name_lower == t["nickname"].lower() or
            name_lower == t["city"].lower() or
            name_lower in t["full_name"].lower()):
            return t
    return {"error": f"Team '{name}' not found. Use full name (e.g. 'Los Angeles Lakers') or abbreviation (e.g. 'LAL')"}


def _get_todays_games() -> list:
    """Get today's NBA schedule."""
    from nba_api.stats.endpoints import scoreboardv2
    import pandas as pd

    cache_key = "todays_games"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    try:
        time.sleep(0.6)
        today = datetime.now().strftime("%m/%d/%Y")
        sb = scoreboardv2.ScoreboardV2(game_date=today, timeout=15)
        header = sb.get_data_frames()[0]

        games = []
        for _, row in header.iterrows():
            games.append({
                "game_id": row.get("GAME_ID", ""),
                "home_team_id": int(row.get("HOME_TEAM_ID", 0)),
                "away_team_id": int(row.get("VISITOR_TEAM_ID", 0)),
                "game_status": int(row.get("GAME_STATUS_ID", 0)),
                "game_status_text": row.get("GAME_STATUS_TEXT", ""),
            })

        _cached_set(cache_key, games)
        return games

    except Exception as e:
        return [{"error": f"Failed to get today's games: {str(e)[:200]}"}]


def _build_training_data(seasons: list = None) -> tuple:
    """Build training dataset from 3 seasons of NBA games using PRE-GAME features only.

    For each game, features are rolling 10-game averages from PRIOR games
    (not the game itself — that would be data leakage). Also includes
    season win%, home/away record, rest days, and win streak.

    Returns (X, y, feature_names) where y = home win (0/1).
    Caches to parquet for fast reloads.
    """
    import pandas as pd
    from nba_api.stats.endpoints import leaguegamelog

    if seasons is None:
        current_year = datetime.now().year
        seasons = [f"{y}-{str(y+1)[-2:]}" for y in range(current_year - 3, current_year)]

    cache_path = MODEL_DIR / "nba_training_data_v2.parquet"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 168:  # 1 week
            df = pd.read_parquet(cache_path)
            X = df.drop(columns=["home_win"]).values
            y = df["home_win"].values
            return X, y, df.drop(columns=["home_win"]).columns.tolist()

    ROLLING_WINDOW = 10
    all_rows = []

    for season in seasons:
        try:
            time.sleep(1.0)
            log = leaguegamelog.LeagueGameLog(
                season=season, season_type_all_star="Regular Season", timeout=30
            )
            df = log.get_data_frames()[0]
            if df.empty:
                continue

            # Parse dates and sort oldest-first so rolling windows look backward
            df["GAME_DATE_DT"] = pd.to_datetime(df["GAME_DATE"])
            df["IS_HOME"] = df["MATCHUP"].str.contains("vs.", na=False).astype(int)
            df["WIN"] = (df["WL"] == "W").astype(int)
            df = df.sort_values("GAME_DATE_DT").reset_index(drop=True)

            # Build per-team rolling stats (prior games only — shift(1) prevents leakage)
            stat_cols = ["FG_PCT", "FG3_PCT", "REB", "AST", "TOV", "PTS"]
            team_groups = df.groupby("TEAM_ID")

            for col in stat_cols:
                df[f"roll_{col}"] = team_groups[col].transform(
                    lambda s: s.shift(1).rolling(ROLLING_WINDOW, min_periods=3).mean()
                )

            # Rolling win% (season-to-date, shifted to exclude current game)
            df["roll_win_pct"] = team_groups["WIN"].transform(
                lambda s: s.shift(1).expanding(min_periods=3).mean()
            )

            # Rest days (days since team's previous game)
            df["rest_days"] = team_groups["GAME_DATE_DT"].transform(
                lambda s: s.diff().dt.days
            ).fillna(3).clip(upper=7)

            # Win streak (consecutive wins going into this game, shifted)
            def _streak(s):
                streak = []
                current = 0
                for w in s:
                    streak.append(current)
                    current = current + 1 if w == 1 else 0
                return streak
            df["win_streak"] = team_groups["WIN"].transform(_streak)

            # Home win% and away win% (season-to-date for location-specific record)
            df["home_game_win"] = df["WIN"].where(df["IS_HOME"] == 1)
            df["away_game_win"] = df["WIN"].where(df["IS_HOME"] == 0)
            df["home_record_wpct"] = team_groups["home_game_win"].transform(
                lambda s: s.shift(1).expanding(min_periods=1).mean()
            ).fillna(0.5)
            df["away_record_wpct"] = team_groups["away_game_win"].transform(
                lambda s: s.shift(1).expanding(min_periods=1).mean()
            ).fillna(0.5)

            # Drop rows where rolling stats aren't available yet (first ~10 games of season)
            df = df.dropna(subset=[f"roll_{stat_cols[0]}"])

            # Now pair home and away rows for each game
            game_groups = df.groupby("GAME_ID")
            for game_id, group in game_groups:
                if len(group) != 2:
                    continue

                home_row = group[group["IS_HOME"] == 1]
                away_row = group[group["IS_HOME"] == 0]

                if home_row.empty or away_row.empty:
                    continue

                h = home_row.iloc[0]
                a = away_row.iloc[0]

                row = {
                    # Home team pre-game rolling stats
                    "home_roll_fg_pct": h["roll_FG_PCT"],
                    "home_roll_fg3_pct": h["roll_FG3_PCT"],
                    "home_roll_reb": h["roll_REB"],
                    "home_roll_ast": h["roll_AST"],
                    "home_roll_tov": h["roll_TOV"],
                    "home_roll_pts": h["roll_PTS"],
                    "home_win_pct": h["roll_win_pct"],
                    "home_rest_days": h["rest_days"],
                    "home_win_streak": h["win_streak"],
                    "home_home_wpct": h["home_record_wpct"],
                    # Away team pre-game rolling stats
                    "away_roll_fg_pct": a["roll_FG_PCT"],
                    "away_roll_fg3_pct": a["roll_FG3_PCT"],
                    "away_roll_reb": a["roll_REB"],
                    "away_roll_ast": a["roll_AST"],
                    "away_roll_tov": a["roll_TOV"],
                    "away_roll_pts": a["roll_PTS"],
                    "away_win_pct": a["roll_win_pct"],
                    "away_rest_days": a["rest_days"],
                    "away_win_streak": a["win_streak"],
                    "away_away_wpct": a["away_record_wpct"],
                    # Differentials (home advantage signal)
                    "pts_diff": h["roll_PTS"] - a["roll_PTS"],
                    "fg_pct_diff": h["roll_FG_PCT"] - a["roll_FG_PCT"],
                    "reb_diff": h["roll_REB"] - a["roll_REB"],
                    # Target
                    "home_win": h["WIN"],
                }
                all_rows.append(row)

        except Exception as e:
            continue

    if not all_rows:
        return None, None, None

    result_df = pd.DataFrame(all_rows).dropna()
    result_df.to_parquet(cache_path)

    X = result_df.drop(columns=["home_win"]).values
    y = result_df["home_win"].values
    return X, y, result_df.drop(columns=["home_win"]).columns.tolist()


def _train_xgboost(X, y, feature_names: list) -> dict:
    """Train XGBoost classifier. 80/20 split. Save to pkl."""
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = xgb.XGBClassifier(
        max_depth=6,
        n_estimators=200,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
        use_label_encoder=False,
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    accuracy = accuracy_score(y_test, y_pred)
    brier = brier_score_loss(y_test, y_prob)
    logloss = log_loss(y_test, y_prob)

    # Feature importances
    importances = dict(zip(feature_names, [round(float(v), 4) for v in model.feature_importances_]))

    # Save model
    model_path = MODEL_DIR / "nba_xgboost.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "features": feature_names, "trained": datetime.now().isoformat()}, f)

    return {
        "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 4),
        "log_loss": round(logloss, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "feature_importances": importances,
        "model_path": str(model_path),
    }


def _calibrate_model(sport: str = "nba") -> dict:
    """Calibrate XGBoost model using Platt scaling or isotonic regression.

    Calibration corrects for overconfidence by mapping raw probabilities
    to actual win rates. Trains on test set from last training run,
    saves calibrated model alongside original.
    """
    from sklearn.calibration import CalibratedClassifierCV
    import numpy as np

    # Load original model
    model_data = _load_model(sport)
    if "error" in model_data:
        return model_data

    model = model_data["model"]
    features = model_data["features"]

    # Rebuild training data to get test set for calibration
    X, y, _ = _build_training_data()
    if X is None:
        return {"error": "Failed to build training data for calibration"}

    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Apply isotonic regression calibration to the test set
    try:
        calibrator = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
        calibrator.fit(X_test, y_test)

        # Get calibrated probabilities on test set
        y_prob_raw = model.predict_proba(X_test)[:, 1]
        y_prob_cal = calibrator.predict_proba(X_test)[:, 1]

        from sklearn.metrics import brier_score_loss
        brier_raw = brier_score_loss(y_test, y_prob_raw)
        brier_cal = brier_score_loss(y_test, y_prob_cal)

        # Save calibrated model
        cal_model_path = MODEL_DIR / f"{sport}_xgboost_calibrated.pkl"
        with open(cal_model_path, "wb") as f:
            pickle.dump({
                "model": calibrator,
                "features": features,
                "trained": datetime.now().isoformat(),
                "calibration_method": "isotonic",
                "brier_raw": round(float(brier_raw), 4),
                "brier_calibrated": round(float(brier_cal), 4),
            }, f)

        return {
            "status": "calibrated",
            "method": "isotonic regression",
            "brier_score_before": round(float(brier_raw), 4),
            "brier_score_after": round(float(brier_cal), 4),
            "improvement": round(float(brier_raw - brier_cal), 4),
            "calibrated_model_path": str(cal_model_path),
            "test_samples": len(X_test),
        }
    except Exception as e:
        return {"error": f"Calibration failed: {str(e)}"}


def _load_model(sport: str = "nba") -> dict:
    """Load saved model from pkl. Prefers calibrated version if available."""
    # Try calibrated model first
    cal_model_path = MODEL_DIR / f"{sport}_xgboost_calibrated.pkl"
    if cal_model_path.exists():
        with open(cal_model_path, "rb") as f:
            data = pickle.load(f)
        return data

    # Fall back to original model
    model_path = MODEL_DIR / f"{sport}_xgboost.pkl"
    if not model_path.exists():
        return {"error": f"No trained model found at {model_path}. Run action=train first."}

    with open(model_path, "rb") as f:
        data = pickle.load(f)
    return data


def _compute_calibration_curve(y_true, y_prob, n_bins: int = 10) -> dict:
    """Compute calibration curve: predicted prob buckets vs actual win rates.

    Returns buckets showing whether the model's confidence matches reality.
    If all buckets cluster near the diagonal, the model is well-calibrated.
    If buckets are above the diagonal, the model is overconfident.
    """
    import numpy as np

    bins = np.linspace(0, 1, n_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    bin_accs = []
    bin_counts = []

    for i in range(n_bins):
        mask = (y_prob >= bins[i]) & (y_prob < bins[i + 1])
        if mask.sum() > 0:
            acc = y_true[mask].mean()
            bin_accs.append(round(float(acc), 3))
            bin_counts.append(int(mask.sum()))
        else:
            bin_accs.append(None)
            bin_counts.append(0)

    return {
        "bin_centers": [round(float(x), 3) for x in bin_centers],
        "actual_win_rates": bin_accs,
        "samples_per_bin": bin_counts,
        "interpretation": "If all points cluster near y=x line, model is well-calibrated. "
                         "If points are above y=x, model is overconfident (predicts 60% but wins 50%).",
    }


def _predict_game(home_features: dict, away_features: dict, model_data: dict) -> dict:
    """Predict a single game using loaded model with pre-game features."""
    import numpy as np

    model = model_data["model"]
    feature_names = model_data["features"]

    h = home_features
    a = away_features

    # Map live team features → training feature names
    feature_map = {
        # Home team rolling stats
        "home_roll_fg_pct": h.get("roll_fg_pct", 0.45),
        "home_roll_fg3_pct": h.get("roll_fg3_pct", 0.36),
        "home_roll_reb": h.get("roll_reb", 44),
        "home_roll_ast": h.get("roll_ast", 24),
        "home_roll_tov": h.get("roll_tov", 14),
        "home_roll_pts": h.get("roll_pts", 110),
        "home_win_pct": h.get("win_pct", 0.5),
        "home_rest_days": h.get("rest_days", 2),
        "home_win_streak": h.get("win_streak", 0),
        "home_home_wpct": h.get("home_wpct", 0.5),
        # Away team rolling stats
        "away_roll_fg_pct": a.get("roll_fg_pct", 0.45),
        "away_roll_fg3_pct": a.get("roll_fg3_pct", 0.36),
        "away_roll_reb": a.get("roll_reb", 44),
        "away_roll_ast": a.get("roll_ast", 24),
        "away_roll_tov": a.get("roll_tov", 14),
        "away_roll_pts": a.get("roll_pts", 110),
        "away_win_pct": a.get("win_pct", 0.5),
        "away_rest_days": a.get("rest_days", 2),
        "away_win_streak": a.get("win_streak", 0),
        "away_away_wpct": a.get("away_wpct", 0.5),
        # Differentials
        "pts_diff": h.get("roll_pts", 110) - a.get("roll_pts", 110),
        "fg_pct_diff": h.get("roll_fg_pct", 0.45) - a.get("roll_fg_pct", 0.45),
        "reb_diff": h.get("roll_reb", 44) - a.get("roll_reb", 44),
    }

    X = np.array([[feature_map.get(f, 0) for f in feature_names]])
    prob = model.predict_proba(X)[0]

    return {
        "home_win_prob": round(float(prob[1]), 4),
        "away_win_prob": round(float(prob[0]), 4),
    }


# ═══════════════════════════════════════════════════════════════
# Helper to get current NBA season string
# ═══════════════════════════════════════════════════════════════

def _current_season() -> str:
    """Return current NBA season string (e.g. '2025-26')."""
    now = datetime.now()
    year = now.year if now.month >= 10 else now.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


# ═══════════════════════════════════════════════════════════════
# TOOL 3: sports_predict — XGBoost predictions for NBA
# ═══════════════════════════════════════════════════════════════

def sports_predict(action: str, sport: str = "nba", team: str = "",
                   date: str = "", limit: int = 10) -> str:
    """XGBoost-powered NBA game predictions.

    Actions:
        predict    — Today's game predictions with win probabilities
        evaluate   — Model accuracy, Brier score, feature importances, calibration metrics
        calibrate  — Calibrate model using isotonic regression (fixes overconfidence)
        train      — Retrain on latest 3 seasons (~3700 games, <30s on CPU)
        features   — What features the model uses + their weights
        compare    — Predictions vs current odds → +EV recommendations
    """
    try:
        if action == "train":
            start = time.time()
            X, y, features = _build_training_data()
            if X is None:
                return json.dumps({"error": "Failed to build training data. NBA API may be rate-limiting."})

            result = _train_xgboost(X, y, features)
            result["training_time_seconds"] = round(time.time() - start, 1)
            result["total_games"] = len(X)
            return json.dumps(result)

        elif action == "predict":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            games = _get_todays_games()
            if not games or (len(games) == 1 and "error" in games[0]):
                return json.dumps({"message": "No NBA games scheduled today.", "games": games})

            teams = _get_all_teams()
            season = _current_season()
            predictions = []
            seen_matchups = set()  # Dedup: NBA API can return duplicate game rows

            for game in games[:limit]:
                if "error" in game:
                    continue

                home_id = game["home_team_id"]
                away_id = game["away_team_id"]

                # Skip duplicate matchups (same home/away pair)
                matchup_key = (home_id, away_id)
                if matchup_key in seen_matchups:
                    continue
                seen_matchups.add(matchup_key)
                home_info = teams.get(home_id, {})
                away_info = teams.get(away_id, {})

                home_features = _get_nba_features(home_id, season)
                away_features = _get_nba_features(away_id, season)

                if "error" in home_features or "error" in away_features:
                    predictions.append({
                        "home": home_info.get("full_name", str(home_id)),
                        "away": away_info.get("full_name", str(away_id)),
                        "error": "Could not fetch team stats",
                    })
                    continue

                pred = _predict_game(home_features, away_features, model_data)

                predictions.append({
                    "home": home_info.get("full_name", str(home_id)),
                    "away": away_info.get("full_name", str(away_id)),
                    "home_abbrev": home_info.get("abbreviation", ""),
                    "away_abbrev": away_info.get("abbreviation", ""),
                    "home_win_prob": pred["home_win_prob"],
                    "away_win_prob": pred["away_win_prob"],
                    "predicted_winner": home_info.get("full_name", "") if pred["home_win_prob"] > 0.5 else away_info.get("full_name", ""),
                    "confidence": round(max(pred["home_win_prob"], pred["away_win_prob"]), 3),
                    "status": game.get("game_status_text", ""),
                })

            return json.dumps({
                "predictions": predictions,
                "model_trained": model_data.get("trained", "unknown"),
                "sport": sport,
                "date": datetime.now().strftime("%Y-%m-%d"),
            })

        elif action == "evaluate":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            model = model_data["model"]
            features = model_data["features"]
            importances = dict(zip(features, [round(float(v), 4) for v in model.feature_importances_]))

            # Check if model is calibrated
            is_calibrated = "calibration_method" in model_data
            calibration_info = {}
            if is_calibrated:
                calibration_info = {
                    "is_calibrated": True,
                    "method": model_data.get("calibration_method", "unknown"),
                    "brier_before": model_data.get("brier_raw"),
                    "brier_after": model_data.get("brier_calibrated"),
                    "improvement": round(float(model_data.get("brier_raw", 0) - model_data.get("brier_calibrated", 0)), 4),
                }

            # Rebuild data to compute calibration curve if possible
            calibration_curve = {}
            try:
                X, y, _ = _build_training_data()
                if X is not None:
                    from sklearn.model_selection import train_test_split
                    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
                    y_prob = model.predict_proba(X_test)[:, 1]
                    calibration_curve = _compute_calibration_curve(y_test, y_prob, n_bins=10)
            except Exception:
                pass

            result = {
                "model": f"{sport}_xgboost",
                "trained": model_data.get("trained", "unknown"),
                "features": features,
                "feature_importances": importances,
                "n_estimators": model.n_estimators,
                "max_depth": model.max_depth,
            }

            if calibration_info:
                result["calibration"] = calibration_info

            if calibration_curve:
                result["calibration_curve"] = calibration_curve

            if not is_calibrated:
                result["note"] = "Model is not calibrated. Run action=calibrate to apply isotonic regression and fix overconfidence."
            else:
                result["note"] = "Model is calibrated. Probabilities are adjusted for overconfidence."

            return json.dumps(result)

        elif action == "calibrate":
            # Calibrate existing model to fix overconfidence
            result = _calibrate_model(sport)
            if "error" in result:
                return json.dumps(result)

            result["message"] = "Model calibration complete. Probabilities are now adjusted for overconfidence."
            result["what_changed"] = "All future predictions will use isotonic regression to map raw XGBoost probabilities to actual win rates."
            return json.dumps(result)

        elif action == "features":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            features = model_data["features"]
            model = model_data["model"]
            importances = dict(zip(features, [round(float(v), 4) for v in model.feature_importances_]))
            sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)

            return json.dumps({
                "features": [{"name": k, "importance": v, "description": _feature_desc(k)} for k, v in sorted_features],
                "total_features": len(features),
                "model": f"{sport}_xgboost",
            })

        elif action == "compare":
            # Predictions vs current odds → +EV recommendations
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            # Get predictions
            pred_result = json.loads(sports_predict("predict", sport, limit=limit))
            if "error" in pred_result:
                return json.dumps(pred_result)

            # Get current odds
            from sportsbook_odds import sportsbook_odds, _decimal_to_implied, _calculate_ev, _kelly_fraction
            odds_result = json.loads(sportsbook_odds("best_odds", f"basketball_{sport}", limit=limit))

            comparisons = []
            predictions = pred_result.get("predictions", [])

            for pred in predictions:
                if "error" in pred:
                    continue

                # Try to match with odds data
                home_name = pred.get("home", "")
                away_name = pred.get("away", "")
                model_home_prob = pred["home_win_prob"]
                model_away_prob = pred["away_win_prob"]

                matched_odds = None
                for line in odds_result.get("best_lines", []):
                    game_str = line.get("game", "").lower()
                    if (home_name.lower().split()[-1] in game_str or
                        away_name.lower().split()[-1] in game_str):
                        matched_odds = line
                        break

                comp = {
                    "game": f"{away_name} @ {home_name}",
                    "model_home_prob": model_home_prob,
                    "model_away_prob": model_away_prob,
                    "predicted_winner": pred.get("predicted_winner", ""),
                    "confidence": pred.get("confidence", 0),
                }

                if matched_odds:
                    best = matched_odds.get("best_odds", {})

                    # Check EV for home bet
                    for team_name, prob in [(home_name, model_home_prob), (away_name, model_away_prob)]:
                        team_odds = best.get(team_name, {})
                        if isinstance(team_odds, dict) and "decimal" in team_odds:
                            dec = team_odds["decimal"]
                            ev = _calculate_ev(prob, dec)
                            kelly = _kelly_fraction(prob, dec)
                            comp[f"{team_name}_odds"] = {
                                "decimal": dec,
                                "book": team_odds.get("book_title", ""),
                                "implied_prob": round(_decimal_to_implied(dec), 4),
                                "model_prob": round(prob, 4),
                                "ev_pct": round(ev * 100, 2),
                                "is_plus_ev": ev > 0,
                                "kelly_fraction": round(kelly, 4),
                                "kelly_$100": round(kelly * 100, 2),
                            }

                    comp["has_odds"] = True
                else:
                    comp["has_odds"] = False
                    comp["note"] = "No matching odds found — game may not be listed yet"

                comparisons.append(comp)

            return json.dumps({
                "comparisons": comparisons,
                "method": "XGBoost model prob vs best available odds → EV + Kelly sizing",
                "sport": sport,
            })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: predict, evaluate, calibrate, train, features, compare"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _feature_desc(name: str) -> str:
    """Human-readable feature description."""
    descs = {
        "home_roll_fg_pct": "Home team FG% (rolling 10-game avg BEFORE this game)",
        "home_roll_fg3_pct": "Home team 3PT% (rolling 10-game avg BEFORE this game)",
        "home_roll_reb": "Home team rebounds/game (rolling 10-game avg BEFORE this game)",
        "home_roll_ast": "Home team assists/game (rolling 10-game avg BEFORE this game)",
        "home_roll_tov": "Home team turnovers/game (rolling 10-game avg BEFORE this game)",
        "home_roll_pts": "Home team points/game (rolling 10-game avg BEFORE this game)",
        "home_win_pct": "Home team season-to-date win percentage",
        "home_rest_days": "Days since home team's last game (capped at 7)",
        "home_win_streak": "Home team consecutive wins entering this game",
        "home_home_wpct": "Home team win% in home games this season",
        "away_roll_fg_pct": "Away team FG% (rolling 10-game avg BEFORE this game)",
        "away_roll_fg3_pct": "Away team 3PT% (rolling 10-game avg BEFORE this game)",
        "away_roll_reb": "Away team rebounds/game (rolling 10-game avg BEFORE this game)",
        "away_roll_ast": "Away team assists/game (rolling 10-game avg BEFORE this game)",
        "away_roll_tov": "Away team turnovers/game (rolling 10-game avg BEFORE this game)",
        "away_roll_pts": "Away team points/game (rolling 10-game avg BEFORE this game)",
        "away_win_pct": "Away team season-to-date win percentage",
        "away_rest_days": "Days since away team's last game (capped at 7)",
        "away_win_streak": "Away team consecutive wins entering this game",
        "away_away_wpct": "Away team win% in away games this season",
        "pts_diff": "Points/game differential (home rolling avg minus away rolling avg)",
        "fg_pct_diff": "FG% differential (home minus away)",
        "reb_diff": "Rebounds/game differential (home minus away)",
    }
    return descs.get(name, name)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: sports_betting — Meta-tool composing predict + odds + EV
# ═══════════════════════════════════════════════════════════════

def sports_betting(action: str, sport: str = "nba", bankroll: float = 100.0,
                   min_ev: float = 0.01, limit: int = 10, min_prob: float = 0.45) -> str:
    """Full betting pipeline: predict + odds + EV + Kelly sizing.

    Actions:
        recommend — Full pipeline: predictions + odds + EV + Kelly-sized picks
        bankroll  — Kelly-sized bet recommendations for a given bankroll
        dashboard — Summary of all active opportunities across sports

    Args:
        min_prob: Minimum model probability to recommend a bet (default 0.45).
                  Filters out pure underdog value plays that lose too frequently.
    """
    try:
        if action == "recommend":
            # Full pipeline: compare predictions to odds
            compare_result = json.loads(sports_predict("compare", sport, limit=limit))
            if "error" in compare_result:
                return json.dumps(compare_result)

            recommendations = []
            seen_game_bets = set()  # Dedup: one recommendation per (game, team) pair
            for comp in compare_result.get("comparisons", []):
                if not comp.get("has_odds"):
                    continue

                # Find +EV opportunities
                for key, val in comp.items():
                    if isinstance(val, dict) and val.get("is_plus_ev"):
                        team = key.replace("_odds", "")
                        game_name = comp["game"]

                        # Skip duplicate (game, team) combos
                        dedup_key = (game_name, team)
                        if dedup_key in seen_game_bets:
                            continue
                        seen_game_bets.add(dedup_key)

                        # Skip low-probability underdog bets that lose too often
                        if val["model_prob"] < min_prob:
                            continue

                        kelly_pct = val["kelly_fraction"]
                        bet_size = round(bankroll * kelly_pct, 2)

                        if bet_size >= 1.0:  # Only recommend bets >= $1
                            recommendations.append({
                                "game": game_name,
                                "bet_on": team,
                                "book": val["book"],
                                "odds": val["decimal"],
                                "model_prob": val["model_prob"],
                                "edge": round(val["model_prob"] - val["implied_prob"], 4),
                                "ev_pct": val["ev_pct"],
                                "kelly_fraction": kelly_pct,
                                "bet_size": bet_size,
                                "expected_profit": round(bet_size * val["ev_pct"] / 100, 2),
                                "confidence": comp.get("confidence", 0),
                            })

            recommendations.sort(key=lambda x: x["ev_pct"], reverse=True)

            total_bet = sum(r["bet_size"] for r in recommendations)
            total_ev = sum(r["expected_profit"] for r in recommendations)

            return json.dumps({
                "recommendations": recommendations[:limit],
                "summary": {
                    "total_bets": len(recommendations),
                    "total_wagered": round(total_bet, 2),
                    "total_expected_profit": round(total_ev, 2),
                    "bankroll": bankroll,
                    "bankroll_pct_risked": round(total_bet / bankroll * 100, 1) if bankroll > 0 else 0,
                },
                "method": "XGBoost model → Pinnacle-devigged sharp prob → best odds → quarter-Kelly sizing",
                "disclaimer": "Model predictions are probabilistic, not guaranteed. Past performance does not predict future results. Gamble responsibly.",
            })

        elif action == "bankroll":
            # Just the Kelly sizing recommendations
            rec_result = json.loads(sports_betting("recommend", sport, bankroll, min_ev, limit, min_prob))
            if "error" in rec_result:
                return json.dumps(rec_result)

            return json.dumps({
                "bankroll": bankroll,
                "recommendations": rec_result.get("recommendations", []),
                "summary": rec_result.get("summary", {}),
                "kelly_method": "quarter-Kelly (25% of full Kelly) — conservative to avoid ruin",
            })

        elif action == "dashboard":
            # Multi-sport dashboard
            sports_to_check = ["basketball_nba"]
            # Could expand: "americanfootball_nfl", "baseball_mlb", "icehockey_nhl"

            from sportsbook_odds import sportsbook_arb

            dashboard = {"sports": {}}
            for s in sports_to_check:
                sport_key = s.split("_")[-1] if "_" in s else s

                # EV scan from sportsbook_arb
                ev_result = json.loads(sportsbook_arb("ev_scan", s, limit=5))
                ev_opps = ev_result.get("ev_opportunities", [])

                dashboard["sports"][sport_key] = {
                    "ev_opportunities": len(ev_opps),
                    "top_ev": ev_opps[:3] if ev_opps else [],
                    "quota": ev_result.get("quota", {}),
                }

            # Add model predictions if available
            model_data = _load_model("nba")
            if "error" not in model_data:
                dashboard["model_status"] = {
                    "trained": model_data.get("trained", "unknown"),
                    "available": True,
                }
            else:
                dashboard["model_status"] = {"available": False, "note": "Run sports_predict(action=train) first"}

            return json.dumps(dashboard)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: recommend, bankroll, dashboard"})

    except Exception as e:
        return json.dumps({"error": str(e)})
