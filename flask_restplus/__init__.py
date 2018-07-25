# -*- coding: utf-8 -*-
from __future__ import absolute_import

from . import apidoc, cors
from .__about__ import __version__, __description__
from .api import Api  # noqa
from .errors import abort, RestError, SpecsError, ValidationError
from .marshalling import marshal, marshal_with, marshal_with_field  # noqa
from .resource import Resource  # noqa
from .swagger import Swagger
from .namespace import Namespace

__all__ = (
    '__version__',
    '__description__',
    'Api',
    'Resource',
    'apidoc',
    'marshal',
    'marshal_with',
    'marshal_with_field',
    'abort',
    'cors',
    'Namespace'
    'RestError',
    'SpecsError',
    'Swagger',
    'ValidationError'
)
