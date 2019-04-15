# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import inspect
import six
import warnings
import marshmallow as ma

from flask import request
from flask.views import http_method_funcs
from webargs.flaskparser import FlaskParser, abort as wa_abort

from .errors import abort
from .marshalling import marshal, marshal_with
from .utils import merge, merge_schema_params
from ._http import HTTPStatus


class Namespace(object):
    '''
    Group resources together.

    Namespace is to API what :class:`flask:flask.Blueprint` is for :class:`flask:flask.Flask`.

    :param str name: The namespace name
    :param str description: An optionale short description
    :param str path: An optional prefix path. If not provided, prefix is ``/+name``
    :param list decorators: A list of decorators to apply to each resources
    :param Api api: an optional API to attache to the namespace
    '''

    def __init__(self, name, description=None, path=None, decorators=None, authorizations=None, **kwargs):
        self.name = name
        self.description = description
        self._path = path

        self._schema = None
        self.schemas = {}
        self.urls = {}
        self.decorators = decorators if decorators else []
        self.resources = []
        self.error_handlers = {}
        self.default_error_handler = None
        self.authorizations = authorizations
        self.apis = []
        if 'api' in kwargs:
            self.apis.append(kwargs['api'])
        self.parser = FlaskParser(error_handler=self.handle_validation_error)
        self.custom_fields_mapping = {}

    @property
    def path(self):
        return (self._path or ('/' + self.name)).rstrip('/')

    def add_resource(self, resource, *urls, **kwargs):
        '''
        Register a Resource for a given API Namespace

        :param Resource resource: the resource ro register
        :param str urls: one or more url routes to match for the resource,
                         standard flask routing rules apply.
                         Any url variables will be passed to the resource method as args.
        :param str endpoint: endpoint name (defaults to :meth:`Resource.__name__.lower`
            Can be used to reference this route in :class:`fields.Url` fields
        :param list|tuple resource_class_args: args to be forwarded to the constructor of the resource.
        :param dict resource_class_kwargs: kwargs to be forwarded to the constructor of the resource.

        Additional keyword arguments not specified above will be passed as-is
        to :meth:`flask.Flask.add_url_rule`.

        Examples::

            namespace.add_resource(HelloWorld, '/', '/hello')
            namespace.add_resource(Foo, '/foo', endpoint="foo")
            namespace.add_resource(FooSpecial, '/special/foo', endpoint="foo")
        '''
        self.resources.append((resource, urls, kwargs))
        for api in self.apis:
            ns_urls = api.ns_urls(self, urls)
            api.register_resource(self, resource, *ns_urls, **kwargs)

    def route(self, *urls, **kwargs):
        '''
        A decorator to route resources.
        '''
        def wrapper(cls):
            doc = kwargs.pop('doc', None)
            if doc is not None:
                self._handle_api_doc(cls, doc)
            self.add_resource(cls, *urls, **kwargs)
            return cls
        return wrapper

    def _handle_api_doc(self, cls, doc):
        if doc is False:
            cls.__apidoc__ = False
            return
        current_doc = getattr(cls, '__apidoc__', {})
        unshortcut_params_description(doc)
        handle_deprecations(doc)
        for http_method in http_method_funcs:
            if http_method in doc:
                if doc[http_method] is False:
                    continue
                unshortcut_params_description(doc[http_method])
                handle_deprecations(doc[http_method])
        if 'expect' in doc and not isinstance(doc['expect'], list):
            doc['expect'] = [doc['expect']]
        if 'expect' in current_doc:
            if 'expect' not in doc:
                doc['expect'] = []
            doc['expect'].extend(current_doc['expect'])
        cls.__apidoc__ = merge(current_doc, doc)

    def doc(self, shortcut=None, **kwargs):
        '''A decorator to add some api documentation to the decorated object'''
        if isinstance(shortcut, six.text_type):
            kwargs['id'] = shortcut
        show = shortcut if isinstance(shortcut, bool) else True

        def wrapper(documented):
            self._handle_api_doc(documented, kwargs if show else False)
            return documented
        return wrapper

    def hide(self, func):
        '''A decorator to hide a resource or a method from specifications'''
        return self.doc(False)(func)

    def abort(self, *args, **kwargs):
        '''
        Properly abort the current request

        See: :func:`~flask_restplus.errors.abort`
        '''
        abort(*args, **kwargs)

    def register_schema(self, schema, name=None, **kwargs) -> ma.Schema:
        '''
        Register given marshmallow schema with the given name.

        Please note that any schemas provided to the `expect_args`, `expect_kwargs`
        or `marshal_with` are automatically registered. Use this function only if you need
        to provide specific name to given schema.
        '''
        if isinstance(schema, ma.Schema):
            schema_class = type(schema)
        elif isinstance(schema, type) and issubclass(schema, ma.Schema):
            schema_class = schema
            schema = None

        if not name:
            name = schema_class.__name__

        if schema:
            kwargs = merge_schema_params(schema, **kwargs)
        schema = schema_class(**kwargs)

        self.schemas[name] = schema
        for api in self.apis:
            api.schemas[name] = schema
        return schema

    def marshal_with(self, fields, code=HTTPStatus.OK, description=None, as_list=False, ):
        '''
        A decorator specifying the fields to use for serialization.

        :param bool as_list: Indicate that the return type is a list
        :param int code: Optionally give the expected HTTP response code if its different from 200
        '''
        def wrapper(func):

            doc = {
                'responses': {
                    code: (description, [fields]) if as_list else (description, fields)
                }
            }
            func.__apidoc__ = merge(getattr(func, '__apidoc__', {}), doc)
            return marshal_with(fields, many=as_list)(func)
        return wrapper

    def marshal_list_with(self, fields, **kwargs):
        '''A shortcut decorator for :meth:`~Api.marshal_with` with ``as_list=True``'''
        return self.marshal_with(fields, as_list=True, **kwargs)

    def marshal(self, *args, **kwargs):
        '''A shortcut to the :func:`marshal` helper'''
        return marshal(*args, **kwargs)

    def errorhandler(self, exception):
        '''A decorator to register an error handler for a given exception'''
        if inspect.isclass(exception) and issubclass(exception, Exception):
            # Register an error handler for a given exception
            def wrapper(func):
                self.error_handlers[exception] = func
                return func
            return wrapper
        else:
            # Register the default error handler
            self.default_error_handler = exception
            return exception

    def param(self, name, description=None, _in='query', **kwargs):
        '''
        A decorator to specify one of the expected parameters

        :param str name: the parameter name
        :param str description: a small description
        :param str _in: the parameter location `(query|header|formData|body|cookie)`
        '''
        param = kwargs
        param['in'] = _in
        param['description'] = description
        return self.doc(params={name: param})

    def response(self, code, description, schema=None, **kwargs):
        '''
        A decorator to specify one of the expected responses

        :param int code: the HTTP status code
        :param str description: a small description about the response
        :param ma.Schema schema: an optional response model

        '''
        # TODO: Allow to reference pre-defined responses
        return self.doc(responses={code: (description, schema, kwargs)})

    def header(self, name, description=None, **kwargs):
        '''
        A decorator to specify one of the expected headers

        :param str name: the HTTP header name
        :param str description: a description about the header

        '''
        header = {'description': description}
        header.update(kwargs)
        return self.doc(headers={name: header})

    def deprecated(self, func):
        '''A decorator to mark a resource or a method as deprecated'''
        return self.doc(deprecated=True)(func)

    def vendor(self, *args, **kwargs):
        '''
        A decorator to expose vendor extensions.

        Extensions can be submitted as dict or kwargs.
        The ``x-`` prefix is optionnal and will be added if missing.

        See: http://swagger.io/specification/#specification-extensions-128
        '''
        for arg in args:
            kwargs.update(arg)
        return self.doc(vendor=kwargs)

    @property
    def payload(self):
        '''Store the input payload in the current request context'''
        return request.get_json()

    def produces(self, mimetypes):
        '''A decorator to specify the MIME types the API can produce'''
        return self.doc(produces=mimetypes)

    def security(self, security):
        '''A decorator to specify the security schemes to use for decorated path or operation'''
        return self.doc(security=security)

    def expect_kwargs(self, *args, **kwargs):
        '''
        A decorator to specify expected inputs.

        This is a shortcut to :meth:`expect_args` with ``as_kwargs=True``.
        '''
        kwargs['as_kwargs'] = True
        return self.expect_args(*args, **kwargs)

    def expect_args(self, argmap, location=None, **kwargs):
        '''
        A decorator to specify expected inputs.

        This decorator is a wrapper for webargs.flaskparser.use_args which, does the same job and extract expected
        parameters to be well documented in the Swagger.

        See also: https://webargs.readthedocs.io/en/latest/api.html?highlight=use_args#webargs.core.Parser.use_args

        :param argmap: Either a `marshmallow.Schema`, a `dict`
            of argname -> `marshmallow.fields.Field` pairs, or a callable
            which accepts a request and returns a `marshmallow.Schema`.
        :param str location: Where to search for args. Defaults to 'json'. Please note that each field
            in `argmap` can provide a specific `location` property. 
            See https://webargs.readthedocs.io/en/latest/quickstart.html#request-locations
        :param kwargs: Additional keyword arguments passed directly to webargs `use_args` function. 
            Please note however that `locations` argument can not be passed
        '''
        def wrapper(func):
            location_ = location or 'json'
            # Get the method for swagger documenting (only set schema and 'in' properties
            func = self.doc(expect={'argmap': argmap, 'location': location_})(func)
            # Decorate returned func with webargs decorator
            return self.parser.use_args(argmap, locations=(location_,), **kwargs)(func)
        return wrapper

    def map_to_openapi_type(self, *args):
        """
        Decorator to set mapping for custom marshmallow fields.
        *args can be:
        a pair of the form (type, format)
        a core marshmallow field type (in which case we reuse that type’s mapping)

        :param args:
        :return:
        """
        def wrapper(field_type):
            self.custom_fields_mapping[field_type] = args
            return field_type
        return wrapper

    def handle_validation_error(self, err, req, schema):
        """
        Handle webargs request validation errors
        :param err: The error
        :param req: The request
        :param schema: The marshmallow schema which validation failed
        """
        wa_abort(400, message='Input payload validation failed',
                 errors=err.messages)


def unshortcut_params_description(data):
    if 'params' in data:
        for name, description in six.iteritems(data['params']):
            if isinstance(description, six.string_types):
                data['params'][name] = {'description': description}


def handle_deprecations(doc):
    if 'parser' in doc:
        warnings.warn('The parser attribute is deprecated, use expect instead', DeprecationWarning, stacklevel=2)
        doc['expect'] = doc.get('expect', []) + [doc.pop('parser')]
    if 'body' in doc:
        warnings.warn('The body attribute is deprecated, use expect instead', DeprecationWarning, stacklevel=2)
        doc['expect'] = doc.get('expect', []) + [doc.pop('body')]
