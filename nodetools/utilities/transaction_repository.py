from typing import List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.sql.sql_manager import SQLManager
import traceback

if TYPE_CHECKING:
    from nodetools.models.processor import ProcessingResult

class TransactionRepository:
    def __init__(self, db_manager: DBConnectionManager, username: str):
        self.db_manager = db_manager
        self.username = username

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
