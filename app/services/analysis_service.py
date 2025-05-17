"""
Enhanced Analysis Service with caching and optimized parallelization
"""
import asyncio
import time
import logging
import chess
import chess.engine
from typing import List, Dict, Any, Tuple, Optional, Callable
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from app.models.analysis import GameAnalysis, PositionAnalysis, MoveAnalysis, AnalysisResponse
from app.services.lichess_service import LichessService
from app.services.cache_service import CacheService
from app.config import STOCKFISH_PATH, ANALYSIS_TIME, ANALYSIS_DEPTH, CANDIDATE_MOVES, MAX_GAMES

logger = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self):
        self.lichess_service = LichessService()
        self.cache_service = CacheService()
        self.engine_path = STOCKFISH_PATH
        self.analysis_time = ANALYSIS_TIME
        self.analysis_depth = ANALYSIS_DEPTH
        self.candidates = CANDIDATE_MOVES
        self.engine_pool = []
        self.engine_semaphore = asyncio.Semaphore(8)  # Limit concurrent engine usage
        self.position_cache = {}  # In-memory position cache for identical positions
        self._progress_callback = None

        # Make sure engine file exists
        self._validate_engine_path()

    def _validate_engine_path(self) -> None:
        """Validate that the Stockfish engine exists and is executable"""
        engine_path = Path(self.engine_path)

        if not engine_path.exists():
            logger.error(f"Stockfish engine not found at: {self.engine_path}")
            # Create stockfish directory if it doesn't exist
            stockfish_dir = engine_path.parent
            stockfish_dir.mkdir(exist_ok=True, parents=True)

            error_msg = (
                f"Stockfish engine not found. Please download Stockfish 17 "
                f"from https://stockfishchess.org/download/ and place it at: {self.engine_path}"
            )
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

    def register_progress_callback(self, callback: Callable[[int, int, str], None]) -> None:
        """Register a callback for reporting progress updates
        
        The callback receives: current_progress, total, status_message
        """
        self._progress_callback = callback

    async def analyze_username(self, username: str) -> AnalysisResponse:
        """Main analysis method that coordinates fetching games and analyzing positions"""
        start_time = time.time()

        try:
            # Check if we have cached results for this username
            cache_key = f"analysis:{username}"
            cached_result = await self.cache_service.get(cache_key)
            
            if cached_result:
                logger.info(f"Using cached analysis for {username}")
                return AnalysisResponse(**cached_result)

            # Initialize the engine pool
            await self.init_engine_pool(num_engines=8)
            logger.info("Engine pool initialized")
                
            # Report progress
            self._report_progress(5, 100, f"Fetching games for {username}")

            # Get the user's last games based on the config
            logger.info(f"Fetching games for user {username}")
            games = await self.lichess_service.get_user_games(username, max_games=MAX_GAMES)

            if not games:
                logger.warning(f"No games found for user {username}")
                self._report_progress(100, 100, "No games found")
                return AnalysisResponse(games=[], analysis_time=time.time() - start_time)

            logger.info(f"Found {len(games)} games for user {username}")

            # Report progress
            self._report_progress(10, 100, f"Found {len(games)} games to analyze")
            
            # Calculate total positions to analyze for progress reporting
            total_positions = sum(len(game.get("moves", [])) for game in games)
            positions_analyzed = 0

            # Analyze all games in parallel
            analyzed_games = []
            
            # Create progress tracking function for positions
            async def analyze_and_track(game):
                nonlocal positions_analyzed
                result = await self._analyze_game(game)
                positions_analyzed += len(game.get("moves", []))
                progress = min(10 + int(90 * positions_analyzed / total_positions), 99)
                self._report_progress(progress, 100, f"Analyzed {positions_analyzed}/{total_positions} positions")
                return result

            # Process games in parallel with a maximum batch size to avoid overwhelming the system
            batch_size = min(len(games), 3)  # Process up to 3 games simultaneously
            for i in range(0, len(games), batch_size):
                batch = games[i:i + batch_size]
                batch_results = await asyncio.gather(
                    *[analyze_and_track(game) for game in batch]
                )
                analyzed_games.extend(batch_results)

            analysis_time = round(time.time() - start_time, 2)
            
            # Create final response
            response = AnalysisResponse(
                games=analyzed_games,
                analysis_time=analysis_time
            )
            
            # Cache the result
            await self.cache_service.set(cache_key, response.model_dump())
            
            # Final progress update
            self._report_progress(100, 100, "Analysis complete")
            
            logger.info(f"Analysis complete: {len(analyzed_games)} games analyzed in {analysis_time}s")
            return response

        except Exception as e:
            logger.error(f"Error during analysis: {str(e)}")
            raise
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        # Clean up the engine pool
        for engine in self.engine_pool:
            try:
                await engine.quit()
            except Exception as e:
                logger.error(f"Error closing chess engine: {str(e)}")
        self.engine_pool = []
        
        # Close the lichess service
        await self.lichess_service.close()

    async def init_engine(self) -> chess.engine.UciProtocol:
        """Initialize and return a chess engine"""
        transport, engine = await chess.engine.popen_uci(self.engine_path)
        return engine

    async def init_engine_pool(self, num_engines: int = 8) -> None:
        """Initialize a pool of chess engines"""
        for _ in range(num_engines):
            engine = await self.init_engine()
            self.engine_pool.append(engine)
        logger.info(f"Initialized pool of {len(self.engine_pool)} engines")

    async def get_engine_from_pool(self) -> chess.engine.UciProtocol:
        """Get an engine from the pool or create a new one if needed"""
        await self.engine_semaphore.acquire()
        if not self.engine_pool:
            # If pool is empty, create a new engine
            return await self.init_engine()
        return self.engine_pool.pop()

    async def release_engine_to_pool(self, engine: chess.engine.UciProtocol) -> None:
        """Release an engine back to the pool"""
        if engine:
            self.engine_pool.append(engine)
            self.engine_semaphore.release()

    def _report_progress(self, current: int, total: int, status: str) -> None:
        """Report progress to callback if registered"""
        if self._progress_callback:
            try:
                self._progress_callback(current, total, status)
            except Exception as e:
                logger.error(f"Error in progress callback: {str(e)}")

    async def _analyze_game(self, game: Dict) -> GameAnalysis:
        """Analyze a single game by analyzing positions in parallel"""
        try:
            analyzed_positions = []
            if "moves" in game and game["moves"]:
                # Create FEN cache for this game to avoid duplicate analysis
                game_cache = {}
                position_tasks = []
                
                # Group positions by their FEN to avoid analyzing duplicates
                fen_groups = {}
                for move_data in game["moves"]:
                    fen = move_data["fen"]
                    if fen not in fen_groups:
                        fen_groups[fen] = []
                    fen_groups[fen].append(move_data)
                
                # Create a task for each unique FEN position
                for fen, moves_with_fen in fen_groups.items():
                    # Check if this position has been analyzed before in any game
                    if fen in self.position_cache:
                        # Reuse cached analysis for all instances of this FEN
                        result = self.position_cache[fen]
                        for move_data in moves_with_fen:
                            # Create position analysis but update move-specific data
                            pos_analysis = PositionAnalysis(
                                fen=fen,
                                move_number=move_data["move_number"],
                                played_move=move_data["played_move"],
                                played_move_eval=result["played_move_eval"],
                                best_moves=result["best_moves"]
                            )
                            game_cache[move_data["move_number"]] = pos_analysis
                    else:
                        # Only analyze the first instance of this FEN
                        position_tasks.append(self._analyze_position_with_engine(moves_with_fen[0], game["game_id"]))
                
                # Run all position analyses in parallel
                if position_tasks:
                    batch_results = await asyncio.gather(*position_tasks, return_exceptions=True)
                    
                    # Process results
                    for i, result in enumerate(batch_results):
                        if isinstance(result, Exception):
                            logger.error(f"Error analyzing position in game {game['game_id']}: {str(result)}")
                            continue
                        
                        # Extract the analyzed position and its data
                        fen = result.fen
                        
                        # Store in cache for future reuse
                        self.position_cache[fen] = {
                            "played_move_eval": result.played_move_eval,
                            "best_moves": result.best_moves
                        }
                        
                        # Apply analysis to all positions with this FEN
                        for move_data in fen_groups[fen]:
                            pos_analysis = PositionAnalysis(
                                fen=fen,
                                move_number=move_data["move_number"],
                                played_move=move_data["played_move"],
                                played_move_eval=result.played_move_eval,
                                best_moves=result.best_moves
                            )
                            game_cache[move_data["move_number"]] = pos_analysis
                
                # Convert the game_cache into a sorted list of positions
                analyzed_positions = [game_cache[move_num] for move_num in sorted(game_cache.keys())]
            else:
                logger.warning(f"No moves found in game {game['game_id']}")

            return GameAnalysis(
                game_id=game["game_id"],
                time_control=game["time_control"],
                moves=analyzed_positions
            )

        except Exception as e:
            logger.error(f"Error analyzing game {game['game_id']}: {str(e)}")
            # Return an empty game analysis in case of error
            return GameAnalysis(
                game_id=game["game_id"],
                time_control=game["time_control"],
                moves=[]
            )

    async def _analyze_position(self, engine: chess.engine.UciProtocol, move_data: Dict) -> PositionAnalysis:
        """Analyze a single chess position"""
        try:
            fen = move_data["fen"]
            board = chess.Board(fen)

            # Set up analysis parameters with both time and depth limits
            limit = chess.engine.Limit(time=self.analysis_time, depth=self.analysis_depth)

            # Get top N candidate moves with timeout
            try:
                analysis_result = await asyncio.wait_for(
                    engine.analyse(board, limit, multipv=self.candidates),
                    timeout=self.analysis_time + 2.0  # Add a buffer to the timeout
                )

                best_moves = []
                for pv in analysis_result:
                    if "pv" in pv and len(pv["pv"]) > 0:
                        move = pv["pv"][0]
                        eval_score = self._normalize_evaluation(pv["score"].relative)
                        best_moves.append(
                            MoveAnalysis(move=board.san(move), eval=eval_score)
                        )

                # Evaluate the played move
                played_move_eval = None

                # Find if the played move is among the best moves
                for move_analysis in best_moves:
                    if move_analysis.move == move_data["played_move"]:
                        played_move_eval = move_analysis.eval
                        break

                # If not found in best moves, use a default evaluation
                if played_move_eval is None:
                    played_move_eval = 0.0

                return PositionAnalysis(
                    fen=fen,
                    move_number=move_data["move_number"],
                    played_move=move_data["played_move"],
                    played_move_eval=played_move_eval,
                    best_moves=best_moves
                )

            except asyncio.TimeoutError:
                logger.warning(f"Analysis timed out for position at move {move_data['move_number']}")
                return PositionAnalysis(
                    fen=fen,
                    move_number=move_data["move_number"],
                    played_move=move_data["played_move"],
                    played_move_eval=0.0,
                    best_moves=[]
                )

        except Exception as e:
            logger.error(f"Error analyzing position {move_data.get('fen', 'unknown')}: {str(e)}")
            # Return a minimal position analysis in case of error
            return PositionAnalysis(
                fen=move_data.get("fen", ""),
                move_number=move_data.get("move_number", 0),
                played_move=move_data.get("played_move", ""),
                played_move_eval=0.0,
                best_moves=[]
            )


    async def _analyze_position_with_engine(self, move_data: Dict, game_id: str) -> PositionAnalysis:
        """Get an engine from the pool, analyze a position, and release the engine back to the pool"""
        engine = None
        try:
            # Check if we've already analyzed this position in this game
            fen = move_data["fen"]
            
            # Get an engine from the pool
            engine = await self.get_engine_from_pool()

            # Analyze the position
            result = await self._analyze_position(engine, move_data)
            return result

        except Exception as e:
            logger.error(f"Error in _analyze_position_with_engine for move {move_data['move_number']} in game {game_id}: {str(e)}")
            raise
        finally:
            # Release the engine back to the pool
            if engine:
                try:
                    await self.release_engine_to_pool(engine)
                except Exception as e:
                    logger.error(f"Error releasing engine to pool: {str(e)}")

    def _normalize_evaluation(self, score) -> float:
        """Convert a chess.engine score to a floating point value"""
        if score.is_mate():
            # Convert mate score to a large value with sign
            mate_score = 100.0 if score.mate() > 0 else -100.0
            return mate_score
        else:
            # Convert centipawns to pawns
            return score.score() / 100.0
