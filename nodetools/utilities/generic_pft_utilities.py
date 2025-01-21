# Standard library imports
from decimal import Decimal
from typing import Optional, Union, Any, Dict, List, Any, Tuple
import binascii
import datetime 
import random
import string
import base64
import brotli
import hashlib
import os
import re
import json
import traceback
import asyncio
import math
from inspect import signature

# Third party imports
import nest_asyncio
import pandas as pd
import requests
import xrpl
from xrpl.wallet import Wallet
from xrpl.models.transactions import Memo
from xrpl.models.response import Response
from xrpl.asyncio.transaction import submit_and_wait
from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.models.requests import AccountInfo, AccountLines, AccountTx
from xrpl.utils import str_to_hex
from loguru import logger

# NodeTools imports
import nodetools.configuration.constants as global_constants
import nodetools.configuration.configuration as config
from nodetools.configuration.constants import PFTSendDistribution
from nodetools.models.models import MemoGroup, MemoConstructionParameters, MemoTransaction
from nodetools.models.memo_processor import MemoProcessor
from nodetools.performance.monitor import PerformanceMonitor
from nodetools.utilities.encryption import MessageEncryption
from nodetools.utilities.transaction_requirements import TransactionRequirementService
from nodetools.utilities.db_manager import DBConnectionManager
from nodetools.utilities.credentials import CredentialManager
from nodetools.utilities.exceptions import *
from nodetools.utilities.xrpl_monitor import XRPLWebSocketMonitor
from nodetools.utilities.transaction_orchestrator import TransactionOrchestrator
from nodetools.utilities.transaction_repository import TransactionRepository
from nodetools.configuration.configuration import NetworkConfig, NodeConfig, RuntimeConfig

nest_asyncio.apply()

