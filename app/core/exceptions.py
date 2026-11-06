"""Core application exception hierarchy for Multi-Tenant RAG API."""

from __future__ import annotations


class AppException(Exception):
    """Base application exception from which all domain errors inherit."""

    def __init__(self, message: str, details: dict[str, str | int] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CorruptedPDFError(AppException):
    """Raised when a PDF file cannot be parsed, is malformed, or corrupted."""

    def __init__(self, message: str = "Uploaded PDF file is corrupted or unreadable.") -> None:
        super().__init__(message=message)


class EmptyDocumentError(AppException):
    """Raised when an uploaded document contains no extractable text."""

    def __init__(self, message: str = "Uploaded document contains no extractable text.") -> None:
        super().__init__(message=message)


class DuplicateDocumentError(AppException):
    """Raised when an identical document hash already exists for the authenticated tenant."""

    def __init__(self, filename: str, file_hash: str) -> None:
        message = (
            f"Document '{filename}' with hash '{file_hash[:12]}...' already exists for this tenant."
        )
        super().__init__(message=message, details={"filename": filename, "file_hash": file_hash})
        self.filename = filename
        self.file_hash = file_hash


class EmbeddingTimeoutError(AppException):
    """Raised when the vector embedding provider times out."""

    def __init__(self, message: str = "Vector embedding service request timed out.") -> None:
        super().__init__(message=message)


class EmbeddingServiceError(AppException):
    """Raised when the vector embedding provider encounters an unrecoverable failure."""

    def __init__(self, message: str = "Vector embedding service encountered an error.") -> None:
        super().__init__(message=message)


class CrossTenantAccessError(AppException):
    """Raised when a tenant isolation invariant is violated."""

    def __init__(
        self,
        message: str = "Cross-tenant access violation detected.",
        details: dict[str, str | int] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)

