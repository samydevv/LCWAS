"""
Lotus Chess Web API - FastAPI application with caching, parallelization, 
WebSockets for progress updates, and Celery task queue integration.
"""
import asyncio
import time
import json
import uuid
import threading
import sys
from loguru import logger
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import sys
import redis
from pathlib import Path
from celery.result import AsyncResult
import socketio
from celery.signals import task_postrun, task_success, task_failure

# Add the parent directory to the Python path so imports work correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.analysis_service import AnalysisService
from app.services.cache_service import CacheService
from app.models.analysis import AnalysisRequest, AnalysisResponse, AnalysisJobStatus, ProgressUpdate
from app.config import API_HOST, API_PORT, REDIS_URL
from app.tasks import celery_app, analyze_games_task

# Configure loguru logger
log_path = Path(__file__).parent.parent / "lotus_chess.log"
config = {
    "handlers": [
        {"sink": sys.stdout, "level": "DEBUG", "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"},
        {"sink": log_path, "level": "DEBUG", "rotation": "10 MB", "retention": "1 week", "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}"}
    ]
}

# Remove default handler and configure with our settings
logger.remove()
for handler in config["handlers"]:
    logger.add(**handler)

# Initialize FastAPI app
app = FastAPI(
    title="Lotus Chess Analysis Service",
    description="A service for analyzing chess games using Stockfish",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Socket.IO for WebSocket communication
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
# Create Socket.IO app and mount it at the root so it handles its own paths
socket_app = socketio.ASGIApp(sio)
# Include the Socket.IO app in the main ASGI app routing
app.mount("/socket.io", socket_app)  # Mount at standard Socket.IO path

# Create a dictionary to store active WebSocket connections
websocket_connections = {}

# Initialize cache service
cache_service = CacheService()

# Add middleware for request logging and timing
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Process the request and get the response
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Log the request details
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"- Status: {response.status_code} "
            f"- Time: {process_time:.2f}s"
        )
        
        # Add processing time header to the response
        response.headers["X-Process-Time"] = f"{process_time:.5f}"
        return response
    except Exception as e:
        logger.error(f"Request failed: {request.method} {request.url.path} - Error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(e)}"}
        )

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred.",
            "error_type": exc.__class__.__name__,
        }
    )

# Dependency to get analysis service
async def get_analysis_service():
    service = AnalysisService()
    yield service

@sio.event
async def connect(sid, environ):
    """Handle Socket.IO connection"""
    logger.info(f"Client connected: {sid}")
    await sio.emit('connection_established', {'status': 'connected'}, to=sid)

@sio.event
async def disconnect(sid):
    """Handle Socket.IO disconnection"""
    logger.info(f"Client disconnected: {sid}")
    
    # Clean up any subscriptions
    for job_id, subscribers in list(websocket_connections.items()):
        if sid in subscribers:
            subscribers.remove(sid)
        # Remove empty lists
        if not subscribers:
            websocket_connections.pop(job_id, None)

@sio.event
async def subscribe_to_job(sid, data):
    """Subscribe client to job updates"""
    job_id = data.get('job_id')
    if not job_id:
        await sio.emit('error', {'message': 'No job_id provided'}, to=sid)
        return
    
    # Add the client to the job's subscribers
    if job_id not in websocket_connections:
        websocket_connections[job_id] = set()
    websocket_connections[job_id].add(sid)
    
    # Send current status right away
    job_result = AsyncResult(job_id, app=celery_app)
    status = 'pending'
    progress = 0
    
    if job_result.ready():
        status = 'completed' if job_result.successful() else 'failed'
    elif job_result.state == 'PROGRESS':
        status = 'progress'
        progress = job_result.info.get('progress', 0) if job_result.info else 0
    
    await sio.emit('job_update', {
        'job_id': job_id,
        'status': status,
        'progress': progress
    }, to=sid)

async def send_job_updates(job_id, status, progress, message=""):
    """Send job updates to all subscribers"""
    if job_id in websocket_connections:
        for sid in websocket_connections[job_id]:
            await sio.emit('job_update', {
                'job_id': job_id,
                'status': status,
                'progress': progress,
                'message': message
            }, to=sid)

