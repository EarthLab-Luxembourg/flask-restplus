# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import

import itertools
import re

from inspect import getdoc
from collections import OrderedDict, Hashable
from six import string_types, iteritems, iterkeys

from flask import current_app
from werkzeug.routing import parse_rule

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin

from .utils import merge, not_none, get_schema
from ._http import HTTPStatus

# TODO: Functions which transforms apidoc into real swagger doc should be moved into an apispec plugin dedicated
# TODO: Register reused parameters (swagger allow to register api wide parameters for being reused over opeerations)

#: Maps Flask/Werkzeug rooting types to Swagger ones
PATH_TYPES = {
    'int': 'integer',
    'float': 'number',
    'string': 'string',
    'default': 'string',
}


#: Maps Python primitives types to Swagger ones
PY_TYPES = {
    int: 'integer',
    float: 'number',
    str: 'string',
    bool: 'boolean',
    None: 'void'
}

#: Maps Webargs locations to Swagger 2.0
LOCATIONS = {
    'querystring': 'query',
    'query': 'query',
    'json': 'body',
    'form': 'formData',
    'headers': 'header',
    'files': 'formData',
    'cookies': ''
}

RE_URL = re.compile(r'<(?:[^:<>]+:)?([^<>]+)>')

DEFAULT_RESPONSE_DESCRIPTION = 'Success'
DEFAULT_RESPONSE = {'description': DEFAULT_RESPONSE_DESCRIPTION}

RE_RAISES = re.compile(r'^:raises\s+(?P<name>[\w\d_]+)\s*:\s*(?P<description>.*)$', re.MULTILINE)

OPENAPI_VERSION = '2.0'


def _v(value):
    '''Dereference values (callable)'''
    return value() if callable(value) else value


def extract_path(path):
    '''
    Transform a Flask/Werkzeug URL pattern in a Swagger one.
    '''
    return RE_URL.sub(r'{\1}', path)


def extract_path_params(path):
    '''
    Extract Flask-style parameters from an URL pattern as Swagger ones.
    '''
    params = OrderedDict()
    for converter, arguments, variable in parse_rule(path):
        if not converter:
            continue
        param = {
            'name': variable,
            'in': 'path',
            'required': True
        }

        if converter in PATH_TYPES:
            param['type'] = PATH_TYPES[converter]
        elif converter in current_app.url_map.converters:
            param['type'] = 'string'
        else:
            raise ValueError('Unsupported type converter: %s' % converter)
        params[variable] = param
    return params


def _param_to_header(param):
    param.pop('in', None)
    param.pop('name', None)
    return _clean_header(param)


def _clean_header(header):
    if isinstance(header, string_types):
        header = {'description': header}
    typedef = header.get('type', 'string')
    if isinstance(typedef, Hashable) and typedef in PY_TYPES:
        header['type'] = PY_TYPES[typedef]
    elif isinstance(typedef, (list, tuple)) and len(typedef) == 1 and typedef[0] in PY_TYPES:
        header['type'] = 'array'
        header['items'] = {'type': PY_TYPES[typedef[0]]}
    elif hasattr(typedef, '__schema__'):
        header.update(typedef.__schema__)
    else:
        header['type'] = typedef
    return not_none(header)


def parse_docstring(obj):
    raw = getdoc(obj)
    summary = raw.strip(' \n').split('\n')[0].split('.')[0] if raw else None
    raises = {}
    details = raw.replace(summary, '').lstrip('. \n').strip(' \n') if raw else None
    for match in RE_RAISES.finditer(raw or ''):
        raises[match.group('name')] = match.group('description')
        if details:
            details = details.replace(match.group(0), '')
    parsed = {
        'raw': raw,
        'summary': summary or None,
        'details': details or None,
        'returns': None,
        'params': [],
        'raises': raises,
    }
    return parsed


