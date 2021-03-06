import inspect

from flask.ext.restful import Api as restful_Api, abort as flask_abort, Resource as flask_Resource
from flask import request

from flask.ext.restful_swagger_2.swagger import create_swagger_endpoint, validate_path_item_object, \
    ValidationError, validate_operation_object, validate_definitions_object, extract_swagger_path, \
    _auth as auth


def abort(http_status_code, schema=None, **kwargs):
    if schema:
        kwargs.update(schema)
    flask_abort(http_status_code, **kwargs)


class ModelError(Exception):
    pass


def auth_required(f):
    """Decorator which checks if the request is permitted to call the view"""

    def decorator(*args, **kwargs):
        if not auth(request.args.get('api_key'), request.endpoint, request.method):
            abort(401)
        return f(*args, **kwargs)

    return decorator


class Resource(flask_Resource):
    decorators = [auth_required]


class Api(restful_Api):
    def __init__(self, *args, **kwargs):
        self._swagger_object = {
            'swagger': '2.0',
            'info': {
                'title': 'Unnamed',
                'version': kwargs.pop('api_version', '0.0')
            },
            'host': '',
            'basePath': '',
            'schemes': [],
            'consumes': [],
            'produces': [],
            'paths': {},
            'definitions': {},
            'parameters': {},
            'responses': {},
            'securityDefinitions': {},
            'security': [],
            'tags': [],
            'externalDocs': {}
        }
        api_spec_url = kwargs.pop('api_spec_url', '/api/swagger')
        super(Api, self).__init__(*args, **kwargs)
        if self.app:
            self._swagger_object['info']['title'] = self.app.name
        api_spec_urls = [
            '{0}.json'.format(api_spec_url),
            '{0}.html'.format(api_spec_url),
        ]
        self.add_resource(create_swagger_endpoint(self), *api_spec_urls, endpoint='swagger')

    def add_resource(self, resource, *urls, **kwargs):
        path_item = {}
        definitions = {}
        for method in [m.lower() for m in resource.methods]:
            f = resource.__dict__.get(method, None)
            operation = f.__dict__.get('__swagger_operation_object', None)
            if operation:
                operation, definitions_ = self._extract_schemas(operation)
                path_item[method] = operation
                definitions.update(definitions_)
        validate_definitions_object(definitions)
        self._swagger_object['definitions'].update(definitions)
        if path_item:
            validate_path_item_object(path_item)
            for url in urls:
                if not url.startswith('/'):
                    raise ValidationError('paths must start with a /')
                self._swagger_object['paths'][extract_swagger_path(url)] = path_item
        super(Api, self).add_resource(resource, *urls, **kwargs)

    def _extract_schemas(self, obj):
        """Converts all schemes in a given object to its proper swagger representation."""
        definitions = {}
        if isinstance(obj, list):
            for i, o in enumerate(obj):
                obj[i], definitions_ = self._extract_schemas(o)
                definitions.update(definitions_)
        if isinstance(obj, dict):
            for k, v in obj.iteritems():
                obj[k], definitions_ = self._extract_schemas(v)
                definitions.update(definitions_)
        if inspect.isclass(obj):
            # Object is a model. Convert it to valid json and get a definition object
            if not issubclass(obj, Schema):
                raise ValueError('"{0}" is not a subclass of the scheme model'.format(obj))
            definition = obj.definitions()
            # The definition itself might contain models, so extract them again
            definition, additional_definitions = self._extract_schemas(definition)
            definitions[obj.__name__] = definition
            definitions.update(additional_definitions)
            obj = obj.reference()
        return obj, definitions


class Schema(dict):
    properties = None

    def __init__(self, **kwargs):
        if self.properties:
            for k, v in kwargs.iteritems():
                if k not in self.properties:
                    raise ValueError(
                            'The model "{0}" does not have an attribute "{1}"'.format(self.__class__.__name__, k))
                if 'type' in self.properties[k]:
                    type_ = self.properties[k]['type']
                    if type_ == 'integer' and not isinstance(v, int):
                        raise ValueError('The attribute "{0}" must be an int, but was "{1}"'.format(k, type(v)))
                    if type_ == 'number' and not isinstance(v, int) and not isinstance(v, float):
                        raise ValueError(
                                'The attribute "{0}" must be an int or float, but was "{1}"'.format(k, type(v)))
                    if type_ == 'string' and not isinstance(v, basestring):
                        raise ValueError('The attribute "{0}" must be a string, but was "{1}"'.format(k, type(v)))
                    if type_ == 'boolean' and not isinstance(v, bool):
                        raise ValueError('The attribute "{0}" must be an int, but was "{1}"'.format(k, type(v)))
                self[k] = v
        if hasattr(self, 'required'):
            for key in self.required:
                if key not in kwargs:
                    raise ValueError('The attribute "{0}" is required'.format(key))

    @classmethod
    def reference(cls):
        return {'$ref': '#/definitions/{0}'.format(cls.__name__)}

    @classmethod
    def definitions(cls):
        return {k: v for k, v in cls.__dict__.iteritems() if not k.startswith('_')}

    @classmethod
    def array(cls):
        return {'type': 'array', 'items': cls}
