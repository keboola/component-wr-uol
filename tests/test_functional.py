import unittest

from keboola.datadirtest.vcr import VCRDataDirTester


class TestComponent(unittest.TestCase):
    def test_functional(self):
        functional_tests = VCRDataDirTester()
        functional_tests.run()


if __name__ == "__main__":
    unittest.main()
