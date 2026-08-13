"""Evidence plane (REF-R7/P1 incremental adoption).

Formal runs already emit hashed artifacts and generation manifests; this
package hosts the verification surface. P1 adds the frozen-reference
differential verifier; P2 will adopt provenance/receipt/fingerprint blocks
end-to-end.
"""

from limit_pullback.evidence.verification.frozen_differential import (
    read_run_summary,
    verify_against_reference,
)
from limit_pullback.evidence.verification.fingerprint import (
    build_version_fingerprint,
    fingerprint_hash,
)
from limit_pullback.evidence.verification.receipt import write_run_receipt

__all__ = [
    "build_version_fingerprint",
    "fingerprint_hash",
    "read_run_summary",
    "verify_against_reference",
    "write_run_receipt",
]
