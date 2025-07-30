from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from utils.rate_limiter import limiter
from utils.middleware import log_requests
from routers import (
    inserate,
    inserate_detailed,
    inserat,
)
from utils.browser import OptimizedPlaywrightManager
from utils.asyncio_optimizations import EventLoopOptimizer

# Global browser manager instance for sharing across all endpoints
browser_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown events"""
    global browser_manager

    # Setup uvloop for maximum performance (2-4x improvement)
    uvloop_enabled = EventLoopOptimizer.setup_uvloop()

    # Optimize event loop settings
    EventLoopOptimizer.optimize_event_loop()

    # Startup: Initialize shared browser manager with optimized settings
    browser_manager = OptimizedPlaywrightManager(max_contexts=20, max_concurrent=10)
    await browser_manager.start()

    # Store browser manager in app state for access by routers
    app.state.browser_manager = browser_manager
    app.state.uvloop_enabled = uvloop_enabled
    app.state.limiter = limiter

    yield

    # Shutdown: Clean up browser resources
    if browser_manager:
        await browser_manager.close()


app = FastAPI(version="1.0.0", lifespan=lifespan)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.middleware("http")(log_requests)


@app.get("/")
async def root(request: Request):
    return {
        "message": "Welcome to the Kleinanzeigen API",
        "endpoints": ["/inserate", "/inserat/{id}", "/inserate-detailed"],
        "status": "operational",
        "rate_limit": "10/minute",
    }


app.include_router(inserate.router)
app.include_router(inserat.router)
app.include_router(inserate_detailed.router)
