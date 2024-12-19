from enum import Enum, auto
import asyncio
import threading
from loguru import logger
from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
from nodetools.protocols.transaction_repository import TransactionRepository
from typing import TYPE_CHECKING
import traceback
from nodetools.task_processing.task_management_rules import create_business_logic
from nodetools.models.processor import TransactionProcessor, ProcessorManager

class NodeToolsState(Enum):
    SYNC = auto()           # Initial sync of historical data
    VERIFICATION = auto()   # Verification of historical data
    ACTIVE = auto()         # Processing new transactions via websocket

class NodeToolsStateManager:
    def __init__(
            self, 
            generic_pft_utilities: GenericPFTUtilities, 
            transaction_repository: TransactionRepository
    ):
        self.generic_pft_utilities = generic_pft_utilities
        self.transaction_repository = transaction_repository
        self.current_state = NodeToolsState.SYNC
        self._shutdown = False
        self._state_lock = threading.Lock()

    @property
    def state(self):
        """Thread-safe state access"""
        with self._state_lock:
            return self.current_state

    @state.setter
    def state(self, new_state: NodeToolsState):
        """Thread-safe state updates with logging"""
        with self._state_lock:
            if self.current_state != new_state:
                logger.info(f"State transition: {self.current_state} -> {new_state}")
                self.current_state = new_state

    async def start(self):
        """Start state management process"""
        while not self._shutdown:
            match self.state:
                case NodeToolsState.SYNC:
                    await self._handle_sync_state()
                case NodeToolsState.VERIFICATION:
                    await self._handle_verification_state()
                case NodeToolsState.ACTIVE:
                    await self._handle_active_state()
            await asyncio.sleep(1)  # Prevent busy-loop

    async def _handle_sync_state(self):
        """Sync historical data from XRPL to PostgreSQL"""
        try:
            logger.info("NodeToolsStateManager: Beginning historical data sync")
            self.generic_pft_utilities.sync_pft_transaction_history()
            logger.info("NodeToolsStateManager: Historical sync complete")
            self.state = NodeToolsState.VERIFICATION
            
        except Exception as e:
            logger.error(f"NodeToolsStateManager: Error in sync state: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)  # Delay before retry

    async def _handle_verification_state(self):
        """Verify cached transactions against business logic"""
        try:
            logger.info("NodeToolsStateManager: Beginning transaction verification")

            # Get business logic configuration
            business_logic = create_business_logic()

            # Initialize processor with configured rules
            processor = TransactionProcessor(business_logic.rules)
            
            # Initialize processor manager
            processor_manager = ProcessorManager(
                repository=self.transaction_repository,
                processor=processor
            )

            # Process transactions
            processed_count = await processor_manager.process_unverified_transactions()
            
            logger.info(f"NodeToolsStateManager: Transaction verification complete: {processed_count} transactions processed")
            self.state = NodeToolsState.ACTIVE
            
        except Exception as e:
            logger.error(f"NodeToolsStateManager: Error in verification state: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(5)

    async def _handle_active_state(self):
        """Process new transactions via websocket"""
        try:
            logger.info("NodeToolsStateManager: Activating WebSocket monitor")
            self.generic_pft_utilities.xrpl_monitor.start()

            while self.state == NodeToolsState.ACTIVE and not self._shutdown:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"NodeToolsStateManager: Error in active state: {e}")
            logger.error(traceback.format_exc())
            self.state = NodeToolsState.SYNC  # Return to sync on error
            self.generic_pft_utilities.xrpl_monitor.stop()
            await asyncio.sleep(5)
                
    def stop(self):
        """Stop state management process"""
        logger.info("NodeToolsStateManager: Stopping state management")
        self._shutdown = True