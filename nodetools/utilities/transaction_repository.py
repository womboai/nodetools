from typing import List, Dict, Any, Optional, TYPE_CHECKING, Tuple, Union
from loguru import logger
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.sql.sql_manager import SQLManager
from nodetools.models.models import MemoTransaction
import traceback
import json
from decimal import Decimal

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
        params: Optional[Union[Dict[str, Any], List[Any]]] = None,
        enforce_column_structure: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Execute a custom query with parameters.
        
        Args:
            query: SQL query string
            params: Optional dictionary of query parameters or list of parameters
            enforce_column_structure: If True, enforce the column structure of the query, 
                otherwise empty results will return None. 
                Useful when placing results into a pandas dataframe that requires a consistent structure
            
        Returns:
            List of dictionaries containing query results
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                
                if params:

                    # Convert named parameters from %(name)s to $1, $2, etc.
                    if isinstance(params, dict):
                        # Create a mapping of param names to positions
                        param_names = list(params.keys())
                        for i, name in enumerate(param_names, 1):
                            query = query.replace(f"%({name})s", f"${i}")
                        # Convert dict to list of values in the correct order
                        param_values = [params[name] for name in param_names]
                    
                    # If params is a list, use it directly
                    else:
                        param_values = params
                else:
                    param_values = []

                # Get the record schema
                if enforce_column_structure:
                    statement = await conn.prepare(query)
                    attributes = statement.get_attributes()

                # Execute query and fetch results
                rows = await conn.fetch(query, *param_values)

                if enforce_column_structure:
                    if not rows:
                        # Use attribute names as keys instead of Attribute objects
                        empty_result = {attr.name: None for attr in attributes}
                        return [empty_result]

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
        params: List[Any],
        enforce_column_structure: bool = False
    ) -> List[Dict[str, Any]]:
        """Execute a query and return results with consistent structure.
        
        Args:
            query_name: Name of the SQL file without extension
            query_category: Category/folder containing the SQL file
            params: List of parameters to pass to the query
            enforce_column_structure: If True, enforce the column structure of the query, 
                otherwise empty results will return None. 
                Useful when placing results into a pandas dataframe that requires a consistent structure
            
        Returns:
            List of dictionaries containing query results or empty structure if no results
        """
        try:
            pool = await self.db_manager.get_pool(self.username)
            
            async with pool.acquire() as conn:
                sql_manager = SQLManager()
                query = sql_manager.load_query(query_category, query_name)
                
                # Get the record schema
                if enforce_column_structure:
                    statement = await conn.prepare(query)
                    attributes = statement.get_attributes()
                
                rows = await conn.fetch(query, *params)

                if enforce_column_structure:
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
        return_query_name: Optional[str] = None,
        return_params: Optional[List[Any]] = None
    ) -> Optional[Any]:
        """Execute a mutation query (INSERT, UPDATE, DELETE).
        
        Args:
            query_name: Name of the SQL file without extension
            query_category: Category/folder containing the SQL file
            params: List of parameters for single operation or list of parameter tuples for batch
            is_batch: If True, uses executemany for batch operations
            return_query_name: Optional name of query to execute after mutation to return relevant data
            return_params: Optional parameters for return query
            
        Returns:
            Optional[Any]: Result of return query if provided, None otherwise
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
                    if return_query_name and return_params is not None:
                        return_query = sql_manager.load_query(query_category, return_query_name)
                        # Replace the parameter placeholder with the array string if it's an array
                        if isinstance(return_params[0], str) and return_params[0].startswith('ARRAY['):
                            return_query = return_query.replace('$1', return_params[0])
                            return await conn.fetch(return_query)
                        else:
                            return await conn.fetch(return_query, *return_params)

                    return None

        except Exception as e:
            logger.error(f"TransactionRepository.{query_name}: Error executing mutation: {e}")
            logger.error(traceback.format_exc())
            raise

    # TODO: Adjust to return MemoTransaction objects instead of dictionaries
    async def get_account_memo_history(
        self,
        account_address: str,
        pft_only: bool = False,
        memo_type_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get transaction history with memos for an account using transaction_memos table.
        
        Args:
            account_address: XRPL account address to get history for
            pft_only: If True, only return transactions with PFT amounts. Defaults to False.
            memo_type_filter: Optional string to filter memo_types using LIKE. E.g. '%google_doc_context_link'
            
        Returns:
            List of dictionaries containing transaction history with memo details
        """ 
        params = [account_address, pft_only, memo_type_filter]

        return await self._execute_query(
            query_name='get_account_memo_history',
            query_category='xrpl',
            params=params,
            enforce_column_structure=True
        )
    
    # TODO: Adjust to return MemoTransaction objects instead of dictionaries
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
        order_by: str = "datetime ASC",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include_processed: bool = False
    ) -> List[MemoTransaction]:
        """Get transactions that haven't been processed yet.
        
        Args:
            order_by: SQL ORDER BY clause
            limit: Optional limit on number of transactions to return
            offset: Optional offset for pagination
            include_processed: If True, includes all transactions regardless of processing status
            
        Returns:
            List of MemoTransaction objects
        """
        params = [
            include_processed,
            order_by,
            offset,
            limit
        ]
        
        results = await self._execute_query(
            query_name='get_unprocessed_transactions',
            query_category='xrpl',
            params=params
        )
        
        return [MemoTransaction(**tx) for tx in results]
    
    async def get_reviewing_result(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get the reviewing result for a transaction if it exists
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            Dict containing the reviewing result if found, None otherwise
        """
        result = await self._execute_query(
            query_name='get_reviewing_result',
            query_category='xrpl',
            params=[tx_hash]
        )
        return result[0] if result else None

    async def store_reviewing_result(self, result: 'ReviewingResult') -> None:
        """Store the reviewing result for a transaction
        
        Args:
            result: ReviewingResult object containing transaction processing outcome
        """
        result_tx : MemoTransaction = result.tx
        params = [
            result_tx.hash,
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

    async def batch_insert_transactions(self, tx_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Batch insert raw XRPL transactions into postfiat_tx_cache.
        
        Args:
            tx_list: List of transaction dictionaries
            
        Returns:
            List[Dict[str, Any]]: List of inserted transaction details (hash and ledger_index)
        """
        if not tx_list:
            return []
        
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

        # Do batch insert and return inserted transactions
        result = await self._execute_mutation(
            query_name='insert_transaction',
            query_category='xrpl',
            params=params,
            is_batch=True,
            return_query_name='get_inserted_transactions',
            return_params=[hash_array]
        ) or []

        return [dict(row) for row in result]

    async def insert_transaction(self, tx: Dict[str, Any]) -> Optional[MemoTransaction]:
        """Insert a single transaction and return the processed record.
        
        Args:
            tx: Transaction dictionary to insert
            
        Returns:
            Optional[MemoTransaction]: Processed record if found, None if not found
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
            
            return MemoTransaction(**result[0]) if result and result[0]['hash'] is not None else None

        except Exception as e:
            logger.error(f"Error storing transaction: {e}")
            logger.error(traceback.format_exc())
            return None
        
    async def get_decoded_memo(self, tx_hash: str) -> Optional[MemoTransaction]:
        """Get a specific transaction with decoded memos by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            MemoTransaction object with decoded memos if found, None otherwise
        """
        result = await self._execute_query(
            query_name='get_decoded_memo',
            query_category='xrpl',
            params=[tx_hash]
        )
        
        return MemoTransaction(**result[0]) if result and result[0]['hash'] is not None else None
        
    async def get_decoded_memo_w_processing(self, tx_hash: str) -> Optional[MemoTransaction]:
        """Get a specific transaction with decoded memos and processing results by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            MemoTransaction object with decoded memos and processing results if found, None otherwise
        """
        result = await self._execute_query(
            query_name='get_decoded_memo_w_processing',
            query_category='xrpl',
            params=[tx_hash]
        )
        
        return MemoTransaction(**result[0]) if result and result[0]['hash'] is not None else None
    
    async def get_last_ledger_index(self, account: str) -> Optional[int]:
        """Get the last processed ledger index for an account.
        
        Args:
            account: XRPL account address
            
        Returns:
            The highest ledger_index processed for this account, or None if no transactions
        """
        results = await self._execute_query(
            query_name='get_last_ledger_index',
            query_category='xrpl',
            params=[account]
        )
        
        if results and results[0]['last_ledger'] is not None:
            return results[0]['last_ledger']
        return None

    # PFT HOLDERS AND BALANCES

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
    
    async def get_pft_holder(self, account: str) -> Optional[Dict[str, Any]]:
        """Get PFT holder data for a specific account from database.
        
        Args:
            account: XRPL account address
            
        Returns:
            Dictionary containing holder details or None if not found
        """
        results = await self._execute_query(
            query_name='get_pft_holder',
            query_category='xrpl',
            params=[account]
        )
        
        if not results:
            return None
            
        return {
            'balance': results[0]['balance'],
            'last_updated': results[0]['last_updated'],
            'last_tx_hash': results[0]['last_tx_hash']
        }
    
    async def update_pft_holder(
        self,
        account: str,
        balance: Decimal,
        last_tx_hash: Optional[str]
    ) -> None:
        """Update or create a PFT holder record with the specified balance.
        
        Args:
            account: XRPL account address
            balance: Current PFT balance
            last_tx_hash: Hash of the last known transaction, or None for new records
        """
        params = [account, balance, last_tx_hash]
        
        await self._execute_mutation(
            query_name='update_pft_holder',
            query_category='xrpl',
            params=params
        )

    # ENCRYPTION

    async def get_address_handshakes(
        self,
        channel_address: str,
        channel_counterparty: str
    ) -> List[Dict[str, Any]]:
        """Get handshake messages between two addresses.
        
        Args:
            channel_address: One end of the encryption channel
            channel_counterparty: The other end of the encryption channel
            
        Returns:
            List of dictionaries containing handshake details ordered by datetime descending
        """
        return await self._execute_query(
            query_name='get_address_handshakes',
            query_category='xrpl',
            params=[channel_address, channel_counterparty]
        )
    
    # AUTHORIZATION
    
    async def authorize_address(
        self,
        address: str,
        auth_source: str,
        auth_source_user_id: str
    ) -> None:
        """Authorize an address for node interaction.
        
        Args:
            address: XRPL address to authorize
            auth_source: Source of authorization (e.g. 'discord', 'twitter')
            auth_source_user_id: User ID from the auth source
        """
        params = [address, auth_source, auth_source_user_id]
        
        await self._execute_mutation(
            query_name='authorize_address',
            query_category='auth',
            params=params
        )

    async def deauthorize_addresses(
        self,
        auth_source: str,
        auth_source_user_id: str
    ) -> None:
        """Deauthorize all addresses for a given auth source user.
        
        Args:
            auth_source: Source of authorization (e.g. 'discord', 'twitter')
            auth_source_user_id: User ID from the auth source
        """
        params = [auth_source, auth_source_user_id]
        
        await self._execute_mutation(
            query_name='deauthorize_addresses',
            query_category='auth',
            params=params
        )

    async def flag_address(
        self,
        address: str,
        flag_type: str,
        yellow_flag_hours: int = 24,
        red_flag_hours: int = 240
    ) -> None:
        """Flag an address with either YELLOW or RED flag status.
        
        Args:
            address: XRPL address to flag
            flag_type: Either 'YELLOW' or 'RED'
            yellow_flag_hours: Number of hours for a yellow flag
            red_flag_hours: Number of hours for a red flag
        """
        if flag_type not in ('YELLOW', 'RED'):
            raise ValueError("flag_type must be either 'YELLOW' or 'RED'")
            
        params = [address, flag_type, str(yellow_flag_hours), str(red_flag_hours)]
        
        await self._execute_mutation(
            query_name='flag_address',
            query_category='auth',
            params=params
        )

    async def clear_address_flags(
        self,
        address: str,
    ) -> None:
        """Clear all flags for a specific address, regardless of expiration status.
        
        Args:
            address: XRPL address to clear flags for
        """
        params = [address]
        
        await self._execute_mutation(
            query_name='clear_address_flags',
            query_category='auth',
            params=params
        )

    async def is_address_authorized(self, account_address: str) -> bool:
        """Check if an address is authorized to interact with the node.
    
        Args:
            account_address: XRPL account address to check
            
        Returns:
            bool: True if address is authorized, False otherwise
        """
        # First clear any expired flags for the address' auth source user
        await self._execute_mutation(
            query_name='clear_expired_flags',
            query_category='auth',
            params=[]
        )

        # Then check if the address is authorized
        result = await self._execute_query(
            query_name='is_address_authorized',
            query_category='auth',
            params=[account_address]
        )
        return result[0]['is_authorized'] if result else False

    async def check_if_user_is_flagged(
        self,
        auth_source: str,
        auth_source_user_id: str
    ) -> bool:
        """Check if a user has any active flags.
        
        Args:
            auth_source: Source of authorization (e.g. 'discord', 'twitter')
            auth_source_user_id: User ID from the auth source
            
        Returns:
            Optional[Tuple[int, str]]: If flagged, returns (cooldown_seconds, flag_type), else None
        """
        # First clear any expired flags
        await self._execute_mutation(
            query_name='clear_expired_flags',
            query_category='auth',
            params=[]
        )
        
        # Then check for active flags
        result = await self._execute_query(
            query_name='check_if_user_is_flagged',
            query_category='auth',
            params=[auth_source, auth_source_user_id]
        )
        if result and result[0]['cooldown_seconds'] is not None:
            return (result[0]['cooldown_seconds'], result[0]['flag_type'])
        return None
    
    async def get_associated_addresses(self, address: str) -> list[str]:
        """Get all addresses associated with the same auth_source_user_id as the given address.
        
        Args:
            address: Any XRPL address belonging to the user
            
        Returns:
            list[str]: List of all addresses associated with the same user
        """
        params = [address]
        
        result = await self._execute_query(
            query_name='get_associated_addresses',
            query_category='auth',
            params=params
        )
        
        return [row['address'] for row in result]