from abc import ABC, abstractmethod


class Adapter(ABC):
    """A data source that yields Reply objects. Authorized sources only."""
    name = "base"

    @abstractmethod
    def fetch(self, cfg, db, log):
        """Yield Reply objects for the configured accounts."""
        raise NotImplementedError
