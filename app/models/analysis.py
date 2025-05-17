from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from datetime import datetime


class MoveAnalysis(BaseModel):
    """Represents analysis of a single chess move."""
    move: str
    eval: float


class PositionAnalysis(BaseModel):
    """Represents analysis of a chess position."""
    fen: str
    move_number: int
    played_move: str
    played_move_eval: float
    best_moves: List[MoveAnalysis]


class GameAnalysis(BaseModel):
    """Represents analysis of a complete chess game."""
    game_id: str
    time_control: str
    moves: List[PositionAnalysis]


class AnalysisResponse(BaseModel):
    """Represents the complete analysis response."""
    games: List[GameAnalysis]
    analysis_time: float


class AnalysisRequest(BaseModel):
    """Represents the analysis request."""
    username: str


class AnalysisJobStatus(BaseModel):
    """Status of an analysis job."""
    job_id: str
    status: str  # "pending", "progress", "completed", "failed"
    progress: int = 0  # 0-100 progress percentage
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ProgressUpdate(BaseModel):
    """Progress update for WebSocket communication."""
    job_id: str
    progress: int
    status: str