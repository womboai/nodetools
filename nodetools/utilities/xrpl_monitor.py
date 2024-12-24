import asyncio
import time
import random
from xrpl.asyncio.clients import AsyncWebsocketClient
import xrpl.models.requests
from loguru import logger
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
    from nodetools.protocols.transaction_repository import TransactionRepository

class XRPLWebSocketMonitor:
    """Monitors XRPL websocket for real-time transaction updates"""

    def __init__(
            self, 
            generic_pft_utilities: 'GenericPFTUtilities',
            transaction_repository: 'TransactionRepository'
        ):
        self.pft_utilities = generic_pft_utilities
        self.network_config = generic_pft_utilities.network_config
        self.node_config = generic_pft_utilities.node_config
        self.transaction_repository = transaction_repository

        # Websocket configuration
        self.ws_urls = self.network_config.websockets
        self.ws_url_index = 0
        self.url = self.ws_urls[self.ws_url_index]

        # Client and queue
        self.client = None
        self.review_queue = None
        self._monitor_task = None
        self._shutdown = False

        # Error handling parameters
        self.reconnect_delay = 1
        self.max_reconnect_delay = 30
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        
        # Ledger monitoring
        self.last_ledger_time = None
        self.LEDGER_TIMEOUT = 30
        self.CHECK_INTERVAL = 4

    def start(self, queue: asyncio.Queue):
        """Start the monitor as an asyncio task"""
        self.review_queue = queue
        self._shutdown = False
        self._monitor_task = asyncio.create_task(self.monitor())
        return self._monitor_task

    async def stop(self):
        """Signal the monitor to stop and wait for it to complete"""
        self._shutdown = True
        if self._monitor_task:
            await self._monitor_task

    async def handle_connection_error(self, error_msg: str) -> bool:
        """Handle connection errors with exponential backoff"""
        logger.error(error_msg)

        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnect_attempts:
            self._switch_node()
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            return False
        
        delay = min(self.reconnect_delay * (1 + random.uniform(0, 0.1)), self.max_reconnect_delay)
        logger.info(f"Reconnecting in {delay:.1f} seconds...")
        await asyncio.sleep(delay)
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
        return True
    
    def _switch_node(self):
        """Switch to next available WebSocket endpoint"""
        self.ws_url_index = (self.ws_url_index + 1) % len(self.ws_urls)
        self.url = self.ws_urls[self.ws_url_index]
        logger.info(f"Switching to WebSocket endpoint: {self.url}")

    async def monitor(self):
        """Main monitoring loop with error handling"""
        while not self._shutdown:
            try:
                await self._monitor_xrpl()
                # Reset reconnection parameters on successful connection
                self.reconnect_delay = 1
                self.reconnect_attempts = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._shutdown:
                    break
                should_continue = await self.handle_connection_error(f"XRPL monitor error: {e}")
                if not should_continue:
                    break

    async def _monitor_xrpl(self):
        """Monitor XRPL for updates"""
        self.last_ledger_time = time.time()

        async with AsyncWebsocketClient(self.url) as self.client:
            # Subscribe to streams
            response = await self.client.request(xrpl.models.requests.Subscribe(
                streams=["ledger"],
                accounts=[self.node_config.node_address, self.network_config.issuer_address]
            ))

            if not response.is_successful():
                raise Exception(f"Subscription failed: {response.result}")
            
            logger.info(f"Successfully subscribed to updates on node {self.url}")

            # Start timeout checking
            timeout_task = asyncio.create_task(self._check_timeouts())

            try:
                async for message in self.client:
                    if self._shutdown:
                        break

                    try:
                        mtype = message.get("type")

                        if mtype == "ledgerClosed":
                            self.last_ledger_time = time.time()
                        elif mtype == "transaction":
                            await self._process_transaction(message)

                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        continue

            finally:
                timeout_task.cancel()
                try:
                    await timeout_task
                except asyncio.CancelledError:
                    pass

    async def _check_timeouts(self):
        """Check for ledger update timeouts"""
        while True:
            await asyncio.sleep(self.CHECK_INTERVAL)
            if self.last_ledger_time is not None:
                time_since_last_ledger = time.time() - self.last_ledger_time
                if time_since_last_ledger > self.LEDGER_TIMEOUT:
                    raise Exception(f"No ledger updates received for {time_since_last_ledger:.1f} seconds")
                
    async def _process_transaction(self, tx_message):
        """Process transaction updates from websocket"""
        try:

            logger.debug(f"XRPLWebSocketMonitor: Received transaction, storing in database: {tx_message}")

            # First insert the transaction into the cache
            if await self.transaction_repository.insert_transaction(tx_message):
                # Retrieve the complete transaction record from the database
                # to ensure consistent format, which includes decoded memo fields
                tx = await self.transaction_repository.get_decoded_transaction(tx_message['hash'])

                logger.debug(f"XRPLWebSocketMonitor: Retrieved transaction from database: {tx}")

                if tx and tx['hash'] == tx_message['hash']:
                    # Place complete transaction record into review queue
                    await self.review_queue.put(tx)
                else:
                    logger.error(f"Failed to retrieve stored transaction {tx_message['hash']} from database")
            else:
                logger.error(f"Failed to store transaction {tx_message['hash']} in database")

        except Exception as e:
            logger.error(f"Error processing transaction update: {e}")
            logger.error(traceback.format_exc())
    
