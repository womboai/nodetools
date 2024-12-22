from enum import Enum
from decimal import Decimal
from pathlib import Path

CONFIG_DIR = Path.home().joinpath("postfiatcreds")

# Super Users
DISCORD_SUPER_USER_IDS = [402536023483088896, 471510026696261632]

# AI MODELS
DEFAULT_OPENROUTER_MODEL = 'anthropic/claude-3.5-sonnet:beta'
DEFAULT_OPEN_AI_MODEL = 'chatgpt-4o-latest'
DEFAULT_ANTHROPIC_MODEL = 'claude-3-5-sonnet-20241022'

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MIN_XRP_PER_TRANSACTION = Decimal('0.000001')  # Minimum XRP amount per transaction
MIN_XRP_BALANCE = 12  # Minimum XRP balance to be able to perform a transaction

# Maximum chunk size for a memo
MAX_MEMO_CHUNK_SIZE = 900

# Maximum length for a commitment sentence
MAX_COMMITMENT_SENTENCE_LENGTH = 950
 
# Maximum history length
MAX_HISTORY = 15  # TODO: rename this to something more descriptive

class SystemMemoType(Enum):
    # SystemMemoTypes cannot be chunked
    INITIATION_REWARD = 'INITIATION_REWARD'  # name is memo_type, value is memo_data pattern
    HANDSHAKE = 'HANDSHAKE'
    INITIATION_RITE = 'INITIATION_RITE'
    GOOGLE_DOC_CONTEXT_LINK = 'google_doc_context_link'
    INITIATION_GRANT = 'discord_wallet_funding'  # TODO: Deprecate this

SYSTEM_MEMO_TYPES = [memo_type.value for memo_type in SystemMemoType]
