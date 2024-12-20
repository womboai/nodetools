from typing import Dict, Any, Set, Optional
from loguru import logger
from nodetools.models.models import BusinessLogicProvider
from nodetools.protocols.transaction_repository import TransactionRepository
import traceback
import asyncio

from nodetools.utilities.transaction_orchestrator import ProcessingResult
from nodetools.utilities.transaction_orchestrator import TransactionReviewer

class ProcessorManager:

    @classmethod
    def create_from_business_logic(
        cls,
        repository: TransactionRepository,
        business_logic: BusinessLogicProvider
    ) -> 'ProcessorManager':
        """Factory method to create a ProcessorManager from a BusinessLogicProvider"""
        processor = TransactionReviewer(business_logic.rules, repository)
        return cls(repository, processor)

    def __init__(
            self,
            repository: TransactionRepository,
            processor: TransactionReviewer
    ):
        self.repository = repository
        self.processor = processor
        self._historical_queue = asyncio.Queue()
        self._realtime_queue = asyncio.Queue()

    async def queue_historical_transaction(self, tx: Dict[str, Any]):
        """Queue a historical transaction for processing"""
        await self._historical_queue.put(tx)

    async def queue_realtime_transaction(self, tx: Dict[str, Any]):
        """Queue a real-time transaction for processing"""
        await self._realtime_queue.put(tx)

    async def process_unverified_transactions(self) -> int:
        """
        Process historicalunverified transactions in chronological order.
        Returns number of transactions processed.
        """
        try:
            logger.debug(f"ProcessorManager.process_unverified_transactions: Processing unverified transactions...")
            # Get unverified transactions ordered by timestamp
            unverified_txs = await self.repository.get_unverified_transactions(
                order_by="close_time_iso ASC",
                include_processed=True   # NOTE: This is a temporary measure for debugging
            )
            
            if not unverified_txs:
                logger.info("No unverified transactions found")
                return 0

            # Queue all historical transactions
            for tx in unverified_txs:
                await self.queue_historical_transaction(tx)

            # Process all historical transactions
            processed_count = 0
            while not self._historical_queue.empty():
                tx = await self._historical_queue.get()
                
                try:
                    result = await self.processor.review_transaction(tx)
                    await self.repository.store_processing_result(tx['hash'], result)
                    processed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing transaction {tx['hash']}: {e}")
                    # Store error result
                    error_result = ProcessingResult(
                        processed=True,  # Mark as processed to avoid reprocessing
                        rule_name="ERROR",
                        notes=str(e)
                    )
                    await self.repository.store_processing_result(tx['hash'], error_result)
                    processed_count += 1

            return processed_count

        except Exception as e:
            logger.error(f"Error in process_unverified_transactions: {e}")
            logger.error(traceback.format_exc())
            raise
