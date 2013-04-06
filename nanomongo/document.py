from bson.objectid import ObjectId

from .errors import ValidationError, ExtraFieldError, ConfigurationError
from .field import Field
from .util import DotNotationMixin, valid_client


class BasesTuple(tuple):
    pass


class Nanomongo(object):
    def __init__(self, fields=None):
        super(Nanomongo, self).__init__()
        if not isinstance(fields, dict):
            raise TypeError('fields kwarg expected of type dict')
        self.fields = fields
        self.client, self.database, self.collection = None, None, None

    @classmethod
    def from_dicts(cls, *args):
        """Create from dict, filtering relevant items"""
        if not args:
            raise TypeError('from_dicts takes at least 1 positional argument')
        fields = {}
        for dct in args:
            if not isinstance(dct, dict):
                raise TypeError('expected input of dictionaries')
            for field_name, field_value in dct.items():
                if isinstance(field_value, Field):
                    fields[field_name] = field_value
        return cls(fields=fields)

    def has_field(self, key):
        """Check existence of field"""
        return key in self.fields

    def list_fields(self):
        """Return a list of strings denoting fields"""
        return sorted(self.fields.keys())

    def validate(self, field_name, value):
        """Validate field input"""
        return self.fields[field_name].validator(value, field_name=field_name)

    def set_client(self, client):
        """Set client, a Client from pymongo or motor expected"""
        if not valid_client(client):
            raise TypeError('pymongo or motor Client expected')
        self.client = client

    def set_db(self, db_string):
        """Set database, string expected"""
        if not db_string or not isinstance(db_string, str):
            raise TypeError('Exected database string')
        self.database = db_string

    def set_collection(self, col_string):
        """Set collection, string expected"""
        if not col_string or not isinstance(col_string, str):
            raise TypeError('Expected collection string')
        self.collection = col_string

    def get_collection(self):
        """Returns collection"""
        if not self.client:
            raise ConfigurationError('Mongo client not set')
        elif not self.database:
            raise ConfigurationError('db not set')
        elif not self.collection:
            raise ConfigurationError('collection not set')
        return self.client[self.database][self.collection]


class DocumentMeta(type):
    """Document Metaclass. Generates allowed field set and their validators
    """

    def __new__(cls, name, bases, dct, **kwargs):
        print('PRE', bases)
        use_dot_notation = kwargs.pop('dot_notation') if 'dot_notation' in kwargs else None
        new_bases = cls._get_bases(bases)
        if use_dot_notation and DotNotationMixin not in new_bases:
            new_bases = (DotNotationMixin,) + new_bases
        print('POST', new_bases)
        return super(DocumentMeta, cls).__new__(cls, name, new_bases, dct)

    def __init__(cls, name, bases, dct, **kwargs):
        # TODO: disallow nanomongo name
        # TODO: disallow duplicate names
        super(DocumentMeta, cls).__init__(name, bases, dct)
        print(dct, '\n')
        if hasattr(cls, 'nanomongo'):
            cls.nanomongo = Nanomongo.from_dicts(cls.nanomongo.fields, dct)
        else:
            cls.nanomongo = Nanomongo.from_dicts(dct)
        if not cls.nanomongo.has_field('_id'):
            cls.nanomongo.fields['_id'] = Field(ObjectId, required=False)
        for field_name, field_value in dct.items():
            if isinstance(field_value, Field):
                delattr(cls, field_name)
        if 'client' in kwargs:
            cls.nanomongo.set_client(kwargs['client'])
        if 'db' in kwargs:
            cls.nanomongo.set_db(kwargs['db'])
        if 'collection' in kwargs:
            cls.nanomongo.set_collection(kwargs['collection'])
        else:
            cls.nanomongo.set_collection(name.lower())

    @classmethod
    def _get_bases(cls, bases):
        # taken from MongoEngine
        if isinstance(bases, BasesTuple):
            return bases
        seen = []
        bases = cls.__get_bases(bases)
        unique_bases = (b for b in bases if not (b in seen or seen.append(b)))
        return BasesTuple(unique_bases)

    @classmethod
    def __get_bases(cls, bases):
        for base in bases:
            if base is object:
                continue
            yield base
            for child_base in cls.__get_bases(base.__bases__):
                yield child_base


class BaseDocument(dict, metaclass=DocumentMeta):
    """BaseDocument class. Subclasses to be used."""

    def __init__(self, *args, **kwargs):
        print('ARGS:', args, 'KWARGS:', kwargs)
        # if input dict, merge (not updating) into kwargs
        if args and not isinstance(args[0], dict):
            raise TypeError('dict or dict subclass argument expected')
        elif args:
            for field_name, field_value in args[0].items():
                if field_name not in kwargs:
                    kwargs[field_name] = field_value
        print('KWARGS:', kwargs)
        dict.__init__(self, *args, **kwargs)
        for field_name, field in self.nanomongo.fields.items():
            if hasattr(field, 'default_value'):
                val = field.default_value
                self[field_name] = val() if callable(val) else val
        for field_name in kwargs:
            if self.nanomongo.has_field(field_name):
                self.nanomongo.validate(field_name, kwargs[field_name])
                self[field_name] = kwargs[field_name]
            else:
                raise ExtraFieldError('Undefined field %s=%s in %s' %
                                      (field_name, kwargs[field_name], self.__class__))

    @classmethod
    def get_collection(cls):
        """Returns collection as set in `cls.nanomongo`"""
        return cls.nanomongo.get_collection()

    @classmethod
    def find(cls, *args, **kwargs):
        """collection.find"""
        if 'as_class' not in kwargs:
            kwargs['as_class'] = cls
        return cls.get_collection().find(*args, **kwargs)

    @classmethod
    def find_one(cls, *args, **kwargs):
        if 'as_class' not in kwargs:
            kwargs['as_class'] = cls
        return cls.get_collection().find_one(*args, **kwargs)

    def __dir__(self):
        """Add defined Fields to dir"""
        return sorted(super(BaseDocument, self).__dir__() + self.nanomongo.list_fields())

    def validate(self):
        """Override to add extra validation"""
        pass

    def validate_all(self):
        """Check against extra fields, run field validators and user-defined validate"""
        for field, value in self.items():
            if not self.nanomongo.has_field(field):
                raise ValidationError('extra field "%s" with value "%s"' % (field, value))
        for field_name, field in self.nanomongo.fields.items():
            if field_name in self:
                field.validator(self[field_name], field_name=field_name)
            elif field.required:
                raise ValidationError('required field "%s" missing' % field_name)
        return self.validate()

    def save(self, **kwargs):
        """Saves document, returning its `_id`"""
        # TODO: change to use partial updates
        self.validate_all()
        return self.get_collection().save(self, **kwargs)
