from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    @abstractmethod
    def fetch_metadata(self, url: str) -> dict[str, Any]:
        """Extrai metadados padronizados da URL."""
        pass
