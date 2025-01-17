from typing import Protocol
from nodetools.utilities.credentials import SecretType

class CredentialManager(Protocol):
    """Protocol for the CredentialManager class"""
    def get_credential(self, credential: str) -> str:
        """Get a specific credential"""
        ...

    def get_ecdh_public_key(self, secret_type: SecretType) -> str:
        """Returns ECDH public key as hex string"""
        ...

    def get_shared_secret(self, received_key: str, secret_type: SecretType) -> bytes: 
        """
        Derive a shared secret using ECDH
        
        Args:
            received_key: public key received from another party
            secret_type: SecretType enum indicating which secret to use

        Returns:
            bytes: The derived shared secret

        Raises:
            ValueError: if received_key is invalid or secret not found
        """
        ...
