from typing import Protocol, Dict
import asyncio

class TransactionResponseManager(Protocol):
    """
    Manages the routing of transactions that need responses to appropriate processing queues.
    Also tracks pending responses and triggers re-review when responses are confirmed.
    """
    @property
    def response_queues(self) -> Dict[str, asyncio.Queue]:
        """Get the response queues"""
        ...

    async def confirm_response_sent(self, request_tx_hash: str):
        """
        Called by response consumers after successfully submitting a response.
        Triggers re-review of the original transaction.
        """
        ...
