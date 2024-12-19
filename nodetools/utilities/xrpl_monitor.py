from enum import Enum, auto
import asyncio
import threading
import time
import random
import pandas as pd
from xrpl.asyncio.clients import AsyncWebsocketClient
import xrpl.models.requests
from loguru import logger
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities

class XRPLWebSocketMonitor:
    """Monitors XRPL websocket for real-time transaction updates"""

    def __init__(self, generic_pft_utilities: 'GenericPFTUtilities'):
        self.pft_utilities = generic_pft_utilities
        self.network_config = generic_pft_utilities.network_config
        self.node_config = generic_pft_utilities.node_config

        # Websocket configuration
        self.ws_urls = self.network_config.websockets
        self.ws_url_index = 0
        self.url = self.ws_urls[self.ws_url_index]

        # Initialize asyncio elements
        self.loop = asyncio.new_event_loop()
        self.client = None
        self._stop_event = threading.Event()

        # Error handling parameters
        self.reconnect_delay = 1
        self.max_reconnect_delay = 30
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        
        # Ledger monitoring
        self.last_ledger_time = None
        self.LEDGER_TIMEOUT = 30
        self.CHECK_INTERVAL = 4

    def start(self):
        """Start the monitor in a separate thread"""
        self.monitor_thread = threading.Thread(target=self._run_monitor, daemon=True)
        self.monitor_thread.start()

    def stop(self):
        """Signal the monitor to stop"""
        self._stop_event.set()

    def _run_monitor(self):
        """Main monitor thread entry point"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.monitor())
        except Exception as e:
            if not self._stop_event.is_set():
                logger.error(f"Unhandled exception in XRPL monitor: {e}")
                logger.error(traceback.format_exc())
        finally:
            self.loop.close()

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
        while not self._stop_event.is_set():
            try:
                await self._monitor_xrpl()
                # Reset reconnection parameters on successful connection
                self.reconnect_delay = 1
                self.reconnect_attempts = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stop_event.is_set():
                    break
                await self.handle_connection_error(f"XRPL monitor error: {e}")

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
                    if self._stop_event.is_set():
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
            
            formatted_tx = {
                "tx_json": tx_message.get("tx_json", {}),
                "meta": tx_message.get("meta", {}),
                "hash": tx_message.get("hash"),
                "ledger_index": tx_message.get("ledger_index"),
                "validated": tx_message.get("validated", False)
            }

            # Create DataFrame in same format as existing code
            tx_df = pd.DataFrame([formatted_tx])
            
            # Process through existing pipeline
            if not tx_df.empty:
                self.pft_utilities.sync_pft_transaction_history()

        except Exception as e:
            logger.error(f"Error processing transaction update: {e}")
            logger.error(traceback.format_exc())
    
