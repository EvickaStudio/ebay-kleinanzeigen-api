from scrapers.inserat import get_inserate_details_optimized
from fastapi import APIRouter, HTTPException, Request
from utils.rate_limiter import limiter

router = APIRouter()


@router.get("/inserat/{id}")
@limiter.limit("100/minute")
async def get_inserat(request: Request, id: str):
    """
    Fetch detailed information for a specific listing.

    Retrieves comprehensive details including description, seller information,
    location, pricing, and other metadata for the specified listing ID.
    """
    if not id or not id.strip():
        raise HTTPException(status_code=400, detail="Invalid listing ID")

    try:
        # The browser_manager is no longer needed for this endpoint
        response = await get_inserate_details_optimized(id)

        if not response.get("success", False):
            raise HTTPException(
                status_code=500, detail="Failed to fetch listing details"
            )

        # Clean response - keep only essential data
        clean_response = {
            "success": response["success"],
            "time_taken": response["time_taken"],
            "data": response["data"],
        }

        # Add minimal performance metrics
        if "performance_metrics" in response:
            metrics = response["performance_metrics"]
            clean_response["performance_metrics"] = {
                "success_rate": metrics.get("success_rate", 100),
                "time_taken": metrics.get("average_page_time", response["time_taken"]),
            }

        return clean_response

    except HTTPException:
        raise
    except Exception as e:
        # Log the exception for debugging
        print(f"Error in get_inserat: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
