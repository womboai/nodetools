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
from nodetools.task_processing.memo_types import SystemMemoType, TaskType
from loguru import logger
import re

TASK_ID_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2}_\d{2}:\d{2}(?:__[A-Z0-9]{4})?)')

def create_business_logic() -> BusinessLogicProvider:
    """Factory function to create all business logic components"""
    # Setup transaction graph
    graph = TransactionGraph()

    ### SYSTEM MEMO PATTERNS ###

    # Initiation rite patterns
    initiation_rite_pattern = MemoPattern(memo_type=SystemMemoType.INITIATION_RITE.value)
    initiation_reward_pattern = MemoPattern(memo_type=SystemMemoType.INITIATION_REWARD.value)
    graph.add_pattern(
        pattern_id="initiation_rite",
        memo_pattern=initiation_rite_pattern,
        transaction_type=TransactionType.REQUEST,
        valid_responses={initiation_reward_pattern}
    )
    graph.add_pattern(
        pattern_id="initiation_reward",
        memo_pattern=initiation_reward_pattern,
        transaction_type=TransactionType.RESPONSE,
    )

    # Google doc link patterns
    google_doc_link_pattern = MemoPattern(memo_type=SystemMemoType.GOOGLE_DOC_CONTEXT_LINK.value)
    graph.add_pattern(
        pattern_id="google_doc_link",
        memo_pattern=google_doc_link_pattern,
        transaction_type=TransactionType.STANDALONE,
    )

    # Handshake patterns
    handshake_request_pattern = MemoPattern(memo_type=SystemMemoType.HANDSHAKE.value)
    handshake_response_pattern = MemoPattern(memo_type=SystemMemoType.HANDSHAKE.value)
    graph.add_pattern(
        pattern_id="handshake_request",
        memo_pattern=handshake_request_pattern,
        transaction_type=TransactionType.REQUEST,
        valid_responses={handshake_response_pattern}
    )
    graph.add_pattern(
        pattern_id="handshake_response",
        memo_pattern=handshake_response_pattern,
        transaction_type=TransactionType.RESPONSE,
    )

    ### TASK MANAGEMENT MEMO PATTERNS ###

    # Create task memo patterns with regex for memo_type
    task_id_pattern = TASK_ID_PATTERN

    request_post_fiat_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.REQUEST_POST_FIAT.value)}.*')
    )
    proposal_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.PROPOSAL.value)}.*')
    )
    acceptance_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.ACCEPTANCE.value)}.*')
    )
    refusal_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.REFUSAL.value)}.*')
    )
    task_output_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.TASK_OUTPUT.value)}.*')
    )
    verification_prompt_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.VERIFICATION_PROMPT.value)}.*')
    )
    verification_response_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.VERIFICATION_RESPONSE.value)}.*')
    )
    reward_pattern = MemoPattern(
        memo_type=task_id_pattern,
        memo_data=re.compile(f'.*{re.escape(TaskType.REWARD.value)}.*')
    )

    # Add patterns to graph
    graph.add_pattern(
        pattern_id="request_post_fiat",
        memo_pattern=request_post_fiat_pattern,
        transaction_type=TransactionType.REQUEST,
        valid_responses={proposal_pattern}
    )
    graph.add_pattern(
        pattern_id="proposal",
        memo_pattern=proposal_pattern,
        transaction_type=TransactionType.RESPONSE,
    )
    graph.add_pattern(
        pattern_id="acceptance",
        memo_pattern=acceptance_pattern,
        transaction_type=TransactionType.STANDALONE,
    )
    graph.add_pattern(
        pattern_id="refusal",
        memo_pattern=refusal_pattern,
        transaction_type=TransactionType.STANDALONE,
    )
    graph.add_pattern(
        pattern_id="task_output",
        memo_pattern=task_output_pattern,
        transaction_type=TransactionType.REQUEST,
        valid_responses={verification_prompt_pattern}
    )
    graph.add_pattern(
        pattern_id="verification_prompt",
        memo_pattern=verification_prompt_pattern,
        transaction_type=TransactionType.RESPONSE
    )
    graph.add_pattern(
        pattern_id="verification_response",
        memo_pattern=verification_response_pattern,
        transaction_type=TransactionType.REQUEST,
        valid_responses={reward_pattern}
    )
    graph.add_pattern(
        pattern_id="reward",
        memo_pattern=reward_pattern,
        transaction_type=TransactionType.RESPONSE
    )

    # Create rules
    rules = [
        InitiationRiteRule(graph),
        InitiationRewardRule(graph),
        GoogleDocLinkRule(graph),
        HandshakeRequestRule(graph),
        HandshakeResponseRule(graph),
        RequestPostFiatRule(graph),
        ProposalRule(graph),
        AcceptanceRule(graph),
        RefusalRule(graph),
        TaskOutputRule(graph),
        VerificationPromptRule(graph),
        VerificationResponseRule(graph),
        RewardRule(graph)
        # TODO: Add more rules here
    ]

    return BusinessLogicProvider(rules)

