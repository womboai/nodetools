from typing import List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.sql.sql_manager import SQLManager
import traceback

if TYPE_CHECKING:
    from nodetools.utilities.transaction_orchestrator import ProcessingResult

class TransactionRepository:
    def __init__(self, db_manager: DBConnectionManager, username: str):
        self.db_manager = db_manager
        self.username = username

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

    async def store_processing_result(self, tx_hash: str, result: 'ProcessingResult') -> None:
        """Store the processing result for a transaction"""
        try:
            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)
            
            with conn.cursor() as cur:
                query = """
                    INSERT INTO transaction_processing_results 
                    (hash, processed, rule_name, response_tx_hash, notes)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (hash) DO UPDATE SET
                        processed = EXCLUDED.processed,
                        rule_name = EXCLUDED.rule_name,
                        response_tx_hash = EXCLUDED.response_tx_hash,
                        notes = EXCLUDED.notes,
                        processed_at = CURRENT_TIMESTAMP
                """
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
            logger.error(f"TransactionRepository.store_processing_result: Error storing processing result: {e}")
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
