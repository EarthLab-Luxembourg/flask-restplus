# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import marshmallow as ma

from functools import wraps

from flask import request, current_app, has_app_context

from .mask import Mask, apply as apply_mask
from .utils import unpack, get_schema

logger = logging.getLogger(__name__)


def marshal(data, fields, many=None, mask=None):
    """Takes raw data (in the form of a dict, list, object) and a dict of
    fields to output and filters the data based on those fields.

    :param data: the actual object(s) from which the fields are taken from
    :param fields: a dict or schema of whose keys will make up the final serialized
                   response output

    >>> from flask_restplus import fields, marshal
    >>> data = { 'a': 100, 'b': 'foo', 'c': None }
    >>> mfields = { 'a': fields.Raw, 'c': fields.Raw, 'd': fields.Raw }

    >>> marshal(data, mfields)
    {'a': 100, 'c': None, 'd': None}

    """
    out = get_schema(fields).dump(data, many=many)
    if mask:
      out = apply_mask(out, fields, mask)
    return out


class marshal_with(object):
    """A decorator that apply marshalling to the return values of your methods.

    >>> from flask_restplus import fields, marshal_with
    >>> mfields = { 'a': fields.Raw }
    >>> @marshal_with(mfields)
    ... def get():
    ...     return { 'a': 100, 'b': 'foo' }
    ...
    ...
    >>> get()
    OrderedDict([('a', 100)])

    see :meth:`flask_restplus.marshal`
    """

    def __init__(self, fields, many=None):
        """
        :param fields: a dict of whose keys will make up the final
                       serialized response output
        """
        self.fields = fields
        self.many = many

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resp = f(*args, **kwargs)
            mask = None
            if has_app_context():
                mask_header = current_app.config['RESTPLUS_MASK_HEADER']
                mask = request.headers.get(mask_header)
            if isinstance(resp, tuple):
                data, code, headers = unpack(resp)
                return (
                    marshal(data, self.fields, self.many, mask),
                    code,
                    headers
                )
            else:
                return marshal(resp, self.fields, self.many, mask)
        return wrapper


class marshal_with_field(object):
    """
    A decorator that formats the return values of your methods with a single field.

    >>> from flask_restplus import marshal_with_field, fields
    >>> @marshal_with_field(fields.List(fields.Integer))
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
