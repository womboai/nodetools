from typing import List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.sql.sql_manager import SQLManager
import traceback
import json

if TYPE_CHECKING:
    from nodetools.utilities.transaction_orchestrator import ProcessingResult

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

    def store_transaction(self, tx_message: Dict[str, Any]) -> bool:
        """Store a single transaction in the postfiat_tx_cache table.
        
        Args:
            tx_message: Raw transaction message from XRPL websocket
            
        Returns:
            bool: True if transaction was stored successfully
        """
        try:
            # Extract tx_json and format fields
            tx_json = tx_message.get("tx_json", {}) if isinstance(tx_message.get("tx_json"), dict) else tx_message.get("transaction", {})
            
            # Convert nested dictionaries to strings
            delivermax = tx_json.get("DeliverMax")
            if isinstance(delivermax, dict):
                delivermax = json.dumps(delivermax)

            # Prepare transaction data
            tx_data = {
                "close_time_iso": tx_message.get("close_time_iso"),
                "hash": tx_message.get("hash"),
                "ledger_hash": tx_message.get("ledger_hash"),
                "ledger_index": tx_message.get("ledger_index"),
                "meta": json.dumps(tx_message.get("meta", {})),
                "tx_json": json.dumps(tx_json),
                "validated": tx_message.get("validated", False),
                
                # Extract from tx_json
                "account": tx_json.get("Account"),
                "delivermax": delivermax,
                "destination": tx_json.get("Destination"),
                "fee": tx_json.get("Fee"),
                "flags": tx_json.get("Flags"),
                "lastledgersequence": tx_json.get("LastLedgerSequence"),
                "sequence": tx_json.get("Sequence"),
                "signingpubkey": tx_json.get("SigningPubKey"),
                "transactiontype": tx_json.get("TransactionType"),
                "txnsignature": tx_json.get("TxnSignature"),
                "date": tx_json.get("date"),
                "memos": json.dumps(tx_json.get("Memos", []))
            }

            conn = self.db_manager.spawn_psycopg2_db_connection(self.username)

            try:
                with conn.cursor() as cur:
                    query = """
                        INSERT INTO postfiat_tx_cache (
                            close_time_iso, hash, ledger_hash, ledger_index, meta,
                            tx_json, validated, account, delivermax, destination,
                            fee, flags, lastledgersequence, sequence, signingpubkey,
                            transactiontype, txnsignature, date, memos
                        ) VALUES (
                            %(close_time_iso)s, %(hash)s, %(ledger_hash)s, %(ledger_index)s, %(meta)s,
                            %(tx_json)s, %(validated)s, %(account)s, %(delivermax)s, %(destination)s,
                            %(fee)s, %(flags)s, %(lastledgersequence)s, %(sequence)s, %(signingpubkey)s,
                            %(transactiontype)s, %(txnsignature)s, %(date)s, %(memos)s
                        ) ON CONFLICT (hash) DO NOTHING
                    """
                    cur.execute(query, tx_data)
                    conn.commit()
                    return True
            finally:
                conn.close()

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
                        p.processed_at
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