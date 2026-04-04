"""IceWhale CRM package."""
from crm.models import CRMEntry, FeatureModule, StatusTag, TypeTag
from crm.schemas import CRMEntryCreate, CRMEntryUpdate, CRMEntryResponse

__all__ = [
    "CRMEntry",
    "TypeTag",
    "StatusTag",
    "FeatureModule",
    "CRMEntryCreate",
    "CRMEntryUpdate",
    "CRMEntryResponse",
]
