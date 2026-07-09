from typing import Any, Optional
from typing_extensions import Literal, TypedDict

from .constants import (
    DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION,
    DOCUMENT_TYPE_UNKNOWN,
    FAILURE_REASON_INVALID_IMAGE_PAYLOAD,
    FAILURE_REASON_LOW_IMAGE_QUALITY,
    FAILURE_REASON_NOT_TARGET_DOCUMENT,
    FAILURE_REASON_OCR_FAILED,
    FAILURE_REASON_PAGE_1_NOT_FOUND,
    FAILURE_REASON_PRIVACY_FILTER_FAILED,
    FAILURE_REASON_UNSUPPORTED_FILE_TYPE,
    IMAGE_QUALITY_LOW,
    IMAGE_QUALITY_READABLE,
    IMAGE_QUALITY_UNREADABLE,
    IMAGE_QUALITY_UNKNOWN,
    SCENE_DIAGRAM_DEFERRED,
    SCENE_DIAGRAM_NOT_PROVIDED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
)

OCRStatus = Literal[STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED]
DocumentType = Literal[DOCUMENT_TYPE_TRAFFIC_ACCIDENT_CONFIRMATION, DOCUMENT_TYPE_UNKNOWN]
FailureReason = Literal[
    FAILURE_REASON_UNSUPPORTED_FILE_TYPE,
    FAILURE_REASON_INVALID_IMAGE_PAYLOAD,
    FAILURE_REASON_NOT_TARGET_DOCUMENT,
    FAILURE_REASON_PAGE_1_NOT_FOUND,
    FAILURE_REASON_LOW_IMAGE_QUALITY,
    FAILURE_REASON_OCR_FAILED,
    FAILURE_REASON_PRIVACY_FILTER_FAILED,
]
ImageQuality = Literal[
    IMAGE_QUALITY_READABLE,
    IMAGE_QUALITY_LOW,
    IMAGE_QUALITY_UNREADABLE,
    IMAGE_QUALITY_UNKNOWN,
]
SceneDiagramStatus = Literal[SCENE_DIAGRAM_NOT_PROVIDED, SCENE_DIAGRAM_DEFERRED]


class VerificationCriteria(TypedDict, total=False):
    title_matched: bool
    accident_labels_matched_count: int
    issuer_structure_matched_count: int


class DocumentCheck(TypedDict, total=False):
    is_target_document: bool
    document_name: Optional[str]
    reason: Optional[str]
    verification_score: int
    verification_criteria: VerificationCriteria


class PageInfo(TypedDict, total=False):
    page_1_processed: bool
    page_2_exists: bool


class AccidentType(TypedDict, total=False):
    value: Optional[str]
    raw_text: Optional[str]


class Damage(TypedDict, total=False):
    raw_text: Optional[str]
    death_count: Optional[int]
    injury_count: Optional[int]
    property_damage_amount: Optional[int]


class ExtractedFields(TypedDict, total=False):
    receipt_number: Optional[str]
    issue_number: Optional[str]
    police_station: Optional[str]
    accident_datetime: Optional[str]
    accident_location: Optional[str]
    accident_type: AccidentType
    accident_cause: Optional[str]
    damage: Damage
    accident_description: Optional[str]
    usage: Optional[str]


class SceneDiagram(TypedDict, total=False):
    page_2_exists: bool
    analysis_status: SceneDiagramStatus
    reason: Optional[str]
    raw_image_ref: None


class Quality(TypedDict, total=False):
    ocr_confidence: Optional[float]
    image_quality: ImageQuality
    warnings: list[str]


class Privacy(TypedDict, total=False):
    masking_applied: bool
    excluded_sensitive_fields: list[str]
    masked_fields: list[str]


class TrafficAccidentConfirmationOCRState(TypedDict, total=False):
    # Supervisor input
    document_image: Optional[str]
    document_mime_type: Optional[str]
    source_filename: Optional[str]

    # OCR node output
    ocr_status: Optional[OCRStatus]
    document_type: Optional[DocumentType]
    ocr_error: Optional[str]
    failure_reason: Optional[FailureReason]
    raw_text_redacted: Optional[str]
    extracted_fields: ExtractedFields
    document_check: DocumentCheck
    page_info: PageInfo
    scene_diagram: SceneDiagram
    quality: Quality
    privacy: Privacy
    missing_fields: list[str]
    limitations: list[str]
    format_errors: list[str]

    # Optional debug or parsed model payload.
    model_response: dict[str, Any]

    # Supervisor output collection
    agent_results: dict[str, Any]
