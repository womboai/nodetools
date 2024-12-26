# Standard imports
from typing import List, Dict, Any, Optional, Union
import re
import traceback
# Third party imports
import xrpl
from loguru import logger
# Local imports
from nodetools.models.models import MemoGroup, MemoStructure, MemoDataStructureType
from nodetools.utilities.compression import compress_data, decompress_data, CompressionError
from nodetools.protocols.encryption import MessageEncryption
from nodetools.protocols.credentials import CredentialManager
from nodetools.utilities.credentials import SecretType
from nodetools.configuration.configuration import NodeConfig

class LegacyMemoProcessor:
    """Handles processing of legacy format memos"""
    
    @staticmethod
    def find_complete_group(group: MemoGroup) -> Optional[MemoGroup]:
        """
        Find first complete sequence of chunks that can be processed.
        Handles cases where duplicate sequences exist due to retries/errors.
        
        Returns None if no complete sequence is found.
        """
        if not group.messages:
            return None
        
        current_sequence = []
        highest_chunk_num = 0
        sequences = []  # List to store all found sequences

        # Sort messages by datetime to process in order
        sorted_msgs = sorted(group.messages, key=lambda tx: tx.get('datetime'))

        for msg in sorted_msgs:
            structure = MemoStructure.from_transaction(msg)
            if not structure.chunk_index:
                continue

            # If we see chunk_1 and already have chunks, this might be a new sequence
            if structure.chunk_index == 1 and current_sequence:
                # Check if previous sequence was complete
                expected_chunks = set(range(1, highest_chunk_num + 1))
                actual_chunks = {
                    MemoStructure.from_transaction(tx).chunk_index 
                    for tx in current_sequence
                }

                if expected_chunks == actual_chunks:
                    # First sequence is complete, add it to our list
                    sequences.append(current_sequence.copy())
                
                # Start fresh sequence either way
                current_sequence = []
                highest_chunk_num = 0

            current_sequence.append(msg)
            highest_chunk_num = max(highest_chunk_num, structure.chunk_index)

        # Don't forget to check the last sequence
        if current_sequence:
            expected_chunks = set(range(1, highest_chunk_num + 1))
            actual_chunks = {
                MemoStructure.from_transaction(tx).chunk_index 
                for tx in current_sequence
            }
            if expected_chunks == actual_chunks:
                sequences.append(current_sequence)

        # Try each sequence until we find one that successfully processes
        for sequence in sequences:
            try:
                # Just attempt to process - if it works, this is our sequence
                LegacyMemoProcessor.process_group(sequence)
                return sequence
            except Exception as e:
                logger.debug(f"Sequence processing failed: {e}")
                continue

        return None
    
    @staticmethod
    def _determine_secret_type(address: str, node_config: NodeConfig) -> SecretType:
        """Determine the SecretType based on the address"""
        if address == node_config.node_address:
            return SecretType.NODE
        elif address == node_config.remembrancer_address:
            return SecretType.REMEMBRANCER
        else:
            raise ValueError(f"No SecretType found for address: {address}")

    @staticmethod
    def process_group(
        sequence: List[Dict[str, Any]], 
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> str:
        """
        Process a complete sequence of chunks.
        
        Processing steps:
        1. Sort by chunk index
        2. Join chunks (removing chunk prefixes)
        3. Decompress if first chunk indicates compression (COMPRESSED__ prefix)
        4. Check for encryption after decompression (WHISPER__ prefix)

        For encrypted messages (WHISPER__ prefix), requires:
        - credential_manager: For accessing private keys
        - message_encryption: For ECDH operations

        Raises exception if processing fails.
        """
        if not sequence:
            raise ValueError("Empty sequence")

        # Sort by chunk index
        sorted_sequence = sorted(
            sequence,
            key=lambda tx: MemoStructure.from_transaction(tx).chunk_index or 0
        )

        # Join chunks (removing chunk prefixes)
        processed_data = ''
        for tx in sorted_sequence:
            chunk_data = tx['memo_data']
            if chunk_match := re.match(r'^chunk_\d+__', chunk_data):
                chunk_data = chunk_data[len(chunk_match.group(0)):]
            processed_data += chunk_data

        # Handle decompression
        if processed_data.startswith('COMPRESSED__'):
            processed_data = processed_data.replace('COMPRESSED__', '', 1)
            try:
                processed_data = decompress_data(processed_data)
            except Exception as e:
                raise ValueError(f"Decompression failed: {e}")

        # Handle decryption
        if processed_data.startswith('WHISPER__'):
            if not all([credential_manager, message_encryption]):
                logger.warning(
                    "Cannot decrypt message - missing required parameters. "
                    f"Need credential_manager: {bool(credential_manager)}, "
                    f"message_encryption: {bool(message_encryption)}"
                )
                return processed_data
            
            # Get channel details from first transaction
            first_tx = sorted_sequence[0]
            channel_address = first_tx['destination']
            channel_counterparty = first_tx['account']
            
            try:
                # Determine secret type based on receiving address
                secret_type = LegacyMemoProcessor._determine_secret_type(channel_address, node_config)
            
                # Get handshake keys
                channel_key, counterparty_key = message_encryption.get_handshake_for_address(
                    channel_address=channel_address,
                    channel_counterparty=channel_counterparty
                )
                if not (channel_key and counterparty_key):
                    logger.warning("LegacyMemoProcessor.process_sequence: Cannot decrypt message - no handshake found")
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
                message = (
                    f"LegacyMemoProcessor.process_sequence: Error decrypting message "
                    f"between address {channel_address} and counterparty {channel_counterparty}: {processed_data}"
                )
                logger.error(message)
                logger.error(traceback.format_exc())
                return f"[Decryption Failed] {processed_data}"

        return processed_data

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
    def process_group(
        group: MemoGroup,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> str:
        """
        Process a complete group of standardized format memos.
        The memo_format (e.g., "e.b.c1/4") indicates which processing steps are needed:
        - 'c' indicates chunking
        - 'b' indicates brotli compression
        - 'e' indicates ECDH encryption
        
        Processing occurs in a fixed order:
        1. Unchunk (if chunked)
        2. Decompress (if compressed)
        3. Decrypt (if encrypted)
        
        For encrypted messages, requires:
        - credential_manager: For accessing private keys
        - message_encryption: For ECDH operations
        - node_config: For determining secret types
        
        Raises ValueError if group is incomplete or processing fails.
        """
        if not group.messages:
            raise ValueError("Empty group")
        
        structure = MemoStructure.from_transaction(group.messages[0])
        if not structure.is_standardized_format:
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
                group.messages,
                key=lambda tx: MemoStructure.from_transaction(tx).chunk_index or 0
            )
            
            processed_data = ''
            for tx in sorted_msgs:
                processed_data += tx['memo_data']
                
        else:
            # Single message
            processed_data = group.messages[0]['memo_data']
        
        # Apply decompression if specified
        if structure.compression_type == MemoDataStructureType.BROTLI:
            try:
                processed_data = decompress_data(processed_data)
            except Exception as e:
                raise ValueError(f"Decompression failed: {e}")
                
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
            first_tx = group.messages[0]
            channel_address = first_tx['destination']
            channel_counterparty = first_tx['account']

            try:
                # Determine secret type based on receiving address
                secret_type = StandardizedMemoProcessor._determine_secret_type(channel_address, node_config)
            
                # Get handshake keys
                channel_key, counterparty_key = message_encryption.get_handshake_for_address(
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
                logger.error(f"Error decrypting message: {e}")
                logger.error(traceback.format_exc())
                return f"[Decryption Failed] {processed_data}"
            
        return processed_data
    
    @staticmethod
    def validate_group(group: MemoGroup) -> bool:
        """
        Validate that all messages in the group have consistent structure.
        """
        if not group.messages:
            return False
            
        first_structure = MemoStructure.from_transaction(group.messages[0])
        if not first_structure.is_standardized_format:
            return False
            
        # Check all messages have same format
        for msg in group.messages[1:]:
            structure = MemoStructure.from_transaction(msg)
            if not structure.is_standardized_format:
                return False
                
            if (structure.encryption_type != first_structure.encryption_type or
                structure.compression_type != first_structure.compression_type or
                structure.total_chunks != first_structure.total_chunks):
                return False
                
        return True

class MemoProcessor:
    """Entry point for memo processing"""
    
    @staticmethod
    def process_group(
        group: MemoGroup,
        credential_manager: Optional[CredentialManager] = None,
        message_encryption: Optional[MessageEncryption] = None,
        node_config: Optional[NodeConfig] = None
    ) -> Optional[str]:
        """Process a group of memos based on their format"""
        if not group.messages:
            return None
        
        first_tx = group.messages[0]
        structure = MemoStructure.from_transaction(first_tx)

        try:
            if structure.is_standardized_format:
                if StandardizedMemoProcessor.validate_group(group):
                    return StandardizedMemoProcessor.process_group(
                        group,
                        credential_manager=credential_manager,
                        message_encryption=message_encryption,
                        node_config=node_config
                    )
                else:
                    logger.warning("Invalid standardized format group")
                    return None
            else:
                group = LegacyMemoProcessor.find_complete_group(group)
                if group:
                    return LegacyMemoProcessor.process_group(
                        group,
                        credential_manager=credential_manager,
                        message_encryption=message_encryption,
                        node_config=node_config
                    )
                return None
        except Exception as e:
            logger.error(f"Failed to process memo group: {e}")
            return None