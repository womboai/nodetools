from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Set, Optional, Dict, Any, Pattern, TYPE_CHECKING, List, Union
from enum import Enum
from loguru import logger
from decimal import Decimal
import re
from datetime import datetime as dt
import copy
from xrpl.models import Memo
from nodetools.configuration.constants import MEMO_VERSION

if TYPE_CHECKING:
    from nodetools.protocols.credentials import CredentialManager
    from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
    from nodetools.protocols.openrouter import OpenRouterTool
    from nodetools.protocols.transaction_repository import TransactionRepository
    from nodetools.protocols.encryption import MessageEncryption
    from nodetools.configuration.configuration import NodeConfig, NetworkConfig

@dataclass
class Dependencies:
    """Container for core dependencies that can be provided by NodeTools"""
    network_config: 'NetworkConfig'
    node_config: 'NodeConfig'
    credential_manager: 'CredentialManager'
    generic_pft_utilities: 'GenericPFTUtilities'
    openrouter: 'OpenRouterTool'
    transaction_repository: 'TransactionRepository'
    message_encryption: 'MessageEncryption'

class InteractionType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    STANDALONE = "standalone"

class MemoDataStructureType(Enum):
    """Components of the standardized memo format"""
    VERSION = "v"   # Version prefix
    ECDH = "e"      # Encryption
    BROTLI = "b"    # Compression
    CHUNK = "c"     # Chunking
    NONE = "-"      # No processing

@dataclass
class MemoTransaction:
    """
    Represents a transaction with a memo
    Corresponds to the transaction_memos + transaction_processing_results tables
    """
    hash: str
    account: str
    destination: str
    pft_amount: Decimal
    xrp_fee: Decimal
    memo_type: str
    memo_format: str
    memo_data: str
    datetime: dt
    transaction_result: str
    processed: Optional[bool] = None
    rule_name: Optional[str] = None
    response_tx_hash: Optional[str] = None
    notes: Optional[str] = None
    reviewed_at: Optional[dt] = None

    def __post_init__(self):
        """Ensure proper initialization of fields"""
        if self.pft_amount is None:
            self.pft_amount = Decimal('0')
        elif isinstance(self.pft_amount, (int, str, float)):
            self.pft_amount = Decimal(str(self.pft_amount))

        if isinstance(self.xrp_fee, (int, str, float)):
            self.xrp_fee = Decimal(str(self.xrp_fee))

        if isinstance(self.datetime, str):
            self.datetime = dt.fromisoformat(self.datetime)
        elif not isinstance(self.datetime, dt):
            raise TypeError(f"datetime must be datetime object or ISO format string, got: {type(self.datetime)}")
        
        if self.memo_type is None:
            raise ValueError("memo_type is required")
        
        if self.memo_format is None:
            raise ValueError("memo_format is required")
        
        if self.memo_data is None:
            raise ValueError("memo_data is required")
        
    def copy(self) -> 'MemoTransaction':
        """Create a deep copy of the MemoTransaction"""
        return copy.deepcopy(self)
    
    def __getitem__(self, key):
        """Allow dictionary-style access to attributes"""
        return asdict(self)[key]

    def __iter__(self):
        """Allow iteration over items"""
        return iter(asdict(self))

    def keys(self):
        """Return dictionary keys"""
        return asdict(self).keys()

    def items(self):
        """Return dictionary items"""
        return asdict(self).items()

    def values(self):
        """Return dictionary values"""
        return asdict(self).values()
    
    def get(self, key, default=None):
        """Dictionary-style get method with default value"""
        try:
            return self[key]
        except KeyError:
            return default

