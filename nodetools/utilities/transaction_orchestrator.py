"""
Orchestrates the processing of both historical and real-time XRPL transactions,
ensuring proper sequencing and consistency of transaction processing.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import asyncio
from loguru import logger
from nodetools.models.models import (
    ResponseRule, 
    TransactionType, 
    TransactionPattern, 
    ResponseGenerator, 
    ResponseParameters,
    Dependencies
)
from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
from nodetools.protocols.transaction_repository import TransactionRepository
from nodetools.protocols.credentials import CredentialManager
from nodetools.protocols.openrouter import OpenRouterTool
from nodetools.configuration.configuration import NodeConfig
from nodetools.task_processing.task_management_rules import create_business_logic, BusinessLogicProvider
import traceback
import time
from datetime import datetime

def format_duration(seconds: float) -> str:
    """Format a duration in H:m:s format"""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

@dataclass
class ReviewingResult:
    """Represents the outcome of reviewing a single transaction"""
    processed: bool
    rule_name: str
    response_tx_hash: Optional[str] = None
    notes: Optional[str] = None
    needs_rereview: bool = False

class TransactionReviewer:
    """
    Handles the core logic of reviewing individual transactions against business rules.
    This is the lowest level component that actually applies business logic to transactions.
    """
    def __init__(self, business_logic: BusinessLogicProvider, repository: TransactionRepository):
        self.graph = business_logic.transaction_graph
        self.pattern_rule_map = business_logic.pattern_rule_map
        self.repository = repository

    async def review_transaction(self, tx: Dict[str, Any]) -> ReviewingResult:
        """Review a single transaction against all rules"""

        # logger.debug(f"Reviewing transaction {tx}")

        # tx_summary = {
        #     'hash': tx.get('hash'),
        #     'pft_amount': tx.get('pft_absolute_amount'),
        #     'xrp_fee': int(tx.get('fee', '0'))/1000000,  # Convert drops to XRP
        #     'account': tx.get('account'),
        #     'destination': tx.get('destination'),
        #     'memo_format': tx.get('memo_format'),
        #     'memo_type': tx.get('memo_type'),
        #     'memo_data': tx.get('memo_data')
        # }
        # logger.debug(f"Reviewing transaction: {tx_summary}")

        # First find matching pattern
        pattern_id = self.graph.find_matching_pattern(tx)

        # logger.debug(f"Found matching pattern_id: {pattern_id}")

        if not pattern_id:
            return ReviewingResult(
                processed=True,  # We've reviewed it and found no matching pattern
                rule_name="NoRule",
                notes="No matching pattern found"
            )
        
        pattern = self.graph.patterns[pattern_id]

        # logger.debug(f"Found pattern: {pattern}")

        # Get the corresponding rule for this pattern
        rule = self.pattern_rule_map[pattern_id]
        if not rule:
            logger.error(f"No rule found for pattern_id: {pattern_id}")
            return ReviewingResult(
                processed=True,
                rule_name="NoRule",
                notes=f"No rule found for pattern {pattern_id}"
            )

        try:

            if await rule.validate(tx):  # Pure business rule validation
                
                # logger.debug(f"Rule {rule.__class__.__name__} validated transaction")

                # Process based on the pattern's transaction type
                match pattern.transaction_type:
                    # Response or standalone transactions don't need responses
                    case TransactionType.RESPONSE | TransactionType.STANDALONE:
                        # logger.debug(f"Processed '{pattern.transaction_type.value}' transaction. No action required.")

                        return ReviewingResult(
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

                        # logger.debug(f"Response query for rule {rule.__class__.__name__}: {response_query.query}")
                        # logger.debug(f"Response params for rule {rule.__class__.__name__}: {response_query.params}")

                        if not response_tx:

                            # DEBUGGING
                            # logger.debug(f"No response found for tx {tx['hash']} using rule {rule.__class__.__name__}. Marking as unprocessed.")

                            return ReviewingResult(
                                processed=False,  # We've reviewed it and found no response
                                rule_name=rule.__class__.__name__,
                                notes="Required response not found",
                                needs_rereview=True
                            )

                        # logger.debug(f"Response found for tx {tx['hash']} using rule {rule.__class__.__name__}. No action required.")

                        # 5. Response found
                        return ReviewingResult(
                            processed=True,  # We've reviewed it and found the required response
                            rule_name=rule.__class__.__name__,
                            response_tx_hash=response_tx.get("hash"),
                            notes="Response found"
                        )
                    
            else:
                # Rule validation failed
                # logger.debug(f"Rule {rule.__class__.__name__} failed validation for transaction {tx['hash']}. No action required.")

                return ReviewingResult(
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

@dataclass
class QueueConfig:
    """Configuration for a response queue and its generator"""
    queue: asyncio.Queue
    pattern: TransactionPattern
    rule: ResponseRule

class ResponseQueueRouter:
    """
    Manages the routing of transactions that need responses to appropriate processing queues.
    Also tracks pending responses and triggers re-review when responses are confirmed.
    """
    def __init__(
            self, 
            business_logic: BusinessLogicProvider, 
            review_queue: asyncio.Queue,
            transaction_repository: TransactionRepository,
            shutdown_event: asyncio.Event
        ):
        self.graph = business_logic.transaction_graph
        self.pattern_rule_map = business_logic.pattern_rule_map
        self.review_queue = review_queue
        self.transaction_repository = transaction_repository
        self._shutdown_event = shutdown_event

        # Track pending responses and their review queues
        self.pending_responses: Dict[str, Dict[str, Any]] = {}  # tx_hash -> original_tx

        # Add pending re-reviews tracking
        self.pending_rereviews: Dict[str, Dict[str, Any]] = {}
        self.MAX_RETRY_COUNT = 10
        self.RETRY_DELAY = 5  # seconds

        # Initialize queue configurations
        self.queue_configs: Dict[str, QueueConfig] = self._initialize_queue_configs()
        self.processing_counts: Dict[str, int] = {
            pattern_id: 0 for pattern_id in self.queue_configs.keys()
        }

        # Start retry task
        self.retry_task = asyncio.create_task(self._retry_pending_reviews())

    def _initialize_queue_configs(self) -> Dict[str, asyncio.Queue]:
        """Initialize queue configurations based on response patterns in business rules"""
        configs: Dict[str, QueueConfig] = {}

        # Create a queue for each RESPONSE type pattern in the graph
        for pattern_id, pattern in self.graph.patterns.items():
            if pattern.transaction_type == TransactionType.RESPONSE:
                rule = self.pattern_rule_map[pattern_id]
                if isinstance(rule, ResponseRule):
                    configs[pattern_id] = QueueConfig(
                        queue=asyncio.Queue(),
                        pattern=pattern,
                        rule=rule
                    )
                    logger.debug(f"TransactionResponseManager: Adding queue config for pattern '{pattern_id}'")
    
        return configs
    
    def get_queue_config(self, pattern_id: str) -> Optional[QueueConfig]:
        """Get the queue configuration for a given pattern ID"""
        return self.queue_configs.get(pattern_id)
    
    def get_all_queue_configs(self) -> Dict[str, QueueConfig]:
        """Get all queue configurations"""
        return self.queue_configs
    
    async def route_transaction(self, tx: Dict[str, Any]) -> bool:
        """Route transaction to appropriate response queue based on its matching rule"""
        try:
            result = await self._determine_response_pattern(tx)
            if result.success:
                # Store original transaction before routing
                self.pending_responses[tx['hash']] = tx

                # Route transaction to appropriate response queue
                await self.queue_configs[result.pattern_id].queue.put(tx)
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
        """Queue transaction for re-review with retry mechanism"""
        if request_tx_hash in self.pending_responses:
            original_tx = self.pending_responses.pop(request_tx_hash)
            
            # Add to pending re-reviews with retry count
            self.pending_rereviews[request_tx_hash] = {
                'tx': original_tx,
                'retries': 0,
                'next_retry': time.time() + self.RETRY_DELAY
            }
            logger.debug(f"Queued {request_tx_hash} for re-review with retries")
    
    async def _retry_pending_reviews(self):
        """Background task to retry pending re-reviews"""
        while not self._shutdown_event.is_set():
            try:
                current_time = time.time()
                
                # Get all transactions that need retry
                for tx_hash, info in list(self.pending_rereviews.items()):
                    if current_time >= info['next_retry']:
                        try:
                            # Check if specific transaction exists in decoded_memos view
                            tx = await self.transaction_repository.get_decoded_transaction(tx_hash)
                            
                            if tx:
                                # Found in database with decoded memos, queue for review
                                await self.review_queue.put(tx)  # Use the complete decoded transaction
                                logger.debug(f"Re-queued transaction {tx_hash} for review after {info['retries']} retries")
                                self.pending_rereviews.pop(tx_hash)
                            else:
                                # Not found, increment retry count
                                info['retries'] += 1
                                if info['retries'] >= self.MAX_RETRY_COUNT:
                                    logger.warning(f"Max retries reached for {tx_hash}, giving up")
                                    self.pending_rereviews.pop(tx_hash)
                                else:
                                    # Schedule next retry with exponential backoff
                                    info['next_retry'] = current_time + (self.RETRY_DELAY * (2 ** info['retries']))
                                    logger.debug(f"Scheduling retry {info['retries']} for {tx_hash}")
                        
                        except Exception as e:
                            logger.error(f"Error during retry for {tx_hash}: {e}")
                            logger.error(traceback.format_exc())
                
                # Sleep briefly to prevent busy-waiting
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Error in retry loop: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5.0)  # Longer sleep on error
    
    def get_queue_sizes(self) -> Dict[str, int]:
        """Get current size of all response queues"""
        return {
            pattern_id: config.queue.qsize() 
            for pattern_id, config in self.queue_configs.items()
        }

class ResponseProcessor:
    """Queue consumer that generates and submits responses to transactions.
    
    Handles the core consume-evaluate-respond loop while delegating the actual
    response generation to a ResponseGenerator provided by the rule.
    """
    def __init__(
            self,
            queue: asyncio.Queue,
            response_manager: ResponseQueueRouter,
            generator: ResponseGenerator,
            credential_manager: CredentialManager,
            generic_pft_utilities: GenericPFTUtilities,
            shutdown_event: asyncio.Event,
            pattern_id: str
        ):
        self.queue = queue
        self.response_manager = response_manager
        self.generator = generator
        self.credential_manager = credential_manager
        self.generic_pft_utilities = generic_pft_utilities
        self._shutdown_event = shutdown_event
        self.pattern_id = pattern_id
        self.processed_count = 0
        self.last_log_time = time.time()
        self.last_activity_time = time.time()
        self.LOG_INTERVAL = 60  # Log progress every minute
        self.IDLE_LOG_INTERVAL = 300  # Log idle status every 5 minutes

    async def run(self):
        """Process transactions from the queue until shutdown"""
        while not self._shutdown_event.is_set():
            try:
                # Get transaction from queue
                tx = await asyncio.wait_for(self.queue.get(), timeout=1.0)

                # Process the transaction
                success = await self._process_transaction(tx)

                if success:
                    self.processed_count += 1
                    self.last_activity_time = time.time()
                    await self.response_manager.confirm_response_sent(tx['hash'])

                self.queue.task_done()

                # Log progress if interval elapsed
                current_time = time.time()
                if current_time - self.last_log_time > self.LOG_INTERVAL:
                    queue_size = self.queue.qsize()
                    logger.info(
                        f"Consumer_{self.pattern_id}: "
                        f"Processed {self.processed_count} transactions. "
                        f"Current queue size: {queue_size}"
                    )
                    self.last_log_time = current_time

            except asyncio.TimeoutError:
                # Log idle status if interval elapsed
                current_time = time.time()
                idle_duration = current_time - self.last_activity_time
                if idle_duration > self.IDLE_LOG_INTERVAL:
                    logger.info(
                        f"Consumer_{self.pattern_id}: "
                        f"Idle for {format_duration(idle_duration)}. "
                        f"Total processed: {self.processed_count}"
                    )
                    self.last_activity_time = current_time  # Reset to avoid spam
                continue

            except Exception as e:
                logger.error(f"BaseConsumer.run: Error processing transaction: {e}")
                logger.error(traceback.format_exc())

    async def _process_transaction(self, tx: Dict[str, Any]) -> bool:
        """Process a single transaction using the generator"""
        try:
            # Evaluate the request
            evaluation = await self.generator.evaluate_request(tx)

            # Construct response parameters
            response_params: ResponseParameters = await self.generator.construct_response(tx, evaluation)

            # Get appropriate wallet based on source
            node_wallet = self.generic_pft_utilities.spawn_wallet_from_seed(
                self.credential_manager.get_credential(f'{response_params.source}__v1xrpsecret')
            )

            # Send response transaction
            return await self.generic_pft_utilities.process_queue_transaction(
                wallet=node_wallet,
                memo=response_params.memo,
                destination=response_params.destination,
                pft_amount=response_params.pft_amount
            )

        except Exception as e:
            logger.error(f"ResponseProcessor._process_transaction: Error processing transaction: {e}")
            logger.error(traceback.format_exc())
            return False

    def stop(self):
        """Signal the consumer to stop processing"""
        self._shutdown = True

class ResponseProcessorManager:
    """Manages the lifecycle of async queue consumers"""
    def __init__(
            self, 
            response_manager: ResponseQueueRouter,
            node_config: NodeConfig,
            credential_manager: CredentialManager,
            generic_pft_utilities: GenericPFTUtilities,
            openrouter: OpenRouterTool,
            transaction_repository: TransactionRepository
        ):
        self.response_manager = response_manager
        self.dependencies = Dependencies(
            node_config=node_config,
            credential_manager=credential_manager,
            generic_pft_utilities=generic_pft_utilities,
            openrouter=openrouter,
            transaction_repository=transaction_repository
        )
        self.consumers: Dict[str, ResponseProcessor] = {}
        self._tasks: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Initialize and start consumers for all response queues"""
        try:
            # Get queue configurations from response manager
            queue_configs = self.response_manager.get_all_queue_configs()

            for pattern_id, config in queue_configs.items():
                # Each rule creates its generator with all necessary dependencies
                generator = config.rule.get_response_generator(self.dependencies)

                # Create consumer
                consumer = ResponseProcessor(
                    queue=config.queue,
                    response_manager=self.response_manager,
                    generator=generator,
                    credential_manager=self.dependencies.credential_manager,
                    generic_pft_utilities=self.dependencies.generic_pft_utilities,
                    shutdown_event=self._shutdown_event,
                    pattern_id=pattern_id
                )

                # Store consumer
                self.consumers[pattern_id] = consumer

                # Create and store task
                task = asyncio.create_task(
                    consumer.run(),
                    name=f"Consumer_{pattern_id}"
                )
                self._tasks.append(task)
                logger.debug(f"ResponseProcessorManager: Started ResponseProcessor for pattern: {pattern_id}")

        except Exception as e:
            logger.error(f"Error starting consumers: {e}")
            logger.error(traceback.format_exc())
            raise

    async def stop(self):
        """Signal all consumers to stop"""
        self._shutdown_event.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

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
            transaction_repository: TransactionRepository,
            credential_manager: CredentialManager,
            node_config: NodeConfig,
            openrouter: OpenRouterTool
    ):
        self.generic_pft_utilities = generic_pft_utilities
        self.transaction_repository = transaction_repository
        self.credential_manager = credential_manager
        self.node_config = node_config
        self.openrouter = openrouter
        self.review_queue = asyncio.Queue()     # Queue for transactions needing review
        self.routing_queue = asyncio.Queue()    # Queue for transactions needing responses
        self.reviewer: TransactionReviewer = None  # will be initialized in start()
        self.response_manager: ResponseQueueRouter = None  # will be initialized in start()
        self.consumer_manager: ResponseProcessorManager = None  # will be initialized in start()
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Coordinate transaction processing"""
        try:
            if not self.reviewer:
                self.reviewer = TransactionReviewer(
                    business_logic=create_business_logic(),
                    repository=self.transaction_repository
                )
            if not self.response_manager:
                self.response_manager = ResponseQueueRouter(
                    business_logic=create_business_logic(),
                    review_queue=self.review_queue,
                    transaction_repository=self.transaction_repository,
                    shutdown_event=self._shutdown_event
                )
            if not self.consumer_manager:
                self.consumer_manager = ResponseProcessorManager(
                    response_manager=self.response_manager,
                    node_config=self.node_config,
                    credential_manager=self.credential_manager,
                    generic_pft_utilities=self.generic_pft_utilities,
                    openrouter=self.openrouter,
                    transaction_repository=self.transaction_repository
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

            # Start all processing tasks
            logger.debug("TransactionOrchestrator: Starting review task")
            review_task = asyncio.create_task(self._review_loop())
            logger.debug("TransactionOrchestrator: Starting response routing task")
            route_task = asyncio.create_task(self._route_loop())
            logger.debug("TransactionOrchestrator: Starting consumer manager")
            consumer_task = asyncio.create_task(self._consumer_loop())

            try:
                await asyncio.gather(review_task, route_task, consumer_task)
            except asyncio.CancelledError:
                logger.info("TransactionOrchestrator: Received shutdown signal")
                # Cancel child tasks
                review_task.cancel()
                route_task.cancel()
                consumer_task.cancel()
                # Wait for tasks to complete
                await asyncio.gather(review_task, route_task, consumer_task, return_exceptions=True)
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
        COUNT_LOG_INTERVAL = 100  # Log count every 100 transactions

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for next transaction with timeout
                    tx = await asyncio.wait_for(self.review_queue.get(), timeout=IDLE_LOG_INTERVAL)
                    
                    result = await self.reviewer.review_transaction(tx)
                    await self.transaction_repository.store_reviewing_result(tx['hash'], result)
                    reviewed_count += 1
                    last_activity_time = time.time()

                    # If transaction needs a response, add to processing queue
                    if not result.processed:
                        logger.debug(f"TransactionOrchestrator: Transaction {tx['hash']} needs a response. Adding to routing queue.")
                        await self.routing_queue.put(tx)

                    # Check if queue just became empty
                    queue_size = self.review_queue.qsize()
                    if queue_size == 0:
                        logger.info(f"Finished reviewing. Total transactions reviewed: {reviewed_count}")

                    if reviewed_count % COUNT_LOG_INTERVAL == 0:
                        logger.debug(f"Progress: {reviewed_count} transactions reviewed. Current queue size: {queue_size}")

                    # Log progress if interval elapsed
                    current_time = time.time()
                    if current_time - last_log_time > LOG_INTERVAL:
                        queue_size = self.review_queue.qsize()
                        logger.debug(f"TransactionOrchestrator: Progress: {reviewed_count} transactions reviewed. Current queue size: {queue_size}")
                        last_log_time = current_time

                except asyncio.TimeoutError:
                    current_time = time.time()
                    idle_duration = current_time - last_activity_time
                    logger.debug(f"TransactionOrchestrator: Review loop idle for {format_duration(idle_duration)}. Total reviewed: {reviewed_count}")
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
        ROUTE_LOG_INTERVAL = 100  # Log count every 100 transactions

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for next transaction with timeout
                    tx = await asyncio.wait_for(self.routing_queue.get(), timeout=IDLE_LOG_INTERVAL)
                    
                    # Route transaction to appropriate response queue
                    routed = await self.response_manager.route_transaction(tx)
                    if routed:
                        routed_count += 1
                        last_activity_time = time.time()

                    # Log progress by count
                    queue_size = self.routing_queue.qsize()
                    if queue_size == 0:
                        logger.debug(f"Finished routing. Total routed: {routed_count}")

                    if routed_count % ROUTE_LOG_INTERVAL == 0:
                        queue_size = self.routing_queue.qsize()
                        logger.debug(f"TransactionOrchestrator: Progress: {routed_count} transactions routed. Current queue size: {queue_size}")

                    # Log progress if interval elapsed
                    current_time = time.time()
                    if current_time - last_log_time > LOG_INTERVAL:
                        queue_size = self.routing_queue.qsize()
                        pending_count = len(self.response_manager.pending_responses)
                        response_queue_sizes = self.response_manager.get_queue_sizes()
                        logger.debug(
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
                    logger.debug(
                        f"TransactionOrchestrator: Process loop idle for {format_duration(idle_duration)}.\n"
                        f"  - Total routed: {routed_count}\n"
                        f"  - Pending responses: {pending_count}"
                    )
                    continue
                    
                except Exception as e:
                    logger.error(f"Error processing transaction: {e}")
                    logger.error(traceback.format_exc())
        finally:
            logger.debug("TransactionOrchestrator: Route loop shutdown complete")

    async def _consumer_loop(self):
        """Manage consumer lifecycle"""
        try:
            await self.consumer_manager.start()
            await self._shutdown_event.wait()  # Wait for shutdown signal
        except Exception as e:
            logger.error(f"Error in consumer loop: {e}")
            logger.error(traceback.format_exc())
        finally:
            await self.consumer_manager.stop()
            logger.debug("TransactionOrchestrator: Consumer loop shutdown complete")

    def stop(self):
        """Stop all transaction processing tasks"""
        logger.debug("TransactionOrchestrator: Stopping all transaction processing tasks")
        self._shutdown_event.set()

