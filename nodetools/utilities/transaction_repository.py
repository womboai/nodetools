from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple, Union
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

    async def _execute_query(
        self,
        query_name: str,
        query_category: str,
        params: List[Any]
    ) -> List[Dict[str, Any]]:
        """Execute a query and return results with consistent structure.
        
        Args:
            query_name: Name of the SQL file without extension
            query_category: Category/folder containing the SQL file
            params: List of parameters to pass to the query
            
        Returns:
            List of dictionaries containing query results or empty structure if no results
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query(query_category, query_name)
                
                # Get the record schema
                statement = await conn.prepare(query)
                attributes = statement.get_attributes()
                
                rows = await conn.fetch(query, *params)
                if not rows:
                    # Use attribute names as keys instead of Attribute objects
                    empty_result = {attr.name: None for attr in attributes}
                    return [empty_result]

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"TransactionRepository.{query_name}: Error executing query: {e}")
            logger.error(traceback.format_exc())
            raise

    async def _execute_mutation(
        self,
        query_name: str,
        query_category: str,
        params: Union[List[Any], List[Tuple[Any, ...]]],
        *,
        is_batch: bool = False,
        count_query_name: Optional[str] = None,
        count_params: Optional[List[Any]] = None
    ) -> None:
        """Execute a mutation query (INSERT, UPDATE, DELETE).
        
        Args:
            query_name: Name of the SQL file without extension
            query_category: Category/folder containing the SQL file
            params: List of parameters for single operation or list of parameter tuples for batch
            is_batch: If True, uses executemany for batch operations
            count_query_name: Optional name of query to count affected rows. Count query must have a single parameter ($1)
            count_params: Optional parameter for count query
            
        Returns:
            Optional[int]: Number of affected rows if count_query_name provided, None otherwise
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                async with conn.transaction():
                    sql_manager = SQLManager()
                    query = sql_manager.load_query(query_category, query_name)

                    if is_batch:
                        await conn.executemany(query, params)
                    else:
                        await conn.execute(query, *params)

                    # Execute count query if provided
                    if count_query_name and count_params is not None:
                        count_query = sql_manager.load_query(query_category, count_query_name)
                        # Replace the parameter placeholder with the array string
                        count_query = count_query.replace('$1', count_params[0])
                        result = await conn.fetchrow(count_query)
                        return result['count'] if result else 0

                    return None

        except Exception as e:
            logger.error(f"TransactionRepository.{query_name}: Error executing mutation: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_account_memo_history(
        self,
        account_address: str,
        pft_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get transaction history with memos for an account using transaction_memos table.
        
        Args:
            account_address: XRPL account address to get history for
            pft_only: If True, only return transactions with PFT amounts. Defaults to False.
            
        Returns:
            List of dictionaries containing transaction history with memo details
        """ 
        params = [
            account_address, account_address, account_address,
            account_address, account_address, pft_only
        ]
        return await self._execute_query(
            query_name='get_account_memo_history',
            query_category='xrpl',
            params=params
        )
    
    async def get_account_memo_histories(self, wallet_addresses: List[str]) -> List[Dict[str, Any]]:
        """Get all transaction histories for the specified wallet addresses.
        
        Args:
            wallet_addresses: List of wallet addresses to query
            
        Returns:
            List of transaction histories with decoded memo data
        """
        results = await self._execute_query(
            query_name='get_account_memo_histories',
            query_category='xrpl',
            params=[wallet_addresses]  # asyncpg automatically handles list->array conversion
        )
        
        # Parse JSON fields in results
        for row in results:
            if isinstance(row.get('tx_json'), str):
                row['tx_json'] = json.loads(row['tx_json'])
            if isinstance(row.get('meta'), str):
                row['meta'] = json.loads(row['meta'])
        
        return results

    async def get_unprocessed_transactions(
        self, 
        order_by: str = "close_time_iso ASC",
        limit: Optional[int] = None,
        include_processed: bool = False
    ) -> List[Dict[str, Any]]:
        """Get transactions that haven't been processed yet.
        
        Args:
            order_by: SQL ORDER BY clause
            limit: Optional limit on number of transactions to return
            include_processed: If True, includes all transactions regardless of processing status
            
        Returns:
            List of dictionaries containing transaction data
        """
        params = [
            include_processed,
            order_by,      # First usage in ORDER BY
            order_by,      # Second usage in ORDER BY
            limit,         # For CASE WHEN NULL check
            limit          # For actual limit value
        ]
        
        return await self._execute_query(
            query_name='get_unprocessed_transactions',
            query_category='xrpl',
            params=params
        )

    async def store_reviewing_result(self, result: 'ReviewingResult') -> None:
        """Store the reviewing result for a transaction
        
        Args:
            result: ReviewingResult object containing transaction processing outcome
        """
        params = [
            result.tx['hash'],
            result.processed,
            result.rule_name,
            result.response_tx_hash,
            result.notes
        ]
        
        await self._execute_mutation(
            query_name='store_reviewing_result',
            query_category='xrpl',
            params=params
        )

    async def batch_insert_transactions(self, tx_list: List[Dict[str, Any]]) -> int:
        """Batch insert transactions into postfiat_tx_cache.
        
        Args:
            tx_list: List of transaction dictionaries
            
        Returns:
            int: Number of transactions successfully inserted
        """
        if not tx_list:
            return 0
        
        # Prepare parameters for batch insert
        params = [(
            tx.get("hash"),
            tx.get("ledger_index"),
            tx.get("close_time_iso"),
            json.dumps(tx.get("tx_json", {})),
            json.dumps(tx.get("meta", {})),
            tx.get("validated", False)
        ) for tx in tx_list]

        # Prepare hash array for count query
        hash_array = "ARRAY[" + ",".join(f"'{tx['hash']}'" for tx in tx_list) + "]"

        # Do batch insert and count in same transaction
        return await self._execute_mutation(
            query_name='insert_transaction',
            query_category='xrpl',
            params=params,
            is_batch=True,
            count_query_name='count_inserted_transactions',
            count_params=[hash_array]
        ) or 0  # Return 0 if None is returned

    async def insert_transaction(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a single transaction and return the processed record.
        
        Args:
            tx: Transaction dictionary to insert
            
        Returns:
            Optional[Dict[str, Any]]: Processed record if found, None if not found
        """
        try:
            # Insert the transaction
            params = [
                tx.get("hash"),
                tx.get("ledger_index"),
                tx.get("close_time_iso"),
                json.dumps(tx.get("tx_json", {})),
                json.dumps(tx.get("meta", {})),
                tx.get("validated", False)
            ]
            
            await self._execute_mutation(
                query_name='insert_transaction',
                query_category='xrpl',
                params=params
            )

            # Get the processed record
            result = await self._execute_query(
                query_name='get_decoded_memo',
                query_category='xrpl',
                params=[tx["hash"]]
            )
            
            return result[0] if result and result[0]['hash'] is not None else None

        except Exception as e:
            logger.error(f"Error storing transaction: {e}")
            logger.error(traceback.format_exc())
            return None
        
    async def get_decoded_memo(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get a specific transaction with decoded memos by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            Dict containing transaction data with decoded memos if found, None otherwise
        """
        result = await self._execute_query(
            query_name='get_decoded_memo',
            query_category='xrpl',
            params=[tx_hash]
        )
        
        return result[0] if result and result[0]['hash'] is not None else None
        
    async def get_decoded_memo_w_processing(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get a specific transaction with decoded memos and processing results by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            Dict containing transaction data with decoded memos if found, None otherwise
        """
        result = await self._execute_query(
            query_name='get_decoded_memo_w_processing',
            query_category='xrpl',
            params=[tx_hash]
        )
        
        return result[0] if result and result[0]['hash'] is not None else None

    async def get_pft_holders(self) -> Dict[str, Dict[str, Any]]:
        """Get current PFT holder data from database.
        
        Returns:
            Dict mapping account addresses to their PFT holding details
        """
        results = await self._execute_query(
            query_name='get_pft_holders',
            query_category='xrpl',
            params=[]
        )
        
        # Transform list of results into account-keyed dictionary
        return {
            row['account']: {
                'balance': row['balance'],
                'last_updated': row['last_updated'],
                'last_tx_hash': row['last_tx_hash']
            }
            for row in results
        }