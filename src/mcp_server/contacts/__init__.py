"""Contact resolution: the enrichment finder chain + the email verifier chain.

Public surface consumed by the ``resolve_contact`` / ``verify_email`` tool
wrappers: the two multi-key enrichment finders (Prospeo primary, Apollo
failover) behind ``ChainedFinder``, the verifier chain
(QuickEmailVerification pool primary, MyEmailVerifier fallback), the
name/domain helpers, and the write-free resolution core.
"""

from .apollo import ApolloFinder
from .finder import (
    ChainedFinder,
    EnrichmentResult,
    Finder,
    ProviderUnavailableError,
)
from .helpers import extract_domain, split_name
from .prospeo import ProspeoFinder, ProspeoResult
from .quickemailverification import QuickEmailVerificationClient
from .resolve import ContactResult, resolve_contact
from .verifier import MyEmailVerifierAPIError, MyEmailVerifierClient, VerifyResult
from .verify_chain import ChainedEmailVerifier, NoVerifierAvailableError

__all__ = [
    "ProspeoFinder",
    "ProspeoResult",
    "ApolloFinder",
    "ChainedFinder",
    "EnrichmentResult",
    "Finder",
    "ProviderUnavailableError",
    "QuickEmailVerificationClient",
    "MyEmailVerifierClient",
    "MyEmailVerifierAPIError",
    "ChainedEmailVerifier",
    "NoVerifierAvailableError",
    "VerifyResult",
    "resolve_contact",
    "ContactResult",
    "split_name",
    "extract_domain",
]