@app.websocket("/ws/analysis/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Legacy WebSocket endpoint for job progress updates"""
    await websocket.accept()
    
    try:
        # Add to subscribers
        if job_id not in websocket_connections:
            websocket_connections[job_id] = set()
        websocket_connections[job_id].add(websocket)
        
        # Send initial status
        job_result = AsyncResult(job_id, app=celery_app)
        status = 'pending'
        progress = 0
        
        if job_result.ready():
            status = 'completed' if job_result.successful() else 'failed'
            progress = 100
        elif job_result.state == 'PROGRESS' and job_result.info:
            status = 'progress'
            progress = job_result.info.get('progress', 0)
            
        await websocket.send_json({
            'job_id': job_id,
            'status': status,
            'progress': progress
        })
        
        # Keep connection alive until client disconnects
        while True:
            data = await websocket.receive_text()
            # Echo any data back (just to keep connection alive)
            if data == "ping":
                await websocket.send_text("pong")
            
    except WebSocketDisconnect:
        # Remove from subscribers when disconnected
        if job_id in websocket_connections and websocket in websocket_connections[job_id]:
            websocket_connections[job_id].remove(websocket)
            if not websocket_connections[job_id]:
                websocket_connections.pop(job_id)

@app.post("/analyze", response_model=AnalysisJobStatus)
async def analyze_games_async(request: AnalysisRequest):
    """
    Start asynchronous analysis of chess games.
    Returns a job ID that can be used to check progress and retrieve results.
    """
    try:
        # Validate input
        if not request.username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        username = request.username.strip()
        if len(username) < 2 or len(username) > 30:
            raise HTTPException(
                status_code=400, 
                detail="Invalid username. Lichess usernames are between 2 and 30 characters."
            )
        
        # Check cache first
        cache_key = f"analysis:{username}"
        cached_result = await cache_service.get(cache_key)
        
        if cached_result:
            logger.info(f"Returning cached analysis for {username}")
            # Create a fake job ID for the cached result
            job_id = f"cached-{uuid.uuid4()}"
            
            # Return success status with cached result
            return AnalysisJobStatus(
                job_id=job_id,
                status="completed",
                progress=100,
                message="Analysis retrieved from cache",
                result=cached_result
            )
            
        # Start a new analysis job
        logger.info(f"Starting new analysis job for {username}")
        task = analyze_games_task.delay(username)
        
        return AnalysisJobStatus(
            job_id=task.id,
            status="pending",
            progress=0,
            message=f"Analysis for {username} started"
        )
        
    except Exception as e:
        logger.error(f"Error starting analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start analysis: {str(e)}"
        )

@app.get("/analysis/{job_id}", response_model=AnalysisJobStatus)
async def get_analysis_status(job_id: str):
    """Get the status or result of an analysis job"""
    try:
        # Handle cached results
        if job_id.startswith("cached-"):
            # For cached results, we don't have a task to check
            # So we just return the completed status
            return AnalysisJobStatus(
                job_id=job_id,
                status="completed",
                progress=100,
                message="Analysis retrieved from cache"
            )
            
        # For regular tasks, check status
        task = AsyncResult(job_id, app=celery_app)
        
        if task.state == 'PENDING':
            return AnalysisJobStatus(
                job_id=job_id,
                status="pending",
                progress=0,
                message="Analysis job is pending"
            )
            
        elif task.state == 'PROGRESS':
            info = task.info or {}
            return AnalysisJobStatus(
                job_id=job_id,
                status="progress",
                progress=info.get('progress', 0),
                message=info.get('status', "Analysis in progress")
            )
            
        elif task.ready():
            if task.successful():
                result = task.result
                status = result.get('status', 'completed')
                result_data = result.get('result')
                
                response = AnalysisJobStatus(
                    job_id=job_id,
                    status=status,
                    progress=100,
                    message="Analysis completed",
                    result=result_data
                )
                
                # Send WebSocket update for completed jobs
                asyncio.create_task(
                    send_job_updates(job_id, "completed", 100, "Analysis completed")
                )
                
                return response
            else:
                # Task failed
                error = str(task.result) if task.result else "Unknown error"
                
                response = AnalysisJobStatus(
                    job_id=job_id,
                    status="failed",
                    progress=0,
                    message=f"Analysis failed: {error}",
                    error=error
                )
                
                # Send WebSocket update for failed jobs
                asyncio.create_task(
                    send_job_updates(job_id, "failed", 0, f"Analysis failed: {error}")
                )
                
                return response
        
        # Should never get here, but just in case
        return AnalysisJobStatus(
            job_id=job_id,
            status="unknown",
            progress=0,
            message="Unknown job state"
        )
            
    except Exception as e:
        logger.error(f"Error retrieving job status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving job status: {str(e)}"
        )

@app.get("/analyze-sync", response_model=AnalysisResponse)
async def analyze_games_sync(
    username: str,
    analysis_service: AnalysisService = Depends(get_analysis_service)
):
    """
    Legacy synchronous API endpoint.
    Analyze the last 5 rapid/blitz games for a given Lichess username.
    """
    try:
        # Validate input
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        username = username.strip()
        if len(username) < 2 or len(username) > 30:
            raise HTTPException(
                status_code=400, 
                detail="Invalid username. Lichess usernames are between 2 and 30 characters."
            )
        
        # Check cache first
        cache_key = f"analysis:{username}"
        cached_result = await cache_service.get(cache_key)
        
        if cached_result:
            logger.info(f"Returning cached analysis for {username}")
            return AnalysisResponse(**cached_result)
        
        logger.info(f"Starting analysis for user: {username}")
        
        # Run the analysis - this is the original synchronous method
        analysis = await analysis_service.analyze_username(username)
        
        # Cache the result
        await cache_service.set(cache_key, analysis.model_dump())
        
        logger.info(f"Analysis completed for {username} in {analysis.analysis_time} seconds")
        
        return analysis
        
    except FileNotFoundError as e:
        logger.error(f"Stockfish engine not found: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Stockfish engine not found. Please check server configuration."
        )
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        
        # Determine the appropriate status code based on the exception
        if "not found" in str(e).lower() or "no such user" in str(e).lower():
            status_code = 404
            detail = f"User '{username}' not found on Lichess"
        elif "rate limit" in str(e).lower():
            status_code = 429
            detail = "Rate limit exceeded. Please try again later."
        else:
            status_code = 500
            detail = f"Analysis failed: {str(e)}"
            
        raise HTTPException(status_code=status_code, detail=detail)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    redis_status = "ok"
    
    # Check Redis connection through cache service
    try:
        if hasattr(cache_service, "redis") and cache_service.redis_available:
            cache_service.redis.ping()
        else:
            redis_status = "unavailable, using memory cache"
    except Exception as e:
        redis_status = f"error: {str(e)}"
    
    # Check Celery connection
    celery_status = "ok"
    try:
        i = celery_app.control.inspect()
        if not i.ping():
            celery_status = "unavailable, tasks will fail"
    except Exception as e:
        celery_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "services": {
            "redis": redis_status,
            "celery": celery_status,
        }
    }

