from typing import Protocol, Union, Optional
import pandas as pd
from xrpl.wallet import Wallet
from xrpl.models import Memo
from decimal import Decimal
from nodetools.configuration.configuration import NetworkConfig, NodeConfig
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.utilities.xrpl_monitor import XRPLWebSocketMonitor
from nodetools.protocols.transaction_repository import TransactionRepository

class GenericPFTUtilities(Protocol):
    """Protocol defining the interface for GenericPFTUtilities implementations"""

    @property
    def network_config(self) -> NetworkConfig:
        """Get the network configuration"""
        ...

    @property
    def node_config(self) -> NodeConfig:
        """Get the node configuration"""
        ...

    @property
    def db_connection_manager(self) -> DBConnectionManager:
        """Get the database connection manager"""
        ...

    @property
    def xrpl_monitor(self) -> XRPLWebSocketMonitor:
        """Get the XRPL monitor"""
        ...

    @property
    def transaction_repository(self) -> TransactionRepository:
        """Get the transaction repository"""
        ...

    def sync_pft_transaction_history(self):
        """Sync transaction history for all PFT holders"""
        ...

    def get_account_memo_history(self, account_address: str, pft_only: bool = True) -> pd.DataFrame:
        """Get memo history for a given account"""
        ...

    def send_memo(self, 
            wallet_seed_or_wallet: Union[str, Wallet], 
            destination: str, 
            memo: Union[str, Memo], 
            username: str = None,
            message_id: str = None,
            chunk: bool = False,
            compress: bool = False, 
            encrypt: bool = False,
            pft_amount: Optional[Decimal] = None
        ) -> Union[dict, list[dict]]:
        """Send a memo to a given account"""
        ...
    
    def verify_transaction_response(self, response: str) -> bool:
        """Verify a transaction response"""
        ...

    def get_all_account_compressed_messages(self, account_address: str) -> pd.DataFrame:
        """Get all compressed messages for a given account"""
        ...

    def construct_handshake_memo(self, user: str, ecdh_public_key: str) -> str:
        """Construct a handshake memo"""
        ...

    def construct_memo(self, memo_data: str, memo_type: str, memo_format: str) -> Memo:
        """Construct a standardized memo object for XRPL transactions"""
        ...

    def spawn_wallet_from_seed(self, seed: str) -> Wallet:
        """Spawn a wallet from a seed"""
        ...

    def get_recent_user_memos(self, account_address: str, num_messages: int) -> str:
        """Get the most recent messages from a user's memo history"""
        ...

    def get_all_account_compressed_messages_for_remembrancer(self, account_address: str) -> pd.DataFrame:
        """Convenience method for getting all messages for a user from the remembrancer's perspective"""
        ...

    async def process_queue_transaction(
            self,
            wallet: Wallet,
            memo: str,
            destination: str,
            pft_amount: Optional[Union[int, float, Decimal]] = None
        ) -> bool:
        """Send and track a node-initiated transaction for queue processing"""
        ...

    def fetch_pft_balance(self, address: str) -> Decimal:
        """Get PFT balance for an account from the XRPL"""
        ...

    def fetch_xrp_balance(self, address: str) -> Decimal:
        """Get XRP balance for an account from the XRPL"""
        ...

    def get_pft_balance(self, account_address: str) -> Decimal:
        """Get PFT balance for an account from the database"""
        ...

    def process_memo_data(
        self,
        memo_type: str,
        memo_data: str,
        decompress: bool = True,
        decrypt: bool = True,
        full_unchunk: bool = False, 
        memo_history: Optional[pd.DataFrame] = None,
        channel_address: Optional[str] = None,
        channel_counterparty: Optional[str] = None,
        channel_private_key: Optional[Union[str, Wallet]] = None
    ) -> str:
        ...

    def verify_xrp_balance(self, address: str, minimum_xrp_balance: int) -> bool:
        """
        Verify that a wallet has sufficient XRP balance.
        
        Args:
            wallet: XRPL wallet object
            minimum_balance: Minimum required XRP balance
            
        Returns:
            tuple: (bool, float) - Whether balance check passed and current balance
        """
        ...

    def handle_trust_line(self, wallet: Wallet, username: str):
        """
        Check and establish PFT trustline if needed.
        
        Args:
            wallet: XRPL wallet object
            username: Discord username

        Raises:
            Exception: If there is an error creating the trust line
        """
        ...