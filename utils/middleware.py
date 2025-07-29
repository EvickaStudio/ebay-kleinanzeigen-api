import time
import logging
from fastapi import Request

logger = logging.getLogger("kleinanzeigen_api")


async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time

    logger.info(
        f"Request: {request.method} {request.url.path} - Completed in {process_time:.4f}s - Status: {response.status_code} - Client: {request.client.host} - User-Agent: {request.headers.get('user-agent')}"
    )

    return response
