#!/usr/bin/env python3
"""
Check if Stockfish is properly installed and configured
"""
import sys
import os
import logging
import asyncio
import chess.engine
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.config import STOCKFISH_PATH

async def test_stockfish():
    """Test if Stockfish can be run and returns a valid UCI response"""
    logger.info(f"Testing Stockfish at: {STOCKFISH_PATH}")
    
    # Check if file exists
    engine_path = Path(STOCKFISH_PATH)
    if not engine_path.exists():
        logger.error(f"Stockfish not found at {STOCKFISH_PATH}")
        logger.info("Please download Stockfish from https://stockfishchess.org/download/")
        logger.info(f"After downloading, place the executable at: {STOCKFISH_PATH}")
        logger.info(f"Be sure to make it executable with: chmod +x {STOCKFISH_PATH}")
        return False
    
    # Check if file is executable
    if not os.access(STOCKFISH_PATH, os.X_OK) and sys.platform != "win32":
        logger.error(f"Stockfish is not executable. Run: chmod +x {STOCKFISH_PATH}")
        return False
    
    try:
        # Try to start the engine
        transport, engine = await chess.engine.popen_uci(STOCKFISH_PATH)
        
        # Get engine info - accessing engine.id as a property, not a method
        engine_id = engine.id
        logger.info(f"Successfully connected to Stockfish")
        logger.info(f"Engine name: {engine_id['name']}")
        
        # Run a simple evaluation
        board = chess.Board()
        info = await engine.analyse(board, chess.engine.Limit(time=0.5))
        
        # Convert centipawns to pawns
        score = info["score"].relative.score() / 100 if not info["score"].relative.is_mate() else "Mate"
        logger.info(f"Initial position evaluation: {score}")
        
        # Clean up
        await engine.quit()
        logger.info("Stockfish test successful!")
        return True
        
    except Exception as e:
        logger.error(f"Error testing Stockfish: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_stockfish())
    sys.exit(0 if result else 1)
