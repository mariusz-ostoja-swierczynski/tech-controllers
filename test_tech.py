import unittest
import asyncio
import aiohttp
import tech
import json

class TestTechMethods(unittest.TestCase):
    def setUp(self):
        self._loop = asyncio.get_event_loop()
        self._session = aiohttp.ClientSession(loop = self._loop)
        self._tech = tech.Tech(self._session)
        self._loop.run_until_complete(self._tech.authenticate("email", "password"))
    """
    def test_authenticate(self):
        result = self._loop.run_until_complete(self._tech.authenticate("email", "password"))
        #authentication = json.loads(json.dumps(result))
        self.assertTrue(result)
    """
    def test_list_modules(self):
        result = self._loop.run_until_complete(self._tech.list_modules())
        self.assertTrue(result[0])

    def test_module_data(self):
        result = self._loop.run_until_complete(self._tech.get_module_data("module_id"))
        zones = json.loads(json.dumps(result))
        self.assertTrue("zones" in zones)

    def tearDown(self):
        self._loop.run_until_complete(self._session.close())

if __name__ == '__main__':
    unittest.main()
