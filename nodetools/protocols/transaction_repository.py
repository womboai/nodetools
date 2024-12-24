from typing import Protocol, TYPE_CHECKING, List, Dict, Any, Optional

if TYPE_CHECKING:
    from nodetools.utilities.transaction_orchestrator import ReviewingResult

class TransactionRepository(Protocol):
    """Protocol for transaction repository"""

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
        ...

    async def reprocess_transactions(
        self,
        tx_hashes: List[str]
    ) -> None:
        """
        Remove processing results for specified transactions so they can be reprocessed.
        
        Args:
            tx_hashes: List of transaction hashes to reprocess
        """
        ...

    async def store_reviewing_result(self, tx_hash: str, result: 'ReviewingResult') -> None:
        """Store the reviewing result for a transaction"""
        ...

    async def get_processing_results(
        self,
        rule_name: Optional[str] = None,
        processed: Optional[bool] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get processing results with optional filters.
        
        Args:
            rule_name: Filter by specific rule
            processed: Filter by processed status
            limit: Limit number of results
        """
        ...

    async def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a custom query with parameters.
        
        Args:
            query: SQL query string
            params: Optional dictionary of query parameters
            
        Returns:
            List of dictionaries containing query results
        """
        ...
    
    async def insert_transaction(self, tx_message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a single transaction and return the processed record"""
        ...

    async def get_decoded_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get a specific transaction with decoded memos by hash.
        
        Args:
            tx_hash: The transaction hash to look up
            
        Returns:
            Dict containing transaction data with decoded memos if found, None otherwise
        """
        ...