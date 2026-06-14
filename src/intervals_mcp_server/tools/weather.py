"""
Weather MCP tool (Open-Meteo) for the coach-trail closed loop.

Adds `get_weather` so the coach can decide heat adjustments (repli salle) for the
weekday midday session (Alex can only run 12h-14h on weekdays). Uses Open-Meteo
(free, no API key). Forecast only. Returns a COMPACT summary (never the raw hourly
arrays) to stay token-safe.
"""

from typing import Any

from intervals_mcp_server.api.client import _get_httpx_client
from intervals_mcp_server.mcp_instance import mcp  # noqa: F401  (import triggers tool registration)

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"


async def _geocode(name: str) -> tuple[float, float, str] | None:
    """Resolve a place name to (lat, lon, label) via Open-Meteo geocoding."""
    client = await _get_httpx_client()
    resp = await client.get(
        OPEN_METEO_GEOCODE,
        params={"name": name, "count": 1, "language": "fr", "format": "json"},
        timeout=20.0,
    )
    resp.raise_for_status()
    results = (resp.json() or {}).get("results") or []
    if not results:
        return None
    r = results[0]
    label = ", ".join(filter(None, [r.get("name"), r.get("admin1"), r.get("country")]))
    return float(r["latitude"]), float(r["longitude"]), label


@mcp.tool()
async def get_weather(
    location_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    date: str | None = None,
) -> str:
    """Get the daily weather forecast for a location (Open-Meteo, no API key).

    Use this to decide heat adjustments for the weekday midday run (12h-14h): it
    highlights the midday-window apparent ("feels-like") temperature, UV and rain
    probability, plus the day's max/min.

    Args:
        location_name: City/place name to geocode (e.g. "Aubervilliers"). Used when
            latitude/longitude are not provided; also used as the display label.
        latitude: Latitude in decimal degrees (preferred; pass together with longitude).
        longitude: Longitude in decimal degrees.
        date: Target day YYYY-MM-DD (optional, defaults to today in the location's
            timezone). Must be within the forecast horizon (~16 days).
    """
    label = location_name or ""
    if latitude is None or longitude is None:
        if not location_name:
            return "Error: provide latitude+longitude, or a location_name to geocode."
        geo = await _geocode(location_name)
        if geo is None:
            return f"Error: could not geocode location '{location_name}'."
        latitude, longitude, label = geo

    client = await _get_httpx_client()
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "auto",
        "forecast_days": 16,
        "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,uv_index",
        "daily": "temperature_2m_max,temperature_2m_min,apparent_temperature_max,uv_index_max,precipitation_probability_max",
    }
    try:
        resp = await client.get(OPEN_METEO_FORECAST, params=params, timeout=20.0)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as exc:  # noqa: BLE001 - surface any fetch error as a tool message
        return f"Error fetching weather: {exc}"

    daily = data.get("daily") or {}
    days = daily.get("time") or []
    if not days:
        return "No forecast data returned."

    target = date or days[0]
    if target not in days:
        return (
            f"Date {target} hors horizon de prevision ({days[0]} -> {days[-1]}). "
            "Choisis une date dans cette fenetre."
        )
    di = days.index(target)

    # Midday window 12:00-14:00 from the hourly series (Alex's weekday slot).
    hourly = data.get("hourly") or {}
    htime = hourly.get("time") or []

    def _hour_vals(key: str) -> list[float]:
        arr = hourly.get(key) or []
        out: list[float] = []
        for hh in ("12:00", "13:00", "14:00"):
            stamp = f"{target}T{hh}"
            if stamp in htime:
                idx = htime.index(stamp)
                if idx < len(arr) and arr[idx] is not None:
                    out.append(arr[idx])
        return out

    def _mx(xs: list[float]) -> Any:
        return max(xs) if xs else None

    def _d(key: str) -> Any:
        arr = daily.get(key) or []
        return arr[di] if di < len(arr) else None

    units = data.get("daily_units") or {}
    tu = units.get("temperature_2m_max", "C")
    loc = label or f"{latitude:.3f},{longitude:.3f}"

    midday_t = _hour_vals("temperature_2m")
    midday_app = _hour_vals("apparent_temperature")
    midday_uv = _hour_vals("uv_index")
    midday_rain = _hour_vals("precipitation_probability")

    lines = [f"Meteo — {loc} — {target}"]
    if midday_t:
        lines.append(
            f"CRENEAU MIDI 12h-14h : temp {_mx(midday_t)}{tu} / "
            f"RESSENTIE max {_mx(midday_app)}{tu} / UV max {_mx(midday_uv)} / "
            f"pluie {_mx(midday_rain)}%"
        )
    else:
        lines.append("Creneau 12h-14h : pas de donnees horaires pour cette date.")
    lines.append(
        f"Jour : max {_d('temperature_2m_max')}{tu} / min {_d('temperature_2m_min')}{tu} / "
        f"ressentie max {_d('apparent_temperature_max')}{tu} / "
        f"UV max {_d('uv_index_max')} / pluie max {_d('precipitation_probability_max')}%"
    )
    lines.append(
        "Regle chaleur : ressentie midi >= ~28-30C ou UV tres fort -> repli salle/tapis "
        "(montee only, descente reportee au frais) ; piloter au RPE."
    )
    return "\n".join(lines)
