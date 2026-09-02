from abc import ABC, abstractmethod


class BaseEngine(ABC):
    @abstractmethod
    def fetch(self, sql: str, **kwargs):
        """Run a SQL task."""
