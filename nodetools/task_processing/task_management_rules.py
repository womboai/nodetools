from nodetools.models.models import TransactionRule
from nodetools.models.models import TransactionGraph, MemoPattern
from typing import Dict, Any, Set, Optional, List
import pandas as pd
from nodetools.task_processing.memo_types import SystemMemoType
from dataclasses import dataclass

@dataclass
class BusinessLogicProvider:
    """Centralizes all business logic configuration"""
    rules: List[TransactionRule]

def create_business_logic() -> BusinessLogicProvider:
    """Factory function to create all business logic components"""
    # Setup transaction graph
    graph = TransactionGraph()

    # Define memo patterns
    initiation_rite_pattern = MemoPattern(
        memo_type=SystemMemoType.INITIATION_RITE.value
    )

    initiation_reward_pattern = MemoPattern(
        memo_type=SystemMemoType.INITIATION_REWARD.value
    )

    # Add node configuration
    graph.add_pattern(
        pattern_id="initiation_rite",
        memo_pattern=initiation_rite_pattern,
        requires_response=True,
        valid_response_patterns={initiation_reward_pattern}
    )

    # Create rules
    rules = [
        InitiationRiteRule(graph)
        # TODO: Add more rules here
    ]

    return BusinessLogicProvider(rules)

class InitiationRiteRule(TransactionRule):
    """Pure business logic for handling initiation rites"""

    def __init__(self, transaction_graph: TransactionGraph):
        super().__init__(transaction_graph)

    @staticmethod
    def is_valid_initiation_rite(rite_text: str) -> bool:
        """Validate if the initiation rite meets basic requirements"""
        if not rite_text or not isinstance(rite_text, str):
            return False
        
        # Remove whitespace
        cleaned_rite = str(rite_text).strip()

        # Check minimum length
        if len(cleaned_rite) < 10:
            return False
        
        return True
    
    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is an initiation rite that needs processing.
        Must be:
        1. A successful transaction
        2. Have INITIATION_RITE memo type
        3. Have valid rite text
        """

        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
            
        if tx.get('memo_type') != SystemMemoType.INITIATION_RITE.value:
            return False
            
        is_valid = self.is_valid_initiation_rite(tx.get('memo_data', ''))
        return is_valid
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
            all_txs: Set[Dict[str, Any]]
        ) -> Optional[Dict[str, Any]]:
        """
        Find if this initiation rite has received a reward response.
        The response must be:
        1. To the same account
        2. Have INITIATION_REWARD memo type
        3. Successful transaction
        """
        node_id = self.get_pattern_id(request_tx)
        if not node_id:
            return None
        
        # Look for matching reward from node account
        for tx in all_txs:
            if (tx.get('Destination') == request_tx.get('Account') and
                tx.get('memo_type') == SystemMemoType.INITIATION_REWARD.value and
                tx.get('transaction_result') == 'tesSUCCESS'):
                return tx
                
        return None