"""
TransactionRules Module

This module defines the business logic rules for processing XRPL transactions in NodeTools.
There are two distinct layers of validation:

1. Pattern Matching (handled by TransactionGraph):
   - Validates the structure of memos (memo_type, memo_data, and memo_format)
   - Matches transactions to their correct workflow type
   - Determines valid response patterns for request transactions
   - Example: Checking if a memo matches the pattern for a proposal (PROPOSED PF ___)

2. Business Rule Validation (handled by Rule classes):
   - Validates transaction-level requirements (e.g., transaction success)
   - Enforces content-specific rules (e.g., minimum length for initiation rites)
   - Validates contextual requirements (e.g., proper sequencing)
   - Example: Checking if an initiation rite contains meaningful content

Example Flow:
1. Transaction received: memo_type="2024-03-20_14:30", memo_data="REQUEST_POST_FIAT ___ Can i get a task to do?"
2. TransactionGraph matches this to the "request_post_fiat" pattern
3. RequestPostFiatRule then used to validate that:
   - The transaction was successful
   - Any other request_post_fiat-specific business rules

When adding new rules, remember:
- Pattern matching logic belongs in create_business_logic()
- Only transaction-specific validation logic belongs in Rule.validate()
"""
from enum import Enum
from nodetools.models.models import (
    TransactionGraph,
    MemoPattern,
    ResponseQuery,
    BusinessLogicProvider,
    RequestRule,
    ResponseRule,
    StandaloneRule,
    TransactionType
)
from typing import Dict, Any, Optional
from loguru import logger
import re

class SystemMemoType(Enum):
    # SystemMemoTypes cannot be chunked
    INITIATION_REWARD = 'INITIATION_REWARD'  # name is memo_type, value is memo_data pattern
    HANDSHAKE = 'HANDSHAKE'
    INITIATION_RITE = 'INITIATION_RITE'
    GOOGLE_DOC_CONTEXT_LINK = 'google_doc_context_link'
    INITIATION_GRANT = 'discord_wallet_funding'  # TODO: Deprecate this

# Task types where the memo_type = task_id, requiring further disambiguation in the memo_data
class TaskType(Enum):
    """Task-related memo types for workflow management"""
    REQUEST_POST_FIAT = 'REQUEST_POST_FIAT ___ '
    PROPOSAL = 'PROPOSED PF ___ '
    ACCEPTANCE = 'ACCEPTANCE REASON ___ '
    REFUSAL = 'REFUSAL REASON ___ '
    TASK_OUTPUT = 'COMPLETION JUSTIFICATION ___ '
    VERIFICATION_PROMPT = 'VERIFICATION PROMPT ___ '
    VERIFICATION_RESPONSE = 'VERIFICATION RESPONSE ___ '
    REWARD = 'REWARD RESPONSE __ '

class MessageType(Enum):
    """Message-related memo types"""
    MEMO = 'chunk_'

TASK_ID_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}(?:__[A-Z0-9]{4})?)')

# System memo patterns
INITIATION_RITE_PATTERN = MemoPattern(memo_type=SystemMemoType.INITIATION_RITE.value)
INITIATION_REWARD_PATTERN = MemoPattern(memo_type=SystemMemoType.INITIATION_REWARD.value)
HANDSHAKE_PATTERN = MemoPattern(memo_type=SystemMemoType.HANDSHAKE.value)
GOOGLE_DOC_LINK_PATTERN = MemoPattern(memo_type=SystemMemoType.GOOGLE_DOC_CONTEXT_LINK.value)

# Define task memo patterns
REQUEST_POST_FIAT_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.REQUEST_POST_FIAT.value)}.*')
)
PROPOSAL_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    # rstrip() removes trailing space from enum value, \s? makes space optional
    # This handles historical data where trailing spaces were inconsistent
    memo_data=re.compile(f'.*{re.escape(TaskType.PROPOSAL.value.rstrip())}\\s?.*')
)
ACCEPTANCE_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.ACCEPTANCE.value)}.*')
)
REFUSAL_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.REFUSAL.value)}.*')
)
TASK_OUTPUT_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.TASK_OUTPUT.value)}.*')
)
VERIFICATION_PROMPT_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.VERIFICATION_PROMPT.value)}.*')
)
VERIFICATION_RESPONSE_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.VERIFICATION_RESPONSE.value)}.*')
)
REWARD_PATTERN = MemoPattern(
    memo_type=TASK_ID_PATTERN,
    memo_data=re.compile(f'.*{re.escape(TaskType.REWARD.value)}.*')
)