@dataclass
class MemoStructure:
    """
    Describes how a memo is structured across transactions.
    This is designed to be used for parsing memos from transactions, but not for constructing memo groups.
    """
    is_chunked: Optional[bool] = None
    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None
    group_id: Optional[str] = None
    compression_type: Optional[MemoDataStructureType] = None  # Might be unknown until processing
    encryption_type: Optional[MemoDataStructureType] = None   # Might be unknown until processing
    version: Optional[str] = None
    is_valid_format: bool = False

    @classmethod
    def invalid_format(cls) -> 'MemoStructure':
        """Return an empty MemoStructure, indicating an invalid format"""
        return cls()
    
    @classmethod
    def is_standardized_memo_format(cls, memo_format: Optional[str]) -> bool:
        """
        Check if memo_format follows the standardized format.
        Examples:
            "v1.0.e.b.c1/4"  # version 1.0, encrypted, compressed, chunk 1 of 4
            "v1.0.-.b.c2/4"  # version 1.0, not encrypted, compressed, chunk 2 of 4
            "v1.0.-.-.-"     # version 1.0, no special processing
        """
        if not memo_format:
            return False
        
        # Split on the last 3 periods to get [v1.0, e, b, c1/4]
        parts = memo_format.rsplit(".", 3)
        if len(parts) != 4:
            return False
        
        version, encryption, compression, chunking = parts

        # Validate version
        if not version.startswith(MemoDataStructureType.VERSION.value):
            return False
        version_num = version[1:]  # Remove 'v' prefix
        if version_num != MEMO_VERSION:
            return False

        # Validate encryption
        if encryption not in {MemoDataStructureType.ECDH.value, MemoDataStructureType.NONE.value}:
            return False
            
        # Validate compression
        if compression not in {MemoDataStructureType.BROTLI.value, MemoDataStructureType.NONE.value}:
            return False
            
        # Validate chunking
        if chunking != MemoDataStructureType.NONE.value:
            chunk_match = re.match(fr'{MemoDataStructureType.CHUNK.value}\d+/\d+', chunking)
            if not chunk_match:
                return False
                
        return True
    
    @classmethod
    def parse_standardized_format(cls, memo_format: str) -> 'MemoStructure':
        """Parse a validated standardized memo_format string."""
        version, encryption, compression, chunking = memo_format.rsplit(".", 3)

        # Parse version
        version_num = version[1:]  # Remove 'v' prefix and convert to enum
        version_type = version_num if version_num == MEMO_VERSION else None

        # Parse encryption
        encryption_type = (
            MemoDataStructureType.ECDH if encryption == MemoDataStructureType.ECDH.value 
            else None
        )

        # Parse compression
        compression_type = (
            MemoDataStructureType.BROTLI if compression == MemoDataStructureType.BROTLI.value 
            else None
        )

        # Parse chunking
        chunk_index = None
        total_chunks = None
        if chunking != MemoDataStructureType.NONE.value:
            chunk_match = re.match(fr'{MemoDataStructureType.CHUNK.value}(\d+)/(\d+)', chunking)
            if chunk_match:  # We know this matches from validation
                chunk_index = int(chunk_match.group(1))
                total_chunks = int(chunk_match.group(2))

        return cls(
            is_chunked=chunk_index is not None,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            group_id=None,  # Will be set from tx
            compression_type=compression_type,
            encryption_type=encryption_type,
            version=version_type,
            is_valid_format=True
        )
    
    @classmethod
    def from_transaction(cls, tx: MemoTransaction) -> 'MemoStructure':
        """
        Extract memo structure from transaction memo fields.
        
        New format examples:
            "v1.0.e.b.c1/4"                    # version 1.0, encrypted, compressed, chunk 1 of 4
            "v1.0.-.b.c2/4"                    # version 1.0, not encrypted, compressed, chunk 2 of 4
            "v1.0.-.-.-"                       # version 1.0, no special processing
            "invalid_format"              # Invalid
        """
        memo_format = tx.memo_format

        # Check if using standardized format
        if cls.is_standardized_memo_format(memo_format):
            structure = cls.parse_standardized_format(memo_format)
            structure.group_id = tx.memo_type  # Set group_id from transaction
            return structure
        else:
            return cls.invalid_format()
    
