from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Set, Optional, Dict, Any, Pattern

@dataclass(frozen=True)  # Making it immutable for hashability
class MemoPattern:
    memo_type: Optional[str | Pattern] = None
    memo_format: Optional[str | Pattern] = None
    memo_data: Optional[str | Pattern] = None

    def matches(self, tx: Dict[str, Any]) -> bool:
        """Check if a transaction's memo matches this pattern"""
        if self.memo_type:
            tx_memo_type = tx.get("memo_type")
            if not tx_memo_type or not self._pattern_matches(self.memo_type, tx_memo_type):
                return False

        if self.memo_format:
            tx_memo_format = tx.get("memo_format")
            if not tx_memo_format or not self._pattern_matches(self.memo_format, tx_memo_format):
                return False

        if self.memo_data:
            tx_memo_data = tx.get("memo_data")
            if not tx_memo_data or not self._pattern_matches(self.memo_data, tx_memo_data):
                return False

        return True

    def _pattern_matches(self, pattern: str | Pattern, value: str) -> bool:
        if isinstance(pattern, Pattern):
            return bool(pattern.match(value))
        return pattern == value
    
    def __hash__(self):
        # Convert Pattern objects to their pattern strings for hashing
        memo_type_hash = self.memo_type.pattern if isinstance(self.memo_type, Pattern) else self.memo_type
        memo_format_hash = self.memo_format.pattern if isinstance(self.memo_format, Pattern) else self.memo_format
        memo_data_hash = self.memo_data.pattern if isinstance(self.memo_data, Pattern) else self.memo_data
        
        return hash((memo_type_hash, memo_format_hash, memo_data_hash))
    
    def __eq__(self, other):
        if not isinstance(other, MemoPattern):
            return False
        
        # Compare Pattern objects by their pattern strings
        def compare_attrs(a, b):
            if isinstance(a, Pattern) and isinstance(b, Pattern):
                return a.pattern == b.pattern
            return a == b
        
        return (compare_attrs(self.memo_type, other.memo_type) and
                compare_attrs(self.memo_format, other.memo_format) and
                compare_attrs(self.memo_data, other.memo_data))

@dataclass
class TransactionPattern:
    memo_pattern: MemoPattern
    requires_response: bool
    valid_response_patterns: Set[MemoPattern]
    node_account: Optional[str] = None

class TransactionGraph:
    def __init__(self):
        self.patterns: Dict[str, TransactionPattern] = {}

    def add_pattern(
            self,
            pattern_id: str,
            memo_pattern: MemoPattern,
            requires_response: bool, 
            valid_response_patterns: Set[MemoPattern]
    ) -> None:
        self.patterns[pattern_id] = TransactionPattern(
            memo_pattern, 
            requires_response, 
            valid_response_patterns, 
        )

    def is_valid_response(self, request_pattern_id: str, response_tx: Dict[str, Any]) -> bool:
        if request_pattern_id not in self.patterns:
            return False
        
        node = self.patterns[request_pattern_id]
        return any(pattern.matches(response_tx) for pattern in node.valid_response_patterns)

    def find_matching_pattern(self, tx: Dict[str, Any]) -> Optional[str]:
        """Find the first pattern ID whose pattern matches the transaction"""
        for pattern_id, pattern in self.patterns.items():
            if pattern.memo_pattern.matches(tx):
                return pattern_id
        return None

class TransactionRule(ABC):
    def __init__(self, transaction_graph: TransactionGraph):
        self.transaction_graph = transaction_graph

    @abstractmethod
    async def matches(self, tx: Dict[str, Any]) -> bool:
        """Determine if this rule applies to the transaction"""
        pass

    @abstractmethod
    async def find_response(
        self,
        request_tx: Dict[str, Any],
        all_txs: Set[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Find valid response transaction from the node account"""
        pass

    def get_pattern_id(self, tx: Dict[str, Any]) -> Optional[str]:
        """Get the pattern ID for this transaction"""
        return self.transaction_graph.find_matching_pattern(tx)