def create_business_logic() -> BusinessLogicProvider:
    """Factory function to create all business logic components"""
    # Setup transaction graph
    graph = TransactionGraph()

    # Create rules so we can map them to patterns
    rules = {
        "initiation_rite": InitiationRiteRule(),
        "initiation_reward": InitiationRewardRule(),
        "google_doc_link": GoogleDocLinkRule(),
        "handshake_request": HandshakeRequestRule(),
        "handshake_response": HandshakeResponseRule(),
        "request_post_fiat": RequestPostFiatRule(),
        "proposal": ProposalRule(),
        "acceptance": AcceptanceRule(),
        "refusal": RefusalRule(),
        "task_output": TaskOutputRule(),
        "verification_prompt": VerificationPromptRule(),
        "verification_response": VerificationResponseRule(),
        "reward": RewardRule()
    }

    # Add initiation rite patterns to graph
    graph.add_pattern(
        pattern_id="initiation_rite",
        memo_pattern=INITIATION_RITE_PATTERN,
        transaction_type=TransactionType.REQUEST,
        valid_responses={INITIATION_REWARD_PATTERN}
    )
    graph.add_pattern(
        pattern_id="initiation_reward",
        memo_pattern=INITIATION_REWARD_PATTERN,
        transaction_type=TransactionType.RESPONSE,
    )

    # Add google doc link patterns to graph
    graph.add_pattern(
        pattern_id="google_doc_link",
        memo_pattern=GOOGLE_DOC_LINK_PATTERN,
        transaction_type=TransactionType.STANDALONE,
    )

    # Add handshake patterns to graph
    graph.add_pattern(
        pattern_id="handshake_request",
        memo_pattern=HANDSHAKE_PATTERN,
        transaction_type=TransactionType.REQUEST,
        valid_responses={HANDSHAKE_PATTERN}
    )
    graph.add_pattern(
        pattern_id="handshake_response",
        memo_pattern=HANDSHAKE_PATTERN,
        transaction_type=TransactionType.RESPONSE,
    )

    # Add patterns to graph
    graph.add_pattern(
        pattern_id="request_post_fiat",
        memo_pattern=REQUEST_POST_FIAT_PATTERN,
        transaction_type=TransactionType.REQUEST,
        valid_responses={PROPOSAL_PATTERN}
    )
    graph.add_pattern(
        pattern_id="proposal",
        memo_pattern=PROPOSAL_PATTERN,
        transaction_type=TransactionType.RESPONSE,
    )
    graph.add_pattern(
        pattern_id="acceptance",
        memo_pattern=ACCEPTANCE_PATTERN,
        transaction_type=TransactionType.STANDALONE,
    )
    graph.add_pattern(
        pattern_id="refusal",
        memo_pattern=REFUSAL_PATTERN,
        transaction_type=TransactionType.STANDALONE,
    )
    graph.add_pattern(
        pattern_id="task_output",
        memo_pattern=TASK_OUTPUT_PATTERN,
        transaction_type=TransactionType.REQUEST,
        valid_responses={VERIFICATION_PROMPT_PATTERN}
    )
    graph.add_pattern(
        pattern_id="verification_prompt",
        memo_pattern=VERIFICATION_PROMPT_PATTERN,
        transaction_type=TransactionType.RESPONSE
    )
    graph.add_pattern(
        pattern_id="verification_response",
        memo_pattern=VERIFICATION_RESPONSE_PATTERN,
        transaction_type=TransactionType.REQUEST,
        valid_responses={REWARD_PATTERN}
    )
    graph.add_pattern(
        pattern_id="reward",
        memo_pattern=REWARD_PATTERN,
        transaction_type=TransactionType.RESPONSE
    )

    return BusinessLogicProvider(
        transaction_graph=graph,
        pattern_rule_map=rules
    )

def is_valid_task_id(memo_type: str) -> bool:
    """Check if a memo type is a valid task ID"""
    return bool(TASK_ID_PATTERN.match(memo_type)) if memo_type else False

def regex_to_sql_pattern(pattern: re.Pattern) -> str:
    """Convert a regex pattern to SQL LIKE pattern"""
    pattern_str = pattern.pattern
    
    # First remove the optional whitespace pattern completely
    pattern_str = re.sub(r'\\s\?', '', pattern_str)
    
    # Then extract the core content between .* markers
    if match := re.match(r'\.\*(.*?)\.\*', pattern_str):
        clean_text = match.group(1).replace('\\', '')
        return f'%{clean_text}%'
    
    return f'%{pattern_str}%'

class InitiationRiteRule(RequestRule):
    """Pure business logic for handling initiation rites"""

    @staticmethod
    def is_valid_initiation_rite(rite_text: str) -> bool:
        """Validate if the initiation rite meets basic requirements"""
        if not rite_text or not isinstance(rite_text, str):
            return False
        
        # Remove whitespace
        cleaned_rite = str(rite_text).strip()

        # Check minimum length
        if len(cleaned_rite) < 10:
            return False
        
        return True
    
    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for an initiation rite.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        2. Have valid rite text
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False

        return self.is_valid_initiation_rite(tx.get('memo_data', ''))
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """
        Get query information for finding an initiation rite response.
        The response must be:
        1. Sent to the same account
        2. Sent from the account that received the initiation rite
        3. Have INITIATION_REWARD memo type
        4. Successful transaction (handled by find_transaction_response)
        """
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                require_after_request := FALSE  -- Check for ANY existing response
            );
        """

        params = {
            # Attempt to retrieve account and destination from top level of tx or tx_json_parsed
            'account': request_tx.get('account', request_tx.get('tx_json_parsed', {}).get('Account')),
            'destination': request_tx.get('destination', request_tx.get('tx_json_parsed', {}).get('Destination')),
            'request_time': request_tx.get('close_time_iso'),
            'response_memo_type': SystemMemoType.INITIATION_REWARD.value
        }
            
        return ResponseQuery(query=query, params=params)
    
class InitiationRewardRule(ResponseRule):
    """Pure business logic for handling initiation rewards"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for an initiation reward.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'

