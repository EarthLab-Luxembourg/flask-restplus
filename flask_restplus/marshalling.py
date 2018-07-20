# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import OrderedDict
from functools import wraps
from six import iteritems

from flask import request, current_app, has_app_context

from .utils import unpack


def marshal(data, fields, envelope=None, skip_none=False, ordered=False):
    """Takes raw data (in the form of a dict, list, object) and a dict of
    fields or a Schema to output and filters the data based on those fields/Schema.

    :param data: the actual object(s) from which the fields are taken from
    :param fields: a dict of whose keys will make up the final serialized
                   response output or a Schema
    :param envelope: optional key that will be used to envelop the serialized
                     response
    :param bool skip_none: optional key will be used to eliminate fields
                           which value is None or the field's key not
                           exist in data
    :param bool ordered: Wether or not to preserve order


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

    schema = fields
    out = schema.dump(data)

    if skip_none:
        items = ((k, v) for k, v in out.items
                 if v is not None and v != OrderedDict() and v != {})

    out = OrderedDict(items) if ordered else dict(items)

    if envelope:
        out = OrderedDict([(envelope, out)]) if ordered else {envelope: out}

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
    >>> @marshal_with(mfields, skip_none=True)
    ... def get():
    ...     return { 'a': 100, 'b': 'foo', 'c': None }
    ...
    ...
    >>> get()
    OrderedDict([('a', 100)])

    see :meth:`flask_restplus.marshal`
    """
    def __init__(self, fields, envelope=None, skip_none=False, ordered=False):
        """
        :param fields: a dict of whose keys will make up the final
                       serialized response output or a Schema
        :param envelope: optional key that will be used to envelop the serialized
                         response
        """
        self.fields = fields
        self.envelope = envelope
        self.skip_none = skip_none
        self.ordered = ordered

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)
            if isinstance(resp, tuple):
                data, code, headers = unpack(resp)
                return (
                    marshal(data, self.fields, self.envelope, self.skip_none, self.ordered),
                    code,
                    headers
                )
            else:
                return marshal(resp, self.fields, self.envelope, self.skip_none, self.ordered)
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
