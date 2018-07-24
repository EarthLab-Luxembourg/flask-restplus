# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import marshmallow as ma

from functools import wraps

from .utils import get_schema, unpack

log = logging.getLogger(__name__)


def marshal(data, fields):
    """Takes raw data (in the form of a dict, list, object) and a dict of
    fields or a Schema to output and filters the data based on those fields/Schema.

    :param data: the actual object(s) from which the fields are taken from
    :param fields: Marshmallow Schema or dict of marshmallow fields

    >>> from flask_restplus import fields, marshal
    >>> data = { 'a': 100, 'b': 'foo', 'c': None }
    >>> mfields = { 'a': fields.str(), 'c': fields.Str(), 'd': fields.Str() }

    >>> marshal(data, mfields)
    OrderedDict([('a', 100), ('c', None), ('d', None)])

    >>> marshal(data, mfields, envelope='data')
    OrderedDict([('data', OrderedDict([('a', 100), ('c', None), ('d', None)]))])

    >>> marshal(data, mfields, skip_none=True)
    OrderedDict([('a', 100)])

    """
    schema = get_schema(fields)
    out, errors = schema.dump(data)

    # Not sure about what to do with errors, so we just log them
    if errors and len(errors) > 0:
        # Maybe we should raise an error ?
        log.error('Marshalling errors %s', ma.pprint(errors))

    return out


class marshal_with(object):
    """A decorator that apply marshalling to the return values of your methods.

    >>> from flask_restplus import marshal_with
    >>> from marshmallow import fields
    >>> mfields = { 'a': fields.Str() }
    >>> @marshal_with(mfields)
    ... def get():
    ...     return { 'a': 100, 'b': 'foo' }
    ...
    ...
    >>> get()
    OrderedDict([('a', 100)])

    >>> @marshal_with(mfields, envelope='data')
    ... def get():
    ...     return { 'a': 100, 'b': 'foo' }
    ...
    ...
    >>> get()
    OrderedDict([('data', OrderedDict([('a', 100)]))])

    >>> mfields = { 'a': fields.Str(), 'c': fields.Str(), 'd': fields.Str() }
    >>> @marshal_with(mfields)
    ... def get():
    ...     return { 'a': 100, 'b': 'foo', 'c': None }
    ...
    ...
    >>> get()
    OrderedDict([('a', 100)])

    see :meth:`flask_restplus.marshal`
    """

    def __init__(self, fields):
        """
        :param fields: a dict of whose keys will make up the final
                       serialized response output or a Schema
        """
        self.fields = fields

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)
            if isinstance(resp, tuple):
                data, code, headers = unpack(resp)
                return (
                    marshal(data, self.fields),
                    code,
                    headers
                )
            else:
                return marshal(resp, self.fields)

        return wrapper


class marshal_with_field(object):
    """
    A decorator that formats the return values of your methods with a single field.

    >>> from flask_restplus import marshal_with_field
    >>> from marshmallow import fields
    >>> @marshal_with_field(fields.List(fields.Str))
    ... def get():
    ...     return ['1', 2, 3.0]
    ...
    >>> get()
    [1, 2, 3]

    see :meth:`flask_restplus.marshal_with`
    """
    def __init__(self, field):
        """
        :param field: a single field with which to marshal the output.
        """
        if isinstance(field, type):
            self.field = field()
        else:
            self.field = field

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)

            if isinstance(resp, tuple):
                data, code, headers = unpack(resp)
                # Wrap data into an object to be able to use field serialization func
                return self.field.serialize('v', {'v': data}), code, headers
            return self.field.serialize('v', {'v': resp})

        return wrapper
