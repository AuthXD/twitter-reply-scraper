from .manual_ingest import ManualIngestAdapter
from .official_api import OfficialAPIAdapter
from .playwright_scraper import PlaywrightAdapter, PlaywrightSearchAdapter

REGISTRY = {
    "manual": ManualIngestAdapter,
    "api": OfficialAPIAdapter,
    "playwright": PlaywrightAdapter,
    "search": PlaywrightSearchAdapter,
}
