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
