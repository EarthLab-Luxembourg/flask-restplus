"""
Custom jsonschema Format Checker.

Register in this module any custom jsonschema format validation
"""
import base64
import binascii

import jsonschema
from jsonschema.compat import str_types


class CustomFormatChecker(jsonschema.FormatChecker):
    """
    Use this jsonschema format checker to validate custom format used by custom fields
    on `fields` module
    """
    pass


@CustomFormatChecker.cls_checks('base64', raises=(TypeError, binascii.Error))
def is_base64(instance):
    if not isinstance(instance, str_types):
        return True

    return base64.b64decode(instance.encode())


def extends(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def extended_validate_properties(validator, properties, instance, schema):

        for property, subschema in properties.items():
            # Add default values
            if "default" in subschema:
                instance.setdefault(property, subschema["default"])

        # Remove instance properties not defined in schema
        unknown_props = []
        for prop in instance:
            if prop not in properties:
                unknown_props.append(prop)

        for prop in unknown_props:
            instance.pop(prop)

        for error in validate_properties(validator, properties, instance, schema):
            yield error

    return jsonschema.validators.extend(
        validator_class, {"properties": extended_validate_properties},
    )


# Draft 4 validator which also add default values if specified in schema when validating data
# And which also drop any properties in validated instance which are not defined in the schema
ExtendedDraft4Validator = extends(jsonschema.Draft4Validator)
