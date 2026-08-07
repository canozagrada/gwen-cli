"""Best-effort geographic grouping for maintenance windows and components.

Providers name maintenance windows in free text ("Baghdad, Iraq - (BGW)"), so
grouping is keyword matching and will occasionally misfile something. It is a
display convenience only -- nothing downstream depends on it being exact.
"""

from __future__ import annotations

import re

OTHER = "Other"

#: Checked in order; the first region with a matching keyword wins, so more
#: specific regions must come before ones they could be confused with.
REGIONS: dict[str, tuple[str, ...]] = {
    "Middle East": (
        "uae", "saudi", "israel", "turkey", "qatar", "kuwait", "bahrain", "oman",
        "jordan", "lebanon", "iraq", "iran", "georgia", "azerbaijan", "armenia",
        "amman", "baghdad", "tbilisi", "dubai", "me-",
    ),
    "North America": (
        "united states", " usa", ", us", "us-", "canada", "virginia", "california",
        "texas", "florida", "illinois", "washington", "new york", "oregon",
        "colorado", "nevada", "arizona", "ohio", "toronto", "montreal", "richmond",
        "ashburn", "chicago", "los angeles", "newark", "dallas", "san jose",
        "seattle", "miami", "atlanta", "denver", "north america",
    ),
    "Latin America": (
        "brazil", "argentina", "chile", "colombia", "peru", "costa rica", "panama",
        "ecuador", "venezuela", "uruguay", "paraguay", "guatemala", "honduras",
        "nicaragua", "el salvador", "dominican republic", "puerto rico", "jamaica",
        "mexico", "buenos aires", "bogota", "lima", "curitiba", "são paulo",
        "sao paulo", "medellín", "querétaro", "queretaro", "south america", "sa-",
    ),
    "Europe": (
        "united kingdom", "uk", "germany", "france", "netherlands", "spain",
        "italy", "belgium", "switzerland", "sweden", "norway", "denmark",
        "finland", "poland", "austria", "ireland", "portugal", "greece",
        "iceland", "czech", "hungary", "romania", "frankfurt", "stuttgart",
        "amsterdam", "reykjavík", "london", "palermo", "marseille", "paris",
        "madrid", "milan", "warsaw", "europe", "eu-",
    ),
    "Asia": (
        "china", "japan", "south korea", "korea", "india", "singapore",
        "hong kong", "thailand", "vietnam", "malaysia", "indonesia",
        "philippines", "taiwan", "pakistan", "bangladesh", "nepal", "sri lanka",
        "cambodia", "myanmar", "mumbai", "kuala lumpur", "nagpur", "karachi",
        "seoul", "tokyo", "osaka", "asia", "ap-",
    ),
    "Oceania": (
        "australia", "new zealand", "fiji", "papua new guinea", "samoa", "guam",
        "maldives", "sydney", "melbourne", "auckland",
    ),
    "Africa": (
        "south africa", "egypt", "nigeria", "kenya", "morocco", "tunisia",
        "algeria", "ethiopia", "ghana", "tanzania", "uganda", "cape town",
        "johannesburg", "lagos", "nairobi", "africa", "af-",
    ),
}

#: Display order for regions in output.
ORDER = (*REGIONS, OTHER)

_CODE = re.compile(r"\(([A-Z]{3})\)")


def classify(*parts: str) -> str:
    """Return the region name best matching *parts*, or `OTHER`."""
    haystack = " ".join(part for part in parts if part).lower()
    for region, keywords in REGIONS.items():
        if any(keyword in haystack for keyword in keywords):
            return region
    return OTHER


def location_code(name: str) -> str:
    """Pull an airport-style code such as `(DFW)` out of *name*."""
    match = _CODE.search(name)
    if match:
        return match.group(1)
    first = name.split()
    return first[0][:3].upper() if first else "???"
