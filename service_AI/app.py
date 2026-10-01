import os
import glob
import json
import logging
from typing import List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_env_file(env_path: str) -> None:
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        print(f"Warning: failed to load env file {env_path}: {exc}")

_load_env_file(os.path.join(os.path.dirname(BASE_DIR), ".env"))
_load_env_file(os.path.join(BASE_DIR, ".env"))

import torch
import pandas as pd
import requests
from flask import Flask, jsonify, request, render_template
# Enable CORS for cross-origin requests from the frontend (mobile/web during development)
try:
    from flask_cors import CORS
except Exception:
    CORS = None

from data import load_dataset
from settings import MOVIE_LENS_100k_DATASET_PATH, YOUTUBE_API_KEY
from tmdb_service import tmdb_service, search_and_cache_movie, MOVIE_CACHE
from youtube_service import initialize_youtube_service
from xgboost_recommender import XGBoostRecommender
from cold_start_recommender import (
    PopularityRecommender,
    ContentRecommender,
    ImplicitRecommender,
    HybridRecommender
)
from movie_manager import MovieManager
from vnpay import vnpay_bp
logger = logging.getLogger(__name__)

# BASE_DIR defined at the top
DATASET_DIR = os.getenv("DATASET_DIR", os.path.join(BASE_DIR, "datasets", "ml-100k"))
CACHE_FILE = os.path.join(BASE_DIR, "tmdb_cache.json")
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
YEAR_BINS = 4
GENRE_COLUMNS = [
    "unknown",
    "Action",
    "Adventure",
    "Animation",
    "Children's",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Film-Noir",
    "Horror",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
]


# _load_env_file defined and called at the top


app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Apply CORS if available; this allows the React Native/web frontend to contact the Flask API
if CORS is not None:
    CORS(app)
else:
    # If Flask-Cors is not installed the server will still work for same-origin calls
    print("Warning: flask_cors not installed; cross-origin requests may fail.\nInstall with: pip install Flask-Cors")

app.register_blueprint(vnpay_bp, url_prefix='/api/vnpay')

@app.get("/api/movies/top_rated")
def api_movies_top_rated():
    """Return top-rated visible movies by average rating from the `rating` table.
    Response shape: { results: [ { movie_id, title, genres, poster_path, overview, vote_average, avg_rating, rating_count, score } ] }
    """
    try:
        top_k = int(request.args.get('top_k', 20))

        # Fetch all ratings (server-side) and compute averages
        resp = _supabase_request('GET', 'rating', params={"select": "item_id,rating"})
        rows = resp.json()

        # Aggregate ratings per movie_id
        agg = {}
        if isinstance(rows, list):
            for r in rows:
                try:
                    mid = int(r.get('item_id'))
                    score = float(r.get('rating'))
                    if not _is_valid_movielens_movie_id(mid):
                        continue
                except Exception:
                    continue
                if mid not in agg:
                    agg[mid] = {'sum': 0.0, 'count': 0}
                agg[mid]['sum'] += score
                agg[mid]['count'] += 1

        # Compute averages and sort
        avg_list = []
        for mid, v in agg.items():
            avg = v['sum'] / v['count'] if v['count'] > 0 else 0.0
            avg_list.append((mid, avg, v['count']))

        # Sort by average rating desc, then by count desc
        avg_list.sort(key=lambda x: (x[1], x[2]), reverse=True)

        results = []
        num_added = 0
        for mid, avg, cnt in avg_list:
            if num_added >= top_k:
                break
            movie_data = MOVIE_DATA.get(mid, {})
            # Skip hidden movies
            if movie_data.get('is_hidden', False):
                continue
            enriched = enrich_movie_with_tmdb(mid, movie_data, save_cache=False)
            enriched['avg_rating'] = float(avg)
            enriched['rating_count'] = int(cnt)
            # Provide a normalized score in [0,1] for UI (avg/5)
            enriched['score'] = float(avg) / 5.0
            results.append(enriched)
            num_added += 1

        # If Supabase has no usable ratings yet, fall back to MovieLens training-data averages
        if not results:
            train_rating_matrix = MODELS_DATA.get('train_rating_matrix')
            if train_rating_matrix is not None:
                movie_count = train_rating_matrix.size(1)
                mv_scores = []
                for mid in range(movie_count):
                    col = train_rating_matrix[:, mid]
                    rated_mask = col > 0
                    rating_count = int(rated_mask.sum().item())
                    if rating_count <= 0:
                        continue
                    avg_rating = float(col[rated_mask].float().mean().item())
                    mv_scores.append((mid, avg_rating, rating_count))

                mv_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)
                mv_results = []
                for mid, avg, cnt in mv_scores[:top_k]:
                    movie_data = MOVIE_DATA.get(mid, {})
                    if movie_data.get('is_hidden', False):
                        continue
                    enriched = enrich_movie_with_tmdb(mid, movie_data, save_cache=False)
                    enriched['avg_rating'] = float(avg)
                    enriched['rating_count'] = int(cnt)
                    enriched['score'] = float(avg) / 5.0
                    mv_results.append(enriched)

                return jsonify({"results": mv_results})

        return jsonify({"results": results})
    except Exception as e:
        logger.warning(f"Failed to compute top-rated movies: {e}")
        return jsonify({"results": []})
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://kzcsegvlfaebwpxipqxx.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_MOVIE_TABLE = os.getenv("SUPABASE_MOVIE_TABLE", "movie")
SUPABASE_MOVIE_FIELDS = [
    "movie_id",
    "movie_title",
    "release_date",
    "video_release_date",
    "IMDb_URL",
    "description",
    "tmdb_id",
    "is_hidden",
    "deleted_at",
    "genres",
] + [f"column{i}" for i in range(6, 25)]
SUPABASE_MOVIES_LOADED = False


def _is_valid_movielens_movie_id(movie_id) -> bool:
    try:
        movie_id_int = int(movie_id)
    except (TypeError, ValueError):
        return False

    movies_emb = MODELS_DATA.get('movies_emb') if isinstance(globals().get('MODELS_DATA'), dict) else None
    if movies_emb is not None:
        return 0 <= movie_id_int < movies_emb.size(0)

    train_rating_matrix = MODELS_DATA.get('train_rating_matrix') if isinstance(globals().get('MODELS_DATA'), dict) else None
    if train_rating_matrix is not None:
        return 0 <= movie_id_int < train_rating_matrix.size(1)

    return movie_id_int >= 0


def _coerce_valid_movielens_ratings(ratings: dict) -> dict:
    """Keep only ratings whose movie ids are valid MovieLens embedding indices."""
    cleaned = {}
    for raw_movie_id, raw_rating in (ratings or {}).items():
        try:
            movie_id = int(raw_movie_id)
            if not _is_valid_movielens_movie_id(movie_id):
                continue
            cleaned[movie_id] = float(raw_rating)
        except Exception:
            continue
    return cleaned


def _supabase_headers():
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    if not key:
        raise RuntimeError("Supabase key is not configured")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _supabase_request(method: str, path: str, params=None, json_data=None, extra_headers=None):
    # Require SUPABASE_URL and at least one key (service or anon)
    if not SUPABASE_URL or not (SUPABASE_SERVICE_KEY or SUPABASE_KEY):
        raise RuntimeError("Supabase configuration is not available")

    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = _supabase_headers()
    if extra_headers:
        headers.update(extra_headers)

    # Small debug output to stdout to help diagnose server-side Supabase calls
    try:
        safe_params = params if params is None or isinstance(params, dict) else str(params)
        print(f"_supabase_request: {method} {url} params={safe_params} headers_apikey_set={('apikey' in headers)}")
    except Exception:
        pass

    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=15)
        try:
            response.raise_for_status()
        except Exception as e:
            # Print response for debugging (avoid printing full keys)
            try:
                print(f"_supabase_request: HTTP {response.status_code} body_len={len(response.text)}")
            except Exception:
                pass
            raise
        try:
            print(f"_supabase_request: HTTP {response.status_code} OK, body_len={len(response.text)}")
        except Exception:
            pass
        return response
    except Exception as exc:
        print(f"_supabase_request: request failed: {exc}")
        raise


