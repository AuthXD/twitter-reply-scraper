import yaml
from pathlib import Path


class Config(dict):
    """Thin dict wrapper so cfg['themes'] etc. reads naturally."""

    @classmethod
    def load(cls, path="config.yaml"):
        data = yaml.safe_load(Path(path).read_text())
        return cls(data)

    @property
    def accounts(self):
        return self.get("accounts", [])

    @property
    def themes(self):
        return self.get("themes", [])
