from typing import Protocol
import sqlalchemy

class DBConnectionManager(Protocol):
    def spawn_sqlalchemy_db_connection_for_user(self, username: str) -> sqlalchemy.engine.Engine:
        ...
