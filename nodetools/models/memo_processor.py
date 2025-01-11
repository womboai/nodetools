# Standard imports
from typing import List, Dict, Any, Optional, Union
import re
import traceback
import asyncio
import math
import binascii
from datetime import datetime
import random
import string
# Third party imports
from xrpl.models import Memo
from xrpl.utils import str_to_hex
from xrpl.wallet import Wallet
from loguru import logger
from cryptography.fernet import InvalidToken
# Local imports
from nodetools.models.models import MemoGroup, MemoStructure, MemoDataStructureType, MemoConstructionParameters, MemoTransaction
from nodetools.utilities.compression import compress_data, decompress_data, CompressionError
from nodetools.protocols.encryption import MessageEncryption
from nodetools.protocols.credentials import CredentialManager
from nodetools.utilities.credentials import SecretType
from nodetools.configuration.configuration import NodeConfig
from nodetools.utilities.exceptions import HandshakeRequiredException
from nodetools.configuration.constants import MAX_CHUNK_SIZE, XRP_MEMO_STRUCTURAL_OVERHEAD
from nodetools.configuration.constants import SystemMemoType

class MemoProcessor:
    """Entry point for memo processing"""
    
    @staticmethod
    async def parse_group(
        group: MemoGroup,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> Optional[str]:
        """
        FROM NODE'S PERSPECTIVE ONLY: Parse a complete group of memos.
        
        Parsing occurs in a fixed order:
        1. Unchunk (if chunked)
        2. Decompress (if compressed)
        3. Decrypt (if encrypted)
        
        For encrypted messages, requires:
        - credential_manager: For accessing private keys
        - message_encryption: For ECDH operations
        - node_config: For determining secret types
        
        Raises ValueError if group is incomplete or parsing fails.
        """
        if not group.memos:
            return None
        
        first_tx = group.memos[0]
        structure = MemoStructure.from_transaction(first_tx)

        if not structure.is_valid_format:
            return None
    
        if not StandardizedMemoProcessor.validate_group(group):
            logger.warning("Invalid standardized format group")
            return None
        
        return await StandardizedMemoProcessor.parse_group(
            group,
            credential_manager=credential_manager,
            message_encryption=message_encryption,
            node_config=node_config
        )
        
    @staticmethod
    async def construct_group(
        memo_params: MemoConstructionParameters,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> MemoGroup:
        """
        FROM NODE'S PERSPECTIVE ONLY: Construct memo(s) from response parameters.
        Processing occurs in a fixed order:
        1. Encrypt (if specified)
        2. Compress (if specified)
        3. Chunk (memos are always chunked)

        Args:
            memo_params: Contains raw memo data and structure
            credential_manager: Required for encryption
            message_encryption: Required for encryption
            node_config: Required for encryption

        Returns:
            MemoGroup containing a single Memo or list of Memos if chunked

        Raises:
            ValueError: If encryption is requested but required parameters are missing
        """
        return await StandardizedMemoProcessor.construct_group(
            memo_params,
            credential_manager=credential_manager,
            message_encryption=message_encryption,
            node_config=node_config
        )
        
    @staticmethod
    async def construct_group_generic(
        memo_params: MemoConstructionParameters,
        wallet: Wallet,
        message_encryption: Optional[MessageEncryption] = None,
    ) -> MemoGroup:
        """
        Construct memo(s) from response parameters.
        Processing occurs in a fixed order:
        1. Encrypt (if specified)
        2. Compress (if specified)
        3. Chunk (memos are always chunked)

        Args:
            memo_params: Contains raw memo data and structure
            wallet: Wallet to use for encryption
            message_encryption: Required for encryption

        Returns:
            MemoGroup containing a single Memo or list of Memos if chunked

        Raises:
            ValueError: If encryption is requested but required parameters are missing
        """
        return await StandardizedMemoProcessor.construct_group_generic(
            memo_params,
            wallet,
            message_encryption=message_encryption,
        )

def generate_custom_id():
    """ Generate a unique memo_type """
    letters = ''.join(random.choices(string.ascii_uppercase, k=2))
    numbers = ''.join(random.choices(string.digits, k=2))
    second_part = letters + numbers
    date_string = datetime.now().strftime("%Y-%m-%d %H:%M")
    output= date_string+'__'+second_part
    output = output.replace(' ',"_")
    return output

def to_hex(string):
    return binascii.hexlify(string.encode()).decode()

def hex_to_text(hex_string):
    bytes_object = bytes.fromhex(hex_string)
    try:
        ascii_string = bytes_object.decode("utf-8")
        return ascii_string
    except UnicodeDecodeError:
        return bytes_object  # Return the raw bytes if it cannot decode as utf-8
    
def construct_encoded_memo(memo_format, memo_type, memo_data):
    """Constructs a memo object with hex-encoded fields, ready for XRPL submission"""
    return Memo(
        memo_data=to_hex(memo_data),
        memo_type=to_hex(memo_type),
        memo_format=to_hex(memo_format)
    )

def encode_memo(memo: Memo) -> Memo:
    """Converts a Memo object with plaintext fields to a Memo object with hex-encoded fields"""
    return Memo(
        memo_data=to_hex(memo.memo_data),
        memo_type=to_hex(memo.memo_type),
        memo_format=to_hex(memo.memo_format)
    )

def decode_memo_fields_to_dict(memo: Union[Memo, dict]) -> Dict[str, Any]:
    """Decodes hex-encoded XRP memo fields from a dictionary to a more readable dictionary format."""
    if hasattr(memo, 'memo_format'):  # This is a Memo object
        fields = {
            'memo_format': memo.memo_format,
            'memo_type': memo.memo_type,
            'memo_data': memo.memo_data
        }
    else:  # This is a dictionary from transaction JSON
        fields = {
            'memo_format': memo.get('MemoFormat', ''),
            'memo_type': memo.get('MemoType', ''),
            'memo_data': memo.get('MemoData', '')
        }
    
    return {
        key: hex_to_text(value or '')
        for key, value in fields.items()
    }

def calculate_memo_size(memo_format: str, memo_type: str, memo_data: str) -> dict:
    """
    Calculates the size components of a memo using consistent logic.
    
    Args:
        memo_format: The format field (usually username)
        memo_type: The type field (usually task_id)
        memo_data: The data field (the actual content)
        
    Returns:
        dict: Size breakdown including:
            - format_size: Size of hex-encoded format
            - type_size: Size of hex-encoded type
            - data_size: Size of hex-encoded data
            - structural_overhead: Fixed overhead for JSON structure
            - total_size: Total size including all components
    """
    format_size = len(str_to_hex(memo_format))
    type_size = len(str_to_hex(memo_type))
    data_size = len(str_to_hex(memo_data))
    structural_overhead = XRP_MEMO_STRUCTURAL_OVERHEAD

    # logger.debug(f"Memo size breakdown:")
    # logger.debug(f"  format_size: {format_size}")
    # logger.debug(f"  type_size: {type_size}")
    # logger.debug(f"  data_size: {data_size}")
    # logger.debug(f"  structural_overhead: {structural_overhead}")
    # logger.debug(f"  total_size: {format_size + type_size + data_size + structural_overhead}")

    return {
        'format_size': format_size,
        'type_size': type_size,
        'data_size': data_size,
        'structural_overhead': structural_overhead,
        'total_size': format_size + type_size + data_size + structural_overhead
    }

def calculate_required_chunks(
        memo: Memo, 
        max_size: int = MAX_CHUNK_SIZE
    ) -> int:
    """
    Calculates how many chunks will be needed to send a memo.
    
    Args:
        memo: Memo object to analyze
        max_size: Maximum size in bytes for each complete Memo object
        
    Returns:
        int: Number of chunks required
        
    Raises:
        ValueError: If the memo cannot be chunked (overhead too large)
    """
    memo_format = memo.memo_format
    memo_type = memo.memo_type
    memo_data = memo.memo_data

    # logger.debug(f"Deconstructed (plaintext) memo sizes: "
    #             f"memo_format: {len(memo_format)}, "
    #             f"memo_type: {len(memo_type)}, "
    #             f"memo_data: {len(memo_data)}")

    # Calculate overhead sizes
    size_info = calculate_memo_size(memo_format, memo_type, "chunk_999__")  # assuming chunk_999__ is worst-case chunk label overhead
    max_data_size = max_size - size_info['total_size']

    # logger.debug(f"Size allocation:")
    # logger.debug(f"  Max size: {max_size}")
    # logger.debug(f"  Total overhead: {size_info['total_size']}")
    # logger.debug(f"  Available for data: {max_size} - {size_info['total_size']} = {max_data_size}")

    if max_data_size <= 0:
        raise ValueError(
            f"No space for data: max_size={max_size}, total_overhead={size_info['total_size']}"
        )
    
    # Calculate number of chunks needed
    data_bytes = memo_data.encode('utf-8')
    required_chunks = math.ceil(len(data_bytes) / max_data_size)
    required_chunks = 1 if required_chunks == 0 else required_chunks
    return required_chunks

def chunk_memos(
        memo: Memo, 
        max_size: int = MAX_CHUNK_SIZE
    ) -> List[Memo]:
    """
    Splits a Memo object into multiple Memo objects, each under MAX_CHUNK_SIZE bytes.
    Updates memo_format with chunk metadata before constructing final Memo objects.
    
    Args:
        memo: Memo object to be chunked
        max_size: Maximum size in bytes for each complete Memo object

    Returns:
        List of unencoded Memo objects ready for final processing
    """
    memo_format = memo.memo_format
    memo_type = memo.memo_type
    memo_data = memo.memo_data

    # Calculate chunks needed and validate size
    num_chunks = calculate_required_chunks(memo, max_size)
    chunk_size = len(memo_data.encode('utf-8')) // num_chunks
            
    # Split into chunks
    chunked_memos = []
    data_bytes = memo_data.encode('utf-8')
    for chunk_number in range(1, num_chunks + 1):
        start_idx = (chunk_number - 1) * chunk_size
        end_idx = start_idx + chunk_size if chunk_number < num_chunks else len(data_bytes)
        chunk = data_bytes[start_idx:end_idx]
        chunk_memo_data = chunk.decode('utf-8', errors='ignore')

        # Debug the sizes
        # test_format = str_to_hex(memo_format)
        # test_type = str_to_hex(memo_type)
        # test_data = str_to_hex(chunk_memo_data)
        
        # logger.debug(f"Chunk {chunk_number} sizes:")
        # logger.debug(f"  Plaintext Format size: {len(memo_format)}")
        # logger.debug(f"  Plaintext Type size: {len(memo_type)}")
        # logger.debug(f"  Plaintext Data size: {len(chunk_memo_data)}")
        # logger.debug(f"  Plaintext Total size: {len(memo_format) + len(memo_type) + len(chunk_memo_data)}")
        # logger.debug(f"  Hex Format size: {len(test_format)}")
        # logger.debug(f"  Hex Type size: {len(test_type)}")
        # logger.debug(f"  Hex Data size: {len(test_data)}")
        # logger.debug(f"  Hex Total size: {len(test_format) + len(test_type) + len(test_data)}")
        
        chunk_memo = Memo(
            memo_format=memo_format,
            memo_type=memo_type,
            memo_data=chunk_memo_data
        )

        chunked_memos.append(chunk_memo)

    return chunked_memos

class StandardizedMemoProcessor:
    """Handles processing of new standardized format memos"""

    @staticmethod
    def _determine_secret_type(address: str, node_config: NodeConfig) -> SecretType:
        """Determines SecretType based on address"""
        if address == node_config.node_address:
            return SecretType.NODE
        elif address == node_config.remembrancer_address:
            return SecretType.REMEMBRANCER
        else:
            raise ValueError(f"No SecretType found for address: {address}")
        
    @staticmethod
    async def parse_group(
        group: MemoGroup,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> str:
        """
        Parse a complete group of standardized format memos.
        The memo_format (e.g., "e.b.c1/4") indicates which processing steps are needed:
        - 'c' indicates chunking
        - 'b' indicates brotli compression
        - 'e' indicates ECDH encryption
        
        Parsing occurs in a fixed order:
        1. Unchunk (if chunked)
        2. Decompress (if compressed)
        3. Decrypt (if encrypted)
        
        For encrypted messages, requires:
        - credential_manager: For accessing private keys
        - message_encryption: For ECDH operations
        - node_config: For determining secret types
        
        Raises ValueError if group is incomplete or parsing fails.
        """
        await asyncio.sleep(0)  # Ensure this is a coroutine
        if not group.memos:
            raise ValueError("Empty group")
        
        structure = MemoStructure.from_transaction(group.memos[0])
        if not structure.is_valid_format:
            raise ValueError("Not a standardized format group")
        
        # For chunked messages, verify completeness and join
        if structure.is_chunked:
            if not structure.total_chunks:
                raise ValueError("Chunked message missing total_chunks")
                
            # Verify we have all chunks
            chunk_indices = group.chunk_indices
            if len(chunk_indices) != structure.total_chunks:
                raise ValueError(f"Missing chunks. Have {len(chunk_indices)}/{structure.total_chunks}")
                
            # Sort and join chunks
            sorted_msgs = sorted(
                group.memos,
                key=lambda tx: MemoStructure.from_transaction(tx).chunk_index or 0
            )
            
            processed_data = ''
            for tx in sorted_msgs:
                processed_data += tx.memo_data
                
        else:
            # Single message
            processed_data = group.memos[0].memo_data
        
        # Apply decompression if specified
        if structure.compression_type == MemoDataStructureType.BROTLI:
            try:
                processed_data = decompress_data(processed_data)
            except CompressionError as e:
                logger.error(f"Decompression failed for group {group.group_id}: {e}")
                raise
                
        # Handle encryption if specified
        if structure.encryption_type == MemoDataStructureType.ECDH:
            if not all([credential_manager, message_encryption, node_config]):
                logger.warning(
                    "Cannot decrypt message - missing required parameters. "
                    f"Need credential_manager: {bool(credential_manager)}, "
                    f"message_encryption: {bool(message_encryption)}, "
                    f"node_config: {bool(node_config)}"
                )
                return processed_data

            # Get channel details from first transaction
            first_tx = group.memos[0]

            # Channel addresses and channel counterparties vary depending on the direction of the message
            # For example, if the message is from the node to the user, the account is the node's address and the destination is the user's address
            # But the channel address must always be the node's address, and the channel counterparty must always be the user's address
            # node_config.auto_handshake_addresses corresponds to the node's addresses that support encrypted channels
            if first_tx.destination in node_config.auto_handshake_addresses:
                channel_address = first_tx.destination
                channel_counterparty = first_tx.account
            else:  # The message is from the user to the node
                channel_address = first_tx.account
                channel_counterparty = first_tx.destination

            try:
                # Determine secret type based on receiving address
                secret_type = StandardizedMemoProcessor._determine_secret_type(channel_address, node_config)
            
                # Get handshake keys
                channel_key, counterparty_key = await message_encryption.get_handshake_for_address(
                    channel_address=channel_address,
                    channel_counterparty=channel_counterparty
                )
                if not (channel_key and counterparty_key):
                    logger.warning("Cannot decrypt message - no handshake found")
                    return processed_data

                # Get shared secret using credential manager's API
                shared_secret = credential_manager.get_shared_secret(
                    received_key=counterparty_key,
                    secret_type=secret_type
                )
                processed_data = message_encryption.process_encrypted_message(
                    processed_data, 
                    shared_secret
                )
            except Exception as e:
                logger.error(
                    f"StandardizedMemoProcessor.process_group: Error decrypting message {group.group_id} "
                    f"between address {channel_address} and counterparty {channel_counterparty}: {e}"
                )
                logger.error(traceback.format_exc())
                return f"[Decryption Failed] {processed_data}"
            
        return processed_data
    
    @staticmethod
    def validate_group(group: MemoGroup) -> bool:
        """
        Validate that all messages in the group have consistent structure.
        """
        if not group.memos:
            return False
            
        first_structure = MemoStructure.from_transaction(group.memos[0])
        if not first_structure.is_valid_format:
            return False
            
        # Check all messages have same format
        for msg in group.memos[1:]:
            structure = MemoStructure.from_transaction(msg)
            if not structure.is_valid_format:
                return False
                
            if (structure.encryption_type != first_structure.encryption_type or
                structure.compression_type != first_structure.compression_type or
                structure.total_chunks != first_structure.total_chunks):
                return False
                
        return True
    
    def construct_final_memo(
        memo_format_prefix: str,  # e.g., "v1.e.b" or "v1.-.-"
        memo_type: str,
        memo_data: str,
        chunk_info: Optional[tuple[int, int]] = None  # (chunk_number, total_chunks)
    ) -> Memo:
        """
        Constructs the final memo with complete format string.
        
        Args:
            memo_format_prefix: Partial format string with version and processing flags
            memo_type: The memo type/group id
            memo_data: The processed memo data
            chunk_info: Optional tuple of (chunk_number, total_chunks)
        
        Returns:
            Memo with complete format string
        """
        # Finalize format string with chunk information
        if chunk_info:
            chunk_number, total_chunks = chunk_info
            memo_format = f"{memo_format_prefix}.c{chunk_number}/{total_chunks}"
        else:
            memo_format = f"{memo_format_prefix}.-"
            
        return construct_encoded_memo(
            memo_format=memo_format,
            memo_type=memo_type,
            memo_data=memo_data
        )

    @staticmethod
    async def construct_group(
        memo_params: MemoConstructionParameters,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> MemoGroup:
        """
        Construct standardized format memo(s) from response parameters.
        Processing occurs in a fixed order:
        1. Encrypt (if specified)
        2. Compress (if specified)
        3. Chunk (memos are always chunked)
        4. Final hex encoding for XRPL submission

        Args:
            memo_params: Contains raw memo data and structure
            credential_manager: Required for encryption
            message_encryption: Required for encryption
            node_config: Required for encryption

        Returns:
            MemoGroup containing a single Memo or list of Memos if chunked

        Raises:
            ValueError: If encryption is requested but required parameters are missing
        """
        await asyncio.sleep(0)  # Ensure this is a coroutine
        processed_data = memo_params.memo_data

        # Handle encryption if specified
        encryption_type = MemoDataStructureType.NONE.value
        if memo_params.should_encrypt:
            if not all([credential_manager, message_encryption, node_config]):
                raise ValueError("Missing required parameters for encryption")

            try:
                # Get handshake keys
                channel_key, counterparty_key = await message_encryption.get_handshake_for_address(
                    channel_address=memo_params.source,
                    channel_counterparty=memo_params.destination
                )
                if not (channel_key and counterparty_key):
                    raise HandshakeRequiredException(memo_params.source, memo_params.destination)
                
                # Get shared secret and encrypt
                secret_type = StandardizedMemoProcessor._determine_secret_type(
                    address=memo_params.source,
                    node_config=node_config
                )
                shared_secret = credential_manager.get_shared_secret(
                    received_key=counterparty_key,
                    secret_type=secret_type
                )
                processed_data = message_encryption.encrypt_memo(
                    processed_data,
                    shared_secret
                )
                encryption_type = MemoDataStructureType.ECDH.value
            except Exception as e:
                logger.error(f"StandardizedMemoProcessor.construct_group: Error encrypting memo: {e}")
                raise

        # Handle compression if specified
        compression_type = MemoDataStructureType.NONE.value
        if memo_params.should_compress:
            try:
                processed_data = compress_data(processed_data)
                compression_type = MemoDataStructureType.BROTLI.value
            except CompressionError as e:
                logger.error(f"StandardizedMemoProcessor.construct_group: Error compressing memo: {e}")
                raise

        # Create base unencoded Memo
        base_memo = Memo(
            memo_format=f"{encryption_type}.{compression_type}",  # Format prefix
            memo_type=memo_params.memo_type,
            memo_data=processed_data
        )

        # Get chunked memos
        chunked_memos = chunk_memos(base_memo)
        
        # Construct final memos with complete memo_format strings
        memos = []
        for idx, memo in enumerate(chunked_memos, 1):
            memo_format = f"{memo.memo_format}.c{idx}/{len(chunked_memos)}"
            memo = construct_encoded_memo(
                memo_format=memo_format,
                memo_type=memo.memo_type,
                memo_data=memo.memo_data
            )
            memos.append(memo)

        return MemoGroup.create_from_memos(memos=memos)
    
    @staticmethod
    async def construct_group_generic(
        memo_params: MemoConstructionParameters,
        wallet: Optional[Wallet] = None,
        message_encryption: Optional[MessageEncryption] = None
    ) -> MemoGroup:
        """
        Construct standardized format memo(s) from response parameters.
        Processing occurs in a fixed order:
        1. Encrypt (if specified)
        2. Compress (if specified)
        3. Chunk (memos are always chunked)
        4. Final hex encoding for XRPL submission

        Args:
            response_params: Contains raw memo data and structure
            credential_manager: Required for encryption
            message_encryption: Required for encryption
            node_config: Required for encryption

        Returns:
            MemoGroup containing a single Memo or list of Memos if chunked

        Raises:
            ValueError: If encryption is requested but required parameters are missing
        """
        await asyncio.sleep(0)  # Ensure this is a coroutine
        processed_data = memo_params.memo_data
        memo_type = memo_params.memo_type or generate_custom_id()

        # Handle encryption if specified
        encryption_type = MemoDataStructureType.NONE.value
        if memo_params.should_encrypt:
            if not all([wallet, message_encryption]):
                raise ValueError("Missing required parameters for encryption")

            try:
                # Get handshake keys
                channel_key, counterparty_key = await message_encryption.get_handshake_for_address(
                    channel_address=memo_params.source,
                    channel_counterparty=memo_params.destination
                )
                if not (channel_key and counterparty_key):
                    raise HandshakeRequiredException(memo_params.source, memo_params.destination)
                
                # Get shared secret and encrypt
                shared_secret = message_encryption.get_shared_secret(
                    received_key=counterparty_key,
                    channel_private_key=wallet.seed
                )
                processed_data = message_encryption.encrypt_memo(
                    processed_data,
                    shared_secret
                )
                encryption_type = MemoDataStructureType.ECDH.value
            except Exception as e:
                logger.error(f"StandardizedMemoProcessor.construct_group: Error encrypting memo: {e}")
                raise

        # Handle compression if specified
        compression_type = MemoDataStructureType.NONE.value
        if memo_params.should_compress:
            try:
                processed_data = compress_data(processed_data)
                compression_type = MemoDataStructureType.BROTLI.value
            except CompressionError as e:
                logger.error(f"StandardizedMemoProcessor.construct_group: Error compressing memo: {e}")
                raise

        # Create base unencoded Memo
        base_memo = Memo(
            memo_format=f"{encryption_type}.{compression_type}",  # Format prefix
            memo_type=memo_type,
            memo_data=processed_data
        )

        # Get chunked memos
        chunked_memos = chunk_memos(base_memo)
        
        # Construct final memos with complete memo_format strings
        memos = []
        for idx, memo in enumerate(chunked_memos, 1):
            memo_format = f"{memo.memo_format}.c{idx}/{len(chunked_memos)}"
            memo = construct_encoded_memo(
                memo_format=memo_format,
                memo_type=memo.memo_type,
                memo_data=memo.memo_data
            )
            memos.append(memo)

        return MemoGroup.create_from_memos(memos=memos)

# class LegacyMemoProcessor:
#     """Handles processing of legacy format memos"""
    
#     @staticmethod
#     def _determine_secret_type(address: str, node_config: NodeConfig) -> SecretType:
#         """Determine the SecretType based on the address"""
#         if address == node_config.node_address:
#             return SecretType.NODE
#         elif address == node_config.remembrancer_address:
#             return SecretType.REMEMBRANCER
#         else:
#             raise ValueError(f"No SecretType found for address: {address}")

#     @staticmethod
#     async def parse_group(
#         group: MemoGroup, 
#         credential_manager: Optional[CredentialManager] = None,
#         message_encryption: Optional[MessageEncryption] = None,
#         node_config: Optional[NodeConfig] = None
#     ) -> str:
#         """
#         Parse a complete sequence of chunks.
        
#         Parsing steps:
#         1. Sort by chunk index
#         2. Join chunks (removing chunk prefixes)
#         3. Decompress if first chunk indicates compression (COMPRESSED__ prefix)
#         4. Check for encryption after decompression (WHISPER__ prefix)

#         For encrypted messages (WHISPER__ prefix), requires:
#         - credential_manager: For accessing private keys
#         - message_encryption: For ECDH operations

#         Raises exception if parsing fails.
#         """
#         await asyncio.sleep(0)  # Ensure this is a coroutine
#         if not group:
#             raise ValueError("Empty sequence")

#         # Sort memos in MemoGroup by chunk index
#         sorted_sequence = sorted(
#             group.memos,
#             key=lambda tx: MemoStructure.from_transaction(tx).chunk_index or 0
#         )

#         # Join chunks (removing chunk prefixes)
#         processed_data = ''
#         for tx in sorted_sequence:
#             chunk_data = tx.memo_data
#             if chunk_match := re.match(r'^chunk_\d+__', chunk_data):
#                 chunk_data = chunk_data[len(chunk_match.group(0)):]
#             processed_data += chunk_data

#         # Handle decompression
#         if processed_data.startswith('COMPRESSED__'):
#             processed_data = processed_data.replace('COMPRESSED__', '', 1)
#             try:
#                 processed_data = decompress_data(processed_data)
#             except CompressionError: 
#                 # This will happen often with legacy memos since they're processed asynchronously and system may not have all chunks yet
#                 raise

#         # Handle decryption
#         if processed_data.startswith('WHISPER__'):
#             if not all([credential_manager, message_encryption]):
#                 logger.warning(
#                     "Cannot decrypt message - missing required parameters. "
#                     f"Need credential_manager: {bool(credential_manager)}, "
#                     f"message_encryption: {bool(message_encryption)}"
#                 )
#                 return processed_data
            
#             # Get channel details from first transaction
#             first_tx = sorted_sequence[0]

#             # Channel addresses and channel counterparties vary depending on the direction of the message
#             # For example, if the message is from the node to the user, the account is the node's address and the destination is the user's address
#             # But the channel address must always be the node's address, and the channel counterparty must always be the user's address
#             # node_config.auto_handshake_addresses corresponds to the node's addresses that support encrypted channels
#             if first_tx.destination in node_config.auto_handshake_addresses:
#                 channel_address = first_tx.destination
#                 channel_counterparty = first_tx.account
#             else:  # The message is from the user to the node
#                 channel_address = first_tx.account
#                 channel_counterparty = first_tx.destination
            
#             try:
#                 # Determine secret type based on receiving address
#                 secret_type = LegacyMemoProcessor._determine_secret_type(channel_address, node_config)
            
#                 # Get handshake keys
#                 channel_key, counterparty_key = await message_encryption.get_handshake_for_address(
#                     channel_address=channel_address,
#                     channel_counterparty=channel_counterparty
#                 )
#                 if not (channel_key and counterparty_key):
#                     logger.warning("LegacyMemoProcessor.process_group: Cannot decrypt message - no handshake found")
#                     return processed_data
            
#                 # Get shared secret using credential manager's API
#                 shared_secret = credential_manager.get_shared_secret(
#                     received_key=counterparty_key, 
#                     secret_type=secret_type
#                 )
#                 processed_data = message_encryption.process_encrypted_message(
#                     processed_data, 
#                     shared_secret
#                 )

#             except InvalidToken:
#                 # This will happen often with legacy memos since they're processed asynchronously and system may not have all chunks yet
#                 raise

#             except Exception as e:
#                 message = (
#                     f"LegacyMemoProcessor.process_group: Error decrypting message {group.group_id} "
#                     f"between address {channel_address} and counterparty {channel_counterparty}: {processed_data}"
#                 )
#                 logger.error(message)
#                 logger.error(traceback.format_exc())
#                 return f"[Decryption Failed] {processed_data}"

#         return processed_data
    
#     @staticmethod
#     async def construct_group(
#         response_params: MemoConstructionParameters,
#         credential_manager: Optional[CredentialManager] = None,
#         message_encryption: Optional[MessageEncryption] = None,
#         node_config: Optional[NodeConfig] = None
#     ) -> MemoGroup:
#         """
#         Construct a group of legacy format memos.
#         Processing order: encrypt → compress → chunk
        
#         Legacy format uses prefixes in memo_data:
#         1. WHISPER__ for encrypted data
#         2. COMPRESSED__ for compressed data (only in first chunk)
#         3. chunk_N__ for chunked data
#         4. Final hex encoding for XRPL submission
#         """
#         await asyncio.sleep(0)  # Ensure this is a coroutine
#         processed_data = response_params.memo.memo_data

#         # Handle encryption if specified
#         if response_params.should_encrypt:
#             if not all([credential_manager, message_encryption]):
#                 raise ValueError("Missing required parameters for encryption")

#             try:
#                 # Get handshake keys
#                 channel_key, counterparty_key = await message_encryption.get_handshake_for_address(
#                     channel_address=response_params.source,
#                     channel_counterparty=response_params.destination
#                 )
#                 if not (channel_key and counterparty_key):
#                     raise HandshakeRequiredException(response_params.source, response_params.destination)
                
#                 # Get shared secret and encrypt
#                 secret_type = StandardizedMemoProcessor._determine_secret_type(
#                     address=response_params.source,
#                     node_config=node_config
#                 )
#                 shared_secret = credential_manager.get_shared_secret(
#                     received_key=counterparty_key,
#                     secret_type=secret_type
#                 )
#                 processed_data = message_encryption.encrypt_memo(
#                     processed_data,
#                     shared_secret
#                 )
#             except Exception as e:
#                 logger.error(f"LegacyMemoProcessor.construct_group: Error encrypting memo: {e}")
#                 raise

#         # Handle compression if specified
#         if response_params.should_compress:
#             try:
#                 processed_data = compress_data(processed_data)
#                 # Only add COMPRESSED__ prefix to first chunk
#                 processed_data = f"COMPRESSED__{processed_data}"
#             except CompressionError as e:
#                 logger.error(f"Compression failed: {e}")
#                 raise

#         # Create base unencoded Memo to pass to chunk_memos
#         base_memo = Memo(
#             memo_format=response_params.memo.memo_format,
#             memo_type=response_params.memo.memo_type,
#             memo_data=processed_data
#         )

#         # Legacy memos should not always be chunked
#         # System memo types cannot be chunked
#         # Check if this is a system memo type
#         is_system_memo = any(
#             base_memo.memo_type == system_type.value 
#             for system_type in SystemMemoType
#         )
#         required_chunks = calculate_required_chunks(memo=base_memo, max_size=MAX_CHUNK_SIZE)

#         if is_system_memo and response_params.should_chunk and required_chunks > 1:
#             raise ValueError("System memo types cannot be chunked via the legacy memo format")
        
#         elif response_params.should_chunk or required_chunks > 1:
#             # Get chunked memos (chunk-memos will add the chunk_N__ prefixes to memo_data)
#             chunked_memos = chunk_memos(base_memo, legacy=True)
#             # Encode each chunk for XRPL
#             encoded_memos = [encode_memo(memo) for memo in chunked_memos]

#             return MemoGroup.create_from_memos(memos=encoded_memos)
            
#         else:
#             # Single memo case - encode for XRPL
#             encoded_memo = encode_memo(base_memo)
#             return MemoGroup.create_from_memos(memos=[encoded_memo])
