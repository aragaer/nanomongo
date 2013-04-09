import unittest

import pymongo
from bson.objectid import ObjectId

from nanomongo.field import Field
from nanomongo.document import BaseDocument

try:
    import motor
    MOTOR_CLIENT = motor.MotorClient().open_sync()
    from .motor_base import async_test_engine, AssertEqual
except:
    MOTOR_CLIENT = None

    def async_test_engine():
        return lambda x: x
    async_test_engine.__test__ = False  # Nose otherwise mistakes it for a test


class MotorDocumentTestCase(unittest.TestCase):
    def setUp(self):
        pymongo.MongoClient().drop_database('nanotestdb')

    @unittest.skipUnless(MOTOR_CLIENT, 'motor not installed or connection refused')
    @async_test_engine()
    def test_insert_find_motor(self, done):
        """Motor: Test document save, find, find_one"""

        class Doc(BaseDocument, dot_notation=True, client=MOTOR_CLIENT, db='nanotestdb'):
            foo = Field(str)
            bar = Field(int, required=False)

        col = Doc.get_collection()
        self.assertTrue(isinstance(col, motor.MotorCollection))
        yield AssertEqual(None, Doc.find_one, None)
        d = Doc(foo='foo value', bar=42)
        _id = yield motor.Op(d.insert)
        self.assertTrue(isinstance(_id, ObjectId))
        yield AssertEqual(1, Doc.find({'foo': 'foo value'}).count, None)
        yield AssertEqual(d, Doc.find_one, {'bar': 42})
        done()

    @unittest.skipUnless(MOTOR_CLIENT, 'motor not installed or connection refused')
    @async_test_engine()
    def test_partial_update(self, done):
        """Motor: partial atomic update with save"""

        class Doc(BaseDocument, dot_notation=True):
            foo = Field(str)
            bar = Field(int, required=False)
            moo = Field(list)

        Doc.register(client=MOTOR_CLIENT, db='nanotestdb')

        d = Doc(foo='foo value', bar=42)
        d.moo = []
        yield motor.Op(d.insert)
        del d.bar  # unset
        yield motor.Op(d.save)
        yield AssertEqual(d, Doc.find_one, {'_id': d._id})
        d.foo = 'new foo'
        d['bar'] = 1337
        d.moo = ['moo 0']
        yield motor.Op(d.save, atomic=True)
        yield AssertEqual(d, Doc.find_one, {'foo': 'new foo', 'bar': 1337})
        d.moo = []
        del d['bar']
        yield motor.Op(d.save)
        yield AssertEqual(d, Doc.find_one, {'_id': d._id})
        done()