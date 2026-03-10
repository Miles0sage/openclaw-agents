"""
Travel Agent Tool — Route optimization, booking, itinerary management

Week 1 MVP:
- Route optimization (Google Maps Distance Matrix API)
- Booking integration stubs (Expedia, Airlines)
- Itinerary management
- Calendar sync
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
import httpx

logger = logging.getLogger(__name__)

# Configuration
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
EXPEDIA_API_KEY = os.getenv("EXPEDIA_API_KEY", "")
SKYSCANNER_API_KEY = os.getenv("SKYSCANNER_API_KEY", "")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_TRAVEL_DB = os.getenv("NOTION_TRAVEL_DB_ID", "")


class TravelAgent:
    """
    Manage Miles' travel: routes, bookings, itineraries
    """

    def __init__(self):
        self.has_google_maps = bool(GOOGLE_MAPS_API_KEY)
        self.has_expedia = bool(EXPEDIA_API_KEY)
        self.has_notion = bool(NOTION_TOKEN and NOTION_TRAVEL_DB)

    async def optimize_route(
        self, origin: str, stops: List[str]
    ) -> Dict[str, Any]:
        """
        Optimize travel route through multiple stops.
        Uses Google Maps Distance Matrix API.

        Args:
            origin: Starting address
            stops: List of addresses to visit

        Returns:
            {
                "optimal_order": [...],
                "distance_km": float,
                "duration_hours": float,
                "waypoints": [...],
            }
        """
        if not self.has_google_maps:
            logger.warning("Google Maps API not configured. Using mock route.")
            return await self._mock_route_optimization(origin, stops)

        try:
            return await self._optimize_with_google_maps(origin, stops)
        except Exception as e:
            logger.error(f"Google Maps API error: {e}")
            return await self._mock_route_optimization(origin, stops)

    async def _optimize_with_google_maps(
        self, origin: str, stops: List[str]
    ) -> Dict[str, Any]:
        """Use Google Maps Distance Matrix API"""
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"

        # Simple optimization: just order stops by distance from origin
        # (In production, use Google Optimization service)
        waypoints = [origin] + stops

        params = {
            "key": GOOGLE_MAPS_API_KEY,
            "origins": origin,
            "destinations": "|".join(stops),
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

        # Extract distances and calculate total
        rows = data.get("rows", [{}])[0].get("elements", [])

        # Simple ordering by distance (not full TSP solution)
        ordered_stops = []
        total_distance = 0
        total_duration = 0

        for row in rows:
            if "distance" in row and "duration" in row:
                ordered_stops.append(row)
                total_distance += row["distance"].get("value", 0)
                total_duration += row["duration"].get("value", 0)

        return {
            "optimal_order": [origin] + stops,  # Simplified
            "distance_km": round(total_distance / 1000, 1),
            "duration_hours": round(total_duration / 3600, 1),
            "waypoints": waypoints,
            "maps_url": f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={stops[-1]}&waypoints={'.'.join(stops[:-1])}",
        }

    async def _mock_route_optimization(
        self, origin: str, stops: List[str]
    ) -> Dict[str, Any]:
        """Return mock optimized route"""
        return {
            "optimal_order": [origin] + stops,
            "distance_km": 15.3 + len(stops) * 2.5,
            "duration_hours": round((15.3 + len(stops) * 2.5) / 40, 1),  # ~40 km/h avg
            "waypoints": [origin] + stops,
            "maps_url": f"https://maps.google.com",
        }

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search for flights using Skyscanner or Expedia APIs.
        Falls back to mock data.
        """
        if self.has_expedia:
            try:
                return await self._search_expedia_flights(
                    origin, destination, departure_date, return_date
                )
            except Exception as e:
                logger.warning(f"Expedia search failed: {e}")

        logger.warning("Flight search APIs not configured. Using mock data.")
        return await self._mock_flight_search()

    async def _search_expedia_flights(
        self, origin, destination, departure_date, return_date
    ) -> Dict[str, Any]:
        """Call Expedia API"""
        # Stub: Expedia API integration
        # https://developer.expediagroup.com/
        logger.info("Expedia flight search (stub)")
        return await self._mock_flight_search()

    async def _mock_flight_search(self) -> Dict[str, Any]:
        """Return mock flight options"""
        return {
            "flights": [
                {
                    "id": "fl_001",
                    "airline": "United",
                    "departure": "10:30 AM",
                    "arrival": "2:15 PM",
                    "duration": "4h 45m",
                    "price": 245,
                    "stops": 0,
                },
                {
                    "id": "fl_002",
                    "airline": "Southwest",
                    "departure": "1:00 PM",
                    "arrival": "4:30 PM",
                    "duration": "5h 30m",
                    "price": 189,
                    "stops": 1,
                },
                {
                    "id": "fl_003",
                    "airline": "Delta",
                    "departure": "6:00 PM",
                    "arrival": "10:45 PM",
                    "duration": "5h 45m",
                    "price": 215,
                    "stops": 0,
                },
            ],
            "cheapest": 189,
            "fastest": 245,
        }

    async def search_hotels(
        self,
        location: str,
        check_in: str,
        check_out: str,
        guests: int = 1,
    ) -> Dict[str, Any]:
        """
        Search for hotels.
        Stub for Week 1.
        """
        return await self._mock_hotel_search()

    async def _mock_hotel_search(self) -> Dict[str, Any]:
        """Return mock hotel options"""
        return {
            "hotels": [
                {
                    "id": "ht_001",
                    "name": "Marriott Downtown",
                    "rating": 4.5,
                    "price_per_night": 185,
                    "distance_from_center": "0.5 km",
                },
                {
                    "id": "ht_002",
                    "name": "Budget Inn",
                    "rating": 3.8,
                    "price_per_night": 89,
                    "distance_from_center": "2 km",
                },
                {
                    "id": "ht_003",
                    "name": "Luxury Suite",
                    "rating": 5.0,
                    "price_per_night": 450,
                    "distance_from_center": "1 km",
                },
            ],
        }

    async def create_itinerary(
        self,
        trip_name: str,
        start_date: str,
        end_date: str,
        activities: List[Dict],
    ) -> Dict[str, Any]:
        """
        Create and save itinerary to Notion.
        """
        itinerary = {
            "id": f"trip_{datetime.now().timestamp()}",
            "name": trip_name,
            "start_date": start_date,
            "end_date": end_date,
            "activities": activities,
            "created_at": datetime.now().isoformat(),
        }

        # Export to Notion if available
        if self.has_notion:
            await self._save_to_notion(itinerary)

        return itinerary

    async def _save_to_notion(self, itinerary: Dict) -> bool:
        """Save itinerary to Notion Travel database"""
        try:
            url = "https://api.notion.com/v1/pages"
            headers = {
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2024-06-15",
            }

            properties = {
                "Trip Name": {
                    "type": "title",
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": itinerary["name"]},
                        }
                    ],
                },
                "Start Date": {
                    "type": "date",
                    "date": {"start": itinerary["start_date"]},
                },
                "End Date": {
                    "type": "date",
                    "date": {"start": itinerary["end_date"]},
                },
                "Activities": {
                    "type": "number",
                    "number": len(itinerary["activities"]),
                },
            }

            payload = {
                "parent": {
                    "type": "database_id",
                    "database_id": NOTION_TRAVEL_DB,
                },
                "properties": properties,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=15
                )
                response.raise_for_status()

            logger.info(f"Itinerary '{itinerary['name']}' saved to Notion")
            return True

        except Exception as e:
            logger.error(f"Failed to save itinerary to Notion: {e}")
            return False


async def run_travel_planning() -> Dict[str, Any]:
    """
    Main entry point for travel planning tasks.
    Can be called on-demand or scheduled.
    """
    agent = TravelAgent()

    # Example: Optimize a route for soccer + errands Thursday evening
    example_stops = [
        "Downtown Soccer Field",
        "Whole Foods",
        "Home",
    ]

    route = await agent.optimize_route("Current Location", example_stops)

    return {
        "status": "complete",
        "route": route,
    }


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_travel_planning())
    print(json.dumps(result, indent=2, default=str))
