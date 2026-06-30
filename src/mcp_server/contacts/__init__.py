"""Contact resolution: Prospeo enrich-person pool + MyEmailVerifier.

Public surface consumed by the ``resolve_contact`` / ``verify_email`` tool
wrappers: the multi-key Prospeo finder, the verifier client, the name/domain
helpers, and the write-free resolution core.
"""

from .helpers import extract_domain, split_name
from .prospeo import ProspeoFinder, ProspeoResult
from .resolve import ContactResult, resolve_contact
from .verifier import MyEmailVerifierClient, VerifyResult

__all__ = [
    "ProspeoFinder",
    "ProspeoResult",
    "MyEmailVerifierClient",
    "VerifyResult",
    "resolve_contact",
    "ContactResult",
    "split_name",
    "extract_domain",
]
