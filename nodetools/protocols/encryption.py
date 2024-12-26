from typing import Protocol, Optional
import pandas as pd

class MessageEncryption(Protocol):
    """Handles encryption/decryption of messages using ECDH-derived shared secrets"""

    def get_shared_secret(self, received_public_key: str, channel_private_key: str) -> str:
        """Get the shared secret from the received public key and channel private key"""
        ...

    def get_handshake_for_address(
            self, 
            channel_address: str, 
            channel_counterparty: str, 
            memo_history: Optional[pd.DataFrame] = None
        ) -> tuple[Optional[str], Optional[str]]:
        """Get handshake public keys between two addresses.
        
        Args:
            channel_address: One end of the encryption channel
            channel_counterparty: The other end of the encryption channel
            memo_history: Optional pre-filtered memo history. If None, will be fetched.
            
        Returns:
            Tuple of (channel_address's ECDH public key, channel_counterparty's ECDH public key)
        """
        ...

    @staticmethod
    def process_encrypted_message(message: str, shared_secret: bytes) -> str:
        """
        Process a potentially encrypted message.
        
        Args:
            message: The message to process
            shared_secret: The shared secret for decryption
            
        Returns:
            Decrypted message if encrypted and decryption succeeds,
            original message otherwise

        Raises:
            ValueError: If the message fails decryption
        """
        ...