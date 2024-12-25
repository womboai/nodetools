from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Set, Optional, Dict, Any, Pattern, TYPE_CHECKING, List
from enum import Enum
from loguru import logger
from decimal import Decimal
from xrpl.models import Memo
import re

if TYPE_CHECKING:
    from nodetools.protocols.credentials import CredentialManager
    from nodetools.protocols.generic_pft_utilities import GenericPFTUtilities
    from nodetools.protocols.openrouter import OpenRouterTool
    from nodetools.protocols.transaction_repository import TransactionRepository
    from nodetools.configuration.configuration import NodeConfig

class InteractionType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    STANDALONE = "standalone"

class MemoDataStructureType(Enum):
    ECDH = "e"      # Encryption
    BROTLI = "b"    # Compression
    CHUNK = "c"     # Chunking
    NONE = "-"      # No processing

@dataclass
class MessageStructure:
    """Describes how a message is structured across transactions"""
    is_chunked: bool
    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None
    group_id: Optional[str] = None
    compression_type: Optional[MemoDataStructureType] = None  # Might be unknown until processing
    encryption_type: Optional[MemoDataStructureType] = None   # Might be unknown until processing

    @property
    def is_complete(self) -> bool:
        """Whether this represents a complete message"""
        return not self.is_chunked  # A non-chunked message is always complete
    
    @classmethod
    def from_transaction(cls, tx: Dict[str, Any]) -> 'MessageStructure':
        """
        Extract message structure from transaction memo fields.
        Tries new standardized memo_format first, falls back to legacy memo_data prefixes.
        
        New format examples:
            "e.b.c1/4"                    # encrypted, compressed, chunk 1 of 4
            "-.b.c2/4"                    # not encrypted, compressed, chunk 2 of 4
            "-.-.-"                       # no special processing
            "invalid_format"              # Invalid - will fall back to legacy
        
        Legacy format example: 
            memo_data with "chunk_1__" prefix and nested "COMPRESSED__" and "WHISPER__" prefixes

        Legacy format caveats:
        1. COMPRESSED__ prefix only appears in first chunk
        2. WHISPER__ prefix only visible after decompression
        3. Structure might need to be updated after processing
        
        Examples:
            First chunk:  "chunk_1__COMPRESSED__<compressed_data>"
            Other chunks: "chunk_2__<compressed_data>"
            After joining and decompressing: "WHISPER__<encrypted_data>"
        """
        memo_data = tx.get("memo_data")
        memo_format = tx.get("memo_format")

        # Try parsing standardized memo_format first
        if memo_format:
            try:
                parts = memo_format.split(".")
                if len(parts) != 3:
                    raise ValueError(f"Invalid memo_format structure: {memo_format}")
                
                encryption, compression, chunking = parts

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
                chunk_index, total_chunks = None, None
                if chunking.startswith(MemoDataStructureType.CHUNK.value):
                    chunk_match = re.match(
                        f'{MemoDataStructureType.CHUNK.value}(\d+)/(\d+)', 
                        chunking
                    )
                    if not chunk_match:
                        raise ValueError(f"Invalid chunking format: {chunking}")
                    chunk_index = int(chunk_match.group(1))
                    total_chunks = int(chunk_match.group(2))
                
                return cls(
                    is_chunked=chunk_index is not None and total_chunks is not None,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    group_id=tx.get("memo_type"),
                    compression_type=compression_type,
                    encryption_type=encryption_type,
                )
            except (ValueError, AttributeError) as e:
                logger.warning(f"Invalid standardized memo_format '{memo_format}', falling back to legacy format parsing: {e}")

        # Fall back to legacy prefix detection
        chunk_match = re.match(r'^chunk_(\d+)__', memo_data)
        
        # Only check compression on first chunk
        is_compressed = (
            "COMPRESSED__" in memo_data 
            if chunk_match and chunk_match.group(1) == "1" 
            else None  # Unknown for other chunks
        )
        
        # Can't determine encryption status from raw memo_data
        is_encrypted = None  # Will be determined after processing
        
        return cls(
            is_chunked=chunk_match is not None,
            chunk_index=int(chunk_match.group(1)) if chunk_match else None,
            total_chunks=None,  # Legacy format doesn't specify total chunks
            group_id=tx.get("memo_type"),
            compression_type=MemoDataStructureType.BROTLI if is_compressed else None,
            encryption_type=is_encrypted
        )
    
    def update_structure_after_processing(self, processed_data: str) -> None:
        """
        Update structure information after processing steps.
        Should be called after decompression to check for encryption.
        """
        if "WHISPER__" in processed_data:
            self.encryption_type = MemoDataStructureType.ECDH
    