class GenericPFTUtilities:
    """Handles general PFT utilities and operations"""
    _instance = None
    _initialized = False

    TX_JSON_FIELDS = [
        'Account', 'DeliverMax', 'Destination', 'Fee', 'Flags',
        'LastLedgerSequence', 'Sequence', 'SigningPubKey', 
        'TransactionType', 'TxnSignature', 'date', 'ledger_index', 'Memos'
    ]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
            self,
            network_config: NetworkConfig,
            node_config: NodeConfig,
            credential_manager: CredentialManager,
            db_connection_manager: DBConnectionManager,
            transaction_repository: TransactionRepository,
        ):
        if not self.__class__._initialized:
            # Get network and node configurations
            self.network_config = network_config
            self.node_config = node_config
            self.pft_issuer = self.network_config.issuer_address
            self.node_address = self.node_config.node_address
            self.node_name = self.node_config.node_name

            # TODO: Revisit this module
            self.transaction_requirements = TransactionRequirementService(self.network_config, self.node_config)

            # Determine endpoint with fallback logic
            self.https_url = (
                self.network_config.local_rpc_url 
                if RuntimeConfig.HAS_LOCAL_NODE and self.network_config.local_rpc_url is not None
                else self.network_config.public_rpc_url
            )
            logger.debug(f"Using https endpoint: {self.https_url}")

            self.db_connection_manager = db_connection_manager
            self.transaction_repository = transaction_repository
            self.credential_manager = credential_manager
            self.message_encryption: Optional[MessageEncryption] = None  # Requires initialization outside of this class

            self.__class__._initialized = True

    @staticmethod
    def convert_ripple_timestamp_to_datetime(ripple_timestamp = 768602652):
        ripple_epoch_offset = 946684800
        unix_timestamp = ripple_timestamp + ripple_epoch_offset
        date_object = datetime.datetime.fromtimestamp(unix_timestamp)
        return date_object

    @staticmethod
    def is_over_1kb(value: Union[str, int, float]) -> bool:
        if isinstance(value, str):
            # For strings, convert to bytes and check length
            return len(value.encode('utf-8')) > 1024
        elif isinstance(value, (int, float)):
            # For numbers, compare directly
            return value > 1024
        else:
            raise TypeError(f"Expected string or number, got {type(value)}")
        
    @staticmethod
    def to_hex(string):
        return binascii.hexlify(string.encode()).decode()

    @staticmethod
    def hex_to_text(hex_string):
        bytes_object = bytes.fromhex(hex_string)
        try:
            ascii_string = bytes_object.decode("utf-8")
            return ascii_string
        except UnicodeDecodeError:
            return bytes_object  # Return the raw bytes if it cannot decode as utf-8

    @staticmethod
    def generate_random_utf8_friendly_hash(length=6):
        # Generate a random sequence of bytes
        random_bytes = os.urandom(16)  # 16 bytes of randomness
        # Create a SHA-256 hash of the random bytes
        hash_object = hashlib.sha256(random_bytes)
        hash_bytes = hash_object.digest()
        # Encode the hash to base64 to make it URL-safe and readable
        base64_hash = base64.urlsafe_b64encode(hash_bytes).decode('utf-8')
        # Take the first `length` characters of the base64-encoded hash
        utf8_friendly_hash = base64_hash[:length]
        return utf8_friendly_hash

    @staticmethod
    def get_number_of_bytes(text):
        text_bytes = text.encode('utf-8')
        return len(text_bytes)
        
    @staticmethod
    def split_text_into_chunks(text, max_chunk_size=global_constants.MAX_CHUNK_SIZE):
        chunks = []
        text_bytes = text.encode('utf-8')
        for i in range(0, len(text_bytes), max_chunk_size):
            chunk = text_bytes[i:i+max_chunk_size]
            chunk_number = i // max_chunk_size + 1
            chunk_label = f"chunk_{chunk_number}__".encode('utf-8')
            chunk_with_label = chunk_label + chunk
            chunks.append(chunk_with_label)
        return [chunk.decode('utf-8', errors='ignore') for chunk in chunks]

    @staticmethod
    def compress_string(input_string):
        # Compress the string using Brotli
        compressed_data=brotli.compress(input_string.encode('utf-8'))
        # Encode the compressed data to a Base64 string
        base64_encoded_data=base64.b64encode(compressed_data)
        # Convert the Base64 bytes to a string
        compressed_string=base64_encoded_data.decode('utf-8')
        return compressed_string

    @staticmethod
    def decompress_string(compressed_string):
        """Decompress a base64-encoded, brotli-compressed string.
        
        Args:
            compressed_string: The compressed string to decompress
            
        Returns:
            str: The decompressed string
            
        Raises:
            ValueError: If decompression fails after all correction attempts
        """
        # logger.debug(f"GenericPFTUtilities.decompress_string: Decompressing string: {compressed_string}")

        def try_decompress(attempt_string: str) -> Optional[str]:
            """Helper function to attempt decompression with error handling"""
            try:
                base64_decoded = base64.b64decode(attempt_string)
                decompressed = brotli.decompress(base64_decoded)
                return decompressed.decode('utf-8')
            except Exception as e:
                # logger.debug(f"GenericPFTUtilities.decompress_string: Decompression attempt failed: {str(e)}")
                return None
            
        # Try original string first
        result = try_decompress(compressed_string)
        if result:
            return result
        
        # Clean string of invalid base64 characters
        valid_chars = set(string.ascii_letters + string.digits + '+/=')
        cleaned = ''.join(c for c in compressed_string if c in valid_chars)
        # logger.debug(f"GenericPFTUtilities.decompress_string: Cleaned string: {cleaned}")

        # Try with different padding lengths
        for i in range(4):
            padded = cleaned + ('=' * i)
            result = try_decompress(padded)
            if result:
                # logger.debug(f"GenericPFTUtilities.decompress_string: Successfully decompressed with {i} padding chars")
                return result

        # If we get here, all attempts failed
        raise ValueError(
            "Failed to decompress string after all correction attempts. "
            "Original string may be corrupted or incorrectly encoded."
        )

    @staticmethod
    def shorten_url(url):
        api_url="http://tinyurl.com/api-create.php"
        params={'url': url}
        response = requests.get(api_url, params=params)
        if response.status_code == 200:
            return response.text
        else:
            return None
    
    @staticmethod
    def check_if_tx_pft(tx):
        ret= False
        try:
            if tx['Amount']['currency'] == "PFT":
                ret = True
        except:
            pass
        return ret
    
    @staticmethod
    def verify_transaction_response(response: Union[Response, list[Response]] ) -> bool:
        """
        Verify that a transaction response or list of responses indicates success.

        Args:
            response: Transaction response from submit_and_wait

        Returns:
            Tuple[bool, Response]: True if the transaction was successful, False otherwise
        """
        try:
            # Handle list of responses
            if isinstance(response, list):
                return all(
                    GenericPFTUtilities.verify_transaction_response(single_response)
                    for single_response in response
                )

            # Handle single response
            if hasattr(response, 'result'):
                result = response.result
            else:
                result = response

            # Check if transaction was validated and successful
            return (
                result.get('validated', False) and
                result.get('meta', {}).get('TransactionResult', '') == 'tesSUCCESS'
            )
        except Exception as e:
            logger.error(f"Error verifying transaction response: {e}")
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def spawn_wallet_from_seed(seed):
        """ outputs wallet initialized from seed"""
        wallet = xrpl.wallet.Wallet.from_seed(seed)
        logger.debug(f'-- Spawned wallet with address {wallet.address}')
        return wallet
    
    @PerformanceMonitor.measure('get_account_memo_history')
    async def get_account_memo_history(
        self, 
        account_address: str, 
        pft_only: bool = False, 
        memo_type_filter: Optional[str] = None
    ) -> pd.DataFrame:
        """Get transaction history with memos for an account.
        
        Args:
            account_address: XRPL account address to get history for
            pft_only: If True, only return transactions with PFT included.
            memo_type_filter: Optional string to filter memo_types using LIKE. E.g. '%google_doc_context_link'
    
        Returns:
            DataFrame containing transaction history with memo details
        """
        results = await self.transaction_repository.get_account_memo_history(
            account_address=account_address,
            pft_only=pft_only,
            memo_type_filter=memo_type_filter
        )

        df = pd.DataFrame(results)

        # Convert datetime column to datetime after DataFrame creation
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df
    
    async def get_latest_valid_memo_groups(
        self,
        memo_history: pd.DataFrame,
        num_groups: Optional[int] = 1
    ) -> Optional[Union[MemoGroup, list[MemoGroup]]]:
        """Get the most recent valid MemoGroup from a set of memo records.
        This method is designed to process data returned from GenericPFTUtilities.get_account_memo_history.
        
        Args:
            memo_history: DataFrame containing memo records
            num_groups: Optional int limiting the number of memo groups to return.
                       If 1 (default), returns a single MemoGroup.
                       If > 1, returns a list of up to num_groups MemoGroups.
                       If 0 or None, returns all valid memo groups.

        Returns:
            Optional[Union[MemoGroup, list[MemoGroup]]]: Most recent valid MemoGroup(s) or None if no valid groups found
        """
        if memo_history.empty or len(memo_history) == 0:
            return None

        # Filter for successful transactions
        filtered_records = memo_history[memo_history['transaction_result'] == "tesSUCCESS"]

        if filtered_records.empty or len(filtered_records) == 0:
            return None
        
        # Get valid MemoTransaction fields
        valid_fields = set(signature(MemoTransaction).parameters.keys())

        valid_groups = []
        
        # Group by memo_type to handle chunked memos
        for memo_type in filtered_records['memo_type'].unique():
            try:
                # Get all transactions for this memo_group
                group_txs: pd.DataFrame = filtered_records[filtered_records['memo_type'] == memo_type]

                # Convert DataFrame rows to MemoTransaction objects
                memo_txs = []
                for tx in group_txs.to_dict(orient='records'):
                    valid_tx = {k: v for k, v in tx.items() if k in valid_fields}
                    memo_txs.append(MemoTransaction(**valid_tx))

                # Create and validate MemoGroup
                memo_group = MemoGroup.create_from_memos(memo_txs)

                # Additional check to ensure we only accept standardized memos
                if not memo_group.structure or not memo_group.structure.is_valid_format:
                    # logger.warning(f"Skipping memo group {memo_type} - not using standardized format")
                    continue

                valid_groups.append(memo_group)

                # Return early if we've reached the desired number of groups
                if len(valid_groups) == num_groups:
                    break
            
            except ValueError as e:
                logger.warning(f"Failed to process memo group {memo_type}: {e}")
                continue

        # If no valid memo groups found, return None
        if not valid_groups:
            return None
        
        # Return a single MemoGroup if num_groups is 1, otherwise return a list
        return valid_groups[0] if num_groups == 1 else valid_groups
    
    async def send_handshake(self, wallet_seed: str, destination: str, username: str = None):
        """Sends a handshake memo to establish encrypted communication"""
        return await self.message_encryption.send_handshake(channel_private_key=wallet_seed, channel_counterparty=destination, username=username)
    
    def register_auto_handshake_wallet(self, wallet_address: str):
        """Register a wallet address for automatic handshake responses."""
        self.message_encryption.register_auto_handshake_wallet(wallet_address)

    def get_auto_handshake_addresses(self) -> set[str]:
        """Get a list of registered auto-handshake addresses"""
        return self.message_encryption.get_auto_handshake_addresses()

    async def get_handshake_for_address(self, channel_address: str, channel_counterparty: str):
        """Get handshake for a specific address"""
        return await self.message_encryption.get_handshake_for_address(channel_address, channel_counterparty)
    
    def get_shared_secret(self, received_public_key: str, channel_private_key: str):
        """
        Get shared secret for a received public key and channel private key.
        The channel private key is the wallet secret.
        """
        return self.message_encryption.get_shared_secret(received_public_key, channel_private_key)
    
    async def send_xrp(
            self,
            wallet_seed_or_wallet: Union[str, xrpl.wallet.Wallet], 
            amount: Union[Decimal, int, float], 
            destination: str, 
            memo_data: Optional[str] = None, 
            memo_type: Optional[str] = None,
            compress: bool = False,
            encrypt: bool = False,
            destination_tag: Optional[int] = None
        ) -> Union[Response, list[Response]]:
        """Send XRP with optional memo processing capabilities.
        
        Args:
            wallet_seed_or_wallet: Either a wallet seed string or a Wallet object
            amount: Amount of XRP to send
            destination: XRPL destination address
            memo_data: Optional memo data to include
            memo_type: Optional memo type identifier
            compress: Whether to compress the memo data
            encrypt: Whether to encrypt the memo data
            destination_tag: Optional destination tag
            
        Returns:
            Single Response or list of Responses depending on number of memos
        """
        # Handle wallet input
        if isinstance(wallet_seed_or_wallet, str):
            wallet = self.spawn_wallet_from_seed(wallet_seed_or_wallet)
        elif isinstance(wallet_seed_or_wallet, xrpl.wallet.Wallet):
            wallet = wallet_seed_or_wallet
        else:
            logger.error("GenericPFTUtilities.send_xrp: Invalid wallet input, raising ValueError")
            raise ValueError("Invalid wallet input")

        if not memo_data:
            return await self._send_memo_single(
                wallet=wallet,
                destination=destination,
                memo=Memo(),  # Empty memo
                xrp_amount=Decimal(amount),
                destination_tag=destination_tag
            )
        
        params = MemoConstructionParameters.construct_standardized_memo(
            source=wallet.address,
            destination=destination,
            memo_data=memo_data,
            memo_type=memo_type,
            should_encrypt=encrypt,
            should_compress=compress
        )

        memo_group = await MemoProcessor.construct_group_generic(
            memo_params=params,
            wallet=wallet,
            message_encryption=self.message_encryption
        )

        return await self.send_memo_group(
            wallet,
            destination,
            memo_group,
            xrp_amount=Decimal(amount),
            destination_tag=destination_tag
        )

    async def send_memo(self, 
        wallet_seed_or_wallet: Union[str, Wallet], 
        destination: str, 
        memo_data: str, 
        memo_type: Optional[str] = None,
        compress: bool = False, 
        encrypt: bool = False,
        pft_amount: Optional[Decimal] = None,
        disable_pft_check: bool = True,
        pft_distribution: PFTSendDistribution = PFTSendDistribution.LAST_CHUNK_ONLY
    ) -> Union[Response, list[Response]]:
        """Primary method for sending memos on the XRPL with PFT requirements.

        This method constructs a MemoGroup using the MemoProcessor and sends it via send_memo_group.
        
        Args:
            wallet_seed_or_wallet: Either a wallet seed string or a Wallet object
            destination: XRPL destination address
            memo_data: The message content to send
            memo_type: Message type identifier
            compress: Whether to compress the memo data (default False)
            encrypt: Whether to encrypt the memo data (default False)
            pft_amount: Optional specific PFT amount to send
            disable_pft_check: Skip PFT requirement check if True
            pft_distribution: Strategy for distributing PFT across chunks:
                - DISTRIBUTE_EVENLY: Split total amount evenly across all chunks
                - LAST_CHUNK_ONLY: Send entire amount with last chunk only
                - FULL_AMOUNT_EACH: Send full amount with each chunk

        Returns:
            list[dict]: Transaction responses for each chunk sent
            
        Raises:
            ValueError: If wallet input is invalid
            HandshakeRequiredException: If encryption requested without prior handshake
        """
        # Handle wallet input
        if isinstance(wallet_seed_or_wallet, str):
            wallet = self.spawn_wallet_from_seed(wallet_seed_or_wallet)
            logger.debug(f"GenericPFTUtilities.send_memo: Spawned wallet for {wallet.address} to send memo to {destination}...")
        elif isinstance(wallet_seed_or_wallet, Wallet):
            wallet = wallet_seed_or_wallet
        else:
            logger.error("GenericPFTUtilities.send_memo: Invalid wallet input, raising ValueError")
            raise ValueError("Invalid wallet input")

        # TODO: Adopt a spec for PFT requirements
        # Get per-tx PFT requirement
        if not disable_pft_check:
            pft_amount = pft_amount or self.transaction_requirements.get_pft_requirement(
                address=destination,
                memo_type=memo_type
            )

        # Construct parameters for memo processing
        params = MemoConstructionParameters.construct_standardized_memo(
            source=wallet.address,
            destination=destination,
            memo_data=memo_data,
            memo_type=memo_type,
            should_encrypt=encrypt,
            should_compress=compress,
            pft_amount=pft_amount
        )

        # Generate memo group using processor
        memo_group = await MemoProcessor.construct_group_generic(
            memo_params=params,
            wallet=wallet,
            message_encryption=self.message_encryption
        )

        # Send memo group
        return await self.send_memo_group(wallet, destination, memo_group, pft_amount, pft_distribution)
    
    async def send_memo_group(
        self,
        wallet_seed_or_wallet: Union[str, Wallet],
        destination: str,
        memo_group: MemoGroup,
        pft_amount: Optional[Decimal] = None,
        pft_distribution: PFTSendDistribution = PFTSendDistribution.FULL_AMOUNT_EACH,
        xrp_amount: Optional[Decimal] = None,
        destination_tag: Optional[int] = None
    ) -> Union[Response, list[Response]]:
        """Send a memo group to a destination
        
        Args:
            wallet_seed_or_wallet: Either a wallet seed string or a Wallet object
            destination: XRPL destination address
            memo_group: MemoGroup object containing memos to send
            pft_amount: Optional total PFT amount to send
            pft_distribution: Strategy for distributing PFT across chunks:
                - DISTRIBUTE_EVENLY: Split total amount evenly across all chunks
                - LAST_CHUNK_ONLY: Send entire amount with last chunk only
                - FULL_AMOUNT_EACH: Send full amount with each chunk
            xrp_amount: Optional XRP amount to send (only sent with last chunk)
            destination_tag: Optional destination tag
        
        Returns:
            Single Response or list of Responses depending on number of memos
        """
        # Handle wallet input
        if isinstance(wallet_seed_or_wallet, str):
            wallet = self.spawn_wallet_from_seed(wallet_seed_or_wallet)
        elif isinstance(wallet_seed_or_wallet, Wallet):
            wallet = wallet_seed_or_wallet
        else:
            logger.error("GenericPFTUtilities.send_memo: Invalid wallet input, raising ValueError")
            raise ValueError("Invalid wallet input")
        
        responses = []
        num_memos = len(memo_group.memos)

        for idx, memo in enumerate(memo_group.memos):
            # Determine PFT amount for this chunk based on distribution strategy
            chunk_pft_amount = None
            match pft_distribution:
                case PFTSendDistribution.DISTRIBUTE_EVENLY:
                    chunk_pft_amount = pft_amount / (Decimal(num_memos) if num_memos > 0 else 1)
                case PFTSendDistribution.LAST_CHUNK_ONLY:
                    chunk_pft_amount = pft_amount if idx == num_memos - 1 else 0
                case PFTSendDistribution.FULL_AMOUNT_EACH:
                    chunk_pft_amount = pft_amount

            # Only send XRP with last chunk
            chunk_xrp_amount = xrp_amount if idx == num_memos - 1 else None

            logger.debug(f"Sending memo {idx + 1} of {len(memo_group.memos)} from {wallet.address} to {destination}")
            responses.append(await self._send_memo_single(
                wallet,
                destination,
                memo,
                chunk_pft_amount,
                chunk_xrp_amount,
                destination_tag
            ))

        return responses if len(memo_group.memos) > 1 else responses[0]

    async def _send_memo_single(
        self, 
        wallet: Wallet, 
        destination: str, 
        memo: Memo, 
        pft_amount: Optional[Decimal] = None,
        xrp_amount: Optional[Decimal] = None,
        destination_tag: Optional[int] = None
    ) -> Response:
        """ Sends a single memo to a destination """
        client = AsyncJsonRpcClient(self.https_url)

        payment_args = {
            "account": wallet.address,
            "destination": destination,
            "memos": [memo]
        }

        if destination_tag is not None:
            payment_args["destination_tag"] = destination_tag

        if pft_amount and pft_amount > 0:
            payment_args["amount"] = xrpl.models.amounts.IssuedCurrencyAmount(
                currency="PFT",
                issuer=self.pft_issuer,
                value=str(pft_amount)
            )
        elif xrp_amount:
            payment_args["amount"] = xrpl.utils.xrp_to_drops(xrp_amount)
        else:
            # Send minimum XRP amount for memo-only transactions
            payment_args["amount"] = xrpl.utils.xrp_to_drops(Decimal(global_constants.MIN_XRP_PER_TRANSACTION))

        payment = xrpl.models.transactions.Payment(**payment_args)

        try:
            logger.debug(f"GenericPFTUtilities._send_memo_single: Submitting transaction to send memo from {wallet.address} to {destination}")
            response = await submit_and_wait(payment, client, wallet)
            return response
        except xrpl.transaction.XRPLReliableSubmissionException as e:
            logger.error(f"GenericPFTUtilities._send_memo_single: Transaction submission failed: {e}")
            logger.error(traceback.format_exc())
            raise
        except Exception as e:
            logger.error(f"GenericPFTUtilities._send_memo_single: Unexpected error: {e}")
            logger.error(traceback.format_exc())
            raise

    async def fetch_account_transactions(
            self,
            account_address: str,
            ledger_index_min: int = -1,
            ledger_index_max: int = -1,
            max_attempts: int = 3,
            retry_delay: float = 0.2,
            limit: int = 1000
        ) -> list[dict]:
        """Fetch transactions for an account from the XRPL"""
        all_transactions = []  # List to store all transactions
        marker = None  # Fetch transactions using marker pagination
        attempt = 0
        client = AsyncJsonRpcClient(self.https_url)

        while attempt < max_attempts:
            try:
                request = xrpl.models.requests.account_tx.AccountTx(
                    account=account_address,
                    ledger_index_min=ledger_index_min,
                    ledger_index_max=ledger_index_max,
                    limit=limit,
                    marker=marker,
                    forward=True
                )
                response = await client.request(request)
                transactions = response.result["transactions"]
                all_transactions.extend(transactions)

                if "marker" not in response.result:
                    break
                marker = response.result["marker"]

            except Exception as e:
                logger.error(f"GenericPFTUtilities.get_account_transactions: Error occurred while fetching transactions (attempt {attempt + 1}): {str(e)}")
                attempt += 1
                if attempt < max_attempts:
                    logger.debug(f"GenericPFTUtilities.get_account_transactions: Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.warning("GenericPFTUtilities.get_account_transactions: Max attempts reached. Transactions may be incomplete.")
                    break

        return all_transactions

    @staticmethod
    def _extract_field(json_data: dict, field: str) -> Any:
        """Extract a field from JSON data, converting dicts to strings.
    
        Args:
            json_data: JSON dictionary to extract from
            field: Field name to extract
            
        Returns:
            Field value or None if not found/invalid
        """
        try:
            value = json_data.get(field)
            return str(value) if isinstance(value, dict) else value
        except AttributeError:
            return None

    async def fetch_formatted_transaction_history(
            self, 
            account_address: str,
            fetch_new_only: bool = True
        ) -> List[Dict[str, Any]]:
        """Fetch and format transaction history for an account.
        
        Retrieves transactions from XRPL and transforms them into a standardized
        format suitable for database storage.
        
        Args:
            account_address: XRPL account address to fetch transactions for
            fetch_new_only: If True, only fetch transactions after the last known ledger index.
                            If False, fetch entire transaction history.
                
        Returns:
            List of dictionaries containing processed transaction data with standardized fields
        """
        ledger_index_min = -1

        if fetch_new_only:
            # Get the last processed ledger index for this account
            last_ledger = await self.transaction_repository.get_last_ledger_index(account=account_address)
            if last_ledger is not None:
                ledger_index_min = last_ledger + 1

        # Fetch transaction history and prepare DataFrame
        transactions = await self.fetch_account_transactions(
            account_address=account_address, 
            ledger_index_min=ledger_index_min
        )
        if not transactions:
            return []
        
        formatted_transactions = []
        for tx in transactions:
            formatted_tx = {
                # Core transaction fields
                'hash': tx.get('hash'),
                'ledger_index': tx.get('ledger_index'),
                'close_time_iso': tx.get('close_time_iso'),
                'validated': tx.get('validated'),
                
                # Store complete transaction data
                'meta': tx.get('meta', {}),
                'tx_json': tx.get('tx_json', {}),
            }
            
            formatted_transactions.append(formatted_tx)
        
        return formatted_transactions

    async def fetch_pft_trustline_data(self, batch_size: int = 200) -> Dict[str, Dict[str, Any]]:
        """Get PFT token holder account information.
        
        Queries the XRPL for all accounts that have trustlines with the PFT issuer account.
        The balances are from the issuer's perspective, so they are negated to show actual
        holder balances (e.g., if issuer shows -100, holder has +100).

        Args:
            batch_size: Number of records to fetch per request (max 400)

        Returns:
            Dict of dictionaries with keys:
                - account (str): XRPL account address of the token holder
            and values:
                - balance (str): Raw balance string from XRPL
                - currency (str): Currency code (should be 'PFT')
                - limit_peer (str): Trustline limit
                - pft_holdings (float): Actual token balance (negated from issuer view)
        """
        # Initialize result dictionary and marker
        all_lines = {}
        marker = None

        client = AsyncJsonRpcClient(self.https_url)
        while True:
            try:
                # Request account lines with pagination
                request = xrpl.models.requests.AccountLines(
                    account=self.pft_issuer,
                    ledger_index="validated",
                    limit=batch_size,
                    marker=marker
                )
                
                response = await client.request(request)

                # Process this batch of lines
                for line in response.result['lines']:
                    all_lines[line['account']] = {
                        'balance': Decimal(line['balance']),
                        'currency': line['currency'],
                        'limit_peer': line['limit_peer'],
                        'pft_holdings': Decimal(line['balance']) * -1
                    }
                
                # Check if there are more results
                marker = response.result.get('marker')
                if not marker:
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching trustline data batch: {e}")
                logger.error(traceback.format_exc())
                break

        return all_lines

    async def get_pft_holders_async(self) -> Dict[str, Dict[str, Any]]:
        """Get current PFT holder data from database (async version)"""
        try:
            return await self.transaction_repository.get_pft_holders()
        except Exception as e:
            logger.error(f"Error getting PFT holders: {e}")
            logger.error(traceback.format_exc())
            return {}
        
    def get_pft_holders(self) -> Dict[str, Dict[str, Any]]:
        """Get current PFT holder data from database (sync version)"""
        try:
            # If we're already in an event loop, use it
            try:
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(self.get_pft_holders_async())
            except RuntimeError:  # No running event loop
                return asyncio.run(self.get_pft_holders_async())
        except Exception as e:
            logger.error(f"Error getting PFT holders: {e}")
            logger.error(traceback.format_exc())
            return {}
        
    async def get_pft_holder_async(self, account_address: str) -> Dict[str, Any]:
        """Get PFT holder data for an account from the database (async version)"""
        try:
            return await self.transaction_repository.get_pft_holder(account_address)
        except Exception as e:
            logger.error(f"Error getting PFT holder: {e}")
            logger.error(traceback.format_exc())
            return {}

    def get_pft_holder(self, account_address: str) -> Dict[str, Any]:
        """Get PFT holder data for an account from the database (sync version)"""
        try:
            try:
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(self.get_pft_holder_async(account_address))
            except RuntimeError:  # No running event loop
                return asyncio.run(self.get_pft_holder_async(account_address))
        except Exception as e:
            logger.error(f"Error getting PFT holder: {e}")
            logger.error(traceback.format_exc())
            return {}
        
    def get_pft_balance(self, account_address: str) -> Decimal:
        """Get PFT balance for an account from the database"""
        holder = self.get_pft_holder(account_address)
        return holder['balance'] if holder else Decimal(0)

    def create_xrp_wallet(self):
        test_wallet = Wallet.create()
        classic_address= test_wallet.classic_address
        wallet_seed = test_wallet.seed
        output_string = f"""Wallet Address: {classic_address}
Wallet Secret: {wallet_seed}
        
STORE YOUR WALLET SECRET IN AN OFFLINE PREFERABLY NON DIGITAL LOCATION
THIS MESSAGE WILL AUTO DELETE IN 60 SECONDS
"""
        return output_string
    
    async def fetch_pft_balance(self, address: str) -> Decimal:
        """Get PFT balance for an account from the XRPL.
    
        Args:
            address (str): XRPL account address
            
        Returns:
            Decimal: PFT balance, 0 if no trustline exists
            
        Raises:
            Exception: If there is an error getting the PFT balance
        """
        client = AsyncJsonRpcClient(self.https_url)
        account_lines = AccountLines(
            account=address,
            ledger_index="validated"
        )
        try:
            response = await client.request(account_lines)
            if response.is_successful():
                pft_lines = [line for line in response.result['lines'] if line['account']==self.pft_issuer]
                return Decimal(pft_lines[0]['balance']) if pft_lines else Decimal(0)
        
        except Exception as e:
            logger.error(f"GenericPFTUtilities.fetch_pft_balance: Error getting PFT balance for {address}: {e}")
            logger.error(traceback.format_exc())
            return Decimal(0)
    
    async def fetch_xrp_balance(self, address: str) -> Decimal:
        """Get XRP balance for an account from the XRPL.
        
        Args:
            account_address (str): XRPL account address
            
        Returns:
            Decimal: XRP balance

        Raises:
            XRPAccountNotFoundException: If the account is not found
            Exception: If there is an error getting the XRP balance
        """
        client = AsyncJsonRpcClient(self.https_url)
        acct_info = AccountInfo(
            account=address,
            ledger_index="validated"
        )
        try:
            response = await client.request(acct_info)
            if response.is_successful():
                return Decimal(response.result['account_data']['Balance']) / 1_000_000

        except Exception as e:
            logger.error(f"GenericPFTUtilities.fetch_xrp_balance: Error getting XRP balance: {e}")
            logger.error(traceback.format_exc())
            return Decimal(0)

    async def verify_xrp_balance(self, address: str, minimum_xrp_balance: int) -> bool:
        """
        Verify that a wallet has sufficient XRP balance.
        
        Args:
            wallet: XRPL wallet object
            minimum_balance: Minimum required XRP balance
            
        Returns:
            tuple: (bool, float) - Whether balance check passed and current balance
        """
        balance = await self.fetch_xrp_balance(address)
        return (balance >= minimum_xrp_balance, balance)
    
    def extract_transaction_info(self, response) -> dict:
        """
        Extract key information from an XRPL transaction response object.
        Handles both native XRP and issued currency (e.g. PFT) transactions.

        Args:
            response (Response): The XRPL transaction response object.

        Returns:
            dict: A dictionary containing extracted transaction information with keys:
                - time: Transaction timestamp
                - amount: Transaction amount
                - currency: Currency code (XRP or token currency)
                - send_address: Sender's XRPL address
                - destination_address: Recipient's XRPL address
                - status: Transaction status
                - hash: Transaction hash
                - xrpl_explorer_url: URL to transaction in XRPL explorer
                - clean_string: Human-readable transaction summary
        """
        transaction_info = {}
        
        try:
            # Handle different response formats
            result = response.result if hasattr(response, 'result') else response
            tx_json = result.get('tx_json', {})
            
            # Extract basic transaction info
            transaction_info.update({
                'hash': result.get('hash'),
                'xrpl_explorer_url': self.network_config.explorer_tx_url_mask.format(hash=result.get('hash')),
                'send_address': tx_json.get('Account'),
                'destination_address': tx_json.get('Destination'),
                'time': result.get('close_time_iso') or tx_json.get('date'),
                'status': result.get('meta', {}).get('TransactionResult') or result.get('engine_result')
            })

            # Handle amount and currency based on transaction type
            amount_info = tx_json.get('DeliverMax') or tx_json.get('Amount')
            
            if isinstance(amount_info, dict):
                # Issued currency (e.g. PFT)
                transaction_info.update({
                    'amount': amount_info.get('value'),
                    'currency': amount_info.get('currency')
                })
            elif amount_info:
                # Native XRP (convert from drops)
                transaction_info.update({
                    'amount': str(int(amount_info) / 1_000_000),
                    'currency': 'XRP'
                })
            
            # Create human-readable summary
            clean_string = (
                f"Transaction of {transaction_info.get('amount', 'unknown amount')} "
                f"{transaction_info.get('currency', 'unknown currency')} "
                f"from {transaction_info.get('send_address', 'unknown sender')} "
                f"to {transaction_info.get('destination_address', 'unknown recipient')} "
                f"on {transaction_info.get('time', 'unknown time')}. "
                f"Status: {transaction_info.get('status', 'unknown')}. "
                f"Explorer: {transaction_info['xrpl_explorer_url']}"
            )
            transaction_info['clean_string'] = clean_string

        except Exception as e:
            logger.error(f"Error extracting transaction info: {str(e)}")
            transaction_info.update({
                'error': str(e),
                'clean_string': f"Error extracting transaction info: {str(e)}"
            })
        
        return transaction_info
        
    async def has_trust_line(self, wallet: xrpl.wallet.Wallet) -> bool:
        """Check if wallet has PFT trustline.
        
        Args:
            wallet: XRPL wallet object

        Returns:
            bool: True if trustline exists
        """
        try:
            pft_holders = self.get_pft_holders()
            return wallet.classic_address in pft_holders
        except Exception as e:
            logger.error(f"GenericPFTUtilities.has_trust_line: Error checking if user {wallet.classic_address} has a trust line: {e}")
            return False
        
    async def handle_trust_line(self, wallet: xrpl.wallet.Wallet, username: str):
        """
        Check and establish PFT trustline if needed.
        
        Args:
            wallet: XRPL wallet object
            username: Discord username

        Raises:
            Exception: If there is an error creating the trust line
        """
        logger.debug(f"GenericPFTUtilities.handle_trust_line: Handling trust line for {username} ({wallet.classic_address})")
        if not await self.has_trust_line(wallet):
            logger.debug(f"GenericPFTUtilities.handle_trust_line: Trust line does not exist for {username} ({wallet.classic_address}), creating now...")
            response = await self.generate_trust_line_to_pft_token(wallet)
            if not response.is_successful():
                raise Exception(f"Error creating trust line: {response.result.get('error')}")
        else:
            logger.debug(f"GenericPFTUtilities.handle_trust_line: Trust line already exists for {wallet.classic_address}")

    async def generate_trust_line_to_pft_token(self, wallet: xrpl.wallet.Wallet) -> Response:
        """
        Generate a trust line to the PFT token.
        
        Args:
            wallet: XRPL wallet object
            
        Returns:
            Response: XRPL transaction response

        Raises:
            Exception: If there is an error creating the trust line
        """
        client = AsyncJsonRpcClient(self.https_url)
        trust_set_tx = xrpl.models.transactions.TrustSet(
            account=wallet.classic_address,
            limit_amount=xrpl.models.amounts.IssuedCurrencyAmount(
                currency="PFT",
                issuer=self.pft_issuer,
                value="100000000",
            )
        )
        logger.debug(f"GenericPFTUtilities.generate_trust_line_to_pft_token: Establishing trust line transaction from {wallet.classic_address} to issuer {self.pft_issuer}...")
        try:
            response = await submit_and_wait(trust_set_tx, client, wallet)
            return response
        except xrpl.transaction.XRPLReliableSubmissionException as e:
            logger.error(f"GenericPFTUtilities.generate_trust_line_to_pft_token: Transaction submission failed: {e}")
            logger.error(traceback.format_exc())
            raise
        except Exception as e:
            logger.error(f"GenericPFTUtilities.generate_trust_line_to_pft_token: Unexpected error: {e}")
            logger.error(traceback.format_exc())
            raise

    async def get_recent_messages(self, wallet_address): 
        incoming_messages = None
        outgoing_messages = None
        try:

            memo_history = await self.get_account_memo_history(wallet_address)
            memo_history = memo_history.sort_values('datetime')

            def format_transaction_message(transaction):
                """
                Format a transaction message with specified elements.
                
                Args:
                transaction (pd.Series): A single transaction from the DataFrame.
                
                Returns:
                str: Formatted transaction message.
                """
                url_mask = self.network_config.explorer_tx_url_mask
                return (f"Task ID: {transaction['memo_type']}\n"
                        f"Memo: {transaction['memo_data']}\n"
                        f"PFT Amount: {transaction['directional_pft']}\n"
                        f"Datetime: {transaction['datetime']}\n"
                        f"XRPL Explorer: {url_mask.format(hash=transaction['hash'])}")
            
            # Only try to format if there are matching transactions
            incoming_df = memo_history[memo_history['direction']=='INCOMING']
            if not incoming_df.empty:
                incoming_messages = format_transaction_message(incoming_df.tail(1).iloc[0])
                
            outgoing_df = memo_history[memo_history['direction']=='OUTGOING']
            if not outgoing_df.empty:
                outgoing_messages = format_transaction_message(outgoing_df.tail(1).iloc[0])

        except Exception as e:
            logger.error(f"GenericPFTUtilities.get_recent_messages: Error getting recent messages for {wallet_address}: {e}")
            logger.error(traceback.format_exc())
        
        return incoming_messages, outgoing_messages
    
    @staticmethod
    def remove_chunk_prefix(self, memo_data: str) -> str:
        """Remove chunk prefix from memo data if present.
        
        Args:
            memo_data: Raw memo data string
                
        Returns:
            str: Memo data with chunk prefix removed if present, otherwise unchanged
        """
        return re.sub(r'^chunk_\d+__', '', memo_data)
