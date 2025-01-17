# XRP ACCOUNT EXCEPTIONS

class XRPAccountNotFoundException(Exception):
    """ This exception is raised when the XRP account is not found """
    def __init__(self, address):
        super().__init__(f"XRP account not found: {address}")

class InsufficientXrpBalanceException(Exception):
    """ This exception is raised when the user does not have enough XRP balance """
    def __init__(self, xrp_address):
        super().__init__(f"Insufficient XRP balance: {xrp_address}")

# MEMO EXCEPTIONS

class HandshakeRequiredException(Exception):
    """ This exception is raised when the full handshake protocol has not been completed between two addresses"""
    def __init__(self, source, counterparty):
        super().__init__(f"Cannot encrypt message: Handshake protocol not completed between {source} and {counterparty}")
