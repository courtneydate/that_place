"""Custom encrypted field for JSON data.

django-encrypted-model-fields v0.6 does not ship EncryptedJSONField.
This module provides one built on top of EncryptedTextField.
"""
import json

from encrypted_model_fields.fields import EncryptedTextField, encrypt_str


class EncryptedJSONField(EncryptedTextField):
    """An encrypted text field that transparently stores and retrieves JSON.

    Values are serialised to a JSON string before encryption and
    deserialised back to a dict/list after decryption.

    get_db_prep_save is overridden directly to avoid the problematic
    EncryptedTextField → CharField → to_python chain which converts a parsed
    dict back to Python repr (single-quoted) rather than valid JSON before
    encryption, causing json.loads to fail on retrieval.
    """

    def get_db_prep_save(self, value, connection):
        """JSON-serialise then encrypt directly, bypassing get_prep_value."""
        if value is None:
            return None
        if not isinstance(value, str):
            value = json.dumps(value)
        return encrypt_str(value).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        """Decrypt and JSON-parse the stored value."""
        if value is None:
            return {}
        # super().from_db_value calls self.to_python, which already decrypts
        # and JSON-parses the value — so the result may already be a dict/list.
        result = super().from_db_value(value, expression, connection)
        if isinstance(result, (dict, list)):
            return result
        if not result:
            return {}
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_python(self, value):
        """Coerce to a Python dict/list for form/serialiser use."""
        if isinstance(value, (dict, list)):
            return value
        value = super().to_python(value)
        if isinstance(value, str) and value:
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        return value if value is not None else {}