@dataclass
class MessageGroup:
    """
    Manages a group of related messages.
    Messages are related if they share the same memo_type (group_id).
    """
    group_id: str
    messages: List[Dict[str, Any]]
    structure: Optional[MessageStructure] = None

    @classmethod
    def create_from_transaction(cls, tx: Dict[str, Any]) -> 'MessageGroup':
        """Create a new message group from an initial transaction"""
        structure = MessageStructure.from_transaction(tx)
        return cls(
            group_id=tx.get("memo_type"),
            messages=[tx],
            structure=structure,
        )
    
    def add_message(self, tx: Dict[str, Any]) -> bool:
        """
        Add a message to the group if it belongs.
        Returns True if message was added, False if it doesn't belong.
        """
        if tx.get("memo_type") != self.group_id:
            return False
        
        new_structure = MessageStructure.from_transaction(tx)
        if not new_structure.is_chunked:
            return False
        
        self.messages.append(tx)
        return True
    
    @property
    def chunk_indices(self) -> Set[int]:
        """Get set of available chunk indices"""
        return {
            MessageStructure.from_transaction(tx).chunk_index
            for tx in self.messages
            if MessageStructure.from_transaction(tx).chunk_index is not None
        }
    
    @property
    def is_sequential(self) -> bool:
        """
        Check if we have a sequential set of chunks with no duplicates.
        For example: {0,1,2} is sequential, {0,1,1,2} or {0,1,3} are not.
        """
        indices = self.chunk_indices
        if not indices:
            return False
        
        # Count occurrences of each index in messages
        index_counts = {}
        for tx in self.messages:
            idx = MessageStructure.from_transaction(tx).chunk_index
            if idx is not None:
                index_counts[idx] = index_counts.get(idx, 0) + 1
                if index_counts[idx] > 1:
                    return False  # Duplicate chunk found
        
        # Check for sequence completeness
        min_idx = min(indices)
        max_idx = max(indices)
        expected_indices = set(range(min_idx, max_idx + 1))
        return indices == expected_indices
    
    @abstractmethod
    async def try_decompress(self) -> Optional[str]:
        """
        Attempt to decompress all chunks in the group.
        Returns decompressed message if successful, None if incomplete/failed.
        """
        pass

@dataclass(frozen=True)  # Making it immutable for hashability
class MemoPattern:
    """
    Defines patterns for matching processed XRPL memos.
    Matching occurs after any necessary unchunking/decompression/decryption.
    """
    memo_type: Optional[str | Pattern] = None
    memo_format: Optional[str | Pattern] = None
    memo_data: Optional[str | Pattern] = None

    def get_message_structure(self, tx: Dict[str, Any]) -> MessageStructure:
        """Extract structural information from the memo fields"""
        return MessageStructure.from_transaction(tx)

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
class MessagePattern:
    memo_pattern: MemoPattern
    content_pattern: Optional[ContentPattern] = None
    transaction_type: InteractionType
    valid_responses: Set[MemoPattern]

    def __post_init__(self):
        # Validate that RESPONSE types don't have valid_responses
        if self.transaction_type == InteractionType.RESPONSE and self.valid_responses:
            raise ValueError("RESPONSE types cannot have valid_responses")
        # Validate that REQUEST types must have valid_responses
        if self.transaction_type == InteractionType.REQUEST and not self.valid_responses:
            raise ValueError("REQUEST types must have valid_responses")

class MessageGraph:
    def __init__(self):
        self.patterns: Dict[str, MessagePattern] = {}
        self.memo_pattern_to_id: Dict[MemoPattern, str] = {}

    def add_pattern(
            self,
            pattern_id: str,
            memo_pattern: MemoPattern,
            transaction_type: InteractionType,
            valid_responses: Optional[Set[MemoPattern]] = None
    ) -> None:
        """
        Add a new pattern to the graph.
        For RESPONSE and STANDALONE types, valid_responses should be None or empty.
        For REQUEST types, valid_responses must be provided.
        """
        self.patterns[pattern_id] = MessagePattern(
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
        if pattern.transaction_type != InteractionType.REQUEST:
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

class MessageRule(ABC):
    """Base class for message processing rules"""
    @abstractmethod
    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate any additional business rules for a message
        This is separate from the message pattern matching
        """
        pass

    @property
    @abstractmethod
    def message_type(self) -> InteractionType:
        """Return the type of message this rule handles"""
        pass

@dataclass
class ResponseQuery:
    """Data class to hold query information for finding responses"""
    query: str
    params: Dict[str, Any]

class RequestRule(MessageRule):
    """Base class for rules that handle request transactions"""
    transaction_type = InteractionType.REQUEST

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

class ResponseRule(MessageRule):
    """Base class for rules that handle response transactions"""
    transaction_type = InteractionType.RESPONSE

    @abstractmethod
    def get_response_generator(self, *args, **kwargs) -> ResponseGenerator:
        """
        Get the response generator for this rule type.
        
        Each rule implementation should document its required dependencies.
        """
        pass

class StandaloneRule(MessageRule):
    """Base class for rules that handle standalone transactions"""
    transaction_type = InteractionType.STANDALONE
    
@dataclass
class BusinessLogicProvider:
    """Centralizes all business logic configuration"""
    transaction_graph: MessageGraph
    pattern_rule_map: Dict[str, MessageRule]  # Maps pattern_id to rule instance

@dataclass
class Dependencies:
    """Container for all possible dependencies needed by ResponseGenerators"""
    node_config: 'NodeConfig'
    credential_manager: 'CredentialManager'
    generic_pft_utilities: 'GenericPFTUtilities'
    openrouter: 'OpenRouterTool'
    transaction_repository: 'TransactionRepository'
