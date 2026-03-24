"""Custom DRF exception handler.

Transforms all API error responses into the standard That Place format:
    { "error": { "code": "ERROR_CODE", "message": "Human readable message", "details": {} } }
"""
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def that_place_exception_handler(exc, context):
    """Handle all DRF exceptions and return a standardised error envelope."""
    response = exception_handler(exc, context)

    if response is None:
        logger.exception('Unhandled exception in view %s', context.get('view'))
        return Response(
            {'error': {'code': 'INTERNAL_ERROR', 'message': 'An unexpected error occurred.', 'details': {}}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data

    # Authentication / permission errors come back as {"detail": "..."}
    if 'detail' in data and len(data) == 1:
        code = getattr(data['detail'], 'code', 'ERROR') if hasattr(data['detail'], 'code') else 'ERROR'
        code = str(code).upper()
        response.data = {
            'error': {
                'code': code,
                'message': str(data['detail']),
                'details': {},
            }
        }
        return response

    # Validation errors — field-level or non_field_errors
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        message = 'Validation failed.'
        if 'non_field_errors' in data:
            message = str(data['non_field_errors'][0])
        response.data = {
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': message,
                'details': {k: [str(e) for e in v] if isinstance(v, list) else [str(v)] for k, v in data.items()},
            }
        }
        return response

    # Fallback for anything else
    response.data = {
        'error': {
            'code': str(response.status_code),
            'message': str(data) if not isinstance(data, dict) else 'An error occurred.',
            'details': data if isinstance(data, dict) else {},
        }
    }
    return response
