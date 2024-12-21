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
from nodetools.task_processing.task_management_rules import create_business_logic, BusinessLogicProvider
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
    def __init__(self, business_logic: BusinessLogicProvider, repository: TransactionRepository):
        self.graph = business_logic.transaction_graph
        self.pattern_rule_map = business_logic.pattern_rule_map
        self.repository = repository

    async def review_transaction(self, tx: Dict[str, Any]) -> ProcessingResult:
        """Review a single transaction against all rules"""

        # # Only debug for specific transaction
        # debug_hash = "B365144B26EB46686ED700F78E30B26316C59F18BB5CA628A166772F4E0F200E"
        # is_debug_tx = tx.get('hash') == debug_hash

        # if is_debug_tx:
        #     logger.debug(f"Reviewing transaction {debug_hash}")
        #     logger.debug(f"Transaction memo_type: {tx.get('memo_type')}")

        # First find matching pattern
        pattern_id = self.graph.find_matching_pattern(tx)

        # if is_debug_tx:
        #     logger.debug(f"Found matching pattern_id: {pattern_id}")

        if not pattern_id:
            return ProcessingResult(
                processed=True,  # We've reviewed it and found no matching pattern
                rule_name="NoRule",
                notes="No matching pattern found"
            )
        
        pattern = self.graph.patterns[pattern_id]

        # if is_debug_tx:
        #     logger.debug(f"Found pattern: {pattern}")

        # Get the corresponding rule for this pattern
        rule = self.pattern_rule_map[pattern_id]
        if not rule:
            logger.error(f"No rule found for pattern_id: {pattern_id}")
            return ProcessingResult(
                processed=True,
                rule_name="NoRule",
                notes=f"No rule found for pattern {pattern_id}"
            )

        try:

            if await rule.validate(tx):  # Pure business rule validation
                
                # if is_debug_tx:
                #     logger.debug(f"Rule {rule.__class__.__name__} validated transaction")

                # Process based on the pattern's transaction type
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

                            # # DEBUGGING
                            # if is_debug_tx:
                            #     logger.debug(f"No response found for tx {tx['hash']} using rule {rule.__class__.__name__}")
                            #     logger.debug(f"Response query for rule {rule.__class__.__name__}: {response_query.query}")
                            #     logger.debug(f"Response params for rule {rule.__class__.__name__}: {response_query.params}")

                            return ProcessingResult(
                                processed=False,  # We've reviewed it and found no response
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
                    
            else:
                # Rule validation failed
                return ProcessingResult(
                    processed=True,  # We've reviewed it and determined it failed validation
                    rule_name=rule.__class__.__name__,
                    notes=f"Failed validation for rule {rule.__class__.__name__}"
                )

        except Exception as e:
            logger.error(f"Error processing rule {rule.__class__.__name__}: {e}")
            logger.error(traceback.format_exc())
    
@dataclass
class ResponseRoutingResult:
    """Represents the result of determining the appropriate response pattern for a transaction"""
    success: bool
    pattern_id: str
    notes: Optional[str] = None

class TransactionResponseManager:
    """
    Manages the routing of transactions that need responses to appropriate processing queues.
    Also tracks pending responses and triggers re-review when responses are confirmed.
    """
    def __init__(self, business_logic: BusinessLogicProvider, review_queue: asyncio.Queue):
        self.graph = business_logic.transaction_graph
        self.pattern_rule_map = business_logic.pattern_rule_map
        self._shutdown = False
        self.review_queue = review_queue

        # Track pending responses and their review queues
        self.pending_responses: Dict[str, Dict[str, Any]] = {}  # tx_hash -> original_tx

        # Create queues based on response patterns from rules
        self.response_queues: Dict[str, asyncio.Queue] = self._initialize_response_queues()
        self.processing_counts: Dict[str, int] = {
            pattern_id: 0 for pattern_id in self.response_queues.keys()
        }

    def _initialize_response_queues(self) -> Dict[str, asyncio.Queue]:
        """Initialize queues based on response patterns in business rules"""
        response_patterns: Dict[str, asyncio.Queue] = {}

        # Create a queue for each RESPONSE type pattern in the graph
        for pattern_id, pattern in self.graph.patterns.items():
            if pattern.transaction_type == TransactionType.RESPONSE:
                logger.debug(f"TransactionResponseManager: Adding response queue for pattern '{pattern_id}'")
                response_patterns[pattern_id] = asyncio.Queue()
    
        return response_patterns
    
    async def route_transaction(self, tx: Dict[str, Any]) -> bool:
        """Route transaction to appropriate response queue based on its matching rule"""
        try:
            result = await self._determine_response_pattern(tx)
            if result.success:
                # Store original transaction before routing
                self.pending_responses[tx['hash']] = tx

                # Route transaction to appropriate response queue
                await self.response_queues[result.pattern_id].put(tx)
                logger.debug(f"Routed transaction {tx['hash']} to {result.pattern_id} queue")
                return True
            return False

        except Exception as e:
            logger.error(f"Error routing transaction {tx['hash']}: {e}")
            logger.error(traceback.format_exc())
            return False
        
    async def _determine_response_pattern(self, tx: Dict[str, Any]) -> ResponseRoutingResult:
        """
        Determines which response queue a transaction should be routed to.
        
        Flow:
        1. Find the request pattern that matches this transaction
        2. Get its first valid response pattern
        3. Convert that response pattern to a pattern ID for queue routing
        
        Returns:
            ResponseRoutingResult with:
            - success: Whether a valid response queue was found
            - pattern_id: The pattern ID of the response queue to use
            - notes: Additional context about the routing decision
        """
        # First find matching pattern in graph
        request_pattern_id = self.graph.find_matching_pattern(tx)
        if not request_pattern_id:
            return ResponseRoutingResult(
                success=False,
                pattern_id="unknown",
                notes="No matching request pattern found"
            )
        
        request_pattern = self.graph.patterns[request_pattern_id]
        
        # Verify it's a request type pattern
        if request_pattern.transaction_type != TransactionType.REQUEST:
            return ResponseRoutingResult(
                success=False,
                pattern_id="unknown",
                notes=f"Pattern {request_pattern_id} is not a request type"
            )
    
        # Get the first valid response pattern
        response_pattern = next(iter(request_pattern.valid_responses))
        response_pattern_id = self.graph.get_pattern_id_by_memo_pattern(response_pattern)

        if not response_pattern_id:
            return ResponseRoutingResult(
                success=False,
                pattern_id="unknown",
                notes="Could not find response pattern ID"
            )

        return ResponseRoutingResult(
            success=True,
            pattern_id=response_pattern_id,
            notes=f"Transaction will be routed to {response_pattern_id} queue"
        )
    
    async def confirm_response_sent(self, request_tx_hash: str):
        """
        Called by response consumers after successfully submitting a response.
        Triggers re-review of the original transaction.
        """
        if request_tx_hash in self.pending_responses:
            original_tx = self.pending_responses.pop(request_tx_hash)
            await self.review_queue.put(original_tx)
            logger.debug(f"Re-queued transaction {request_tx_hash} for review after response")
    
    def get_queue_sizes(self) -> Dict[str, int]:
        """Get current size of all response queues"""
        return {
            pattern_id: queue.qsize() 
            for pattern_id, queue in self.response_queues.items()
        }

    def stop(self):
        """Stop the response manager"""
        self._shutdown = True

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
        self.review_queue = asyncio.Queue()     # Queue for transactions needing review
        self.routing_queue = asyncio.Queue()    # Queue for transactions needing responses
        self.reviewer: TransactionReviewer = None  # will be initialized in start()
        self.response_manager: TransactionResponseManager = None  # will be initialized in start()

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
        instance.response_manager = TransactionResponseManager(business_logic.rules)
        return instance

    async def start(self):
        """Coordinate transaction processing"""
        try:
            if not self.reviewer:
                self.reviewer = TransactionReviewer(
                    business_logic=create_business_logic(),
                    repository=self.transaction_repository
                )
            if not self.response_manager:
                self.response_manager = TransactionResponseManager(
                    business_logic=create_business_logic(),
                    review_queue=self.review_queue
                )

            # Start websocket with review queue
            self.generic_pft_utilities.xrpl_monitor.start(queue=self.review_queue)

            # Sync and process historical data
            self.generic_pft_utilities.sync_pft_transaction_history()
            
            # Get unverified transactions and add them to review queue
            logger.debug("TransactionOrchestrator: Getting unverified transactions")
            unverified_txs = await self.transaction_repository.get_unverified_transactions(
                order_by="close_time_iso ASC",
                include_processed=False   # For debugging only
            )
            logger.debug(f"TransactionOrchestrator: Found {len(unverified_txs)} unverified transactions")

            for tx in unverified_txs:
                await self.review_queue.put(tx)

            # Start review and processing tasks
            logger.debug("TransactionOrchestrator: Starting review task")
            review_task = asyncio.create_task(self._review_loop())
            logger.debug("TransactionOrchestrator: Starting processing task")
            processing_task = asyncio.create_task(self._route_loop())

            try:
                await asyncio.gather(review_task, processing_task)
            except asyncio.CancelledError:
                logger.info("TransactionOrchestrator: Received shutdown signal")
                # Cancel child tasks
                review_task.cancel()
                processing_task.cancel()
                # Wait for tasks to complete
                await asyncio.gather(review_task, processing_task, return_exceptions=True)
                logger.info("TransactionOrchestrator: Shutdown complete")

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

        try:
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
                        await self.routing_queue.put(tx)

                    # Log progress if interval elapsed
                    current_time = time.time()
                    if current_time - last_log_time > LOG_INTERVAL:
                        queue_size = self.review_queue.qsize()
                        logger.info(f"TransactionOrchestrator: Progress: {reviewed_count} transactions reviewed. Current queue size: {queue_size}")
                        last_log_time = current_time

                except asyncio.TimeoutError:
                    current_time = time.time()
                    idle_duration = current_time - last_activity_time
                    logger.info(f"TransactionOrchestrator: Review loop idle for {self.format_duration(idle_duration)}. Total reviewed: {reviewed_count}")
                    continue
                    
                except Exception as e:
                    logger.error(f"Error reviewing transaction: {e}")
                    logger.error(traceback.format_exc())
        finally:
            logger.debug("TransactionOrchestrator: Review loop shutdown complete")

    async def _route_loop(self):
        """Continuously route transactions that need responses"""
        routed_count = 0
        last_log_time = time.time()
        last_activity_time = time.time()
        LOG_INTERVAL = 60  # Log progress every minute
        IDLE_LOG_INTERVAL = 300  # Log idle status every 5 minutes

        try:
            while not self._shutdown:
                try:
                    # Wait for next transaction with timeout
                    tx = await asyncio.wait_for(self.routing_queue.get(), timeout=IDLE_LOG_INTERVAL)
                    
                    # Route transaction to appropriate response queue
                    routed = await self.response_manager.route_transaction(tx)
                    if routed:
                        routed_count += 1
                        last_activity_time = time.time()

                    # Log progress if interval elapsed
                    current_time = time.time()
                    if current_time - last_log_time > LOG_INTERVAL:
                        queue_size = self.routing_queue.qsize()
                        pending_count = len(self.response_manager.pending_responses)
                        response_queue_sizes = self.response_manager.get_queue_sizes()
                        logger.info(
                            f"TransactionOrchestrator: Progress update:\n"
                            f"  - Total routed: {routed_count}\n"
                            f"  - Routing queue size: {queue_size}\n"
                            f"  - Pending responses: {pending_count}\n"
                            f"  - Response queue sizes: {response_queue_sizes}"
                        )
                        last_log_time = current_time

                except asyncio.TimeoutError:
                    current_time = time.time()
                    idle_duration = current_time - last_activity_time
                    pending_count = len(self.response_manager.pending_responses)
                    logger.info(
                        f"TransactionOrchestrator: Process loop idle for {self.format_duration(idle_duration)}.\n"
                        f"  - Total routed: {routed_count}\n"
                        f"  - Pending responses: {pending_count}"
                    )
                    continue
                    
                except Exception as e:
                    logger.error(f"Error processing transaction: {e}")
                    logger.error(traceback.format_exc())
        finally:
            logger.debug("TransactionOrchestrator: Route loop shutdown complete")

    def stop(self):
        """Stop state management process"""
        logger.info("NodeToolsStateManager: Stopping state management")
        self._shutdown = True

    def format_duration(self, seconds: float) -> str:
        """Format a duration in H:m:s format"""
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"