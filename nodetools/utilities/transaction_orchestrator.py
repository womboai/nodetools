"""
Orchestrates the processing of both historical and real-time XRPL transactions,
ensuring proper sequencing and consistency of transaction processing.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import asyncio
from loguru import logger
from nodetools.models.models import TransactionRule, TransactionType
from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
from nodetools.protocols.transaction_repository import TransactionRepository
from nodetools.task_processing.task_management_rules import create_business_logic
import traceback
import time

@dataclass
class ProcessingResult:
    """Represents the outcome of processing a single transaction"""
    processed: bool
    rule_name: str
    response_tx_hash: Optional[str] = None
    notes: Optional[str] = None

class TransactionReviewer:
    """
    Handles the core logic of reviewing individual transactions against business rules.
    This is the lowest level component that actually applies business logic to transactions.
    """
    def __init__(self, rules: List[TransactionRule], repository: TransactionRepository):
        self.rules = rules
        self.repository = repository

    async def review_transaction(self, tx: Dict[str, Any]) -> ProcessingResult:
        """Review a single transaction against all rules"""
        for rule in self.rules:
            try:
                # 1. Check if transaction matches rule's criteria
                if await rule.matches(tx):

                    # 2. Get the pattern ID and configuration
                    pattern_id = rule.get_pattern_id(tx)
                    if not pattern_id:
                        return ProcessingResult(
                            processed=True,  # We've reviewed it and found no matching pattern
                            rule_name=rule.__class__.__name__,
                            notes="Matched rule but no matching pattern found"
                        )

                    pattern = rule.transaction_graph.patterns[pattern_id]

                    # 3. Check if response is required
                    match pattern.transaction_type:

                        # Response or standalone transactions don't need responses
                        case TransactionType.RESPONSE | TransactionType.STANDALONE:
                            return ProcessingResult(
                                processed=True, 
                                rule_name=rule.__class__.__name__,
                                notes=f"Processed {pattern.transaction_type.value} transaction"
                            )
                        
                        # Request transactions need responses
                        case TransactionType.REQUEST:
                            # 4. Get response query and execute it
                            response_query = await rule.find_response(tx)
                            result = await self.repository.execute_query(
                                response_query.query,
                                response_query.params
                            )
                            response_tx = result[0] if result else None

                            if not response_tx:
                                logger.debug(f"No response found for tx {tx['hash']} using rule {rule.__class__.__name__}")
                                logger.debug(f"Response query for rule {rule.__class__.__name__}: {response_query.query}")
                                logger.debug(f"Response params for rule {rule.__class__.__name__}: {response_query.params}")

                                return ProcessingResult(
                                    processed=False,
                                    rule_name=rule.__class__.__name__,
                                    notes="Required response not found"
                                )

                            # 5. Response found
                            return ProcessingResult(
                                processed=True,  # We've reviewed it and found the required response
                                rule_name=rule.__class__.__name__,
                                response_tx_hash=response_tx.get("hash"),
                                notes="Response found"
                            )

            except Exception as e:
                logger.error(f"Error processing rule {rule.__class__.__name__}: {e}")
                logger.error(traceback.format_exc())
                continue

        # No matching rules found
        return ProcessingResult(
            processed=True,  # We've reviewed it and found it doesn't match any rules
            rule_name="NoRule",
            notes="No matching rules found"
        )

class TransactionOrchestrator:
    """
    Coordinates the entire transaction processing pipeline, including:
    - Historical data synchronization
    - Real-time transaction monitoring
    - Transaction verification
    - Sequential processing of transactions
    """
    def __init__(
            self, 
            generic_pft_utilities: GenericPFTUtilities, 
            transaction_repository: TransactionRepository
    ):
        self.generic_pft_utilities = generic_pft_utilities
        self.transaction_repository = transaction_repository
        self._shutdown = False
        self.review_queue = asyncio.Queue()         # Queue for transactions needing review
        self.processing_queue = asyncio.Queue()    # Queue for transactions needing responses
        self.reviewer = None  # will be initialized in start()

    @classmethod
    def create_from_business_logic(
        cls,
        generic_pft_utilities: GenericPFTUtilities,
        transaction_repository: TransactionRepository
    ) -> 'TransactionOrchestrator':
        """Factory method to create an Orchestrator with business logic"""
        instance = cls(generic_pft_utilities, transaction_repository)
        business_logic = create_business_logic()
        instance.reviewer = TransactionReviewer(business_logic.rules, transaction_repository)
        return instance

    # async def process_unverified_transactions(self) -> int:
    #     """Process historical unverified transactions"""
    #     try:
    #         logger.info("TransactionOrchestrator: Processing unverified transactions...")
    #         unverified_txs = await self.transaction_repository.get_unverified_transactions(
    #             order_by="close_time_iso ASC",
    #             include_processed=False
    #         )

    #         if not unverified_txs:
    #             logger.debug("TransactionOrchestrator: No unverified transactions found")
    #             return 0 
            
    #         total_txs = len(unverified_txs)
    #         logger.info(f"TransactionOrchestrator: Found {total_txs} transactions to review")

    #         processed_count = 0
    #         for tx in unverified_txs:
    #             try:
    #                 result = await self.reviewer.review_transaction(tx)
    #                 await self.transaction_repository.store_processing_result(tx['hash'], result)
    #                 processed_count += 1

    #                 # if result.processed is False, add to queue for processing
    #                 if not result.processed:
    #                     await self.processing_queue.put(tx)

    #                 # Log progress every 100 transactions
    #                 if processed_count % 100 == 0:
    #                     progress = (processed_count / total_txs) * 100
    #                     logger.debug(f"Progress {progress:.1f}% - Reviewed {processed_count}/{total_txs} transactions")

    #             except Exception as e:
    #                 logger.error(f"TransactionOrchestrator: Error processing transaction {tx['hash']}: {e}")
    #                 # Store error result
    #                 error_result = ProcessingResult(
    #                     processed=True,  # Mark as processed to avoid reprocessing
    #                     rule_name="ERROR",
    #                     notes=str(e)
    #                 )
    #                 await self.transaction_repository.store_processing_result(tx['hash'], error_result)
    #                 processed_count += 1

    #         return processed_count
        
    #     except Exception as e:
    #         logger.error(f"TransactionOrchestrator: Error processing unverified transactions: {e}")
    #         logger.error(traceback.format_exc())
    #         raise

    async def start(self):
        """Coordinate transaction processing"""
        try:
            # Initialize reviewer if not already done
            if not self.reviewer:
                self.reviewer = TransactionReviewer(
                    rules=create_business_logic().rules,
                    repository=self.transaction_repository
                )

            # Start websocket with review queue
            self.generic_pft_utilities.xrpl_monitor.start(queue=self.review_queue)

            # Sync and process historical data
            logger.info("TransactionOrchestrator: Beginning historical data sync")
            self.generic_pft_utilities.sync_pft_transaction_history()
            
            # Get unverified transactions and add them to review queue
            unverified_txs = await self.transaction_repository.get_unverified_transactions(
                order_by="close_time_iso ASC",
                include_processed=False
            )
            for tx in unverified_txs:
                await self.review_queue.put(tx)

            # Start review and processing tasks
            review_task = asyncio.create_task(self._review_loop())
            processing_task = asyncio.create_task(self._process_loop())

            await asyncio.gather(review_task, processing_task)

        except Exception as e:
            logger.error(f"TransactionOrchestrator: Error in transaction processing: {e}")
            logger.error(traceback.format_exc())
            raise

    async def _review_loop(self):
        """Continuously review transactions from the review queue"""
        reviewed_count = 0
        last_log_time = time.time()
        last_activity_time = time.time()
        LOG_INTERVAL = 60  # Log progress every minute
        IDLE_LOG_INTERVAL = 300  # Log idle status every 5 minutes

        while not self._shutdown:
            try:
                # Wait for next transaction with timeout
                tx = await asyncio.wait_for(self.review_queue.get(), timeout=IDLE_LOG_INTERVAL)
                
                result = await self.reviewer.review_transaction(tx)
                await self.transaction_repository.store_processing_result(tx['hash'], result)
                reviewed_count += 1
                last_activity_time = time.time()

                # If transaction needs a response, add to processing queue
                if not result.processed:
                    await self.processing_queue.put(tx)

                # Log progress if interval elapsed
                current_time = time.time()
                if current_time - last_log_time > LOG_INTERVAL:
                    queue_size = self.review_queue.qsize()
                    logger.info(f"TransactionOrchestrator: Progress: {reviewed_count} transactions reviewed. Current queue size: {queue_size}")
                    last_log_time = current_time

            except asyncio.TimeoutError:
                current_time = time.time()
                idle_duration = current_time - last_activity_time
                logger.info(f"TransactionOrchestrator: Review loop idle for {idle_duration:.1f} seconds. Total reviewed: {reviewed_count}")
                continue
                
            except Exception as e:
                logger.error(f"Error reviewing transaction: {e}")
                logger.error(traceback.format_exc())

    async def _process_loop(self):
        """Continuously process transactions that need responses"""
        processed_count = 0
        last_log_time = time.time()
        last_activity_time = time.time()
        LOG_INTERVAL = 60  # Log progress every minute
        IDLE_LOG_INTERVAL = 300  # Log idle status every 5 minutes

        while not self._shutdown:
            try:
                # Wait for next transaction with timeout
                tx = await asyncio.wait_for(self.processing_queue.get(), timeout=IDLE_LOG_INTERVAL)
                
                # TODO: Implement response generation and submission

                processed_count += 1
                last_activity_time = time.time()

                # Log progress if interval elapsed
                current_time = time.time()
                if current_time - last_log_time > LOG_INTERVAL:
                    queue_size = self.processing_queue.qsize()
                    logger.info(f"TransactionOrchestrator: Progress: {processed_count} transactions processed. Current queue size: {queue_size}")
                    last_log_time = current_time

            except asyncio.TimeoutError:
                current_time = time.time()
                idle_duration = current_time - last_activity_time
                logger.info(f"TransactionOrchestrator: Process loop idle for {idle_duration:.1f} seconds. Total processed: {processed_count}")
                continue
                
            except Exception as e:
                logger.error(f"Error processing transaction: {e}")
                logger.error(traceback.format_exc())
                
    def stop(self):
        """Stop state management process"""
        logger.info("NodeToolsStateManager: Stopping state management")
        self._shutdown = True
