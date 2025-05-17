# Lotus Chess Analysis System - Architecture & Flow Control Diagram

## System Architecture Diagram

```mermaid
graph TB
    subgraph "User Interface"
        UI[Web UI] --> Client
        Client[Client Browser] -- WebSocket --> SIO
    end

    subgraph "FastAPI Server"
        API[FastAPI Application] -- REST API --> Tasks
        SIO[Socket.IO Integration] -- Realtime Updates --> Client
        Tasks[Task Manager] --> Celery
    end

    subgraph "Task Queue System"
        Celery[Celery Task Queue] --> Worker
        Worker[Celery Worker] --> Analysis
        Analysis[Analysis Service] --> StockfishPool
        StockfishPool[Stockfish Engine Pool] --> Cache
    end

    subgraph "External Services"
        Analysis --> Lichess[Lichess API]
    end

    subgraph "Storage"
        Cache[Cache Service] --> Redis
        Redis[(Redis Cache)]
    end

    Client -- HTTP Request --> API
    API -- API Response --> Client
    Worker -- Status Updates --> SIO
```

## Data Flow Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant UI as Web UI
    participant API as FastAPI Server
    participant Celery as Celery Queue
    participant Worker as Celery Worker
    participant Cache as Cache Service
    participant Lichess as Lichess API
    participant SF as Stockfish Engine
    
    User->>UI: Enter Lichess username
    UI->>API: POST /analyze {username}
    API->>Celery: Submit analysis task
    API-->>UI: Return job_id
    UI->>API: Connect WebSocket with job_id
    
    Worker->>Lichess: Fetch recent games
    Lichess-->>Worker: Return game data
    
    loop For each game
        Worker->>Cache: Check if analysis exists
        alt Analysis exists in cache
            Cache-->>Worker: Return cached analysis
        else Cache miss
            loop For each position
                Worker->>Cache: Check if position exists
                alt Position exists in cache
                    Cache-->>Worker: Return cached evaluation
                else Cache miss
                    Worker->>SF: Analyze position
                    SF-->>Worker: Return evaluation
                    Worker->>Cache: Store position & eval
                end
            end
        end
        Worker->>API: Update progress via WebSocket
        API->>UI: Send progress update
    end

    Worker->>Cache: Store complete analysis
    Worker->>API: Send complete results
    API->>UI: Send completion update
    UI->>User: Display detailed analysis
```

## Component Structure

```mermaid
classDiagram
    class Main {
        +app: FastAPI
        +setup_socketio()
        +setup_routes()
    }

    class AnalysisService {
        +analyze_user_games(username)
        +analyze_position(fen)
        +get_best_moves(position)
    }

    class LichessService {
        +get_user_games(username)
        +parse_pgn(pgn)
    }

    class CacheService {
        +get(key)
        +set(key, value)
        +position_exists(fen)
        +get_position_eval(fen)
    }

    class Tasks {
        +analyze_games_task(username)
        +update_progress(job_id, progress)
    }

    class StockfishEngine {
        +analyze(fen, depth)
        +get_evaluation()
        +get_best_move()
    }

    class Models {
        +GameAnalysis
        +MoveAnalysis
        +BestMove
    }

    Main --> AnalysisService
    Main --> Tasks
    AnalysisService --> LichessService
    AnalysisService --> CacheService
    AnalysisService --> StockfishEngine
    Tasks --> AnalysisService
    AnalysisService --> Models
```

## Flow Control Explanation

### 1. Client Request Flow
1. User enters a Lichess username in the web UI
2. Client sends an HTTP POST request to `/analyze` endpoint
3. FastAPI server validates the request and creates a Celery task
4. Server returns a job ID to the client
5. Client establishes a WebSocket connection to receive real-time updates

### 2. Background Processing Flow
1. Celery worker picks up the analysis task
2. Worker uses LichessService to fetch the user's recent games
3. For each game:
   - Check if full game analysis exists in cache
   - If not, process each position in the game
   - For each position:
     - Check position cache
     - If position is not cached, analyze with Stockfish
     - Store position evaluation in cache
   - Send progress updates through WebSocket

### 3. Caching System Flow
1. Two-tiered caching system:
   - Redis for persistent storage of complete analyses
   - In-memory cache for position evaluations during analysis
2. Cache keys:
   - Complete analyses: `username:timestamp`
   - Positions: `fen_string`
3. Cache fallbacks:
   - If Redis is unavailable, use in-memory only
   - If position is not cached, perform full analysis

### 4. Result Delivery Flow
1. When analysis is complete, worker stores full results in Redis
2. Final results are sent to the client via WebSocket
3. UI renders the analysis with interactive chess board visualization
4. User can navigate through the games and positions

## Module Relationships

- **app/main.py**: Entry point, FastAPI setup, route definitions
- **app/tasks.py**: Celery task definitions, background processing
- **app/config.py**: System configuration, environment variables
- **app/models/analysis.py**: Data models for game analysis
- **app/services/analysis_service.py**: Core analysis business logic
- **app/services/lichess_service.py**: Integration with Lichess API
- **app/services/cache_service.py**: Caching system implementation
- **client_example.html**: Web user interface with interactive board