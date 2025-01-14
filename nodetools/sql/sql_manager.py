from importlib import resources
import pathlib
from typing import Optional, List
from loguru import logger
import traceback
import sqlparse

class SQLManager:
    """Manages SQL script loading and parsing"""
    
    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            # No need to calculate path - we'll use package resources
            self.base_path = None
        else:
            self.base_path = pathlib.Path(base_path)

    def load_query(self, category: str, name: str) -> str:
        """Load SQL query from file
        
        Args:
            category: The category of SQL (e.g., 'init', 'queries')
            name: The name of the SQL file without extension
            
        Returns:
            str: The contents of the SQL file
        """
        if self.base_path:
            # Use direct file system path if provided
            file_path = self.base_path / category / f"{name}.sql"
            
            try:
                return file_path.read_text()
            except FileNotFoundError:
                logger.error(f"SQL file not found: {file_path}")
                logger.error(traceback.format_exc())
                raise
        else:
            # Use package resources
            try:
                package_path = f"nodetools.sql.{category}"
                with resources.files(package_path).joinpath(f"{name}.sql").open('r') as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Failed to load SQL file: {name}.sql from {package_path}")
                logger.error(traceback.format_exc())
                raise

    def load_statements(self, category: str, name: str) -> List[str]:
        """Load and parse SQL file into individual statements
        
        Args:
            category: The category of SQL (e.g., 'init', 'queries')
            name: The name of the SQL file without extension

        Returns:
            List[str]: List of individual SQL statements
        """
        raw_sql = self.load_query(category, name)
        statements = sqlparse.split(raw_sql)
        return [stmt for stmt in statements if stmt.strip()]
    
    def get_table_names(self, category: str, name: str) -> List[str]:
        """Extract table names from CREATE TABLE statements in SQL file"""
        statements = self.load_statements(category, name)
        return self.get_table_names_from_statements(statements)
    
    def get_table_names_from_statements(self, statements: List[str]) -> List[str]:
        """Extract table names from CREATE TABLE statements"""
        return [name for stmt in statements if stmt and (name := self._get_table_name_from_statement(stmt))]
    
    def _get_table_name_from_statement(self, statement: str) -> Optional[str]:
        """Extract table name from CREATE TABLE statement"""
        table_name = None
        parsed = sqlparse.parse(statement)[0]
        if (parsed.get_type() == 'CREATE' and any(token.value.upper() == 'TABLE' for token in parsed.tokens)):
            for i, token in enumerate(parsed.tokens):
                if token.value.upper() == 'TABLE':
                    for next_token in parsed.tokens[i+1:]:  # Look at subsequent tokens
                        match next_token:
                            case _ if next_token.ttype == sqlparse.tokens.Whitespace:
                                continue
                            case _ if next_token.value.upper() in {'IF', 'NOT', 'EXISTS'}:
                                continue
                            case _:
                                table_name = next_token.value.strip('"').split('.')[-1]
                                return table_name

    def get_function_names(self, category: str, name: str) -> List[str]:
        """Extract function names from CREATE OR REPLACE FUNCTION statements"""
        statements = self.load_statements(category, name)
        return self.get_function_names_from_statements(statements)
    
    def get_function_names_from_statements(self, statements: List[str]) -> List[str]:
        """Extract function names from CREATE OR REPLACE FUNCTION statements"""
        return [name for stmt in statements if stmt and (name := self._get_function_name_from_statement(stmt))]

    def _get_function_name_from_statement(self, statement: str) -> Optional[str]:
        """Extract function name from CREATE OR REPLACE FUNCTION statement"""
        func_name = None
        parsed = sqlparse.parse(statement)[0]
        if parsed.get_type() in ['CREATE', 'CREATE OR REPLACE']:
            for i, token in enumerate(parsed.tokens):
                if token.value.upper() == 'FUNCTION':
                    for next_token in parsed.tokens[i+1:]:
                        if next_token.ttype != sqlparse.tokens.Whitespace:
                            func_name = next_token.value.split('(')[0].strip('"')
                            return func_name

    def get_view_names(self, category: str, name: str) -> List[str]:
        """Extract view names from CREATE OR REPLACE VIEW statements"""
        statements = self.load_statements(category, name)
        return self.get_view_names_from_statements(statements)
    
    def get_view_names_from_statements(self, statements: List[str]) -> List[str]:
        """Extract view names from CREATE OR REPLACE VIEW statements"""
        return [name for stmt in statements if stmt and (name := self._get_view_name_from_statement(stmt))]
    
    def _get_view_name_from_statement(self, statement: str) -> Optional[str]:
        """Extract view name from CREATE OR REPLACE VIEW statement"""
        view_name = None
        parsed = sqlparse.parse(statement)[0]
        if parsed.get_type() in ['CREATE', 'CREATE OR REPLACE']:
            for i, token in enumerate(parsed.tokens):
                if token.value.upper() == 'VIEW':
                    for next_token in parsed.tokens[i+1:]:
                        if next_token.ttype != sqlparse.tokens.Whitespace:
                            view_name = next_token.value.strip('"').split('.')[-1]
                            return view_name

    def get_index_names(self, category: str, name: str) -> List[str]:
        """Extract index names from CREATE INDEX IF NOT EXISTS statements"""
        statements = self.load_statements(category, name)
        return self.get_index_names_from_statements(statements)
    
    def get_index_names_from_statements(self, statements: List[str]) -> List[str]:
        """Extract index names from CREATE INDEX IF NOT EXISTS statements"""
        return [name for stmt in statements if stmt and (name := self._get_index_name_from_statement(stmt))]
    
    def _get_index_name_from_statement(self, statement: str) -> Optional[str]:
        """Extract index name from CREATE INDEX IF NOT EXISTS statement"""
        index_name = None
        parsed = sqlparse.parse(statement)[0]
        if (parsed.get_type() == 'CREATE' and any(token.value.upper() == 'INDEX' for token in parsed.tokens)):
            for i, token in enumerate(parsed.tokens):
                if token.value.upper() == 'INDEX':
                    for next_token in parsed.tokens[i+1:]:
                        match next_token:
                            case _ if next_token.ttype == sqlparse.tokens.Whitespace:
                                continue
                            case _ if next_token.value.upper() in {'IF', 'NOT', 'EXISTS'}:
                                continue
                            case _:
                                index_name = next_token.value.strip('"').split('.')[-1]
                                return index_name

    def get_trigger_names(self, category: str, name: str) -> List[str]:
        """Extract trigger names from CREATE TRIGGER statements"""
        statements = self.load_statements(category, name)
        return self.get_trigger_names_from_statements(statements)
    
    def get_trigger_names_from_statements(self, statements: List[str]) -> List[str]:
        """Extract trigger names from CREATE TRIGGER statements"""
        return [name for stmt in statements if stmt and (name := self._get_trigger_name_from_statement(stmt))]
    
    def _get_trigger_name_from_statement(self, statement: str) -> Optional[str]:
        """Extract trigger name from CREATE TRIGGER statement"""
        trigger_name = None
        parsed = sqlparse.parse(statement)[0]
        if (parsed.get_type() == 'CREATE' and any(token.value.upper() == 'TRIGGER' for token in parsed.tokens)):
            for i, token in enumerate(parsed.tokens):
                if token.value.upper() == 'TRIGGER':
                    for next_token in parsed.tokens[i+1:]:
                        match next_token:
                            case _ if next_token.ttype == sqlparse.tokens.Whitespace:
                                continue
                            case _:
                                trigger_name = next_token.value.strip('"').split('.')[-1]
                                return trigger_name