@dataclass
class MemoGroup:
    """
    Manages a group of related memos from individual transactions.
    Memos are related if they share the same memo_type (group_id) and have a consistent memo_format (MemoStructure).
    These memos can be reconstituted into a single memo by unchunking.
    Additional processing can be applied to the unchunked memo_data.
    """
    group_id: str
    memos: List[Union[MemoTransaction, Memo]]  # Supports both parsed txs and Memo objects
    structure: Optional[MemoStructure] = None

    @classmethod
    def create_from_transaction(cls, tx: MemoTransaction) -> 'MemoGroup':
        """Create a new message group from an initial transaction"""
        structure = MemoStructure.from_transaction(tx)
        return cls(
            group_id=tx.memo_type,
            memos=[tx],
            structure=structure,
        )
    
    @classmethod
    def create_from_memos(cls, memos: List[Memo]) -> 'MemoGroup':
        """Create a new message group from constructed memos"""
        structure = MemoStructure.from_transaction(memos[0])
        return cls(
            group_id=memos[0].memo_type,
            memos=memos,
            structure=structure
        )
    
    def _is_structure_consistent(self, new_structure: MemoStructure) -> bool:
        """
        Check if a new message's structure is consistent with the group.
        Only applies to new format messages, whose structure can be interpreted from memo_format.
        """            
        return (
            new_structure.encryption_type == self.structure.encryption_type and
            new_structure.compression_type == self.structure.compression_type and
            new_structure.total_chunks == self.structure.total_chunks
        )
    
    def add_memo(self, tx: MemoTransaction) -> bool:
        """
        Add a memo to the group if it belongs.
        Returns True if memo was added, False if it doesn't belong.
        """
        if tx.transaction_result != 'tesSUCCESS':
            return False

        if tx.memo_type != self.group_id:
            return False
        
        new_structure = MemoStructure.from_transaction(tx)

        # For new format messages, validate consistency
        if new_structure.is_valid_format:
            if not self._is_structure_consistent(new_structure):
                logger.warning(f"Inconsistent message structure in group {self.group_id}")
                return False
            self.memos.append(tx)
            return True
        
        # For legacy format messages, handle duplicate chunks
        if new_structure.chunk_index is not None:
            # Find any existing memo with the same chunk index
            existing_memo = next(
                (memo for memo in self.memos 
                if MemoStructure.from_transaction(memo).chunk_index == new_structure.chunk_index),
                None
            )
            
            if existing_memo:
                # If we found a duplicate chunk, only replace if new tx has earlier datetime
                if tx.datetime < existing_memo.datetime:
                    self.memos.remove(existing_memo)
                    self.memos.append(tx)
                    return True
                return False  # Duplicate chunk with later datetime, ignore it
        
        # No duplicate found, add the new memo
        self.memos.append(tx)
        return True
        
    @property
    def chunk_indices(self) -> Set[int]:
        """Get set of available chunk indices"""
        return {
            MemoStructure.from_transaction(tx).chunk_index
            for tx in self.memos
            if MemoStructure.from_transaction(tx).chunk_index is not None
        }
    
    @property
    def pft_amount(self) -> Decimal:
        """Total PFT amount across all transactions in this group"""
        return sum(
            (memo.pft_amount for memo in self.memos if isinstance(memo, MemoTransaction)),
            Decimal(0)
        )
    
class StructuralPattern(Enum):
    """
    Defines patterns for matching XRPL memo structure before content processing.
    Used to determine if memos need grouping and how they should be processed.
    """
    # NO_MEMO = "no_memo"                    # No memo present 
    DIRECT_MATCH = "direct_match"          # Can be pattern matched directly
    NEEDS_GROUPING = "needs_grouping"      # New format, needs grouping
    INVALID_STRUCTURE = "invalid_structure"  # Invalid structure, cannot be processed

    @staticmethod
    def match(tx: MemoTransaction) -> str:
        """Determine how a transaction's memos should be handled"""

        # NOTE: This is commented out because unprocessed transactions are queried from the transaction_memos table
        # and the transaction_memos table only has transactions with memos, so the NO_MEMO case is never hit
        # if not bool(tx.get('has_memos')):
        #     return StructuralPattern.NO_MEMO

        # Check if there is no memo present
        structure = MemoStructure.from_transaction(tx)
        if structure.is_valid_format:
            # New format: Use metadata to determine grouping needs
            return StructuralPattern.NEEDS_GROUPING if structure.is_chunked else StructuralPattern.DIRECT_MATCH
        else:
            return StructuralPattern.INVALID_STRUCTURE

