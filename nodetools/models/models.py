from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Set, Optional, Dict, Any, Pattern, TYPE_CHECKING
from enum import Enum
from loguru import logger
from decimal import Decimal
from xrpl.models import Memo

if TYPE_CHECKING:
    from nodetools.protocols.credentials import CredentialManager
    from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
    from nodetools.protocols.openrouter import OpenRouterTool
    from nodetools.protocols.transaction_repository import TransactionRepository
    from nodetools.configuration.configuration import NodeConfig

class TransactionType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    STANDALONE = "standalone"

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
    transaction_type: TransactionType
    valid_responses: Set[MemoPattern]

    def __post_init__(self):
        # Validate that RESPONSE types don't have valid_responses
        if self.transaction_type == TransactionType.RESPONSE and self.valid_responses:
            raise ValueError("RESPONSE types cannot have valid_responses")
        # Validate that REQUEST types must have valid_responses
        if self.transaction_type == TransactionType.REQUEST and not self.valid_responses:
            raise ValueError("REQUEST types must have valid_responses")

class TransactionGraph:
    def __init__(self):
        self.patterns: Dict[str, TransactionPattern] = {}
        self.memo_pattern_to_id: Dict[MemoPattern, str] = {}

    def add_pattern(
            self,
            pattern_id: str,
            memo_pattern: MemoPattern,
            transaction_type: TransactionType,
            valid_responses: Optional[Set[MemoPattern]] = None
    ) -> None:
        """
        Add a new pattern to the graph.
        For RESPONSE and STANDALONE types, valid_responses should be None or empty.
        For REQUEST types, valid_responses must be provided.
        """
        self.patterns[pattern_id] = TransactionPattern(
            memo_pattern=memo_pattern, 
            transaction_type=transaction_type, 
            valid_responses=valid_responses, 
        )
        # Update the reverse lookup
        self.memo_pattern_to_id[memo_pattern] = pattern_id

    def is_valid_response(self, request_pattern_id: str, response_tx: Dict[str, Any]) -> bool:
        if request_pattern_id not in self.patterns:
            return False
        
        pattern = self.patterns[request_pattern_id]
        if pattern.transaction_type != TransactionType.REQUEST:
            return False

        return any(resp_pattern.matches(response_tx) for resp_pattern in pattern.valid_responses)

    def find_matching_pattern(self, tx: Dict[str, Any]) -> Optional[str]:
        """Find the first pattern ID whose pattern matches the transaction"""

        # # Only debug for specific transaction
        # debug_hash = "B365144B26EB46686ED700F78E30B26316C59F18BB5CA628A166772F4E0F200E"
        # is_debug_tx = tx.get('hash') == debug_hash
        
        # if is_debug_tx:
        #     logger.debug(f"Finding pattern for transaction {debug_hash}")
        #     logger.debug(f"Transaction memo_type: {tx.get('memo_type')}")

        for pattern_id, pattern in self.patterns.items():

            # # DEBUGGING
            # if is_debug_tx:
            #     logger.debug(f"Testing pattern '{pattern_id}' with memo_type: {pattern.memo_pattern.memo_type}")
            #     if pattern.memo_pattern.matches(tx):
            #         logger.debug(f"Found matching pattern: {pattern_id}")
            #         return pattern_id
            #     logger.debug(f"Pattern '{pattern_id}' did not match")
            #     continue

            if pattern.memo_pattern.matches(tx):
                return pattern_id
        return None
    
    def get_pattern_id_by_memo_pattern(self, memo_pattern: MemoPattern) -> Optional[str]:
        """Get the pattern ID for a given memo pattern"""
        return self.memo_pattern_to_id.get(memo_pattern)

class TransactionRule(ABC):
    """Base class for transaction processing rules"""
    @abstractmethod
    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate any additional business rules for a transaction
        This is separate from the transaction pattern matching
        """
        pass

    @property
    @abstractmethod
    def transaction_type(self) -> TransactionType:
        """Return the type of transaction this rule handles"""
        pass

@dataclass
class ResponseQuery:
    """Data class to hold query information for finding responses"""
    query: str
    params: Dict[str, Any]

class RequestRule(TransactionRule):
    """Base class for rules that handle request transactions"""
    transaction_type = TransactionType.REQUEST

    @abstractmethod
    async def find_response(self, request_tx: Dict[str, Any]) -> Optional[ResponseQuery]:
        """Get query information for finding a valid response transaction"""
        pass

@dataclass
class ResponseParameters:
    """Standardized response parameters for transaction construction"""
    source: str  # Name of the address that should send the response
    memo: Memo  # XRPL memo object
    destination: str  # XRPL destination address
    pft_amount: Optional[Decimal] = None  # Optional PFT amount for the transaction

class ResponseGenerator(ABC):
    """Protocol defining how to generate a response"""
    @abstractmethod
    async def evaluate_request(self, request_tx: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate the request and return response parameters"""
        pass

    @abstractmethod
    async def construct_response(
        self, 
        request_tx: Dict[str, Any],
        evaluation_result: Dict[str, Any]
    ) -> ResponseParameters:
        """Construct the response memo and parameters"""
        pass

class ResponseRule(TransactionRule):
    """Base class for rules that handle response transactions"""
    transaction_type = TransactionType.RESPONSE

    @abstractmethod
    def get_response_generator(self, *args, **kwargs) -> ResponseGenerator:
        """
        Get the response generator for this rule type.
        
        Each rule implementation should document its required dependencies.
        """
        pass

class StandaloneRule(TransactionRule):
    """Base class for rules that handle standalone transactions"""
    transaction_type = TransactionType.STANDALONE
    
@dataclass
class BusinessLogicProvider:
    """Centralizes all business logic configuration"""
    transaction_graph: TransactionGraph
    pattern_rule_map: Dict[str, TransactionRule]  # Maps pattern_id to rule instance

@dataclass
class Dependencies:
    """Container for all possible dependencies needed by ResponseGenerators"""
    node_config: 'NodeConfig'
    credential_manager: 'CredentialManager'
    generic_pft_utilities: 'GenericPFTUtilities'
    openrouter: 'OpenRouterTool'
    transaction_repository: 'TransactionRepository'
