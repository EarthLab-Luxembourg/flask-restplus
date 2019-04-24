# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import marshmallow as ma

from collections import OrderedDict
from copy import deepcopy
from six import iteritems
from webargs import argmap2schema

from ._http import HTTPStatus

FIRST_CAP_RE = re.compile('(.)([A-Z][a-z]+)')
ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')


__all__ = ('merge', 'camel_to_dash', 'default_id', 'not_none', 'not_none_sorted', 'unpack', 'get_schema')


def merge(first, second):
    '''
    Recursively merges two dictionnaries.

    Second dictionnary values will take precedance over those from the first one.
    Nested dictionnaries are merged too.

    :param dict first: The first dictionnary
    :param dict second: The second dictionnary
    :return: the resulting merged dictionnary
    :rtype: dict
    '''
    if not isinstance(second, dict):
        return second
    result = deepcopy(first)
    for key, value in iteritems(second):
        if key in result and isinstance(result[key], dict):
                result[key] = merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def camel_to_dash(value):
    '''
    Transform a CamelCase string into a low_dashed one

    :param str value: a CamelCase string to transform
    :return: the low_dashed string
    :rtype: str
    '''
    first_cap = FIRST_CAP_RE.sub(r'\1_\2', value)
    return ALL_CAP_RE.sub(r'\1_\2', first_cap).lower()


def default_id(resource, method):
    '''Default operation ID generator'''
    return '{0}_{1}'.format(method, camel_to_dash(resource))


def not_none(data):
    '''
    Remove all keys where value is None

    :param dict data: A dictionnary with potentialy some values set to None
    :return: The same dictionnary without the keys with values to ``None``
    :rtype: dict
    '''
    return dict((k, v) for k, v in iteritems(data) if v is not None)


def not_none_sorted(data):
    '''
    Remove all keys where value is None

    :param OrderedDict data: A dictionnary with potentialy some values set to None
    :return: The same dictionnary without the keys with values to ``None``
    :rtype: OrderedDict
    '''
    return OrderedDict((k, v) for k, v in sorted(iteritems(data)) if v is not None)


def unpack(response, default_code=HTTPStatus.OK):
    '''
    Unpack a Flask standard response.

    Flask response can be:
    - a single value
    - a 2-tuple ``(value, code)``
    - a 3-tuple ``(value, code, headers)``

    .. warning::

        When using this function, you must ensure that the tuple is not the reponse data.
        To do so, prefer returning list instead of tuple for listings.

    :param response: A Flask style response
    :param int default_code: The HTTP code to use as default if none is provided
    :return: a 3-tuple ``(data, code, headers)``
    :rtype: tuple
    :raise ValueError: if the response does not have one of the expected format
    '''
    if not isinstance(response, tuple):
        # data only
        return response, default_code, {}
    elif len(response) == 1:
        # data only as tuple
        return response[0], default_code, {}
    elif len(response) == 2:
        # data and code
        data, code = response
        return data, code, {}
    elif len(response) == 3:
        # data, code and headers
        data, code, headers = response
        return data, code or default_code, headers
    else:
        raise ValueError('Too many response values')


def get_schema(argmap, req=None):
    """
    Get a marshmallow schema instance based on the given argmap.

    :return: Marshmallow schema instance
    """
    if callable(argmap):
        argmap = argmap(req)

    if isinstance(argmap, ma.Schema):
        schema = argmap
    elif isinstance(argmap, type) and issubclass(argmap, ma.Schema):
        schema = argmap()
    else:
        schema = argmap2schema(argmap)()
    return schema


def merge_schema_attrs(schema, **kwargs):
    """Extend a marshmallow schema intance with given keyword arguments.

    This function can be used to extend an already instantiated schema.
    For example:

    ```
    schema = MySchema(dump_only=('a', 'b'), many=True, exclude=('e',))
    schema_extended = extend_schema(schema, dump_only=('c',), many=False, context="context")
    ```

    `schema` will got `dump_only=('a', 'b', 'c'), many=False, context="context", exclude=('e',))
    """
    result = {}

    for attr in ['many', 'context', 'partial', 'unknown']:
        if attr in kwargs:
            # Use provided value
            value = kwargs[attr]
        else:
            # Use provided schema attribute value
            value = getattr(schema, attr, None)
        result[attr] = value

    for attr in ['only', 'exclude', 'load_only', 'dump_only']:
        value = getattr(schema, attr, None)
        if attr in kwargs and kwargs[attr] is not None:
            # Merge values
            value = tuple(kwargs[attr]) + tuple(value or [])
        result[attr] = value
    return result

def extend_schema(schema, **kwargs):
    """Creates a new schema instance using given instance and arguments

    Creates a new marshmallow schema instance using given instance attributes merged with given ones
    as keyword arguments.
    It is particularly useful when you want to create a new schema instance with some more `only` or `exclude` attributes
    for example.

    :param schema: Marshmallow schema instance
    :param kwargs: Marshmallow schema constructor arguments
    :return: A new marshmallow schema instance combining attributes from given instance and provided ones
    """
    schema_class = type(schema)
    kwargs = merge_schema_attrs(schema, **kwargs)
    return schema_class(**kwargs)
