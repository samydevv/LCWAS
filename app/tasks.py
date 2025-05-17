"""
Celery tasks for handling long-running chess analysis jobs
"""
import os
import sys
from pathlib import Path
from celery import Celery
import json
import logging
import redis

# Add the parent directory to the Python path so imports work correctly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# Create Redis client for pub/sub
redis_client = redis.from_url(REDIS_URL)

# Create Celery app
celery_app = Celery('lotus_chess',
                    broker=REDIS_URL,
                    backend=REDIS_URL)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max for analysis tasks
    worker_prefetch_multiplier=1,  # Don't prefetch tasks
)

@celery_app.task(bind=True, name='analyze_games')
def analyze_games_task(self, username: str):
    """
    Celery task to analyze games for a user
    This runs in a separate process, so we need to import locally to avoid circular imports
    """
    from app.services.analysis_service import AnalysisService
    import asyncio
    
    try:
        # Set up task progress tracking
        self.update_state(state='PROGRESS', meta={'progress': 0, 'status': 'Starting analysis'})
        
        # Create a new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create analysis service
        service = AnalysisService()
        
        # Set up progress tracking callback
        def progress_callback(current, total, status):
            percent = int(100 * current / max(total, 1))
            self.update_state(state='PROGRESS', 
                               meta={'progress': percent, 'status': status})
            
            # Publish progress updates to Redis
            try:
                redis_client.publish(
                    'job_updates',
                    json.dumps({
                        'job_id': self.request.id,
                        'status': 'progress',
                        'progress': percent,
                        'message': status
                    })
                )
            except Exception as e:
                logger.error(f"Error publishing progress to Redis: {str(e)}")
        
        # Register progress callback with service
        service.register_progress_callback(progress_callback)
        
        # Run analysis
        result = loop.run_until_complete(service.analyze_username(username))
        
        # Convert to dict for serialization
        result_dict = result.model_dump()
        
        # Clean up
        loop.run_until_complete(service.cleanup())
        loop.close()
        
        # Publish completion event to Redis
        try:
            redis_client.publish(
                'job_updates',
                json.dumps({
                    'job_id': self.request.id,
                    'status': 'completed',
                    'progress': 100,
                    'message': 'Analysis completed',
                    'has_result': True
                })
            )
            logger.info(f"Published completion event for job {self.request.id}")
        except Exception as e:
            logger.error(f"Error publishing completion event to Redis: {str(e)}")
        
        return {'status': 'SUCCESS', 'result': result_dict}
    
    except Exception as e:
        logger.error(f"Error in analysis task: {str(e)}", exc_info=True)
        
        # Publish error event to Redis
        try:
            redis_client.publish(
                'job_updates',
                json.dumps({
                    'job_id': self.request.id,
                    'status': 'failed',
                    'progress': 0,
                    'message': f'Analysis failed: {str(e)}',
                    'error': str(e)
                })
            )
        except Exception as redis_err:
            logger.error(f"Error publishing error event to Redis: {str(redis_err)}")
            
        return {'status': 'FAILURE', 'error': str(e)}
