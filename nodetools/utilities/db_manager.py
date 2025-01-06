import sqlalchemy
import psycopg2
from nodetools.utilities.credentials import CredentialManager
from loguru import logger
import asyncpg

class DBConnectionManager:
    ''' supports 1 database for the collective and one for the user'''
    _instance = None
    _initialized = False
    _pool = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, credential_manager: CredentialManager):
        if not self.__class__._initialized:
            self.credential_manager = credential_manager
            self.__class__._initialized = True

    def spawn_sqlalchemy_db_connection_for_user(self, username):
        """Create a SQLAlchemy engine for the specified user"""
        db_connstring = self.credential_manager.get_credential(f'{username}_postgresconnstring')
        engine = sqlalchemy.create_engine(db_connstring)
        return engine
    
    def list_sqlalchemy_db_table_names_for_user(self, username):
        engine = self.spawn_sqlalchemy_db_connection_for_user(username)
        table_names = sqlalchemy.inspect(engine).get_table_names()
        return table_names
    
    def spawn_psycopg2_db_connection(self, username):
        db_connstring = self.credential_manager.get_credential(f'{username}_postgresconnstring')
        db_user = db_connstring.split('://')[1].split(':')[0]
        db_password = db_connstring.split('://')[1].split(':')[1].split('@')[0]
        db_host = db_connstring.split('://')[1].split(':')[1].split('@')[1].split('/')[0]
        db_name = db_connstring.split('/')[-1:][0]
        psycop_conn = psycopg2.connect(user=db_user, password=db_password, host=db_host, database=db_name)
        return psycop_conn
    
    async def get_pool(self, username):
        """Get or create connection pool for the specified user"""
        if self._pool is None:
            db_connstring = self.credential_manager.get_credential(f'{username}_postgresconnstring')
            self._pool = await asyncpg.create_pool(db_connstring)
        return self._pool

    async def close(self):
        """Close the connection pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None
