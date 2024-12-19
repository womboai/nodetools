from typing import List, Dict, Any, Set, Optional
from dataclasses import dataclass
from loguru import logger
from nodetools.models.models import TransactionRule
from nodetools.protocols.transaction_repository import TransactionRepository
import traceback

@dataclass
class ProcessingResult:
    processed: bool
    rule_name: str
    response_tx_hash: Optional[str] = None
    notes: Optional[str] = None

class TransactionProcessor:
    def __init__(self, rules: List[TransactionRule]):
        self.rules = rules

    async def process_transaction(self, tx: Dict[str, Any], all_txs: Set[Dict[str, Any]]) -> ProcessingResult:
        """Process a single transaction against all rules"""
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
                    if not pattern.requires_response:
                        return ProcessingResult(
                            processed=True,  # We've reviewed it and no response needed
                            rule_name=rule.__class__.__name__,
                            notes="No response required"
                        )

                    # 4. Look for required response
                    response_tx = await rule.find_response(tx, all_txs)
                    if not response_tx:
                        return ProcessingResult(
                            processed=False,  # We need to keep checking this one until we find a response
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
    
class ProcessorManager:
    def __init__(
            self,
            repository: TransactionRepository,
            processor: TransactionProcessor
    ):
        self.repository = repository
        self.processor = processor

    async def process_unverified_transactions(self, batch_size: Optional[int] = None) -> int:
        """
        Process unverified transactions in chronological order.
        Returns number of transactions processed.
        """
        try:
            logger.debug(f"ProcessorManager.process_unverified_transactions: Processing unverified transactions...")
            # Get unverified transactions ordered by timestamp
            unverified_txs = await self.repository.get_unverified_transactions(
                order_by="close_time_iso ASC",
                limit=batch_size,
                include_processed=True   # NOTE: This is a temporary measure for debugging
            )
            
            if not unverified_txs:
                logger.info("No unverified transactions found")
                return 0

            processed_count = 0

            # Process each transaction
            for tx in unverified_txs:
                try:
                    result = await self.processor.process_transaction(tx, unverified_txs)
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
