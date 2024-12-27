from typing import List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.sql.sql_manager import SQLManager
import traceback
import json

if TYPE_CHECKING:
    from nodetools.utilities.transaction_orchestrator import ReviewingResult

class TransactionRepository:
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_manager: DBConnectionManager, username: str):
        if not self.__class__._initialized:
            self.db_manager = db_manager
            self.username = username
            self._pool = None
            self.__class__._initialized = True

    async def get_account_memo_history(
        self,
        account_address: str,
        pft_issuer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get transaction history with memos for an account.
        
        Args:
            account_address: XRPL account address to get history for
            pft_issuer: If provided, only return PFT transactions for this issuer
            
        Returns:
            List of dictionaries containing transaction history with memo details
        """ 
        try:
            pool = await self.db_manager.get_pool(self.username)

            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_account_memo_history')

                # Convert all %s to numbered parameters
                param_count = query.count('%s')
                for i in range(param_count):
                    query = query.replace('%s', f'${i+1}', 1)
                
                if pft_issuer:
                    query += f" AND tx_json_parsed::text LIKE ${param_count+1}"
                    params = [
                        account_address, account_address, account_address,
                        account_address, account_address, f"%{pft_issuer}%"
                    ]
                else:
                    params = [
                        account_address, account_address, account_address,
                        account_address, account_address
                    ]
                    
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"TransactionRepository.get_account_memo_history: Error getting memo history: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_unprocessed_transactions(
        self, 
        order_by: str = "close_time_iso ASC",
        limit: Optional[int] = None,
        include_processed: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get transactions that haven't been processed yet.
        
        Args:
            order_by: SQL ORDER BY clause
            limit: Optional limit on number of transactions to return
            include_processed: If True, includes all transactions regardless of processing status
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_unverified_transactions')

                # Convert %s to numbered parameters
                query = query.replace('%s', '$1', 1)  # include_processed
                query = query.replace('%s', '$2', 1)  # first order_by
                query = query.replace('%s', '$3', 1)  # second order_by
                query = query.replace('%s', 'CAST($4 AS INTEGER)', 1)  # limit for CASE WHEN
                query = query.replace('%s', 'CAST($5 AS INTEGER)', 1)  # limit for actual limit
                
                rows = await conn.fetch(
                    query,
                    include_processed,
                    order_by,      # First usage in ORDER BY
                    order_by,      # Second usage in ORDER BY
                    limit,         # For CASE WHEN NULL check
                    limit          # For actual limit value
                )
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_unverified_transactions: Error getting unverified transactions: {e}")
            logger.error(traceback.format_exc())
            raise

    async def store_reviewing_result(self, tx_hash: str, result: 'ReviewingResult') -> None:
        """Store the reviewing result for a transaction"""
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                async with conn.transaction():
                    sql_manager = SQLManager()
                    query = sql_manager.load_query('xrpl', 'store_reviewing_result')
                    
                    # Convert %s to numbered parameters
                    query = query.replace('%s', '$1', 1)
                    query = query.replace('%s', '$2', 1)
                    query = query.replace('%s', '$3', 1)
                    query = query.replace('%s', '$4', 1)
                    query = query.replace('%s', '$5', 1)
                    
                    await conn.execute(
                        query,
                        tx_hash,
                        result.processed,
                        result.rule_name,
                        result.response_tx_hash,
                        result.notes
                    )
                
        except Exception as e:
            logger.error(f"TransactionRepository.store_reviewing_result: Error storing reviewing result: {e}")
            logger.error(traceback.format_exc())
            raise

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a custom query with parameters."""
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                # Convert named parameters from %(name)s to $1, $2, etc.
                if params:
                    # Create a mapping of param names to positions
                    param_names = list(params.keys())
                    for i, name in enumerate(param_names, 1):
                        query = query.replace(f"%({name})s", f"${i}")
                    # Convert dict to list of values in the correct order
                    param_values = [params[name] for name in param_names]
                else:
                    param_values = []

                # Execute query and fetch results
                rows = await conn.fetch(query, *param_values)
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"TransactionRepository.execute_query: Error executing query: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            logger.error(traceback.format_exc())
            raise

    async def batch_insert_transactions(self, tx_list: List[Dict[str, Any]]) -> int:
        """Batch insert transactions into postfiat_tx_cache.
        
        Args:
            transactions: List of transaction dictionaries
            
        Returns:
            int: Number of transactions successfully inserted
        """
        try:
            pool = await self.db_manager.get_pool(self.username)

            async with pool.acquire() as conn:
                async with conn.transaction():
                    sql_manager = SQLManager()
                    query = sql_manager.load_query('xrpl', 'insert_transaction')

                    # Convert %(name)s style parameters to $1, $2, etc.
                    query = query.replace("%(hash)s", "$1")
                    query = query.replace("%(ledger_index)s", "$2")
                    query = query.replace("%(close_time_iso)s", "$3")
                    query = query.replace("%(tx_json)s", "$4")
                    query = query.replace("%(meta)s", "$5")
                    query = query.replace("%(validated)s", "$6")
                
                    # Execute batch insert
                    await conn.executemany(
                        query,
                        [(
                            tx.get("hash"),
                            tx.get("ledger_index"),
                            tx.get("close_time_iso"),
                            json.dumps(tx.get("tx_json", {})),
                            json.dumps(tx.get("meta", {})),
                            tx.get("validated", False)
                        ) for tx in tx_list]
                    )

                    # Get count of new insertions
                    hash_array = "ARRAY[" + ",".join(f"'{t['hash']}'" for t in tx_list) + "]"
                    row = await conn.fetchrow(f"""
                        SELECT COUNT(*) FROM postfiat_tx_cache 
                        WHERE hash = ANY({hash_array})
                        AND xmin::text = txid_current()::text
                    """)
                    return row[0]

        except Exception as e:
            logger.error(f"TransactionRepository: Error batch inserting transactions: {e}")
            logger.error(traceback.format_exc())
            raise

    async def insert_transaction(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a single transaction and return the processed record"""
        try:
            pool = await self.db_manager.get_pool(self.username)


            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Load and execute insert query
                    sql_manager = SQLManager()
                    insert_query = sql_manager.load_query('xrpl', 'insert_transaction')

                    # Replace %(name)s style parameters with $1, $2, etc.
                    # TODO: This is a hack to get around the fact that psycopg2 doesn't support %(name)s style parameters
                    insert_query = insert_query.replace("%(hash)s", "$1")
                    insert_query = insert_query.replace("%(ledger_index)s", "$2")
                    insert_query = insert_query.replace("%(close_time_iso)s", "$3")
                    insert_query = insert_query.replace("%(tx_json)s", "$4")
                    insert_query = insert_query.replace("%(meta)s", "$5")
                    insert_query = insert_query.replace("%(validated)s", "$6")
                    
                    await conn.execute(
                        insert_query,
                        tx.get("hash"),
                        tx.get("ledger_index"),
                        tx.get("close_time_iso"),
                        json.dumps(tx.get("tx_json", {})),
                        json.dumps(tx.get("meta", {})),
                        tx.get("validated", False)
                    )

                    # Immediately get processed record
                    row = await conn.fetchrow("""
                        SELECT * FROM decoded_memos WHERE hash = $1
                    """, tx["hash"])
                    
                    return dict(row) if row else None

        except Exception as e:
            logger.error(f"Error storing transaction: {e}")
            logger.error(traceback.format_exc())
            return False
        
    async def get_decoded_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get a specific transaction with decoded memos by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            Dict containing transaction data with decoded memos if found, None otherwise
        """
        try:
            pool = await self.db_manager.get_pool(self.username)

            async with pool.acquire() as conn:
                query = """
                    SELECT 
                        m.*,
                        p.processed,
                        p.rule_name,
                        p.response_tx_hash,
                        p.notes,
                        p.reviewed_at
                    FROM decoded_memos m
                    LEFT JOIN transaction_processing_results p ON m.hash = p.hash
                    WHERE m.hash = $1
                """
                row = await conn.fetchrow(query, tx_hash)
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_decoded_transaction: Error getting transaction {tx_hash}: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_active_wallet_transactions(self, wallet_addresses: List[str]) -> List[Dict[str, Any]]:
        """Get all transactions for the specified wallet addresses.
        
        Args:
            wallet_addresses: List of wallet addresses to query
            
        Returns:
            List of transactions with decoded memo data
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_active_wallet_transactions')
                
                # Convert %(wallet_addresses)s to $1
                query = query.replace("%(wallet_addresses)s", "$1")
                
                # Execute query with tuple of addresses
                rows = await conn.fetch(query, tuple(wallet_addresses))
                
                results = []
                for row in rows:
                    row_dict = dict(row)
                    # Parse JSON fields
                    if isinstance(row.get('tx_json'), str):
                        row_dict['tx_json'] = json.loads(row['tx_json'])
                    if isinstance(row.get('meta'), str):
                        row_dict['meta'] = json.loads(row['meta'])
                    results.append(row_dict)
                
                return results
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_active_wallet_transactions: Error getting transactions: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_pft_holders(self) -> Dict[str, Dict[str, Any]]:
        """Get current PFT holder data from database"""
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_pft_holders')
                
                rows = await conn.fetch(query)
                
                results = {}
                for row in rows:
                    row_dict = dict(row)
                    results[row_dict['account']] = {
                        'balance': row_dict['balance'],
                        'last_updated': row_dict['last_updated'],
                        'last_tx_hash': row_dict['last_tx_hash']
                    }
                
                return results
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_pft_holders: Error getting PFT holders: {e}")
            logger.error(traceback.format_exc())
            raise