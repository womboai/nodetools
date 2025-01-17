from typing import Protocol
import asyncio

class XRPLWebSocketMonitor(Protocol):
    """Protocol for XRPLWebSocketMonitor"""

    @property
    def monitor_task(self) -> asyncio.Task:
        """The monitor task"""
        ...

    def start(self, queue: asyncio.Queue):
        """Start the monitor as an asyncio task"""
        ...

    def stop(self):
        """Signal the monitor to stop and wait for it to complete"""
        ...