def _fetch_ratings_from_supabase(user_uuid: str) -> dict:
    """Fetch ratings for a Supabase user id (UUID) from the `rating` table.
    Returns a dict mapping movie_id (int) -> rating (float).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        try:
            print(f"_fetch_ratings_from_supabase: Supabase config missing (SUPABASE_URL={bool(SUPABASE_URL)}, SUPABASE_KEY_set={bool(SUPABASE_KEY)})")
        except Exception:
            pass
        return {}

    try:
        # Query rating table for this user directly (server-side filter)
        params = {"select": "item_id,rating,user_uuid,user_id", "user_uuid": f"eq.{user_uuid}"}
        resp = _supabase_request("GET", "rating", params=params)
        rows = resp.json()
        # Log fetched rows for debugging (don't log full data in production)
        try:
            rows_count = len(rows) if isinstance(rows, list) else 1
        except Exception:
            rows_count = 1
        logger.debug(f"_fetch_ratings_from_supabase: fetched rows_count={rows_count}")
        try:
            sample = rows[:5] if isinstance(rows, list) else [rows]
            logger.debug(f"_fetch_ratings_from_supabase: sample_rows={sample}")
        except Exception:
            pass
        result = {}
        if isinstance(rows, list):
            for r in rows:
                try:
                    mid = int(r.get("item_id"))
                    score = float(r.get("rating"))
                    result[mid] = score
                except Exception:
                    continue

        # If no rows matched by UUID, try legacy numeric user_id via the profile
        if not result:
            try:
                profile = _fetch_profile_from_supabase(user_uuid)
                numeric_id = profile.get('raw', {}).get('user_id') if isinstance(profile.get('raw', {}), dict) else None
                if numeric_id:
                    print(f"_fetch_ratings_from_supabase: no uuid matches, trying numeric user_id={numeric_id}")
                    num_ratings = _fetch_ratings_from_supabase_by_user_id(int(numeric_id))
                    if num_ratings:
                        return num_ratings
            except Exception:
                pass
        logger.debug(f"_fetch_ratings_from_supabase: matched_ratings_count={len(result)}")
        # Also print to stdout so development servers show this information
        try:
            print(f"_fetch_ratings_from_supabase: matched_ratings_count={len(result)} for user={user_uuid}")
        except Exception:
            pass
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch ratings from Supabase for user {user_uuid}: {e}")
        return {}


def _fetch_profile_from_supabase(user_uuid: str) -> dict:
    """Fetch the stored Supabase profile row for a user id, if available."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}

    try:
        resp = _supabase_request("GET", "profile", params={"select": "*", "id": f"eq.{user_uuid}"})
        rows = resp.json()
        if not rows:
            return {}

        row = rows[0] if isinstance(rows, list) else {}
        return {
            "id": row.get("id"),
            "name": row.get("name"),
            "email": row.get("email"),
            "gender": row.get("gender"),
            "job": row.get("job"),
            "phone": row.get("phone"),
            "role": row.get("role"),
            "banned": row.get("banned"),
            "is_locked": row.get("is_locked"),
            "raw": row,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch Supabase profile for user {user_uuid}: {e}")
        return {}


def _fetch_ratings_from_supabase_by_user_id(user_id: int) -> dict:
    """Fetch ratings by numeric user_id (legacy rows). Returns dict movie_id->rating."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}

    try:
        resp = _supabase_request("GET", "rating", params={"select": "item_id,rating,user_uuid,user_id", "user_id": f"eq.{user_id}"})
        rows = resp.json()
        result = {}
        for r in rows:
            try:
                mid = int(r.get("item_id"))
                score = float(r.get("rating"))
                result[mid] = score
            except Exception:
                continue
        print(f"_fetch_ratings_from_supabase_by_user_id: matched_ratings_count={len(result)} for numeric_user_id={user_id}")
        return result
    except Exception as e:
        logger.warning(f"Failed to fetch ratings from Supabase for numeric user {user_id}: {e}")
        return {}


def _normalize_supabase_movie_row(row: dict) -> dict:
    movie_id = row.get("movie_id") or row.get("id")
    if movie_id is None:
        return {}

    try:
        movie_id = int(movie_id)
    except (ValueError, TypeError):
        return {}

    title = row.get("title") or row.get("movie_title") or row.get("Movie_Title") or ""
    release_date = row.get("release_date") or row.get("Release_Date") or ""
    imdb_url = row.get("imdb_url") or row.get("IMDb_URL") or row.get("IMDbUrl") or ""
    description = row.get("description") or row.get("Description") or ""
    tmdb_id = row.get("tmdb_id") or row.get("tmdbId")
    if tmdb_id is not None and tmdb_id != "":
        try:
            tmdb_id = int(tmdb_id)
        except (ValueError, TypeError):
            tmdb_id = None

    genres = row.get("genres")
    if genres is None:
        genres = []
        for idx in range(6, 25):
            for key in (f"column{idx}", f"Column{idx}", f"COLUMN{idx}"):
                if key in row:
                    value = row.get(key)
                    if value in (1, "1", True, "true", "t", "on"):
                        genres.append(GENRE_COLUMNS[idx - 6])
                        break
    elif isinstance(genres, str):
        try:
            genres = json.loads(genres)
        except Exception:
            genres = [g.strip() for g in genres.split(",") if g.strip()]

    return {
        "movie_id": movie_id,
        "title": title,
        "release_date": release_date,
        "imdb_url": imdb_url,
        "description": description,
        "tmdb_id": tmdb_id,
        "genres": genres,
        "is_hidden": bool(row.get("is_hidden", False)),
        "deleted_at": row.get("deleted_at"),
    }


def _load_movies_from_supabase() -> list:
    global SUPABASE_MOVIES_LOADED
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []

    try:
        response = _supabase_request("GET", SUPABASE_MOVIE_TABLE, params={"select": "*"})
        rows = response.json()
        movies = []
        for row in rows:
            movie = _normalize_supabase_movie_row(row)
            if movie:
                movies.append(movie)

        if movies:
            SUPABASE_MOVIES_LOADED = True
        return movies
    except Exception as e:
        logger.warning(f"Failed to load Supabase movie data: {e}")
        return []


def _latest_file(pattern: str) -> Optional[str]:
    candidates = glob.glob(os.path.join(BASE_DIR, pattern))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _load_data_and_models():
    """Load dataset and trained embeddings for RSAttAE inference."""
    train_df, val_df, test_df, train_rating_matrix, val_rating_matrix, test_rating_matrix, users_features, movies_features = load_dataset(
        MOVIE_LENS_100k_DATASET_PATH,
        split=1,
        val_size=0.15
    )
    
    train_rating_matrix = train_rating_matrix.to(torch.float32)
    movies_features = movies_features.to(torch.float32)

    users_emb_path = _latest_file("users_embeddings_attention_autoencoder_*.pt")
    movies_emb_path = _latest_file("movies_embeddings_attention_autoencoder_*.pt")

    if not users_emb_path or not movies_emb_path:
        raise FileNotFoundError(
            "Missing trained embeddings. Run train_user_attention_autoencoder.py and "
            "train_movie_attention_autoencoder.py to generate *.pt files."
        )

    users_emb = torch.load(users_emb_path, map_location="cpu").float()
    movies_emb = torch.load(movies_emb_path, map_location="cpu").float()

    users_emb = users_emb / (users_emb.norm(dim=1, keepdim=True) + 1e-8)
    movies_emb = movies_emb / (movies_emb.norm(dim=1, keepdim=True) + 1e-8)

    movies_features_norm = movies_features / (movies_features.norm(dim=1, keepdim=True) + 1e-8)

    return {
        'train_rating_matrix': train_rating_matrix,
        'users_emb': users_emb,
        'movies_emb': movies_emb,
        'movies_features': movies_features,
        'movies_features_norm': movies_features_norm,
        'device': DEVICE
    }




def _load_movie_titles() -> List[str]:
    """Load movie titles from MovieLens 100K dataset only."""
    item_path = os.path.join(DATASET_DIR, "u.item")
    if not os.path.exists(item_path):
        return []
    df = pd.read_table(
        item_path,
        header=None,
        sep="|",
        encoding="latin-1",
        names=[
            "movie_id",
            "movie_title",
            "release_date",
            "video_release_date",
            "imdb_url",
            "unknown",
            "Action",
            "Adventure",
            "Animation",
            "Children's",
            "Comedy",
            "Crime",
            "Documentary",
            "Drama",
            "Fantasy",
            "Film-Noir",
            "Horror",
            "Musical",
            "Mystery",
            "Romance",
            "Sci-Fi",
            "Thriller",
            "War",
            "Western",
        ],
    )
    titles = df["movie_title"].tolist()
    return titles


def _load_movie_data() -> dict:
    """Load detailed movie data from MovieLens 100K dataset only."""
    item_path = os.path.join(DATASET_DIR, "u.item")
    if not os.path.exists(item_path):
        return {}
    
    df = pd.read_table(
        item_path,
        header=None,
        sep="|",
        encoding="latin-1",
        names=[
            "movie_id",
            "movie_title",
            "release_date",
            "video_release_date",
            "imdb_url",
            "unknown",
            "Action",
            "Adventure",
            "Animation",
            "Children's",
            "Comedy",
            "Crime",
            "Documentary",
            "Drama",
            "Fantasy",
            "Film-Noir",
            "Horror",
            "Musical",
            "Mystery",
            "Romance",
            "Sci-Fi",
            "Thriller",
            "War",
            "Western",
        ],
    )
    
    # Convert to dictionary indexed by movie_id (from dataset column, 1-based)
    movie_data_dict = {}
    for idx, row in df.iterrows():
        genre_cols = GENRE_COLUMNS
        genres = [g for g in genre_cols if row.get(g, 0) == 1]
        
        movie_id = int(row["movie_id"])  # Use actual movie_id from dataset, not iterrows idx
        movie_data_dict[movie_id] = {
            "movie_id": movie_id,
            "title": row["movie_title"],
            "release_date": row["release_date"],
            "imdb_url": row["imdb_url"],
            "genres": genres,
        }
    
    return movie_data_dict


def _load_tmdb_cache():
    """Load TMDB cache from file."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
    return {}


def _save_tmdb_cache():
    """Save TMDB cache to file."""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(MOVIE_CACHE, f)
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


def _merge_custom_movies():
    """Keep the recommender dataset anchored to MovieLens 100K.

    Supabase can still store admin-created movie rows, but they are not merged into
    the trained-model movie index to avoid breaking embedding alignment.
    """
    try:
        custom_movies = MovieManager.load_custom_movies()
        logger.info(f"Loaded {len(custom_movies)} custom movies for storage, but kept MOVIE_DATA on MovieLens 100K")
    except Exception as e:
        logger.warning(f"Failed to merge custom movies: {e}")


def refresh_movie_data():
    """Reload movie metadata cache from MovieLens 100K dataset."""
    global MOVIE_TITLES, MOVIE_DATA
    MOVIE_TITLES = _load_movie_titles()
    MOVIE_DATA = _load_movie_data()
    logger.info(f"Refreshed movie cache: {len(MOVIE_DATA)} movies")


def filter_hidden_movies(movies_list):
    """Filter out hidden movies from a list (for user-facing endpoints)."""
    return [m for m in movies_list if not m.get("is_hidden", False)]


# Initialize YouTube service
youtube_service = initialize_youtube_service(YOUTUBE_API_KEY)

# User ratings storage (in production, use database)
USER_RATINGS = {}  # Format: {session_id: {movie_id: rating}}
USER_PREFERENCES = {}  # Format: {session_id: {favorite_genres: [], ...}}
USER_INTERACTIONS = {}  # Format: {session_id: {clicks: [], views: []}}

print("Loading data and embeddings...")
MODELS_DATA = _load_data_and_models()
MOVIE_TITLES = _load_movie_titles()
MOVIE_DATA = _load_movie_data()
ENABLE_XGBOOST_RECOMMENDER = os.getenv("ENABLE_XGBOOST_RECOMMENDER", "0") == "1"
XGB_MODEL_PATH = _latest_file("xgb_recommender*.json") if ENABLE_XGBOOST_RECOMMENDER else None
XGB_RECOMMENDER = XGBoostRecommender(XGB_MODEL_PATH) if ENABLE_XGBOOST_RECOMMENDER else None

# Merge custom movies from movies_custom.json
print("Loading custom movies...")
_merge_custom_movies()

# Load TMDB cache
print("Loading TMDB cache...")
cached_data = _load_tmdb_cache()
MOVIE_CACHE.update(cached_data)
print(f"Loaded {len(cached_data)} cached TMDB entries")

# Initialize cold-start recommenders
print("Initializing cold-start recommenders...")
popularity_rec = PopularityRecommender(MOVIE_CACHE)
content_rec = ContentRecommender(
    MODELS_DATA['movies_features'], 
    GENRE_COLUMNS,
    movies_emb=MODELS_DATA['movies_emb']  # Pass embeddings for new genre logic
)
implicit_rec = ImplicitRecommender(MODELS_DATA['movies_emb'])
hybrid_rec = HybridRecommender(popularity_rec, content_rec, implicit_rec)

print("Ready to serve recommendations!")


def get_popular_movies_cold_start(session_id: str, top_k: int = 20, favorite_genres: list = None):
    """Get popular visible (non-hidden) movies for cold-start users."""
    try:
        # Get user preferences if exist
        prefs = USER_PREFERENCES.get(session_id, {})
        if favorite_genres is None:
            favorite_genres = prefs.get('favorite_genres', [])
        
        # Calculate scores for each visible movie
        movie_scores = []
        for movie_id, movie_data in MOVIE_DATA.items():
            # Skip hidden movies for users
            if movie_data.get("is_hidden", False):
                continue
            
            score = 0.0
            
            # Base score from enriched TMDB data
            cache_key = f"ml_{movie_id}"
            if cache_key in MOVIE_CACHE:
                vote_avg = MOVIE_CACHE[cache_key].get('vote_average', 5.0)
                score = vote_avg / 10.0  # Normalize to [0, 1]
            else:
                score = 0.5  # Default middle score
            
            # Bonus for matching favorite genres
            if favorite_genres:
                movie_genres = movie_data.get('genres', [])
                genre_matches = sum(1 for g in favorite_genres if g in movie_genres)
                if genre_matches > 0:
                    score += 0.3 * (genre_matches / len(favorite_genres))
            
            movie_scores.append((movie_id, score))
        
        # Sort by score and get top K
        movie_scores.sort(key=lambda x: x[1], reverse=True)
        top_movies = movie_scores[:top_k]
        
        # Format results
        recommendations = []
        for movie_id, score in top_movies:
            movie_data = MOVIE_DATA.get(movie_id, {})
            enriched = enrich_movie_with_tmdb(movie_id, movie_data, save_cache=False)
            enriched["score"] = float(score)
            recommendations.append(enriched)
        
        return recommendations
        
    except Exception as e:
        logger.error(f"Error in cold start recommendations: {e}")
        # Fallback to first N visible movies
        fallback = []
        for movie_id in list(MOVIE_DATA.keys())[:top_k]:
            movie_data = MOVIE_DATA[movie_id]
            # Skip hidden movies
            if movie_data.get("is_hidden", False):
                continue
            enriched = enrich_movie_with_tmdb(movie_id, movie_data, save_cache=False)
            enriched["score"] = 0.5
            fallback.append(enriched)
        return fallback


def _get_method_message(method: str, favorite_genres: list, clicked_movies: list) -> str:
    """Get user-friendly message for recommendation method."""
    messages = {
        "cold_start_popular": "Phim được đánh giá cao nhất",
        "cold_start_genre": f"Gợi ý dựa trên sở thích: {', '.join(favorite_genres[:3])}",
        "cold_start_implicit": f"Gợi ý dựa trên {len(clicked_movies)} phim bạn đã xem",
        "hybrid": "Gợi ý kết hợp (AI Similarity)",
        "collaborative_filtering": "Gợi ý từ AI (XGBoost)",
        "fallback_popular": "Phim được đánh giá cao nhất",
        "fallback_hybrid": "Gợi ý kết hợp (Dự phòng)"
    }
    return messages.get(method, "Phim gợi ý cho bạn")


def _score_movies_with_xgboost(user_vector: torch.Tensor, top_k: int, exclude_ids: List[int] = None):
    """Score all movies with XGBoost and return top-k visible recommendations."""
    if not XGB_RECOMMENDER.ready:
        raise RuntimeError("XGBoost recommender model is not available")

    movies_emb = MODELS_DATA['movies_emb']
    movies_features = MODELS_DATA['movies_features']
    num_movies = movies_emb.size(0)

    scores = XGB_RECOMMENDER.score_movies(user_vector, movies_emb, movies_features)
    scores = torch.from_numpy(scores).float()

    exclude_ids = exclude_ids or []
    if exclude_ids:
        valid_excludes = [mid for mid in exclude_ids if 0 <= mid < num_movies]
        if valid_excludes:
            scores[valid_excludes] = float("-inf")

    top_k = max(1, min(top_k, num_movies))
    top_scores, top_indices = torch.topk(scores, k=top_k)

    recommendations = []
    for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
        movie_data = MOVIE_DATA.get(idx, {})
        if movie_data.get("is_hidden", False):
            continue
        enriched = enrich_movie_with_tmdb(idx, movie_data)
        enriched["score"] = float(score)
        recommendations.append(enriched)

    return recommendations


def _recommend_via_rsattae_xgb(user_vector: torch.Tensor, top_k: int, candidates: int = 200, exclude_ids: List[int] = None, hybrid_alpha: float = 1.0):
    """Generate candidates with RSAttAE (cosine) then re-rank with XGBoost.
    - user_vector: torch Tensor (embedding) of shape (D,) or (1,D)
    - candidates: number of candidates to generate via cosine
    - hybrid_alpha: weight on XGBoost prob (1.0 = only XGB)
    """
    if not XGB_RECOMMENDER.ready:
        raise RuntimeError("XGBoost recommender model is not available")

    movies_emb = MODELS_DATA['movies_emb']
    movies_features = MODELS_DATA['movies_features']
    num_movies = movies_emb.size(0)

    # Cosine scores (embeddings are normalized on load)
    cos_scores = torch.mv(movies_emb, user_vector).detach()

    # Exclude seen
    exclude_ids = exclude_ids or []
    if exclude_ids:
        valid_excludes = [mid for mid in exclude_ids if 0 <= mid < num_movies]
        if valid_excludes:
            mask = torch.zeros(num_movies, dtype=torch.bool)
            mask[valid_excludes] = True
            cos_scores = cos_scores.masked_fill(mask, float("-inf"))

    cand_k = max(1, min(candidates, num_movies))
    cand_scores, cand_indices = torch.topk(cos_scores, k=cand_k)
    cand_indices_list = cand_indices.tolist()

    # Prepare candidate inputs for XGBoost
    cand_embs = movies_emb[cand_indices_list]
    cand_feats = movies_features[cand_indices_list]

    probs = XGB_RECOMMENDER.score_movies(user_vector, cand_embs, cand_feats)
    probs = np.asarray(probs, dtype=np.float32)

    if hybrid_alpha < 1.0:
        # normalize cosine candidate scores to [0,1]
        cs = cand_scores.detach().cpu().numpy().astype(np.float32)
        cs_min, cs_max = cs.min(), cs.max()
        if cs_max - cs_min > 1e-8:
            cs_norm = (cs - cs_min) / (cs_max - cs_min)
        else:
            cs_norm = (cs - cs_min)
        final_scores = hybrid_alpha * probs + (1.0 - hybrid_alpha) * cs_norm
    else:
        final_scores = probs

    # Sort candidates by final score and format results
    pairs = list(zip(cand_indices_list, final_scores.tolist()))
    pairs.sort(key=lambda x: x[1], reverse=True)

    recommendations = []
    for mid, score in pairs[:top_k]:
        movie_data = MOVIE_DATA.get(mid, {})
        if movie_data.get("is_hidden", False):
            continue
        enriched = enrich_movie_with_tmdb(mid, movie_data)
        enriched["score"] = float(score)
        recommendations.append(enriched)

    return recommendations


@app.get("/api/user/status/<session_id>")
def api_user_status(session_id: str):
    """Get user status (rating count, preferences, etc.)"""
    supabase_user_id = request.args.get("supabase_user_id")
    ratings = USER_RATINGS.get(session_id, {})
    profile = {}

    if supabase_user_id:
        supabase_ratings = _fetch_ratings_from_supabase(supabase_user_id)
        if supabase_ratings:
            try:
                ratings = _coerce_valid_movielens_ratings(supabase_ratings)
            except Exception:
                ratings = supabase_ratings
            try:
                print(f"api_user_status: using sb ratings count={len(ratings)} for user={supabase_user_id}")
            except Exception:
                pass
        else:
            # Try to fetch profile and numeric legacy user_id fallback
            profile = _fetch_profile_from_supabase(supabase_user_id)
            numeric_id = None
            try:
                numeric_id = profile.get('raw', {}).get('user_id')
            except Exception:
                numeric_id = None
            if numeric_id:
                try:
                    num_ratings = _fetch_ratings_from_supabase_by_user_id(int(numeric_id))
                    if num_ratings:
                        try:
                            ratings = _coerce_valid_movielens_ratings(num_ratings)
                        except Exception:
                            ratings = num_ratings
                        print(f"api_user_status: numeric fallback used, ratings_count={len(ratings)} for user_id={numeric_id}")
                except Exception:
                    pass
        # Ensure profile is set if not already
        if not profile:
            profile = _fetch_profile_from_supabase(supabase_user_id)

    prefs = USER_PREFERENCES.get(session_id, {})
    
    return jsonify({
        "session_id": session_id,
        "supabase_user_id": supabase_user_id,
        "rating_count": len(ratings),
        "has_preferences": len(prefs) > 0,
        "onboarded": len(ratings) >= 5,
        "profile": profile,
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/genres")
def api_genres():
    """Get list of available genres."""
    genres_list = [
        {"genre": "Action", "describe": "Phim hành động"},
        {"genre": "Adventure", "describe": "Phim phiêu lưu"},
        {"genre": "Animation", "describe": "Phim hoạt hình"},
        {"genre": "Children's", "describe": "Phim thiếu nhi"},
        {"genre": "Comedy", "describe": "Phim hài"},
        {"genre": "Crime", "describe": "Phim tội phạm"},
        {"genre": "Documentary", "describe": "Phim tài liệu"},
        {"genre": "Drama", "describe": "Phim tâm lý"},
        {"genre": "Fantasy", "describe": "Phim kỳ ảo"},
        {"genre": "Film-Noir", "describe": "Phim đen trắng"},
        {"genre": "Horror", "describe": "Phim kinh dị"},
        {"genre": "Musical", "describe": "Phim nhạc kịch"},
        {"genre": "Mystery", "describe": "Phim bí ẩn"},
        {"genre": "Romance", "describe": "Phim tình cảm"},
        {"genre": "Sci-Fi", "describe": "Phim khoa học viễn tưởng"},
        {"genre": "Thriller", "describe": "Phim giật gân"},
        {"genre": "War", "describe": "Phim chiến tranh"},
        {"genre": "Western", "describe": "Phim miền tây"},
    ]
    return jsonify({
        "genres": genres_list,
        "count": len(genres_list)
    })


@app.post("/api/recommend")
def api_recommend_post():
    """Get personalized recommendations with enhanced cold-start handling."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    top_k = data.get("top_k", 20)
    supabase_user_id = data.get("supabase_user_id") or data.get("user_uuid")
    
    # Get user data
    ratings = USER_RATINGS.get(session_id, {})

    # If caller provided a Supabase user id, prefer ratings stored in Supabase
    if supabase_user_id:
        try:
            logger.debug(f"api_recommend_post: supabase_user_id={supabase_user_id}")
            print(f"api_recommend_post: received supabase_user_id={supabase_user_id}")
            sb_ratings = _fetch_ratings_from_supabase(supabase_user_id)
            logger.debug(f"api_recommend_post: sb_ratings_count={len(sb_ratings)}")
            print(f"api_recommend_post: sb_ratings_count={len(sb_ratings)}")
            if sb_ratings:
                # Override in-memory ratings with persisted ratings
                try:
                    ratings = _coerce_valid_movielens_ratings(sb_ratings)
                except Exception:
                    ratings = sb_ratings
                try:
                    sample_keys = list(ratings.keys())[:5]
                    print(f"api_recommend_post: using sb ratings count={len(ratings)}, sample_keys={sample_keys}")
                except Exception:
                    print(f"api_recommend_post: using sb ratings count={len(ratings)} (keys not shown)")
            else:
                # Try legacy numeric user_id from profile (some rows store user_id instead of user_uuid)
                profile = _fetch_profile_from_supabase(supabase_user_id)
                numeric_id = None
                try:
                    numeric_id = profile.get('raw', {}).get('user_id')
                except Exception:
                    numeric_id = None
                if numeric_id:
                    try:
                        num_ratings = _fetch_ratings_from_supabase_by_user_id(int(numeric_id))
                        print(f"api_recommend_post: numeric lookup returned {len(num_ratings)} ratings for user_id={numeric_id}")
                        if num_ratings:
                            try:
                                ratings = _coerce_valid_movielens_ratings(num_ratings)
                            except Exception:
                                ratings = num_ratings
                    except Exception as e:
                        print(f"api_recommend_post: numeric lookup failed: {e}")
        except Exception as e:
            logger.warning(f"api_recommend_post: Supabase lookup failed: {e}")
            print(f"api_recommend_post: Supabase lookup failed: {e}")
            # If Supabase lookup fails, continue with in-memory ratings
            pass
    prefs = USER_PREFERENCES.get(session_id, {})
    interactions = USER_INTERACTIONS.get(session_id, {})
    
    favorite_genres = prefs.get('favorite_genres', [])
    clicked_movies = interactions.get('clicks', [])
    num_ratings = len(ratings)
    
    # Require at least 5 ratings for personalized recommendations
    if num_ratings < 5:
        return jsonify({
            "recommendations": [],
            "session_id": session_id,
            "based_on_ratings": num_ratings,
            "method": "none",
            "message": "Đánh giá ít nhất 5 phim để nhận gợi ý"
        })
    
    # COLLABORATIVE FILTERING: User has enough ratings (>= 5)
    try:
        # Create user profile from rated movies
        rated_movie_ids = list(ratings.keys())
        rated_scores = [ratings[mid] / 5.0 for mid in rated_movie_ids]
        movies_emb = MODELS_DATA['movies_emb']

        # Weighted average of movie embeddings
        rated_embs = movies_emb[rated_movie_ids]
        weights = torch.tensor(rated_scores, dtype=torch.float32).unsqueeze(1)
        user_profile = (rated_embs * weights).sum(dim=0) / weights.sum()
        user_profile = user_profile / (user_profile.norm() + 1e-8)

        if ENABLE_XGBOOST_RECOMMENDER and XGB_RECOMMENDER is not None and XGB_RECOMMENDER.ready:
            candidate_size = int(os.getenv("XGB_CANDIDATE_SIZE", "200"))
            hybrid_alpha = float(os.getenv("XGB_HYBRID_ALPHA", "1.0"))
            recommendations = _recommend_via_rsattae_xgb(
                user_profile,
                top_k=top_k,
                candidates=candidate_size,
                exclude_ids=rated_movie_ids,
                hybrid_alpha=hybrid_alpha,
            )
            method_name = "xgboost_classifier"
            model_name = "XGBoost Recommender (RSAttAE features)"
        else:
            num_movies = movies_emb.size(0)
            scores = torch.mv(movies_emb, user_profile)

            # Exclude rated movies
            mask = torch.zeros(num_movies, dtype=torch.bool)
            mask[rated_movie_ids] = True
            scores = scores.masked_fill(mask, float("-inf"))

            # Get top K
            top_k = max(1, min(top_k, num_movies))
            top_scores, top_indices = torch.topk(scores, k=top_k)

            # Format results - filter out hidden movies
            recommendations = []
            for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
                movie_data = MOVIE_DATA.get(idx, {})
                # Skip hidden movies for users
                if movie_data.get("is_hidden", False):
                    continue
                enriched = enrich_movie_with_tmdb(idx, movie_data)
                enriched["score"] = float(score)
                recommendations.append(enriched)
            method_name = "collaborative_filtering"
            model_name = "RSAttAE (Attention Autoencoder)"
        
        return jsonify({
            "recommendations": recommendations,
            "session_id": session_id,
            "based_on_ratings": num_ratings,
            "method": method_name,
            "model": model_name
        })
        
    except Exception as e:
        logger.error(f"Error in collaborative filtering: {e}")
        # Fallback to hybrid
        recs, method = hybrid_rec.adaptive_recommend(
            movie_data=MOVIE_DATA,
            num_ratings=num_ratings,
            favorite_genres=favorite_genres,
            clicked_movie_ids=clicked_movies,
            top_k=top_k,
            exclude_ids=list(ratings.keys())
        )
        recommendations = []
        for movie_id, score in recs:
            movie_data = MOVIE_DATA.get(movie_id, {})
            # Skip hidden movies for users
            if movie_data.get("is_hidden", False):
                continue
            enriched = enrich_movie_with_tmdb(movie_id, movie_data, save_cache=False)
            enriched["score"] = float(score)
            recommendations.append(enriched)
        
        return jsonify({
            "recommendations": recommendations,
            "session_id": session_id,
            "method": "fallback_hybrid",
            "error": str(e)
        }), 200


@app.get("/api/movies/similar/<int:movie_id>")
def api_similar_movies(movie_id: int):
    """Get similar visible (non-hidden) movies based on embedding cosine similarity."""
    top_k = request.args.get("top_k", 10, type=int)
    # Default to enriching with TMDB so list results include posters/overview.
    # Clients can opt-out with `enrich=false`.
    enrich = request.args.get("enrich", default="true", type=str).lower() == "true"
    
    try:
        movies_emb = MODELS_DATA['movies_emb']
        if movie_id < 0 or movie_id >= movies_emb.size(0):
            return jsonify({"error": "Movie ID out of range"}), 400
        
        query_emb = movies_emb[movie_id]
        # Since embeddings were normalized in _load_data_and_models, dot product is cosine similarity
        scores = torch.mv(movies_emb, query_emb)
        
        # Exclude self
        scores[movie_id] = float("-inf")
        
        top_k = max(1, min(top_k, movies_emb.size(0) - 1))
        top_scores, top_indices = torch.topk(scores, k=top_k)
        
        recommendations = []
        for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
            movie_data = MOVIE_DATA.get(idx, {})
            # Skip hidden movies for users
            if movie_data.get("is_hidden", False):
                continue
            if enrich:
                enriched = enrich_movie_with_tmdb(idx, movie_data)
                enriched["score"] = float(score)
                recommendations.append(enriched)
            else:
                # Fast, no external calls
                item = {
                    "movie_id": idx,
                    "score": float(score),
                    "title": movie_data.get("title", MOVIE_TITLES[idx]) if idx < len(MOVIE_TITLES) else movie_data.get("title", "")
                }
                recommendations.append(item)
            
        return jsonify({
            "movie_id": movie_id,
            "results": recommendations
        })
    except Exception as e:
        logger.error(f"Error in similar movies: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/api/movies/onboarding")
def api_onboarding_movies():
    """Get a diverse set of visible (non-hidden) movies for onboarding rating grid."""
    limit = request.args.get("limit", 20, type=int)
    # Default to enriching with TMDB so list results include posters/overview.
    # Clients can opt-out with `enrich=false`.
    enrich = request.args.get("enrich", default="true", type=str).lower() == "true"
    
    try:
        # Get visible movies that have TMDB data (posters) and are somewhat popular
        # For now, just take a diverse sample from different genres
        movies_to_show = []
        movies_per_genre = max(1, limit // len(GENRE_COLUMNS))
        
        selected_ids = set()
        
        for genre in GENRE_COLUMNS:
            if genre == "unknown": continue
            
            genre_movies = [mid for mid, data in MOVIE_DATA.items() 
                           if genre in data.get("genres", []) and not data.get("is_hidden", False)]
            
            # Take some movies from each genre
            import random
            sample = random.sample(genre_movies, min(len(genre_movies), movies_per_genre))
            for mid in sample:
                if mid not in selected_ids:
                    selected_ids.add(mid)
                    movie_data = MOVIE_DATA[mid]
                    if enrich:
                        enriched = enrich_movie_with_tmdb(mid, movie_data)
                        # Only add if we have a poster when enriching
                        if enriched.get("poster_path"):
                            movies_to_show.append(enriched)
                    else:
                        # Minimal data without calling TMDB (fast)
                        cache_key = f"ml_{mid}"
                        poster_path = None
                        if isinstance(MOVIE_CACHE, dict):
                            poster_path = MOVIE_CACHE.get(cache_key, {}).get("poster_path")
                            try:
                                tmdb_id = movie_data.get("tmdb_id")
                                if poster_path is None and tmdb_id is not None:
                                    poster_path = MOVIE_CACHE.get(tmdb_id, {}).get("poster_path") or MOVIE_CACHE.get(str(tmdb_id), {}).get("poster_path")
                            except Exception:
                                pass
                        movies_to_show.append({
                            "movie_id": mid,
                            "title": movie_data.get("title", ""),
                            "genres": movie_data.get("genres", []),
                            "release_date": movie_data.get("release_date", ""),
                            "poster_path": poster_path,
                        })
                
                if len(movies_to_show) >= limit:
                    break
            if len(movies_to_show) >= limit:
                break
                
        # If not enough, fill with any visible movies that have posters
        if len(movies_to_show) < limit:
            remaining = [mid for mid in MOVIE_DATA.keys() 
                        if mid not in selected_ids and not MOVIE_DATA[mid].get("is_hidden", False)]
            random.shuffle(remaining)
            for mid in remaining:
                movie_data = MOVIE_DATA[mid]
                enriched = enrich_movie_with_tmdb(mid, movie_data)
                if enriched.get("poster_path"):
                    movies_to_show.append(enriched)
                    selected_ids.add(mid)
                if len(movies_to_show) >= limit:
                    break
                    
        random.shuffle(movies_to_show)
        return jsonify({"movies": movies_to_show})
        
    except Exception as e:
        logger.error(f"Error in onboarding movies: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/api/recommend")
def api_recommend():
    """API endpoint for recommendations (JSON response)."""
    user_id = request.args.get("user_id", type=int)
    top_n = request.args.get("top_n", default=10, type=int)
    exclude_seen = request.args.get("exclude_seen", default=1, type=int)

    if user_id is None:
        return jsonify({"error": "user_id is required"}), 400

    train_rating_matrix = MODELS_DATA['train_rating_matrix']
    users_emb = MODELS_DATA['users_emb']
    movies_emb = MODELS_DATA['movies_emb']

    num_users = train_rating_matrix.size(0)
    num_movies = train_rating_matrix.size(1)

    if user_id < 0 or user_id >= num_users:
        return jsonify({"error": f"user_id out of range [0, {num_users-1}]"}), 400

    try:
        user_vec = users_emb[user_id]

        if ENABLE_XGBOOST_RECOMMENDER and XGB_RECOMMENDER is not None and XGB_RECOMMENDER.ready:
            exclude_ids = torch.where(train_rating_matrix[user_id] > 0)[0].tolist() if exclude_seen else []
            candidate_size = int(os.getenv("XGB_CANDIDATE_SIZE", "200"))
            hybrid_alpha = float(os.getenv("XGB_HYBRID_ALPHA", "1.0"))
            results = _recommend_via_rsattae_xgb(
                user_vec,
                top_k=top_n,
                candidates=candidate_size,
                exclude_ids=exclude_ids,
                hybrid_alpha=hybrid_alpha,
            )
            model_name = "XGBoost Recommender (RSAttAE features)"
        else:
            scores = torch.mv(movies_emb, user_vec)

            if exclude_seen:
                seen = train_rating_matrix[user_id] > 0
                scores = scores.masked_fill(seen, float("-inf"))

            top_n = max(1, min(top_n, num_movies))
            top_scores, top_indices = torch.topk(scores, k=top_n)

            results = []
            for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
                # Skip hidden movies for users
                if MOVIE_DATA.get(idx, {}).get("is_hidden", False):
                    continue
                item = {"movie_id": idx, "score": float(score)}
                if idx < len(MOVIE_TITLES):
                    item["title"] = MOVIE_TITLES[idx]
                results.append(item)
            model_name = "RSAttAE (Information-Aware Attention Autoencoder)"

        return jsonify({
            "user_id": user_id,
            "top_n": top_n,
            "exclude_seen": bool(exclude_seen),
            "results": results,
            "model": model_name
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/recommend_coldstart")
def api_recommend_coldstart():
    """Cold-start recommendations using content features (genres/year)."""
    top_n = request.args.get("top_n", default=10, type=int)
    genres_raw = request.args.get("genres", default="", type=str)

    movies_features_norm = MODELS_DATA['movies_features_norm']
    num_movies = movies_features_norm.size(0)

    selected = [g.strip() for g in genres_raw.split(",") if g.strip()]
    selected_set = {g.lower() for g in selected}

    try:
        user_vec = torch.zeros(YEAR_BINS + len(GENRE_COLUMNS), dtype=torch.float32)

        # Uniform preference over year bins
        user_vec[:YEAR_BINS] = 1.0 / YEAR_BINS

        # Genre preferences
        for idx, genre in enumerate(GENRE_COLUMNS):
            if genre.lower() in selected_set:
                user_vec[YEAR_BINS + idx] = 1.0

        if user_vec.sum() == 0:
            user_vec[:YEAR_BINS] = 1.0 / YEAR_BINS

        user_vec = user_vec / (user_vec.norm() + 1e-8)
        scores = torch.mv(movies_features_norm, user_vec)

        top_n = max(1, min(top_n, num_movies))
        top_scores, top_indices = torch.topk(scores, k=top_n)

        results = []
        for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
            # Skip hidden movies for users
            if MOVIE_DATA.get(idx, {}).get("is_hidden", False):
                continue
            item = {"movie_id": idx, "score": float(score)}
            if idx < len(MOVIE_TITLES):
                item["title"] = MOVIE_TITLES[idx]
            results.append(item)

        return jsonify({
            "top_n": top_n,
            "results": results,
            "model": "RSAttAE (Cold-start via Content Features)"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/recommend_from_movies")
def api_recommend_from_movies():
    """Cold-start recommendations from clicked visible (non-hidden) movies (implicit feedback)."""
    top_n = request.args.get("top_n", default=10, type=int)
    movie_ids_raw = request.args.get("movie_ids", default="", type=str)
    exclude_seed = request.args.get("exclude_seed", default=1, type=int)

    movies_emb = MODELS_DATA['movies_emb']
    num_movies = movies_emb.size(0)

    try:
        movie_ids = [int(x.strip()) for x in movie_ids_raw.split(",") if x.strip()]
        if not movie_ids:
            return jsonify({"error": "movie_ids is required (comma-separated)"}), 400

        valid_ids = [mid for mid in movie_ids if 0 <= mid < num_movies]
        if not valid_ids:
            return jsonify({"error": "No valid movie_ids provided"}), 400

        seed_emb = movies_emb[valid_ids].mean(dim=0)
        seed_emb = seed_emb / (seed_emb.norm() + 1e-8)

        scores = torch.mv(movies_emb, seed_emb)

        if exclude_seed:
            mask = torch.zeros(num_movies, dtype=torch.bool)
            mask[valid_ids] = True
            scores = scores.masked_fill(mask, float("-inf"))

        top_n = max(1, min(top_n, num_movies))
        top_scores, top_indices = torch.topk(scores, k=top_n)

        results = []
        for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
            # Skip hidden movies for users
            if MOVIE_DATA.get(idx, {}).get("is_hidden", False):
                continue
            item = {"movie_id": idx, "score": float(score)}
            if idx < len(MOVIE_TITLES):
                item["title"] = MOVIE_TITLES[idx]
            results.append(item)

        return jsonify({
            "top_n": top_n,
            "seed_movies": valid_ids,
            "exclude_seed": bool(exclude_seed),
            "results": results,
            "model": "RSAttAE (Cold-start via Clicked Movies)"
        })

    except ValueError:
        return jsonify({"error": "movie_ids must be integers"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/")
def index():
    """Render web interface."""
    num_users = MODELS_DATA['train_rating_matrix'].size(0)
    return render_template('index.html', num_users=num_users, genres=GENRE_COLUMNS)


@app.get("/api/tmdb/search")
def api_tmdb_search():
    """Search for a movie on TMDB - only show non-hidden movies."""
    query = request.args.get("query", "", type=str).strip()
    
    if not query:
        return jsonify({"error": "query is required"}), 400
    
    try:
        # First check if movie exists in our database and is hidden
        query_lower = query.lower()
        is_hidden_in_db = False
        
        for movie_id, movie_data in MOVIE_DATA.items():
            title = movie_data.get("title", "").lower()
            if query_lower in title:
                # If movie is hidden or deleted, don't show it
                if movie_data.get("is_hidden", False) or movie_data.get("deleted_at"):
                    is_hidden_in_db = True
                break
        
        # If movie is hidden in database, don't show it
        if is_hidden_in_db:
            return jsonify({"results": []})
        
        # Search from TMDB
        movie_data = tmdb_service.search_movie(query)
        if not movie_data:
            return jsonify({"results": []})
        
        # Get full details
        tmdb_id = movie_data.get("id")
        details = tmdb_service.get_movie_details(tmdb_id)
        
        if details:
            formatted = tmdb_service.format_movie_data(details, include_credits=True)
        else:
            formatted = tmdb_service.format_movie_data(movie_data)
        
        return jsonify({"results": [formatted]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/tmdb/movie/<int:tmdb_id>")
def api_tmdb_movie(tmdb_id: int):
    """Get detailed movie information from TMDB."""
    try:
        movie_data = tmdb_service.get_movie_details(tmdb_id)
        if not movie_data:
            return jsonify({"error": "Movie not found"}), 404
        
        formatted = tmdb_service.format_movie_data(movie_data, include_credits=True)
        
        # Add reviews
        reviews = tmdb_service.get_movie_reviews(tmdb_id)
        formatted["reviews"] = reviews[:5]  # Top 5 reviews
        
        # Add watch providers
        watch_providers = tmdb_service.get_watch_providers(tmdb_id)
        if watch_providers:
            formatted["watch_providers"] = watch_providers
        
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/tmdb/reviews/<int:tmdb_id>")
def api_tmdb_reviews(tmdb_id: int):
    """Get reviews for a movie from TMDB."""
    try:
        reviews = tmdb_service.get_movie_reviews(tmdb_id)
        return jsonify({"reviews": reviews})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.get("/api/tmdb/popular")
def api_tmdb_popular():
    """Get popular movies from TMDB."""
    try:
        movies = tmdb_service.get_popular_movies()
        results = []
        
        for movie in movies[:20]:  # Top 20
            formatted = tmdb_service.format_movie_data(movie)
            results.append(formatted)
        
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/movie/<int:movie_id>/tmdb")
def api_movie_with_tmdb(movie_id: int):
    """Get movie from ML-100K with TMDB enrichment."""
    if movie_id < 0 or movie_id >= len(MOVIE_TITLES):
        return jsonify({"error": "Movie ID out of range"}), 400
    
    # Skip hidden movies for users
    if MOVIE_DATA.get(movie_id, {}).get("is_hidden", False):
        return jsonify({"error": "Movie not found"}), 404
    
    try:
        # Get local movie data
        local_data = MOVIE_DATA.get(movie_id, {})

        # Check cache first
        cache_key = f"ml_{movie_id}"
        if cache_key in MOVIE_CACHE:
            cached = MOVIE_CACHE[cache_key]
            response_data = {
                "movie_id": movie_id,
                "title": local_data.get("title", MOVIE_TITLES[movie_id]),
                "genres": local_data.get("genres", []),
                "imdb_url": local_data.get("imdb_url", ""),
                "poster_path": cached.get("poster_path"),
                "overview": cached.get("overview"),
                "vote_average": cached.get("vote_average")
            }
            # If we have a tmdb_id in cache, get full details
            tmdb_id = cached.get("tmdb_id")
            if tmdb_id:
                details = tmdb_service.get_movie_details(tmdb_id)
                if details:
                    response_data["tmdb"] = tmdb_service.format_movie_data(details, include_credits=True)
            return jsonify(response_data)

        # Clean title and extract year
        import re
        title = local_data.get("title", MOVIE_TITLES[movie_id])
        year = None
        
        # Try to extract year from title or release_date
        match = re.search(r'\((\d{4})\)', title)
        if match:
            year = int(match.group(1))
            title = re.sub(r'\s*\(\d{4}\)', '', title).strip()
        
        if not year and local_data.get("release_date"):
            try:
                year = int(local_data.get("release_date").split("-")[0])
            except: pass
        
        tmdb_movie = tmdb_service.search_movie(title, year)
        
        # Fallback: search without year if no result
        if not tmdb_movie:
            tmdb_movie = tmdb_service.search_movie(title, None)
        
        response_data = {
            "movie_id": movie_id,
            "title": local_data.get("title", MOVIE_TITLES[movie_id]),
            "genres": local_data.get("genres", []),
            "imdb_url": local_data.get("imdb_url", ""),
        }
        
        if tmdb_movie:
            tmdb_id = tmdb_movie.get("id")
            details = tmdb_service.get_movie_details(tmdb_id)
            
            if details:
                formatted = tmdb_service.format_movie_data(details, include_credits=True)
                response_data["tmdb"] = formatted
                response_data["poster_path"] = formatted.get("poster_path")
                response_data["overview"] = formatted.get("overview")
                response_data["vote_average"] = formatted.get("vote_average")
            else:
                # Fallback to search result info
                response_data["poster_path"] = tmdb_service.get_image_url(tmdb_movie.get("poster_path"))
                response_data["overview"] = tmdb_movie.get("overview")
                response_data["vote_average"] = tmdb_movie.get("vote_average")
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def enrich_movie_with_tmdb(movie_id: int, movie_data: dict, save_cache: bool = False) -> dict:
    """Enrich movie data with TMDB information (poster, overview, etc.)."""
    enriched = {
        "movie_id": movie_id,
        "title": movie_data.get("title", ""),
        "genres": movie_data.get("genres", []),
        "release_date": movie_data.get("release_date", ""),
        "imdb_url": movie_data.get("imdb_url", ""),
    }
    
    try:
        # Check if already cached
        cache_key = f"ml_{movie_id}"
        if cache_key in MOVIE_CACHE:
            tmdb_data = MOVIE_CACHE[cache_key]
            enriched["poster_path"] = tmdb_data.get("poster_path")
            enriched["overview"] = tmdb_data.get("overview")
            enriched["vote_average"] = tmdb_data.get("vote_average")
            return enriched
            
        # Parse title to remove year (format is "Title (Year)")
        import re
        title = movie_data.get("title", "")
        year = None
        
        # Try to extract year from title
        match = re.search(r'^(.+?)\s*\((\d{4})\)$', title)
        if match:
            title = match.group(1).strip()
            year = int(match.group(2))
        elif movie_data.get("release_date"):
            # Fallback to release_date
            try:
                year = int(movie_data.get("release_date").split("-")[0])
            except:
                pass
        
        # Try multiple search strategies
        tmdb_movie = None
        
        # Strategy 1: Search with title and year
        if year:
            tmdb_movie = tmdb_service.search_movie(title, year)
        
        # Strategy 2: Search without year if first attempt failed
        if not tmdb_movie:
            tmdb_movie = tmdb_service.search_movie(title, None)
        
        # Strategy 3: Simplify title (remove subtitle after comma/colon) and retry
        if not tmdb_movie and (',' in title or ':' in title or '(' in title):
            simple_title = re.split(r'[,:(]', title)[0].strip()
            if len(simple_title) > 3:  # Avoid too short titles
                tmdb_movie = tmdb_service.search_movie(simple_title, year)
                if not tmdb_movie:
                    tmdb_movie = tmdb_service.search_movie(simple_title, None)
        
        if tmdb_movie:
            poster = tmdb_movie.get("poster_path")

            # Nếu search trả về movie nhưng không có poster
            # → thử gọi thêm movie details
            if not poster and tmdb_movie.get("id"):
                try:
                    details = tmdb_service.get_movie_details(tmdb_movie["id"])
                    if details:
                        poster = details.get("poster_path")
                        tmdb_movie = details
                except:
                    pass

            # Set data if found
            if tmdb_movie:
                enriched["poster_path"] = tmdb_movie.get("poster_path")
                enriched["overview"] = tmdb_movie.get("overview")
                enriched["vote_average"] = tmdb_movie.get("vote_average")

                # Cache if found
                MOVIE_CACHE[cache_key] = {
                    "tmdb_id": tmdb_movie.get("id"),
                    "poster_path": enriched["poster_path"],
                    "overview": enriched["overview"],
                    "vote_average": enriched["vote_average"],
                }

                if save_cache and len(MOVIE_CACHE) % 10 == 0:
                    _save_tmdb_cache()
            
        return enriched

        
    except Exception as e:
        logger.warning(f"Failed to enrich movie {movie_id}: {e}")
    
    return enriched


@app.get("/api/movies")
def api_movies_list():
    """Get list of all visible (non-hidden) movies with pagination and optional genre filter."""
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=20, type=int)
    genre_filter = request.args.get("genre", default="", type=str).strip()
    # Default to enriching with TMDB so search results include posters/overview.
    # Clients can opt-out with `enrich=false`.
    enrich = request.args.get("enrich", default="true", type=str).lower() == "true"
    
    # Get all visible movies (exclude hidden ones)
    movies_list = []
    for movie_id, movie_data in MOVIE_DATA.items():
        # Skip hidden movies for users
        if movie_data.get("is_hidden", False):
            continue
        
        # Apply genre filter if specified
        if genre_filter:
            if genre_filter not in movie_data.get("genres", []):
                continue
        
        if enrich:
            # Enrich with TMDB data (poster, overview, etc.)
            enriched = enrich_movie_with_tmdb(movie_id, movie_data, save_cache=True)
            movies_list.append(enriched)
        else:
            # Include poster_path from local TMDB cache when available to avoid extra network calls
            cache_key = f"ml_{movie_id}"
            poster_path = None
            if isinstance(MOVIE_CACHE, dict):
                poster_path = MOVIE_CACHE.get(cache_key, {}).get("poster_path")
                # Fallback: try numeric TMDB id keys if available
                try:
                    tmdb_id = movie_data.get("tmdb_id")
                    if poster_path is None and tmdb_id is not None:
                        poster_path = MOVIE_CACHE.get(tmdb_id, {}).get("poster_path") or MOVIE_CACHE.get(str(tmdb_id), {}).get("poster_path")
                except Exception:
                    pass
            movies_list.append({
                "movie_id": movie_id,
                "title": movie_data.get("title", ""),
                "genres": movie_data.get("genres", []),
                "release_date": movie_data.get("release_date", ""),
                "poster_path": poster_path,
            })
    
    # Sort by movie_id
    movies_list.sort(key=lambda x: x["movie_id"])
    
    # Pagination
    total = len(movies_list)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_movies = movies_list[start_idx:end_idx]
    
    return jsonify({
        "movies": paginated_movies,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page
    })


@app.get("/api/search")
def api_search_movies():
    """Search for visible (non-hidden) movies by title and/or genre."""
    query = request.args.get("q", default="", type=str).strip().lower()
    genre_filter = request.args.get("genre", default="", type=str).strip()
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=20, type=int)
    enrich = request.args.get("enrich", default="false", type=str).lower() == "true"
    
    if not query and not genre_filter:
        return jsonify({"error": "Please provide either 'q' (search query) or 'genre' parameter"}), 400
    
    # Search through all movies
    results = []
    for movie_id, movie_data in MOVIE_DATA.items():
        # Skip hidden movies and deleted movies
        if movie_data.get("is_hidden", False) or movie_data.get("deleted_at"):
            continue
        
        # Apply genre filter if specified
        if genre_filter:
            if genre_filter not in movie_data.get("genres", []):
                continue
        
        # Apply title search if query specified
        if query:
            title = movie_data.get("title", "").lower()
            if query not in title:
                continue
        
        if enrich:
            enriched = enrich_movie_with_tmdb(movie_id, movie_data, save_cache=True)
            results.append(enriched)
        else:
            cache_key = f"ml_{movie_id}"
            poster_path = None
            if isinstance(MOVIE_CACHE, dict):
                poster_path = MOVIE_CACHE.get(cache_key, {}).get("poster_path")
                try:
                    tmdb_id = movie_data.get("tmdb_id")
                    if poster_path is None and tmdb_id is not None:
                        poster_path = MOVIE_CACHE.get(tmdb_id, {}).get("poster_path") or MOVIE_CACHE.get(str(tmdb_id), {}).get("poster_path")
                except Exception:
                    pass
            results.append({
                "movie_id": movie_id,
                "title": movie_data.get("title", ""),
                "genres": movie_data.get("genres", []),
                "release_date": movie_data.get("release_date", ""),
                "poster_path": poster_path,
            })
    
    # Sort by title for better UX
    results.sort(key=lambda x: x["title"])
    
    # Pagination
    total = len(results)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_results = results[start_idx:end_idx]
    
    return jsonify({
        "results": paginated_results,
        "query": query,
        "genre": genre_filter,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page
    })


@app.get("/api/movie/<int:movie_id>/videos")
def api_movie_videos(movie_id: int):
    """Get videos/trailers for a movie."""
    if movie_id < 0 or movie_id >= len(MOVIE_TITLES):
        return jsonify({"error": "Movie ID out of range"}), 400
    
    # Skip hidden movies for users
    if MOVIE_DATA.get(movie_id, {}).get("is_hidden", False):
        return jsonify({"error": "Movie not found"}), 404
    
    try:
        # Get local movie data
        local_data = MOVIE_DATA.get(movie_id, {})
        title = local_data.get("title", MOVIE_TITLES[movie_id])
        release_date = local_data.get("release_date", "")
        
        # Extract year
        year = None
        if release_date:
            try:
                year = int(release_date.split("-")[0])
            except:
                pass
        
        # Search TMDB
        tmdb_movie = tmdb_service.search_movie(title, year)
        
        if not tmdb_movie:
            return jsonify({"videos": []})
        
        tmdb_id = tmdb_movie.get("id")
        videos = tmdb_service.get_movie_videos(tmdb_id)
        
        # Filter for trailers and teasers
        youtube_videos = [
            {
                "key": v.get("key"),
                "name": v.get("name"),
                "type": v.get("type"),
                "site": v.get("site"),
                "url": f"https://www.youtube.com/watch?v={v.get('key')}" if v.get("site") == "YouTube" else None
            }
            for v in videos if v.get("site") == "YouTube"
        ]
        
        return jsonify({"videos": youtube_videos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/rate")
def api_rate_movie():
    """Rate a movie and get personalized recommendations."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    movie_id = data.get("movie_id")
    rating = data.get("rating")
    
    if movie_id is None or rating is None:
        return jsonify({"error": "movie_id and rating are required"}), 400
    
    movie_id = int(movie_id)
    rating = float(rating)
    
    if movie_id < 0 or movie_id >= len(MOVIE_TITLES):
        return jsonify({"error": "Invalid movie_id"}), 400
    
    if rating < 0 or rating > 5:
        return jsonify({"error": "Rating must be between 0 and 5"}), 400
    
    # Store rating
    if session_id not in USER_RATINGS:
        USER_RATINGS[session_id] = {}
    
    USER_RATINGS[session_id][movie_id] = rating
    
    return jsonify({
        "success": True,
        "message": "Rating saved",
        "total_ratings": len(USER_RATINGS[session_id])
    })


@app.post("/api/recommend_from_ratings")
def api_recommend_from_ratings():
    """Get recommendations based on user ratings."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    top_n = data.get("top_n", 10)
    
    # Get user ratings
    ratings = USER_RATINGS.get(session_id, {})
    
    if not ratings:
        return jsonify({"error": "No ratings found. Please rate some movies first."}), 400
    
    try:
        movies_emb = MODELS_DATA['movies_emb']
        num_movies = movies_emb.size(0)
        
        # Create user profile from rated movies
        rated_movie_ids = list(ratings.keys())
        rated_scores = [ratings[mid] / 5.0 for mid in rated_movie_ids]  # Normalize to [0, 1]
        
        # Weighted average of movie embeddings based on ratings
        rated_embs = movies_emb[rated_movie_ids]
        weights = torch.tensor(rated_scores, dtype=torch.float32).unsqueeze(1)
        user_profile = (rated_embs * weights).sum(dim=0) / weights.sum()
        user_profile = user_profile / (user_profile.norm() + 1e-8)
        
        # Compute scores
        scores = torch.mv(movies_emb, user_profile)
        
        # Exclude already rated movies
        mask = torch.zeros(num_movies, dtype=torch.bool)
        mask[rated_movie_ids] = True
        scores = scores.masked_fill(mask, float("-inf"))
        
        # Get top N
        top_n = max(1, min(top_n, num_movies))
        top_scores, top_indices = torch.topk(scores, k=top_n)
        
        results = []
        for idx, score in zip(top_indices.tolist(), top_scores.tolist()):
            # Skip hidden movies for users
            if MOVIE_DATA.get(idx, {}).get("is_hidden", False):
                continue
            item = {"movie_id": idx, "score": float(score)}
            if idx < len(MOVIE_TITLES):
                item["title"] = MOVIE_TITLES[idx]
            results.append(item)
        
        return jsonify({
            "results": results,
            "based_on_ratings": len(ratings),
            "model": "RSAttAE (Based on User Ratings)"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/ratings/<session_id>")
def api_get_ratings(session_id: str):
    """Get ratings for a specific session."""
    ratings = USER_RATINGS.get(session_id, {})
    
    # Format with movie titles
    formatted_ratings = []
    for movie_id, rating in ratings.items():
        formatted_ratings.append({
            "movie_id": movie_id,
            "rating": rating
        })
    
    return jsonify({
        "ratings": formatted_ratings,
        "total": len(ratings)
    })


@app.get("/api/user_ratings")
def api_get_user_ratings():
    """Get current user's ratings."""
    session_id = request.args.get("session_id", "default")
    ratings = USER_RATINGS.get(session_id, {})
    
    # Format with movie titles
    formatted_ratings = []
    for movie_id, rating in ratings.items():
        formatted_ratings.append({
            "movie_id": movie_id,
            "title": MOVIE_TITLES[movie_id] if movie_id < len(MOVIE_TITLES) else f"Movie {movie_id}",
            "rating": rating
        })
    
    return jsonify({
        "ratings": formatted_ratings,
        "total": len(ratings)
    })


@app.post("/api/preferences")
def api_save_preferences():
    """Save user preferences (favorite genres, etc.) for cold-start."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    favorite_genres = data.get("favorite_genres", [])
    
    # Validate genres
    valid_genres = set(GENRE_COLUMNS)
    validated_genres = [g for g in favorite_genres if g in valid_genres]
    
    # Save preferences
    USER_PREFERENCES[session_id] = {
        "favorite_genres": validated_genres,
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
    return jsonify({
        "success": True,
        "favorite_genres": validated_genres,
        "message": "Preferences saved successfully"
    })


@app.get("/api/preferences/<session_id>")
def api_get_preferences(session_id: str):
    """Get user preferences."""
    prefs = USER_PREFERENCES.get(session_id, {})
    return jsonify({
        "preferences": prefs,
        "has_preferences": len(prefs) > 0
    })


@app.post("/api/user/reset")
def api_reset_user_data():
    """Reset local session data and clear persisted Supabase user data when available."""
    data = request.get_json() or {}

    session_id = data.get("session_id", "default")
    supabase_user_id = data.get("supabase_user_id") or data.get("user_uuid")

    ratings = USER_RATINGS.pop(session_id, {})
    preferences = USER_PREFERENCES.pop(session_id, {})
    interactions = USER_INTERACTIONS.pop(session_id, {"clicks": [], "views": []})

    removed_local = {
        "ratings": len(ratings),
        "preferences": len(preferences),
        "interactions_clicks": len(interactions.get("clicks", [])),
        "interactions_views": len(interactions.get("views", [])),
    }

    removed_supabase = {
        "ratings": 0,
        "watch_history": 0,
    }

    if supabase_user_id and SUPABASE_URL and SUPABASE_KEY:
        try:
            profile = _fetch_profile_from_supabase(supabase_user_id)
            numeric_user_id = None
            try:
                numeric_user_id = profile.get("raw", {}).get("user_id")
            except Exception:
                numeric_user_id = None

            rating_filters = [{"user_uuid": f"eq.{supabase_user_id}"}]
            if numeric_user_id not in (None, ""):
                rating_filters.append({"user_id": f"eq.{numeric_user_id}"})

            for params in rating_filters:
                try:
                    _supabase_request("DELETE", "rating", params=params)
                except Exception as exc:
                    logger.warning(f"Failed to delete Supabase ratings for user {supabase_user_id}: {exc}")

            # watch_history uses the Supabase auth user id in the client code
            try:
                _supabase_request("DELETE", "watch_history", params={"user_id": f"eq.{supabase_user_id}"})
            except Exception as exc:
                logger.warning(f"Failed to delete Supabase watch history for user {supabase_user_id}: {exc}")
        except Exception as exc:
            logger.warning(f"Failed to reset Supabase user data for {supabase_user_id}: {exc}")

    return jsonify({
        "success": True,
        "session_id": session_id,
        "removed_local": removed_local,
        "removed_supabase": removed_supabase,
    })


@app.post("/api/track_view")
def api_track_view():
    """Track movie view/click for implicit feedback."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    movie_id = data.get("movie_id")
    
    if movie_id is None:
        return jsonify({"error": "movie_id is required"}), 400
    
    movie_id = int(movie_id)
    
    # Initialize interactions if not exists
    if session_id not in USER_INTERACTIONS:
        USER_INTERACTIONS[session_id] = {
            "clicks": [],
            "views": []
        }
    
    # Add to clicks list (avoid duplicates)
    if movie_id not in USER_INTERACTIONS[session_id]["clicks"]:
        USER_INTERACTIONS[session_id]["clicks"].append(movie_id)
    
    return jsonify({
        "success": True,
        "total_clicks": len(USER_INTERACTIONS[session_id]["clicks"])
    })


@app.post("/api/track_interaction")
def api_track_interaction():
    """Track general user interaction with a movie."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    session_id = data.get("session_id", "default")
    movie_id = data.get("movie_id")
    interaction_type = data.get("type", "view")  # view, click, detail_view
    
    if movie_id is None:
        return jsonify({"error": "movie_id is required"}), 400
    
    movie_id = int(movie_id)
    
    # Initialize interactions if not exists
    if session_id not in USER_INTERACTIONS:
        USER_INTERACTIONS[session_id] = {
            "clicks": [],
            "views": []
        }
    
    # Add to appropriate list
    if interaction_type in ["click", "detail_view"]:
        if movie_id not in USER_INTERACTIONS[session_id]["clicks"]:
            USER_INTERACTIONS[session_id]["clicks"].append(movie_id)
    elif interaction_type == "view":
        if movie_id not in USER_INTERACTIONS[session_id]["views"]:
            USER_INTERACTIONS[session_id]["views"].append(movie_id)
    
    return jsonify({
        "success": True,
        "total_clicks": len(USER_INTERACTIONS[session_id]["clicks"]),
        "total_views": len(USER_INTERACTIONS[session_id]["views"])
    })


@app.get("/api/interactions/<session_id>")
def api_get_interactions(session_id: str):
    """Get user interactions."""
    interactions = USER_INTERACTIONS.get(session_id, {"clicks": [], "views": []})
    return jsonify({
        "interactions": interactions,
        "total_clicks": len(interactions.get("clicks", [])),
        "total_views": len(interactions.get("views", []))
    })


@app.route("/api/cache/save", methods=["POST"])
def save_cache():
    """Manually save TMDB cache."""
    _save_tmdb_cache()
    return jsonify({
        "success": True,
        "cached_items": len(MOVIE_CACHE)
    })


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Clear TMDB cache (to force re-fetch with improved search)."""
    global MOVIE_CACHE
    old_count = len(MOVIE_CACHE)
    MOVIE_CACHE.clear()
    _save_tmdb_cache()
    return jsonify({
        "success": True,
        "cleared_items": old_count
    })


@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    """Get cache statistics."""
    return jsonify({
        "total_cached": len(MOVIE_CACHE),
        "cache_file": CACHE_FILE,
        "cache_exists": os.path.exists(CACHE_FILE)
    })



# ==================== ADMIN ENDPOINTS ====================

@app.post("/api/admin/movie")
def api_admin_add_movie():
    """Thêm phim mới"""

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        # 1. Thêm movie
        movie = MovieManager.add_movie(
            title=data.get("title", ""),
            release_date=data.get("release_date", ""),
            genres=data.get("genres", []),
            tmdb_id=data.get("tmdb_id"),
            description=data.get("description", ""),
            imdb_url=data.get("imdb_url", "")
        )

        refresh_movie_data()

        # 2. Gọi webhook n8n
        requests.post(
            "http://localhost:5678/webhook-test/8904cc6d-ed98-4759-bd81-6341a005461a",
            headers={
                "Content-Type": "application/json"
            },
            json={
                "id": movie.get("id"),
                "title": movie.get("title"),
                "release_date": movie.get("release_date"),
                "genres": movie.get("genres"),
                "tmdb_id": movie.get("tmdb_id"),
                "description": movie.get("description"),
                "imdb_url": movie.get("imdb_url"),
            }
        )

        return jsonify({
            "success": True,
            "movie": movie
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.put("/api/admin/movie/<int:movie_id>")
def api_admin_update_movie(movie_id):
    """Cập nhật phim (chỉ admin)"""
    # TODO: Thêm check role admin từ Supabase

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        movie = MovieManager.update_movie(
            str(movie_id),
            **{k: v for k, v in data.items() if k in
               ["title", "release_date", "genres", "description", "tmdb_id", "imdb_url", "is_hidden"]}
        )
        refresh_movie_data()
        return jsonify({"success": True, "movie": movie})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/admin/movie/<int:movie_id>")
def api_admin_delete_movie(movie_id):
    """Xóa/ẩn phim (chỉ admin)"""
    # TODO: Thêm check role admin từ Supabase

    soft_delete = request.args.get("hard_delete", "false").lower() != "true"

    try:
        result = MovieManager.delete_movie(str(movie_id), soft_delete=soft_delete)
        refresh_movie_data()
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/admin/movies")
def api_admin_list_movies():
    """Lấy danh sách tất cả phim cho admin (kể cả ẩn)"""
    # TODO: Thêm check role admin từ Supabase

    include_hidden = request.args.get("include_hidden", "true").lower() == "true"
    genre_filter = request.args.get("genre")

    try:
        movies = MovieManager.list_movies(include_hidden=include_hidden, genre_filter=genre_filter)
        return jsonify({"movies": movies, "total": len(movies)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/admin/movie/<int:movie_id>")
def api_admin_get_movie(movie_id):
    """Lấy chi tiết 1 phim (cho admin)"""
    # TODO: Thêm check role admin từ Supabase

    try:
        movie = MovieManager.get_movie(str(movie_id))
        if movie:
            return jsonify({"movie": movie})
        else:
            return jsonify({"error": "Movie not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/admin/stats")
def api_admin_stats():
    """Thống kê phim cho admin"""
    # TODO: Thêm check role admin từ Supabase

    try:
        stats = MovieManager.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============ YouTube API Endpoints ============

@app.get("/api/youtube/search/trailer/<movie_title>")
def api_youtube_search_trailer(movie_title: str):
    """Search for a movie trailer on YouTube."""
    year = request.args.get("year", type=int)
    
    try:
        result = youtube_service.search_trailer(movie_title, year)
        if not result:
            return jsonify({"error": "Trailer not found"}), 404
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/youtube/search/movie/<movie_title>")
def api_youtube_search_full_movie(movie_title: str):
    """Search for a full movie on YouTube."""
    year = request.args.get("year", type=int)
    
    try:
        result = youtube_service.search_full_movie(movie_title, year)
        if not result:
            return jsonify({"error": "Full movie not found"}), 404
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/youtube/search")
def api_youtube_search():
    """Search for content on YouTube."""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    query = data.get("query")
    search_type = data.get("type", "trailer")  # trailer, movie, or general
    
    if not query:
        return jsonify({"error": "query is required"}), 400
    
    try:
        if search_type == "trailer":
            result = youtube_service.search_trailer(query)
        elif search_type == "movie":
            result = youtube_service.search_full_movie(query)
        else:
            result = youtube_service.search_movies(query, max_results=5)
        
        if not result:
            return jsonify({"error": "Not found"}), 404
        
        return jsonify({"result": result} if isinstance(result, dict) else {"results": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import atexit
    
    # Save cache on exit
    atexit.register(_save_tmdb_cache)
    port = int(os.getenv("PORT", "5000"))
    try:
        app.run(host="0.0.0.0", port=port, debug=False)
    except OSError as exc:
        if "Address already in use" in str(exc):
            fallback_port = port + 1
            logger.warning(f"Port {port} is busy, retrying on {fallback_port}")
            app.run(host="0.0.0.0", port=fallback_port, debug=False)
        else:
            raise
