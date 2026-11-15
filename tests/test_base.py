import os
import unittest

from timerecorder import config, log

class TestBase(unittest.TestCase):

    # pytest instantiates every collected TestCase class, including this base, with only a method name
    def __init__(self, methodName='runTest', testroot='test-files'):
        unittest.TestCase.__init__(self, methodName)
        if not os.path.exists(testroot):
            os.mkdir(testroot)

        testLog = testroot + '/tests.log'
        log.init(testLog)

        config.init(testroot + '/config.yml')
