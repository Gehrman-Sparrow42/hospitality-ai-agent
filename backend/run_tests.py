import os
import unittest
from test_unit import TestDatabaseAndLogic

if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDatabaseAndLogic)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        exit(1)
