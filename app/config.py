"""
Configuration settings for the Lotus Chess application
"""
import os
import logging
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file if it exists
load_dotenv()

# API Settings
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", 8000))

# Lichess API Settings
LICHESS_API_URL = os.getenv("LICHESS_API_URL", "https://lichess.org/api")
LICHESS_API_TOKEN = os.getenv("LICHESS_API_TOKEN", "")  # Optional
LICHESS_RATE_LIMIT_DELAY = float(os.getenv("LICHESS_RATE_LIMIT_DELAY", 0.05))  # 20 req/sec

# Redis Configuration for caching and Celery
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

# Cache settings
CACHE_TIMEOUT = int(os.getenv("CACHE_TIMEOUT", 86400))  # 24 hours in seconds

# Log the Lichess API URL being used
logging.info(f"Using Lichess API at: {LICHESS_API_URL}")

# Stockfish Settings
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", None)
ANALYSIS_TIME = float(os.getenv("ANALYSIS_TIME", 2.0))  # seconds per position
ANALYSIS_DEPTH = int(os.getenv("ANALYSIS_DEPTH", 18))  # analysis depth
CANDIDATE_MOVES = int(os.getenv("CANDIDATE_MOVES", 3))  # number of candidate moves

# Determine default Stockfish path based on OS if not set
if STOCKFISH_PATH is None:
    base_path = Path(__file__).parent.parent / "stockfish"
    
    import platform
    if platform.system() == "Windows":
        STOCKFISH_PATH = str(base_path / "stockfish-windows-x86-64-avx2.exe")
    elif platform.system() == "Darwin":  # macOS
        if platform.processor() == 'arm':
            STOCKFISH_PATH = str(base_path / "stockfish-macos-arm")
        else:
            STOCKFISH_PATH = str(base_path / "stockfish-macos-x86")
    else:  # Linux and others
        STOCKFISH_PATH = str(base_path / "stockfish-ubuntu-x86-64-avx2")
    
    # Log the selected Stockfish path
    logging.info(f"Using Stockfish at: {STOCKFISH_PATH}")

# Game retrieval settings
MAX_GAMES = int(os.getenv("MAX_GAMES", 5))
