import asyncio
import os
import unittest

import main
from fastapi import HTTPException


class FrontendServingTests(unittest.TestCase):
    def test_prefers_vue_dist_when_build_exists(self):
        expected = os.path.join(os.path.dirname(main.__file__), "frontend", "dist")
        self.assertEqual(os.path.normpath(main.frontend_dir), os.path.normpath(expected))

    def test_root_and_history_fallback_serve_vue_index(self):
        root_response = asyncio.run(main.index())
        route_response = asyncio.run(main.frontend_fallback("advisor"))

        expected = open(
            os.path.join(main.frontend_dir, "index.html"), encoding="utf-8"
        ).read().encode("utf-8")
        self.assertEqual(root_response.body, expected)
        self.assertEqual(route_response.body, expected)

    def test_register_history_route_uses_vue_index(self):
        response = asyncio.run(main.frontend_fallback("register"))

        expected = open(
            os.path.join(main.frontend_dir, "index.html"), encoding="utf-8"
        ).read().encode("utf-8")
        self.assertEqual(response.body, expected)

    def test_api_paths_are_not_served_by_spa_fallback(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(main.frontend_fallback("api/not-a-route"))

        self.assertEqual(404, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