@dataclass(frozen=True)  # Making it immutable for hashability
class MemoPattern:
    """
    Defines patterns for matching processed XRPL memos.
    Matching occurs after any necessary unchunking/decompression/decryption.
    """
    memo_type: Optional[str | Pattern] = None
    memo_format: Optional[str | Pattern] = None
    memo_data: Optional[str | Pattern] = None

    def get_message_structure(self, tx: MemoTransaction) -> MemoStructure:
        """Extract structural information from the memo fields"""
        return MemoStructure.from_transaction(tx)

    def matches(self, tx: MemoTransaction) -> bool:
        """Check if a transaction's memo matches this pattern"""
        if self.memo_type:
            if not tx.memo_type or not self._pattern_matches(self.memo_type, tx.memo_type):
                return False

        if self.memo_format:
            if not tx.memo_format or not self._pattern_matches(self.memo_format, tx.memo_format):
                return False

        if self.memo_data:
            if not tx.memo_data or not self._pattern_matches(self.memo_data, tx.memo_data):
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
class InteractionPattern:
    memo_pattern: MemoPattern
    transaction_type: InteractionType
    valid_responses: Set[MemoPattern]
    notify: bool = False

    def __post_init__(self):
        # Validate that RESPONSE types don't have valid_responses
        if self.transaction_type == InteractionType.RESPONSE and self.valid_responses:
            raise ValueError("RESPONSE types cannot have valid_responses")
        # Validate that REQUEST types must have valid_responses
        if self.transaction_type == InteractionType.REQUEST and not self.valid_responses:
            raise ValueError("REQUEST types must have valid_responses")

class InteractionGraph:
    def __init__(self):
        self.patterns: Dict[str, InteractionPattern] = {}
        self.memo_pattern_to_id: Dict[MemoPattern, str] = {}

    def add_pattern(
            self,
            pattern_id: str,
            memo_pattern: MemoPattern,
            transaction_type: InteractionType,
            valid_responses: Optional[Set[MemoPattern]] = None,
            notify: bool = False
    ) -> None:
        """
        Add a new pattern to the graph.
        For RESPONSE and STANDALONE types, valid_responses should be None or empty.
        For REQUEST types, valid_responses must be provided.

        Args:
            pattern_id: Unique identifier for the pattern
            memo_pattern: The memo pattern to match
            transaction_type: Type of interaction (REQUEST/RESPONSE/STANDALONE)
            valid_responses: Set of valid response patterns (required for REQUEST type)
            notify: Whether transactions matching this pattern should trigger notifications
        """
        self.patterns[pattern_id] = InteractionPattern(
            memo_pattern=memo_pattern, 
            transaction_type=transaction_type, 
            valid_responses=valid_responses,
            notify=notify
        )
        # Update the reverse lookup
        self.memo_pattern_to_id[memo_pattern] = pattern_id

    def is_valid_response(self, request_pattern_id: str, response_tx: MemoTransaction) -> bool:
        if request_pattern_id not in self.patterns:
            return False
        
        pattern = self.patterns[request_pattern_id]
        if pattern.transaction_type != InteractionType.REQUEST:
            return False

        return any(resp_pattern.matches(response_tx) for resp_pattern in pattern.valid_responses)

    def find_matching_pattern(self, tx: MemoTransaction) -> Optional[str]:
        """Find the first pattern ID whose pattern matches the transaction"""
        for pattern_id, pattern in self.patterns.items():
            if pattern.memo_pattern.matches(tx):
                return pattern_id
            continue
        return None
    
    def get_pattern_id_by_memo_pattern(self, memo_pattern: MemoPattern) -> Optional[str]:
        """Get the pattern ID for a given memo pattern"""
        return self.memo_pattern_to_id.get(memo_pattern)
    