class Swagger(object):
    '''
    A Swagger documentation wrapper for an API instance.
    '''

    def __init__(self, api):
        self.api = api
        self.spec = None
        self.marshmallow_plugin = MarshmallowPlugin()

    def as_dict(self):
        '''
        Output the specification as a serializable ``dict``.

        :returns: the full Swagger specification in a serializable format
        :rtype: dict
        '''
        basepath = self.api.base_path
        if len(basepath) > 1 and basepath.endswith('/'):
            basepath = basepath[:-1]
        infos = {}
        if self.api.description:
            infos['description'] = _v(self.api.description)
        if self.api.terms_url:
            infos['termsOfService'] = _v(self.api.terms_url)
        if self.api.contact and (self.api.contact_email or self.api.contact_url):
            infos['contact'] = {
                'name': _v(self.api.contact),
                'email': _v(self.api.contact_email),
                'url': _v(self.api.contact_url),
            }
        if self.api.license:
            infos['license'] = {'name': _v(self.api.license)}
            if self.api.license_url:
                infos['license']['url'] = _v(self.api.license_url)

        paths = {}
        tags = self.extract_tags(self.api)

        for ns in self.api.namespaces:
            for resource, urls, kwargs in ns.resources:
                for url in self.api.ns_urls(ns, urls):
                    paths[extract_path(url)] = self.serialize_resource(ns, resource, url, kwargs)

        # merge in the top-level authorizations
        for ns in self.api.namespaces:
            if ns.authorizations:
                if self.api.authorizations is None:
                    self.api.authorizations = {}
                self.api.authorizations = merge(self.api.authorizations, ns.authorizations)

        self.spec = APISpec(
            title=_v(self.api.title),
            version=_v(self.api.version),
            plugins=(self.marshmallow_plugin,),
            info=infos,
            openapi_version=OPENAPI_VERSION,
            **{
                'basePath': basepath,
                'produces': list(iterkeys(self.api.representations)),
                'consumes': ['application/json'],                  
                'security': self.security_requirements(self.api.security) or None,
                'host': self.get_host(),
            }
        )

        for component_id, component in iteritems(self.api.authorizations or {}):
            self.spec.components.security_scheme(component_id, component)

        # Inject custom fields mapping of the API to the Marshmallow plugin
        # Must do this AFTER spec initialization because before that, the plugin have no spec defined
        for field_type, args in self.api.custom_fields_mapping.items():
            self.marshmallow_plugin.map_to_openapi_type(*args)(field_type)

        # Extract API tags
        for tag in tags:
            self.spec.tag(tag)

        # Extract API definitions
        for name, schema in self.api.schemas.items():
            self.spec.components.schema(name, schema=schema)

        # Extract API paths
        for ns in self.api.namespaces:
            for resource, urls, kwargs in ns.resources:
                for url in self.api.ns_urls(ns, urls):
                    self.spec.path(extract_path(url), self.serialize_resource(ns, resource, url, kwargs))
        
        # register errors 
        # Calls this last so we are sure that spec is initialized (required for using marshmallow plugin)
        # And previous definitions have been registered (becauses responses can reference definitions)
        for name, component in iteritems(self.register_errors() or {}):
            self.spec.components.response(name, component)

        return self.spec.to_dict()

    def get_host(self):
        hostname = current_app.config.get('SERVER_NAME', None) or None
        if hostname and self.api.blueprint and self.api.blueprint.subdomain:
            hostname = '.'.join((self.api.blueprint.subdomain, hostname))
        return hostname

    def extract_tags(self, api):
        tags = []
        by_name = {}
        for tag in api.tags:
            if isinstance(tag, string_types):
                tag = {'name': tag}
            elif isinstance(tag, (list, tuple)):
                tag = {'name': tag[0], 'description': tag[1]}
            elif isinstance(tag, dict) and 'name' in tag:
                pass
            else:
                raise ValueError('Unsupported tag format for {0}'.format(tag))
            tags.append(tag)
            by_name[tag['name']] = tag
        for ns in api.namespaces:
            if not ns.resources:
                continue
            if ns.name not in by_name:
                tags.append({
                    'name': ns.name,
                    'description': ns.description
                } if ns.description else {'name': ns.name})
            elif ns.description:
                by_name[ns.name]['description'] = ns.description
        return tags

    def extract_resource_doc(self, resource, url):
        doc = getattr(resource, '__apidoc__', {})
        if doc is False:
            return False
        doc['name'] = resource.__name__
        params = doc.get('params', OrderedDict())
        expect = doc.get('expect', [])
        params = merge(params, extract_path_params(url))
        # Track parameters for late deduplication
        up_params = {(n, p.get('in', 'query')): p for n, p in params.items()}
        need_to_go_down = set()
        methods = [m.lower() for m in resource.methods or []]
        for method in methods:
            method_doc = doc.get(method, OrderedDict())
            method_impl = getattr(resource, method)
            if hasattr(method_impl, 'im_func'):
                method_impl = method_impl.im_func
            elif hasattr(method_impl, '__func__'):
                method_impl = method_impl.__func__
            method_doc = merge(method_doc, getattr(method_impl, '__apidoc__', OrderedDict()))
            if method_doc is not False:
                method_doc['docstring'] = parse_docstring(method_impl)
                method_params = merge(params, method_doc.get('params', {}))
                inherited_params = OrderedDict((k, v) for k, v in iteritems(params) if k in method_params)
                method_doc['params'] = merge(inherited_params, method_params)
                method_doc['expect'] = expect + method_doc.get('expect', [])
                for name, param in method_doc['params'].items():
                    key = (name, param.get('in', 'query'))
                    if key in up_params:
                        need_to_go_down.add(key)
            doc[method] = method_doc
        # Deduplicate parameters
        # For each couple (name, in), if a method overrides it,
        # we need to move the paramter down to each method
        if need_to_go_down:
            for method in methods:
                method_doc = doc.get(method)
                if not method_doc:
                    continue
                params = {
                    (n, p.get('in', 'query')): p
                    for n, p in (method_doc['params'] or {}).items()
                }
                for key in need_to_go_down:
                    if key not in params:
                        method_doc['params'][key[0]] = up_params[key]
        doc['params'] = OrderedDict(
            (k[0], p) for k, p in up_params.items() if k not in need_to_go_down
        )
        return doc

    def register_errors(self):
        responses = {}
        for exception, handler in iteritems(self.api.error_handlers):
            doc = parse_docstring(handler)
            response = {
                'description': doc['summary']
            }
            apidoc = getattr(handler, '__apidoc__', {})
            self.process_headers(response, apidoc)
            if 'responses' in apidoc:
                _, model = list(apidoc['responses'].values())[0]
                response['schema'] = model
            # Resolve marshmallow schema to include references if needed
            self.marshmallow_plugin.resolve_schema(response)
            responses[exception.__name__] = not_none(response)
        return responses

    def serialize_resource(self, ns, resource, url, kwargs):
        doc = self.extract_resource_doc(resource, url)
        if doc is False:
            return
        path = {
            'parameters': self.parameters_for(doc) or None
        }
        for method in [m.lower() for m in resource.methods or []]:
            methods = [m.lower() for m in kwargs.get('methods', [])]
            if doc[method] is False or methods and method not in methods:
                continue
            path[method] = self.serialize_operation(doc, method)
            path[method]['tags'] = [ns.name]
        return not_none(path)

    def serialize_operation(self, doc, method):
        operation = {
            'responses': self.responses_for(doc, method) or None,
            'summary': doc[method]['docstring']['summary'],
            'description': self.description_for(doc, method) or None,
            'operationId': self.operation_id_for(doc, method),
            'parameters': self.parameters_for(doc[method]) or None,
            'security': self.security_for(doc, method),
        }
        # Handle 'produces' mimetypes documentation
        if 'produces' in doc[method]:
            operation['produces'] = doc[method]['produces']
        # Handle deprecated annotation
        if doc.get('deprecated') or doc[method].get('deprecated'):
            operation['deprecated'] = True
        # Handle form exceptions:
        doc_params = list(doc.get('params', {}).values())
        all_params = doc_params + (operation['parameters'] or [])
        if all_params and any(p['in'] == 'formData' for p in all_params):
            if any(p['type'] == 'file' for p in all_params):
                operation['consumes'] = ['multipart/form-data']
            else:
                operation['consumes'] = ['application/x-www-form-urlencoded', 'multipart/form-data']
        operation.update(self.vendor_fields(doc, method))
        return not_none(operation)

    def vendor_fields(self, doc, method):
        '''
        Extract custom 3rd party Vendor fields prefixed with ``x-``

        See: http://swagger.io/specification/#specification-extensions-128
        '''
        return dict(
            (k if k.startswith('x-') else 'x-{0}'.format(k), v)
            for k, v in iteritems(doc[method].get('vendor', {}))
        )

    def description_for(self, doc, method):
        '''Extract the description metadata and fallback on the whole docstring'''
        parts = []
        if 'description' in doc:
            parts.append(doc['description'])
        if method in doc and 'description' in doc[method]:
            parts.append(doc[method]['description'])
        if doc[method]['docstring']['details']:
            parts.append(doc[method]['docstring']['details'])

        return '\n'.join(parts).strip()

    def operation_id_for(self, doc, method):
        '''Extract the operation id'''
        return doc[method]['id'] if 'id' in doc[method] else self.api.default_id(doc['name'], method)

    def parameters_for(self, doc):
        params = []
        for name, param in iteritems(doc['params']):
            param['name'] = name
            if 'type' not in param and 'schema' not in param:
                param['type'] = 'string'
            if 'in' not in param:
                param['in'] = 'query'

            if 'type' in param and 'schema' not in param:
                ptype = param.get('type', None)
                if isinstance(ptype, (list, tuple)):
                    typ = ptype[0]
                    param['type'] = 'array'
                    param['items'] = {'type': PY_TYPES.get(typ, typ)}

                elif isinstance(ptype, (type, type(None))) and ptype in PY_TYPES:
                    param['type'] = PY_TYPES[ptype]

            params.append(param)

        for expected in doc.get('expect', []):
            if 'argmap' in expected:
                expected['schema'] = expected.pop('argmap')
            expected['in'] = LOCATIONS[expected.pop('location')]

            params.append(expected)

        return params

    def responses_for(self, doc, method):
        # TODO: simplify/refactor responses/model handling
        responses = {}

        for d in doc, doc[method]:
            if 'responses' in d:
                for code, response in iteritems(d['responses']):
                    if isinstance(response, string_types):
                        description = response
                        model = None
                        kwargs = {}
                    elif len(response) == 3:
                        description, model, kwargs = response
                    elif len(response) == 2:
                        description, model = response
                        kwargs = {}
                    else:
                        raise ValueError('Unsupported response specification')
                    description = description or DEFAULT_RESPONSE_DESCRIPTION
                    if code in responses:
                        responses[code].update(description=description)
                    else:
                        responses[code] = {'description': description}
                    if model:
                        responses[code]['schema'] = self.serialize_schema(model)
                    self.process_headers(responses[code], doc, method, kwargs.get('headers'))
            if 'model' in d:
                code = str(d.get('default_code', HTTPStatus.OK))
                if code not in responses:
                    responses[code] = self.process_headers(DEFAULT_RESPONSE.copy(), doc, method)
                responses[code]['schema'] = self.serialize_schema(d['model'])

            if 'docstring' in d:
                for name, description in iteritems(d['docstring']['raises']):
                    for exception, handler in iteritems(self.api.error_handlers):
                        error_responses = getattr(handler, '__apidoc__', {}).get('responses', {})
                        code = list(error_responses.keys())[0] if error_responses else None
                        if code and exception.__name__ == name:
                            responses[code] = {'$ref': '#/responses/{0}'.format(name)}
                            break

        if not responses:
            responses[str(HTTPStatus.OK.value)] = self.process_headers(DEFAULT_RESPONSE.copy(), doc, method)
        return responses

    def process_headers(self, response, doc, method=None, headers=None):
        method_doc = doc.get(method, {})
        if 'headers' in doc or 'headers' in method_doc or headers:
            response['headers'] = dict(
                (k, _clean_header(v)) for k, v
                in itertools.chain(
                    iteritems(doc.get('headers', {})),
                    iteritems(method_doc.get('headers', {})),
                    iteritems(headers or {})
                )
            )
        return response

    def serialize_schema(self, model):
        if isinstance(model, (list, tuple)):
            model = model[0]
            return {
                'type': 'array',
                'items': model,
            }

        return model

    def security_for(self, doc, method):
        security = None
        if 'security' in doc:
            auth = doc['security']
            security = self.security_requirements(auth)

        if 'security' in doc[method]:
            auth = doc[method]['security']
            security = self.security_requirements(auth)

        return security

    def security_requirements(self, value):
        if isinstance(value, (list, tuple)):
            return [self.security_requirement(v) for v in value]
        elif value:
            requirement = self.security_requirement(value)
            return [requirement] if requirement else None
        else:
            return []

    def security_requirement(self, value):
        if isinstance(value, (string_types)):
            return {value: []}
        elif isinstance(value, dict):
            return dict(
                (k, v if isinstance(v, (list, tuple)) else [v])
                for k, v in iteritems(value)
            )
        else:
            return None
