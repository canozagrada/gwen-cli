"""Name a provider's region -- `azure/scus`, `aws/us-east-1`, `cloudflare/dfw` --
and work out whether an incident is about it.

The three hyperscalers get a catalog of their regions, which allows two things
plain text matching cannot do:

- Short names resolve to one region: `scus`, `southcentralus` and
  `South Central US` are all `azure/southcentralus`.
- An incident that names *no* region in the catalog can be recognised as
  such, and treated as affecting every region. Status feeds are terse; an
  unmatched incident is more likely global than irrelevant, and a missed
  priority-1 alert costs more than a spare one.

Any other provider (Cloudflare, GitHub, extra Statuspage vendors) matches its
region as a whole word in the incident or component name, so `cloudflare/dfw`
matches "Dallas, TX, United States - (DFW)".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import providers


@dataclass(frozen=True)
class Region:
    code: str
    #: How status text refers to it, longest first is not required.
    names: tuple[str, ...]
    #: Extra names accepted in config, e.g. "scus". Never matched in text,
    #: where a three-letter abbreviation would match ordinary words.
    aliases: tuple[str, ...] = ()
    #: Geography, using the labels in `regions.ORDER`.
    geo: str = "Other"
    #: Azure's paired region, for suggesting failover targets.
    pair: str | None = None


def _azure(code, name, short=(), geo="North America", pair=None):
    return Region(code, (name.lower(), code), tuple(short), geo, pair)


def _aws(code, *names, geo):
    return Region(code, (code, *(n.lower() for n in names)), (), geo)


def _gcp(code, *names, geo):
    return Region(code, (code, *(n.lower() for n in names)), (), geo)


NA, LATAM, EU, ASIA, OCEANIA, ME, AFRICA = (
    "North America",
    "Latin America",
    "Europe",
    "Asia",
    "Oceania",
    "Middle East",
    "Africa",
)

CATALOGS: dict[str, dict[str, Region]] = {
    "azure": {
        r.code: r
        for r in (
            _azure("eastus", "East US", ["eus"], pair="westus"),
            _azure("eastus2", "East US 2", ["eus2"], pair="centralus"),
            _azure("centralus", "Central US", ["cus"], pair="eastus2"),
            _azure(
                "northcentralus", "North Central US", ["ncus"], pair="southcentralus"
            ),
            _azure(
                "southcentralus", "South Central US", ["scus"], pair="northcentralus"
            ),
            _azure("westcentralus", "West Central US", ["wcus"], pair="westus2"),
            _azure("westus", "West US", ["wus"], pair="eastus"),
            _azure("westus2", "West US 2", ["wus2"], pair="westcentralus"),
            _azure("westus3", "West US 3", ["wus3"], pair="eastus"),
            _azure("canadacentral", "Canada Central", ["cac"], pair="canadaeast"),
            _azure("canadaeast", "Canada East", ["cae"], pair="canadacentral"),
            _azure(
                "brazilsouth", "Brazil South", ["brs"], LATAM, pair="southcentralus"
            ),
            _azure("mexicocentral", "Mexico Central", [], LATAM),
            _azure("northeurope", "North Europe", ["neu"], EU, pair="westeurope"),
            _azure("westeurope", "West Europe", ["weu"], EU, pair="northeurope"),
            _azure("uksouth", "UK South", ["uks"], EU, pair="ukwest"),
            _azure("ukwest", "UK West", ["ukw"], EU, pair="uksouth"),
            _azure("francecentral", "France Central", ["frc"], EU, pair="francesouth"),
            _azure("francesouth", "France South", ["frs"], EU, pair="francecentral"),
            _azure(
                "germanywestcentral",
                "Germany West Central",
                ["gwc"],
                EU,
                pair="germanynorth",
            ),
            _azure(
                "germanynorth", "Germany North", ["gn"], EU, pair="germanywestcentral"
            ),
            _azure("swedencentral", "Sweden Central", ["sdc"], EU),
            _azure(
                "switzerlandnorth",
                "Switzerland North",
                ["szn"],
                EU,
                pair="switzerlandwest",
            ),
            _azure(
                "switzerlandwest",
                "Switzerland West",
                ["szw"],
                EU,
                pair="switzerlandnorth",
            ),
            _azure("norwayeast", "Norway East", ["noe"], EU, pair="norwaywest"),
            _azure("norwaywest", "Norway West", ["now"], EU, pair="norwayeast"),
            _azure("italynorth", "Italy North", [], EU),
            _azure("polandcentral", "Poland Central", [], EU),
            _azure("spaincentral", "Spain Central", [], EU),
            _azure("eastasia", "East Asia", ["ea"], ASIA, pair="southeastasia"),
            _azure("southeastasia", "Southeast Asia", [], ASIA, pair="eastasia"),
            _azure("japaneast", "Japan East", ["jpe"], ASIA, pair="japanwest"),
            _azure("japanwest", "Japan West", ["jpw"], ASIA, pair="japaneast"),
            _azure("koreacentral", "Korea Central", ["krc"], ASIA, pair="koreasouth"),
            _azure("koreasouth", "Korea South", ["krs"], ASIA, pair="koreacentral"),
            _azure("centralindia", "Central India", ["inc"], ASIA, pair="southindia"),
            _azure("southindia", "South India", ["ins"], ASIA, pair="centralindia"),
            _azure("westindia", "West India", [], ASIA, pair="southindia"),
            _azure(
                "australiaeast",
                "Australia East",
                ["aue"],
                OCEANIA,
                pair="australiasoutheast",
            ),
            _azure(
                "australiasoutheast",
                "Australia Southeast",
                ["ause"],
                OCEANIA,
                pair="australiaeast",
            ),
            _azure("australiacentral", "Australia Central", [], OCEANIA),
            _azure("uaenorth", "UAE North", [], ME, pair="uaecentral"),
            _azure("uaecentral", "UAE Central", [], ME, pair="uaenorth"),
            _azure("qatarcentral", "Qatar Central", [], ME),
            _azure("israelcentral", "Israel Central", [], ME),
            _azure(
                "southafricanorth",
                "South Africa North",
                ["san"],
                AFRICA,
                pair="southafricawest",
            ),
            _azure(
                "southafricawest",
                "South Africa West",
                ["saw"],
                AFRICA,
                pair="southafricanorth",
            ),
        )
    },
    "aws": {
        r.code: r
        for r in (
            _aws("us-east-1", "N. Virginia", "Northern Virginia", geo=NA),
            _aws("us-east-2", "Ohio", geo=NA),
            _aws("us-west-1", "N. California", "Northern California", geo=NA),
            _aws("us-west-2", "Oregon", geo=NA),
            _aws("ca-central-1", "Canada (Central)", "Canada Central", geo=NA),
            _aws("ca-west-1", "Calgary", geo=NA),
            _aws("mx-central-1", "Mexico (Central)", geo=LATAM),
            _aws("sa-east-1", "Sao Paulo", "São Paulo", geo=LATAM),
            _aws("eu-west-1", "Ireland", geo=EU),
            _aws("eu-west-2", "London", geo=EU),
            _aws("eu-west-3", "Paris", geo=EU),
            _aws("eu-central-1", "Frankfurt", geo=EU),
            _aws("eu-central-2", "Zurich", geo=EU),
            _aws("eu-north-1", "Stockholm", geo=EU),
            _aws("eu-south-1", "Milan", geo=EU),
            _aws("eu-south-2", "Spain", geo=EU),
            _aws("ap-northeast-1", "Tokyo", geo=ASIA),
            _aws("ap-northeast-2", "Seoul", geo=ASIA),
            _aws("ap-northeast-3", "Osaka", geo=ASIA),
            _aws("ap-southeast-1", "Singapore", geo=ASIA),
            _aws("ap-southeast-3", "Jakarta", geo=ASIA),
            _aws("ap-southeast-5", "Malaysia", geo=ASIA),
            _aws("ap-southeast-7", "Thailand", geo=ASIA),
            _aws("ap-east-1", "Hong Kong", geo=ASIA),
            _aws("ap-south-1", "Mumbai", geo=ASIA),
            _aws("ap-south-2", "Hyderabad", geo=ASIA),
            _aws("ap-southeast-2", "Sydney", geo=OCEANIA),
            _aws("ap-southeast-4", "Melbourne", geo=OCEANIA),
            _aws("me-south-1", "Bahrain", geo=ME),
            _aws("me-central-1", "UAE", geo=ME),
            _aws("il-central-1", "Tel Aviv", geo=ME),
            _aws("af-south-1", "Cape Town", geo=AFRICA),
        )
    },
    "gcp": {
        r.code: r
        for r in (
            _gcp("us-central1", "Iowa", geo=NA),
            _gcp("us-east1", "South Carolina", geo=NA),
            _gcp("us-east4", "Northern Virginia", "N. Virginia", geo=NA),
            _gcp("us-east5", "Columbus", geo=NA),
            _gcp("us-south1", "Dallas", geo=NA),
            _gcp("us-west1", "Oregon", geo=NA),
            _gcp("us-west2", "Los Angeles", geo=NA),
            _gcp("us-west3", "Salt Lake City", geo=NA),
            _gcp("us-west4", "Las Vegas", geo=NA),
            _gcp("northamerica-northeast1", "Montréal", "Montreal", geo=NA),
            _gcp("northamerica-northeast2", "Toronto", geo=NA),
            _gcp("southamerica-east1", "São Paulo", "Sao Paulo", geo=LATAM),
            _gcp("southamerica-west1", "Santiago", geo=LATAM),
            _gcp("europe-west1", "Belgium", geo=EU),
            _gcp("europe-west2", "London", geo=EU),
            _gcp("europe-west3", "Frankfurt", geo=EU),
            _gcp("europe-west4", "Netherlands", geo=EU),
            _gcp("europe-west6", "Zurich", "Zürich", geo=EU),
            _gcp("europe-west8", "Milan", geo=EU),
            _gcp("europe-west9", "Paris", geo=EU),
            _gcp("europe-north1", "Finland", geo=EU),
            _gcp("europe-central2", "Warsaw", geo=EU),
            _gcp("europe-southwest1", "Madrid", geo=EU),
            _gcp("asia-east1", "Taiwan", geo=ASIA),
            _gcp("asia-east2", "Hong Kong", geo=ASIA),
            _gcp("asia-northeast1", "Tokyo", geo=ASIA),
            _gcp("asia-northeast2", "Osaka", geo=ASIA),
            _gcp("asia-northeast3", "Seoul", geo=ASIA),
            _gcp("asia-south1", "Mumbai", geo=ASIA),
            _gcp("asia-south2", "Delhi", geo=ASIA),
            _gcp("asia-southeast1", "Singapore", geo=ASIA),
            _gcp("asia-southeast2", "Jakarta", geo=ASIA),
            _gcp("australia-southeast1", "Sydney", geo=OCEANIA),
            _gcp("australia-southeast2", "Melbourne", geo=OCEANIA),
            _gcp("me-west1", "Tel Aviv", geo=ME),
            _gcp("me-central1", "Doha", geo=ME),
            _gcp("me-central2", "Dammam", geo=ME),
            _gcp("africa-south1", "Johannesburg", geo=AFRICA),
        )
    },
}


class TargetError(ValueError):
    """A target in the config does not name a known provider or region."""


@dataclass(frozen=True)
class Target:
    """`provider` alone, or `provider/region`."""

    provider: str
    region: str | None = None

    def __str__(self) -> str:
        return f"{self.provider}/{self.region}" if self.region else self.provider

    @property
    def geo(self) -> str | None:
        catalog = CATALOGS.get(self.provider, {})
        region = catalog.get(self.region or "")
        return region.geo if region else None


def parse(spec: str) -> Target:
    """Parse `azure/scus` into `Target("azure", "southcentralus")`."""
    name, _, region = spec.strip().partition("/")
    try:
        key = providers.resolve(name).key
    except KeyError as exc:
        raise TargetError(exc.args[0]) from None
    region = region.strip().lower()
    if not region:
        return Target(key)

    catalog = CATALOGS.get(key)
    if catalog is None:
        return Target(key, region)
    for entry in catalog.values():
        if region == entry.code or region in entry.aliases or region in entry.names:
            return Target(key, entry.code)
    raise TargetError(
        f"unknown {providers.PROVIDERS[key].label} region {region!r}; "
        f"run 'gwen regions {key}' to list them"
    )


def _pattern(term: str) -> re.Pattern:
    # Whole words only, so "dfw" does not match inside another word.
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])")


@dataclass
class _Compiled:
    #: (pattern, region code), longest name first.
    names: list[tuple[re.Pattern, str]] = field(default_factory=list)


_COMPILED: dict[str, _Compiled] = {}


def _compiled(provider: str) -> _Compiled:
    if provider not in _COMPILED:
        pairs = [
            (name, region.code)
            for region in CATALOGS[provider].values()
            for name in region.names
        ]
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        _COMPILED[provider] = _Compiled(
            [(_pattern(name), code) for name, code in pairs]
        )
    return _COMPILED[provider]


def mentioned(provider: str, text: str, codes: list[str] = ()) -> set[str] | None:
    """Region codes of *provider* that *text* (or explicit *codes*) refer to.

    Returns None for providers without a catalog: there is no way to tell
    "names no region" from "names a region we do not know".
    """
    catalog = CATALOGS.get(provider)
    if catalog is None:
        return None
    found = {code for code in codes if code in catalog}
    remaining = text.lower()
    for pattern, code in _compiled(provider).names:
        # Blank out each match so "East US 2" is not also read as "East US".
        remaining, hits = pattern.subn(" ", remaining)
        if hits:
            found.add(code)
    return found


def names(term: str, text: str) -> bool:
    """Does *text* contain *term* as a whole word, ignoring case?"""
    return bool(_pattern(term.lower()).search(text.lower()))


def matches(target: Target, text: str, codes: list[str] = ()) -> bool:
    """Does an incident with this *text* and region *codes* affect *target*?"""
    if target.region is None:
        return True
    regions = mentioned(target.provider, text, codes)
    if regions is None:
        return names(target.region, text)
    # Naming no known region at all means the incident could be anywhere.
    return not regions or target.region in regions
