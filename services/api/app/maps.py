import os
from typing import Annotated, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import Current, DB, require, throttle
from .models import Booking, User
from .schemas import PickupPoint
from .tracking import VISIBLE, latest, location_record

router = APIRouter(prefix="/maps", tags=["maps"])
Customer = Annotated[User, Depends(require("customer"))]
Address = Annotated[str, Field(min_length=5, max_length=250)]


class Preview(BaseModel):
    pickup: Address
    pickup_point: PickupPoint | None = None
    destination: Address


class TripRoute(BaseModel):
    mode: Literal["planned", "driver"] = "planned"


def waypoint(text, lat=None, lon=None):
    if lat is not None and lon is not None:
        return {"location":{"latLng":{"latitude":lat, "longitude":lon}}}
    return {"address":text}


def coordinates(waypoint, key):
    if "location" in waypoint:
        point = waypoint["location"]["latLng"]
        return [point["longitude"],point["latitude"]]
    response = httpx.get("https://api.openrouteservice.org/geocode/search",
                         headers={"Authorization":key},params={"text":waypoint["address"]+", Bengaluru, India",
                         "boundary.country":"IND","focus.point.lat":12.9716,"focus.point.lon":77.5946,"size":1},timeout=6)
    response.raise_for_status()
    features = response.json().get("features",[])
    if not features:
        raise HTTPException(404,"An address could not be found. Try a more specific address or set a pickup pin.")
    return features[0]["geometry"]["coordinates"]


def driving_route(origin, destination):
    key = os.getenv("OPENROUTESERVICE_API_KEY")
    if not key:
        raise HTTPException(503,"Routing is unavailable. You can open directions in Google Maps.")
    try:
        response = httpx.post("https://api.openrouteservice.org/v2/directions/driving-car/geojson",
                             headers={"Authorization":key},
                             json={"coordinates":[coordinates(origin,key),coordinates(destination,key)]}, timeout=8)
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            raise HTTPException(404,"No driving route was returned for these locations.")
        route = features[0]
        points = route["geometry"]["coordinates"]
        if not isinstance(points,list) or not 2 <= len(points) <= 10000:
            raise ValueError("Invalid route geometry")
        if not all(isinstance(p,list) and len(p)==2 and -180<=p[0]<=180 and -90<=p[1]<=90 for p in points):
            raise ValueError("Invalid route coordinates")
        duration = float(route["properties"]["summary"]["duration"])
        distance = float(route["properties"]["summary"]["distance"])
        if not (0 <= duration <= 400000 and 0 <= distance <= 10_000_000):
            raise ValueError("Invalid route values")
        return {"distance_m":round(distance),"duration_s":round(duration),
                "line":[[lat,lon] for lon,lat in points],"provider":"openrouteservice"}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as cause:
        raise HTTPException(502,"The routing provider could not calculate this route.") from cause


@router.post("/preview")
def preview(data: Preview, user: Customer, db: DB):
    if os.getenv("OPENROUTESERVICE_API_KEY"):
        throttle(db, f"routes:{user.id}", 18)
    point = data.pickup_point
    return driving_route(waypoint(data.pickup,point.latitude if point else None,point.longitude if point else None),
                        waypoint(data.destination))


@router.post("/bookings/{booking_id}/route")
def booking_route(booking_id: UUID, data: TripRoute, user: Current, db: DB):
    booking = db.get(Booking, booking_id)
    if not booking or user.id not in (booking.customer_id,booking.driver_id):
        raise HTTPException(404,"Booking not found.")
    pickup = waypoint(booking.pickup, booking.pickup_latitude / 1_000_000 if booking.pickup_latitude is not None else None,
                      booking.pickup_longitude / 1_000_000 if booking.pickup_longitude is not None else None)
    destination = waypoint(booking.destination) if booking.destination else None
    origin = pickup
    if data.mode == "driver":
        point = latest(db, booking.id) if booking.status in VISIBLE else None
        if not point or point.driver_id != booking.driver_id or location_record(point)["stale"]:
            raise HTTPException(409,"A fresh driver location is required for an ETA.")
        origin = waypoint("",point.latitude_e6 / 1_000_000,point.longitude_e6 / 1_000_000)
        if booking.status != "IN_PROGRESS":
            destination = pickup
    if not destination:
        raise HTTPException(422,"Enter a destination before asking for a route.")
    if os.getenv("OPENROUTESERVICE_API_KEY"):
        throttle(db, f"routes:{user.id}", 18)
    return driving_route(origin,destination)