def is_valid_task_id(memo_type: str) -> bool:
    """Check if a memo type is a valid task ID"""
    return bool(TASK_ID_PATTERN.match(memo_type)) if memo_type else False

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
    
    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is an initiation rite that needs processing.
        Must:
        1. Be a successful transaction
        2. Have INITIATION_RITE memo type
        3. Have valid rite text
        """

        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
            
        if tx.get('memo_type') != SystemMemoType.INITIATION_RITE.value:
            return False
            
        is_valid = self.is_valid_initiation_rite(tx.get('memo_data', ''))
        return is_valid
    
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
        pattern_id = self.get_pattern_id(request_tx)
        if not pattern_id:
            return None
        
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                require_after_request := FALSE  -- Check for ANY existing response
            );
        """

        # logger.debug(f"request_tx: memo_type: {request_tx['memo_type']}, memo_format: {request_tx['memo_format']}, memo_data: {request_tx['memo_data']}")
        
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

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is an initiation reward.
        Must:
        1. Be a successful transaction
        2. Have INITIATION_REWARD memo type
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
            
        if tx.get('memo_type') != SystemMemoType.INITIATION_REWARD.value:
            return False
            
        return True

class GoogleDocLinkRule(StandaloneRule):
    """Pure business logic for handling google doc links"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a google doc link
        Must:
        1. Be a successful transaction
        2. Have GOOGLE_DOC_CONTEXT_LINK memo type
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False

        if tx.get('memo_type') != SystemMemoType.GOOGLE_DOC_CONTEXT_LINK.value:
            return False
        return True
    
class HandshakeRequestRule(RequestRule):
    """Pure business logic for handling handshake requests"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a handshake request
        Must:
        1. Be a successful transaction
        2. Have HANDSHAKE memo type
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if tx.get('memo_type') != SystemMemoType.HANDSHAKE.value:
            return False
        return True
    
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
        pattern_id = self.get_pattern_id(request_tx)
        if not pattern_id:
            return None
        
        query = """
            SELECT * FROM find_transaction_response(
                request_account := %(account)s,
                request_destination := %(destination)s,
                request_time := %(request_time)s,
                response_memo_type := %(response_memo_type)s,
                require_after_request := FALSE  -- Check for ANY existing response
            );
        """

        # logger.debug(f"request_tx: memo_type: {request_tx['memo_type']}, memo_format: {request_tx['memo_format']}, memo_data: {request_tx['memo_data']}")
        
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

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a handshake response
        Must:
        1. Be a successful transaction
        2. Have HANDSHAKE memo type
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if tx.get('memo_type') != SystemMemoType.HANDSHAKE.value:
            return False
        return True

class RequestPostFiatRule(RequestRule):
    """Pure business logic for handling post-fiat requests"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a post-fiat request.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have REQUEST_POST_FIAT ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
            
        if not is_valid_task_id(tx.get('memo_type')):
            return False
            
        memo_data = tx.get('memo_data', '')
        if TaskType.REQUEST_POST_FIAT.value not in memo_data:
            return False
            
        return True
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """
        Get query information for finding a proposal response.
        """
        pattern_id = self.get_pattern_id(request_tx)
        if not pattern_id:
            return None
        
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
            'response_memo_data': f'%{TaskType.PROPOSAL.value}%'
        }
            
        return ResponseQuery(query=query, params=params)
    
class ProposalRule(ResponseRule):
    """Pure business logic for handling proposals"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a proposal.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have PROPOSAL ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
            
        if not is_valid_task_id(tx.get('memo_type')):
            return False
            
        memo_data = tx.get('memo_data', '')
        if TaskType.PROPOSAL.value not in memo_data:
            return False
            
        return True
    
class AcceptanceRule(StandaloneRule):
    """Pure business logic for handling acceptances"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is an acceptance.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have ACCEPTANCE ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.ACCEPTANCE.value not in memo_data:
            return False
        
        return True
    
class RefusalRule(StandaloneRule):
    """Pure business logic for handling refusals"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a refusal.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have REFUSAL ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.REFUSAL.value not in memo_data:
            return False
        
        return True
    
class TaskOutputRule(RequestRule):
    """Pure business logic for handling task outputs"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a task output.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have TASK_OUTPUT ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.TASK_OUTPUT.value not in memo_data:
            return False
        
        return True
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """
        Get query information for finding a verification prompt response.
        """
        pattern_id = self.get_pattern_id(request_tx)
        if not pattern_id:
            return None
        
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
            'response_memo_data': f'%{TaskType.VERIFICATION_PROMPT.value}%'
        }
            
        return ResponseQuery(query=query, params=params)
    
class VerificationPromptRule(ResponseRule):
    """Pure business logic for handling verification prompts"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a verification prompt.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have VERIFICATION_PROMPT ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.VERIFICATION_PROMPT.value not in memo_data:
            return False
        
        return True
    
class VerificationResponseRule(RequestRule):
    """Pure business logic for handling verification responses"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a verification response.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have VERIFICATION_RESPONSE ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.VERIFICATION_RESPONSE.value not in memo_data:
            return False
        
        return True
    
    async def find_response(
            self,
            request_tx: Dict[str, Any],
        ) -> Optional[ResponseQuery]:
        """
        Get query information for finding a verification prompt response.
        """
        pattern_id = self.get_pattern_id(request_tx)
        if not pattern_id:
            return None
        
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
            'response_memo_data': f'%{TaskType.REWARD.value}%'
        }
            
        return ResponseQuery(query=query, params=params)
    
class RewardRule(ResponseRule):
    """Pure business logic for handling rewards"""

    async def matches(self, tx: Dict[str, Any]) -> bool:
        """
        Check if this transaction is a reward.
        Must:
        1. Be a successful transaction
        2. Have valid task ID as memo_type
        3. Have REWARD ___ as part of memo_data
        """
        if tx.get('transaction_result') != 'tesSUCCESS':
            return False
        
        if not is_valid_task_id(tx.get('memo_type')):
            return False
        
        memo_data = tx.get('memo_data', '')
        if TaskType.REWARD.value not in memo_data:
            return False
        
        return True