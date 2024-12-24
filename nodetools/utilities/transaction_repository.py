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
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)

            with conn.cursor() as cur:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_account_memo_history')
                
                if pft_issuer:
                    query += " AND tx_json_parsed::text LIKE %s"
                    params = (
                        account_address, account_address, account_address,
                        account_address, account_address, f"%{pft_issuer}%"
                    )
                else:
                    params = (
                        account_address, account_address, account_address,
                        account_address, account_address
                    )
                    
                cur.execute(query, params)
                
                columns = [desc[0] for desc in cur.description]
                results = []
                
                for row in cur.fetchall():
                    results.append(dict(zip(columns, row)))
                
                return results

        except Exception as e:
            logger.error(f"TransactionRepository.get_account_memo_history: Error getting memo history: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    async def get_unverified_transactions(
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
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_unverified_transactions')
                cur.execute(query, (
                    include_processed,
                    order_by,  # Used twice in the ORDER BY clause
                    order_by,
                    limit,     # For CASE WHEN NULL check
                    limit      # For actual limit value
                ))
                
                columns = [desc[0] for desc in cur.description]
                results = []
                
                for row in cur.fetchall():
                    results.append(dict(zip(columns, row)))
                
                return results
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_unverified_transactions: Error getting unverified transactions: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    async def reprocess_transactions(
        self,
        tx_hashes: List[str]
    ) -> None:
        """
        Remove processing results for specified transactions so they can be reprocessed.
        
        Args:
            tx_hashes: List of transaction hashes to reprocess
        """
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                query = """
                    DELETE FROM transaction_processing_results 
                    WHERE hash = ANY(%s)
                """
                cur.execute(query, (tx_hashes,))
                conn.commit()
                
                logger.info(f"Cleared processing results for {cur.rowcount} transactions")
                
        except Exception as e:
            logger.error(f"TransactionRepository.reprocess_transactions: Error clearing processing results: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    async def store_reviewing_result(self, tx_hash: str, result: 'ReviewingResult') -> None:
        """Store the reviewing result for a transaction"""
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'store_reviewing_result')
                values = (
                    tx_hash,
                    result.processed,
                    result.rule_name,
                    result.response_tx_hash,
                    result.notes
                )
                cur.execute(query, values)
                conn.commit()
                
        except Exception as e:
            logger.error(f"TransactionRepository.store_reviewing_result: Error storing reviewing result: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a custom query with parameters."""
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                cur.execute(query, params or {})
                # logger.debug(f"Executed query: {query}, params: {params}")
                
                # Get column names from cursor description
                columns = [desc[0] for desc in cur.description]
                results = []
                
                # Convert rows to dictionaries
                for row in cur.fetchall():
                    results.append(dict(zip(columns, row)))
                
                return results
                
        except Exception as e:
            logger.error(f"TransactionRepository.execute_query: Error executing query: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    def batch_insert_transactions(self, tx_list: List[Dict[str, Any]]) -> int:
        """Batch insert transactions into postfiat_tx_cache.
        
        Args:
            transactions: List of transaction dictionaries
            
        Returns:
            int: Number of transactions successfully inserted
        """
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)

            with conn.cursor() as cur:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'insert_transaction')

                # Prepare transaction data
                tx_data = [{
                    "hash": tx.get("hash"),
                    "ledger_index": tx.get("ledger_index"),
                    "close_time_iso": tx.get("close_time_iso"),
                    "tx_json": json.dumps(tx.get("tx_json", {})),
                    "meta": json.dumps(tx.get("meta", {})),
                    "validated": tx.get("validated", False)
                } for tx in tx_list]
                
                # Execute batch insert
                cur.executemany(query, tx_data)

                # Get count of new insertions
                hash_array = "ARRAY[" + ",".join(f"'{t['hash']}'" for t in tx_data) + "]"
                cur.execute(f"""
                    SELECT COUNT(*) FROM postfiat_tx_cache 
                    WHERE hash = ANY({hash_array})
                    AND xmin::text = txid_current()::text
                """)
                inserted = cur.fetchone()[0]

                conn.commit()
                return inserted
            
        except Exception as e:
            logger.error(f"TransactionRepository: Error batch inserting transactions: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    async def insert_transaction(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a single transaction and return the processed record"""
        try:
            pool = await self.db_manager.get_pool(self.username)


            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Load and execute insert query
                    sql_manager = SQLManager()
                    insert_query = sql_manager.load_query('xrpl', 'insert_transaction')
                    
                    await conn.execute(
                        insert_query,
                        hash=tx.get("hash"),
                        ledger_index=tx.get("ledger_index"),
                        close_time_iso=tx.get("close_time_iso"),
                        tx_json=json.dumps(tx.get("tx_json", {})),
                        meta=json.dumps(tx.get("meta", {})),
                        validated=tx.get("validated", False)
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
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
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
                    WHERE m.hash = %s
                """
                cur.execute(query, (tx_hash,))
                
                row = cur.fetchone()
                if row:
                    columns = [desc[0] for desc in cur.description]
                    return dict(zip(columns, row))
                return None
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_decoded_transaction: Error getting transaction {tx_hash}: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()

    def get_active_wallet_transactions(self, wallet_addresses: List[str]) -> List[Dict[str, Any]]:
        """Get all transactions for the specified wallet addresses.
        
        Args:
            wallet_addresses: List of wallet addresses to query
            
        Returns:
            List of transactions with decoded memo data
        """
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                sql_manager = SQLManager()
                query = sql_manager.load_query('xrpl', 'get_active_wallet_transactions')
                
                # Convert list to tuple for SQL IN clause
                params = {'wallet_addresses': tuple(wallet_addresses)}
                
                cur.execute(query, params)
                
                columns = [desc[0] for desc in cur.description]
                results = []
                
                for row in cur.fetchall():
                    # Parse JSON fields
                    row_dict = dict(zip(columns, row))
                    if isinstance(row_dict.get('tx_json'), str):
                        row_dict['tx_json'] = json.loads(row_dict['tx_json'])
                    if isinstance(row_dict.get('meta'), str):
                        row_dict['meta'] = json.loads(row_dict['meta'])
                    results.append(row_dict)
                
                return results
                
        except Exception as e:
            logger.error(f"TransactionRepository.get_active_wallet_transactions: Error getting transactions: {e}")
            logger.error(traceback.format_exc())
            raise
        finally:
            conn.close()