@dataclass
class ValidationResult:
    """Result of a validation check"""
    valid: bool
    notes: Optional[str] = None

class InteractionRule(ABC):
    """Base class for interaction processing rules"""
    transaction_type: InteractionType

    @abstractmethod
    async def validate(self, tx: MemoTransaction, *args, **kwargs) -> ValidationResult:
        """
        Validate any additional business rules for an interaction
        This is separate from the interaction pattern matching
        """
        pass

@dataclass
class ResponseQuery:
    """Data class to hold query information for finding responses"""
    query: str
    params: Dict[str, Any]

class RequestRule(InteractionRule):
    """Base class for rules that handle request transactions"""
    transaction_type = InteractionType.REQUEST

    @abstractmethod
    async def validate(
        self,
        tx: MemoTransaction,
        dependencies: Dependencies
    ) -> ValidationResult:
        """Validate transaction against business rules"""
        pass

    @abstractmethod
    async def find_response(self, request_tx: MemoTransaction) -> Optional[ResponseQuery]:
        """Get query information for finding a valid response transaction"""
        pass

@dataclass
class MemoConstructionParameters:
    """
    Parameters for transaction construction.
    
    For standardized memos:
    - memo_type and memo_data are provided directly
    - memo_format will be constructed during processing
    
    For legacy memos:
    - memo contains the pre-constructed Memo object
    - memo_type and memo_data should be None
    """
    source: str  # Name of the address that should send the response
    destination: str  # XRPL destination address
    memo_type: Optional[str] = None  # Unique group ID for standardized memos
    memo_data: Optional[str] = None  # Payload for standardized memos
    pft_amount: Optional[Decimal] = None  # Optional PFT amount for the transaction
    should_encrypt: bool = False  # Whether the memo should be encrypted
    should_compress: bool = False  # Whether the memo should be compressed
    should_chunk: bool = False  # Whether the memo should be chunked
    processed_memo: Optional[Union[Memo, List[Memo]]] = None  # The final XRPL memo after processing

    @classmethod
    def construct_standardized_memo(
        cls,
        source: str,
        destination: str,
        memo_data: str,
        memo_type: str,
        should_encrypt: bool = False,
        should_compress: bool = False,
        pft_amount: Optional[Decimal] = None
    ) -> 'MemoConstructionParameters':
        """Create MemoConstructionParameters for a standardized memo."""
        return cls(
            source=source,
            destination=destination,
            memo_data=memo_data,
            memo_type=memo_type,
            should_encrypt=should_encrypt,
            should_compress=should_compress,
            pft_amount=pft_amount
        )

class ResponseGenerator(ABC):
    """Abstract base class defining how to generate a response"""
    @abstractmethod
    async def evaluate_request(self, request_tx: MemoTransaction) -> Dict[str, Any]:
        """Evaluate the request and return response parameters"""
        pass

    @abstractmethod
    async def construct_response(
        self, 
        request_tx: MemoTransaction,
        evaluation_result: Dict[str, Any]
    ) -> MemoConstructionParameters:
        """Construct the response memo and parameters"""
        pass

class ResponseRule(InteractionRule):
    """Base class for rules that handle response transactions"""
    transaction_type = InteractionType.RESPONSE

    @abstractmethod
    def get_response_generator(self, *args, **kwargs) -> ResponseGenerator:
        """
        Get the response generator for this rule type.
        
        Each rule implementation should document its required dependencies.
        """
        pass

class StandaloneRule(InteractionRule):
    """Base class for rules that handle standalone transactions"""
    transaction_type = InteractionType.STANDALONE
    
@dataclass
class BusinessLogicProvider(ABC):
    """Abstract base class that defines required business logic interface"""
    transaction_graph: InteractionGraph
    pattern_rule_map: Dict[str, InteractionRule]  # Maps pattern_id to rule instance

    @classmethod
    @abstractmethod
    def create(cls) -> 'BusinessLogicProvider':
        """Factory method that implementations must provide"""
        pass