class GoogleDocLinkRule(StandaloneRule):
    """Pure business logic for handling google doc links"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a google doc link.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
class HandshakeRequestRule(RequestRule):
    """Pure business logic for handling handshake requests"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a handshake request.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'

    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """
        Get query information for finding a handshake response.
        The response must be:
        1. Sent to the same account
        2. Sent from the account that received the handshake request
        3. Have HANDSHAKE memo type
        4. Successful transaction (handled by find_transaction_response)
        """
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                require_after_request := FALSE  -- Check for ANY existing response
            );
        """

        params = {
            # Attempt to retrieve account and destination from top level of tx or tx_json_parsed
            'account': request_tx.get('account', request_tx.get('tx_json_parsed', {}).get('Account')),
            'destination': request_tx.get('destination', request_tx.get('tx_json_parsed', {}).get('Destination')),
            'request_time': request_tx.get('close_time_iso'),
            'response_memo_type': SystemMemoType.HANDSHAKE.value
        }
            
        return ResponseQuery(query=query, params=params)

class HandshakeResponseRule(ResponseRule):
    """Pure business logic for handling handshake responses"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a handshake response.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'

class RequestPostFiatRule(RequestRule):
    """Pure business logic for handling post-fiat requests"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a post-fiat request.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """Get query information for finding a proposal response."""
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                response_memo_data := %(response_memo_data)s,
                require_after_request := TRUE
            );
        """
        
        params = {
            'account': request_tx.get('account', request_tx.get('tx_json_parsed', {}).get('Account')),
            'destination': request_tx.get('destination', request_tx.get('tx_json_parsed', {}).get('Destination')),
            'request_time': request_tx.get('close_time_iso'),
            'response_memo_type': request_tx.get('memo_type'),
            'response_memo_data': regex_to_sql_pattern(PROPOSAL_PATTERN.memo_data)
        }
            
        return ResponseQuery(query=query, params=params)
    
class ProposalRule(ResponseRule):
    """Pure business logic for handling proposals"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a proposal.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
class AcceptanceRule(StandaloneRule):
    """Pure business logic for handling acceptances"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for an acceptance.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
class RefusalRule(StandaloneRule):
    """Pure business logic for handling refusals"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a refusal.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
class TaskOutputRule(RequestRule):
    """Pure business logic for handling task outputs"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a task output.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """Get query information for finding a verification prompt response."""
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                response_memo_data := %(response_memo_data)s,
                require_after_request := TRUE
            );
        """
        
        params = {
            'account': request_tx.get('account', request_tx.get('tx_json_parsed', {}).get('Account')),
            'destination': request_tx.get('destination', request_tx.get('tx_json_parsed', {}).get('Destination')),
            'request_time': request_tx.get('close_time_iso'),
            'response_memo_type': request_tx.get('memo_type'),
            'response_memo_data': regex_to_sql_pattern(VERIFICATION_PROMPT_PATTERN.memo_data)
        }
            
        return ResponseQuery(query=query, params=params)
    
class VerificationPromptRule(ResponseRule):
    """Pure business logic for handling verification prompts"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a verification prompt.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
class VerificationResponseRule(RequestRule):
    """Pure business logic for handling verification responses"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a verification response.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """Get query information for finding a verification prompt response."""
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                response_memo_data := %(response_memo_data)s,
                require_after_request := TRUE
            );
        """
        
        params = {
            'account': request_tx.get('account', request_tx.get('tx_json_parsed', {}).get('Account')),
            'destination': request_tx.get('destination', request_tx.get('tx_json_parsed', {}).get('Destination')),
            'request_time': request_tx.get('close_time_iso'),
            'response_memo_type': request_tx.get('memo_type'),
            'response_memo_data': regex_to_sql_pattern(REWARD_PATTERN.memo_data)
        }
            
        return ResponseQuery(query=query, params=params)
    
class RewardRule(ResponseRule):
    """Pure business logic for handling rewards"""

    async def validate(self, tx: Dict[str, Any]) -> bool:
        """
        Validate business rules for a reward.
        Pattern matching is handled by TransactionGraph.
        Must:
        1. Be a successful transaction
        """
        return tx.get('transaction_result') == 'tesSUCCESS'
