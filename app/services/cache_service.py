"""
Cache service for storing and retrieving analysis results
"""
import redis
import json
import logging
import hashlib
from typing import Dict, Any, Optional
from cachetools import TTLCache
import asyncio

from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB, CACHE_TIMEOUT

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        # Set up in-memory cache as a fallback
        self.memory_cache = TTLCache(maxsize=100, ttl=CACHE_TIMEOUT)
        self.lock = asyncio.Lock()
        
        # Try to connect to Redis
        try:
            self.redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                socket_timeout=2,
                decode_responses=True
            )
            # Test connection
            self.redis.ping()
            self.redis_available = True
            logger.info("Redis cache service initialized successfully")
        except Exception as e:
            self.redis_available = False
            logger.warning(f"Redis connection failed, using in-memory cache instead: {str(e)}")

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a value from cache"""
        # Normalize the key (hash it to ensure consistent length and valid characters)
        cache_key = self._normalize_key(key)
        
        try:
            # Try Redis first if available
            if self.redis_available:
                data = self.redis.get(cache_key)
                if data:
                    logger.debug(f"Cache hit for key: {cache_key[:16]}...")
                    return json.loads(data)
                    
            # Fall back to memory cache
            async with self.lock:
                if cache_key in self.memory_cache:
                    logger.debug(f"Memory cache hit for key: {cache_key[:16]}...")
                    return self.memory_cache[cache_key]
                    
            logger.debug(f"Cache miss for key: {cache_key[:16]}...")
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving from cache: {str(e)}")
            return None
            
    async def set(self, key: str, value: Dict[str, Any]) -> None:
        """Store a value in cache"""
        # Normalize the key
        cache_key = self._normalize_key(key)
        
        try:
            # Store as JSON string
            data = json.dumps(value)
            
            # Store in Redis if available
            if self.redis_available:
                self.redis.setex(cache_key, CACHE_TIMEOUT, data)
                
            # Also store in memory cache as backup
            async with self.lock:
                self.memory_cache[cache_key] = value
                
            logger.debug(f"Cached data for key: {cache_key[:16]}...")
            
        except Exception as e:
            logger.error(f"Error storing in cache: {str(e)}")
    
    def _normalize_key(self, key: str) -> str:
        """Create a consistent hash from any input string"""
        return f"lotus_chess:{hashlib.md5(key.encode()).hexdigest()}"
