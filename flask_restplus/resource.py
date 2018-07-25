# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from flask import request
from flask.views import MethodView
from werkzeug.wrappers import BaseResponse

from .utils import unpack


class Resource(MethodView):
    '''
    Represents an abstract RESTPlus resource.

    Concrete resources should extend from this class
    and expose methods for each supported HTTP method.
    If a resource is invoked with an unsupported HTTP method,
    the API will return a response with status 405 Method Not Allowed.
    Otherwise the appropriate method is called and passed all arguments
    from the url rule used when adding the resource to an Api instance.
    See :meth:`~flask_restplus.Api.add_resource` for details.
    '''

    representations = None
    method_decorators = []

    def __init__(self, api=None, *args, **kwargs):
        self.api = api

    def dispatch_request(self, *args, **kwargs):
        # Taken from flask
        meth = getattr(self, request.method.lower(), None)
        if meth is None and request.method == 'HEAD':
            meth = getattr(self, 'get', None)
        assert meth is not None, 'Unimplemented method %r' % request.method

        for decorator in self.method_decorators:
            meth = decorator(meth)

        # meth = self.validate_payload(meth) - Now done by webargs

        resp = meth(*args, **kwargs)

        if isinstance(resp, BaseResponse):
            return resp

        representations = self.representations or {}

        mediatype = request.accept_mimetypes.best_match(representations, default=None)
        if mediatype in representations:
            data, code, headers = unpack(resp)
            resp = representations[mediatype](data, code, headers)
            resp.headers['Content-Type'] = mediatype
            return resp

        return resp

    # def validate_payload(self, func):
    #     '''Perform a payload validation on expected model if necessary'''
    #     if getattr(func, '__apidoc__', False) is not False:
    #         doc = func.__apidoc__
    #         for expect in doc.get('expect', []):
    #             func = use_args(**expect)(func)
    #     return func
