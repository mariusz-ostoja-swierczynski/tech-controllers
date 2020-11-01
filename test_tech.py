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
        self._loop.run_until_complete(self._tech.authenticate("mariusz.ostoja@gmail.com", "tiramisu2312"))
    """
    def test_authenticate(self):
        result = self._loop.run_until_complete(self._tech.authenticate("mariusz.ostoja@gmail.com", "tiramisu2312"))
        #authentication = json.loads(json.dumps(result))
        self.assertTrue(result)
    """
    def test_list_modules(self):
        result = self._loop.run_until_complete(self._tech.list_modules())
        self.assertTrue(result[0])

    def test_module_data(self):
        result = self._loop.run_until_complete(self._tech.module_data("3ba4d851c388be33b4b7e436d2a4d48a"))
        zones = json.loads(json.dumps(result))
        self.assertTrue("zones" in zones)

    def tearDown(self):
        self._loop.run_until_complete(self._session.close())

if __name__ == '__main__':
    unittest.main()