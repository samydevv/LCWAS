import asyncio
import chess.pgn
import io
from typing import List, Dict, Any
import logging
import requests
import time
from app.config import LICHESS_API_URL, LICHESS_API_TOKEN, LICHESS_RATE_LIMIT_DELAY, MAX_GAMES

logger = logging.getLogger(__name__)

class LichessService:
    def __init__(self):
        self.rate_limit_delay = LICHESS_RATE_LIMIT_DELAY
        self.api_token = LICHESS_API_TOKEN
    
    async def setup(self):
        # No need for setup with requests
        pass
    
    async def close(self):
        # No need to close anything with requests
        pass
    
    async def get_user_games(self, username: str, max_games: int = MAX_GAMES) -> List[Dict[str, Any]]:
        """
        Fetch the last N rapid/blitz games for a given Lichess username
        Returns a list of chess games in PGN format
        """
        # Try the standard API endpoint first
        games = await self._get_games_standard_api(username, max_games)
        
        # If we didn't get any moves, try the alternative API endpoint
        if games and all(len(game.get("moves", [])) == 0 for game in games):
            logger.warning(f"No moves found in games from standard API, trying alternative endpoint")
            games = await self._get_games_alternative_api(username, max_games)
        
        return games
        
    async def _get_games_standard_api(self, username: str, max_games: int) -> List[Dict[str, Any]]:
        """Use the standard API to get games"""
        # Prepare API parameters - only blitz and rapid games
        params = {
            "max": max_games,
            "perfType": "blitz,rapid",
            "ongoing": "false",
            "finished": "true",
            "sort": "dateDesc",
            "pgnInJson": "false",  # Ensure we get proper PGN format
            "clocks": "false",     # We don't need clock times
            "evals": "false",      # We'll do our own evals
            "opening": "false"     # Don't need opening info
        }
        
        games = []
        try:
            # Prepare headers with authentication if available
            headers = {"Accept": "application/x-chess-pgn"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            # Use requests to make a synchronous call in an executor
            url = f"{LICHESS_API_URL}/games/user/{username}"
            logger.info(f"Fetching games for {username} from {url}")
            
            # Run the request in a thread pool to not block asyncio
            def make_request():
                try:
                    resp = requests.get(url, params=params, headers=headers, verify=False)
                    return resp
                except Exception as e:
                    logger.error(f"Error in HTTP request: {str(e)}")
                    raise
            
            # Execute the request in a separate thread
            response = await asyncio.get_event_loop().run_in_executor(None, make_request)
            
            if response.status_code != 200:
                logger.error(f"Lichess API error: {response.status_code} - {response.text}")
                return []
            
            # Parse PGN data
            pgn_text = response.text
            logger.info(f"Received {len(pgn_text)} bytes of PGN data")
            
            # Debug - log a snippet of the PGN data
            if pgn_text:
                logger.info(f"PGN snippet: {pgn_text[:200]}...")
            else:
                logger.warning("Received empty PGN data from Lichess API")
                return []
            
            # Parse the PGN data into game objects
            parsed_games = await self._parse_pgn_games(pgn_text)
            logger.info(f"Parsed {len(parsed_games)} games from Lichess")
            return parsed_games
            
        except requests.RequestException as e:
            logger.error(f"Error fetching games for {username}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return []
            
    async def _get_games_alternative_api(self, username: str, max_games: int) -> List[Dict[str, Any]]:
        """Try the alternative API endpoint that returns JSON directly"""
        params = {
            "max": max_games,
            "perfType": "blitz,rapid",
            "ongoing": "false",
            "finished": "true",
            "sort": "dateDesc",
            "moves": "true",       # Include moves in the output
            "pgnInJson": "true",   # Include PGN in the JSON
            "clocks": "false",
            "evals": "false"
        }
        
        games = []
        try:
            # Prepare headers
            headers = {"Accept": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            
            # Alternative endpoint
            url = f"{LICHESS_API_URL}/games/user/{username}"
            logger.info(f"Fetching games using alternative endpoint: {url}")
            
            def make_request():
                try:
                    resp = requests.get(url, params=params, headers=headers, verify=False)
                    return resp
                except Exception as e:
                    logger.error(f"Error in HTTP request: {str(e)}")
                    raise
            
            response = await asyncio.get_event_loop().run_in_executor(None, make_request)
            
            if response.status_code != 200:
                logger.error(f"Lichess API error: {response.status_code} - {response.text}")
                return []
            
            # Parse JSON data
            json_data = response.json()
            logger.info(f"Received JSON data with {len(json_data)} games")
            
            # Convert JSON games to our format
            for game_json in json_data:
                game_id = game_json.get("id", "unknown")
                time_control = f"{game_json.get('clock', {}).get('initial', 0)}+{game_json.get('clock', {}).get('increment', 0)}"
                
                # Create a parsed game structure
                parsed_game = {
                    "game_id": game_id,
                    "time_control": time_control,
                    "pgn": game_json.get("pgn", ""),
                    "moves": []
                }
                
                # Parse moves from the JSON directly
                moves_str = game_json.get("moves", "").split()
                
                # We need to convert UCI moves to SAN format
                board = chess.Board()
                for i, move_uci in enumerate(moves_str):
                    try:
                        # Parse the UCI move
                        move = chess.Move.from_uci(move_uci)
                        # Convert to SAN
                        move_san = board.san(move)
                        # Get FEN before the move
                        fen = board.fen()
                        # Add to our moves list
                        parsed_game["moves"].append({
                            "move_number": i + 1,
                            "fen": fen,
                            "played_move": move_san
                        })
                        # Apply the move to advance the board
                        board.push(move)
                    except Exception as e:
                        logger.error(f"Error parsing move {i+1} of game {game_id}: {str(e)}")
                
                logger.info(f"Parsed game {game_id} with {len(parsed_game['moves'])} moves from JSON")
                games.append(parsed_game)
                
                # Respect rate limiting
                await asyncio.sleep(self.rate_limit_delay)
            
            return games
            
        except Exception as e:
            logger.error(f"Error fetching games from alternative API: {str(e)}")
            return []
    
    async def _parse_pgn_games(self, pgn_text: str) -> List[Dict[str, Any]]:
        """Parse a multi-game PGN string into a list of game objects"""
        games = []
        if not pgn_text.strip():
            logger.warning("Empty PGN text received, cannot parse games")
            return games
            
        pgn_io = io.StringIO(pgn_text)
        
        # Process each game in the PGN
        game_count = 0
        while True:
            try:
                game = chess.pgn.read_game(pgn_io)
                if game is None:  # End of file
                    break
                
                game_count += 1
                
                # Extract game ID from the Site header, which contains the URL
                site = game.headers.get("Site", "")
                game_id = site.split("/")[-1] if "/" in site else f"game_{game_count}"
                
                parsed_game = {
                    "game_id": game_id,
                    "time_control": game.headers.get("TimeControl", ""),
                    "pgn": str(game),
                    "moves": []
                }
                
                # Log game headers for debugging
                logger.info(f"Game {game_id} headers: {dict(game.headers)}")
                
                # Parse moves
                board = game.board()
                move_count = 0
                
                for i, move in enumerate(game.mainline_moves()):
                    move_count += 1
                    try:
                        move_san = board.san(move)
                        fen = board.fen()
                        parsed_game["moves"].append({
                            "move_number": i + 1,
                            "fen": fen,
                            "played_move": move_san
                        })
                        board.push(move)
                    except Exception as e:
                        logger.error(f"Error parsing move {i+1} of game {game_id}: {str(e)}")
                
                logger.info(f"Parsed game {game_id} with {len(parsed_game['moves'])} moves")
                
                if not parsed_game["moves"]:
                    logger.warning(f"No moves parsed for game {game_id}")
                
                games.append(parsed_game)
            except Exception as e:
                logger.error(f"Error parsing game: {str(e)}")
                # Continue to next game
                continue
                
            # Respect rate limiting
            await asyncio.sleep(self.rate_limit_delay)
        
        return games