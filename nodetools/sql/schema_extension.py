from abc import ABC, abstractmethod
from typing import List, Tuple

class SchemaExtension(ABC):
    """Base class for node-specific schema extensions."""

    @abstractmethod
    def get_table_definitions(self) -> List[str]:
        """Return SQL statements for creating tables."""
        pass

    @abstractmethod
    def get_function_definitions(self) -> List[str]:
        """Return SQL statements for creating functions."""
        pass

    @abstractmethod
    def get_trigger_definitions(self) -> List[str]:
        """Return SQL statements for creating triggers."""
        pass

    @abstractmethod
    def get_view_definitions(self) -> List[str]:
        """Return SQL statements for creating views."""
        pass

    @abstractmethod
    def get_index_definitions(self) -> List[str]:
        """Return SQL statements for creating indexes."""
        pass

    def get_privileges(self) -> List[Tuple[str, str]]:
        """Return list of (table_name, privilege) tuples to grant to postfiat role."""
        return []
    
    
