"""Apollo.io enrichment: the failover tier behind Prospeo.

``client`` owns the multi-key HTTP call and the status dispatch; ``parse``
owns the pure response mapping, kept separate so it stays testable against a
recorded response without a key or a paid plan.
"""

from .client import APOLLO_MATCH_URL, ApolloFinder
from .parse import PROVIDER, extract_person

__all__ = ["ApolloFinder", "APOLLO_MATCH_URL", "extract_person", "PROVIDER"]
