"""Canonical intent enum used by the contract surface."""

from enum import Enum


class Intent(str, Enum):
    """Intent buckets and extended agent-facing routes from the contract docs."""

    LOCAL_METADATA = "LOCAL_METADATA"
    LOCAL_MUTATION = "LOCAL_MUTATION"
    REMOTE_METADATA = "REMOTE_METADATA"
    QUERY = "QUERY"
    GENERATION = "GENERATION"
    RESEARCH = "RESEARCH"
    DOCTOR = "DOCTOR"
    WORKSPACE_QUERY = "WORKSPACE_QUERY"
    WORKSPACE_COMPARE = "WORKSPACE_COMPARE"
    RADAR_STATUS = "RADAR_STATUS"
    RADAR_BRIEF = "RADAR_BRIEF"
    INBOX_TRIAGE = "INBOX_TRIAGE"
    INBOX_APPLY = "INBOX_APPLY"


__all__ = ["Intent"]