# Mount the static files directory to serve client_example.html
app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent), name="static")

# Add a root route that redirects to the client example
@app.get("/")
async def root():
    """Redirect to client example"""
    return RedirectResponse(url="/static/louts_chess_analysis.html")

# Celery signal handlers
@task_success.connect
@task_failure.connect
@task_postrun.connect
def task_completion_handler(sender=None, **kwargs):
    """Handle task completion signals from Celery"""
    job_id = kwargs.get('task_id')
    state = kwargs.get('state')
    logger.debug(f"Celery task signal received: task_id={job_id}, state={state}")
    
    status = 'completed' if state == 'SUCCESS' else 'failed'
    progress = 100 if status == 'completed' else 0
    
    # Send update to WebSocket clients
    logger.debug(f"Creating async task to send job updates for job_id={job_id}, status={status}")
    asyncio.create_task(send_job_updates(job_id, status, progress, f"Analysis {status}"))

def redis_listener():
    """Listen for Redis messages and emit updates via Socket.IO"""
    try:
        logger.info("Starting Redis listener thread")
        pubsub = cache_service.redis.pubsub()
        pubsub.subscribe("job_updates")
        
        # Track which jobs we've already processed completion for
        completed_jobs = set()
        
        for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    job_id = data.get("job_id")
                    status = data.get("status")
                    progress = data.get("progress", 0)
                    message_text = data.get("message", "")
                    
                    # Skip completed status updates for jobs we've already processed
                    if status == "completed" and job_id in completed_jobs:
                        logger.debug(f"Skipping duplicate completion for job_id={job_id}")
                        continue
                        
                    # Track completed jobs
                    if status == "completed":
                        completed_jobs.add(job_id)
                    
                    logger.info(f"Received Redis message for job_id={job_id}, status={status}, progress={progress}")
                    
                    # Emit the update to all connected clients
                    asyncio.run(send_job_updates(job_id, status, progress, message_text))
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in Redis message: {message['data']}")
                except Exception as e:
                    logger.error(f"Error processing Redis message: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in Redis listener: {str(e)}", exc_info=True)

# Start the Redis listener in a separate thread
listener_thread = threading.Thread(target=redis_listener, daemon=True)
listener_thread.start()

# Run the application directly when this file is executed
if __name__ == "__main__":
    logger.info(f"Starting Lotus Chess Analysis Service on {API_HOST}:{API_PORT}")
    uvicorn.run(app, host=API_HOST, port=API_PORT, reload=False)
