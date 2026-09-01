"""Domain exception hierarchy.

Services raise these; the API layer maps them to HTTP status codes in one
place, so business logic never imports ``fastapi``.
"""
from __future__ import annotations


class JakalError(Exception):
    """Base for all domain errors. ``http_status`` drives the API mapping."""

    http_status: int = 400


class NotFoundError(JakalError):
    http_status = 404


class AuthenticationError(JakalError):
    http_status = 401


class AuthorizationError(JakalError):
    http_status = 403


class ConflictError(JakalError):
    http_status = 409


class SeparationOfDutiesError(AuthorizationError):
    """The approver may not be the requester of the same action."""


class CryptoPolicyError(JakalError):
    """A signature failed a required cryptographic policy (e.g. strict PQC)."""

    http_status = 422
