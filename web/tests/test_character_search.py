import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app


SAMPLE_HTML = """
<div class="card shadow-sm">
  <div class="card-header text-center">
    Character: <span class="user-select-all fw-bold text-warning">amiya \\(arknights\\)</span>
  </div>
  <div class="text-center">
    <img src="preview/amiya_(arknights).jpg" alt="thumbnail">
  </div>
  <div class="card-body">
    <div class="p-1">Prompt tags:</div>
    <div class="user-select-all p-2 alert alert-secondary">amiya \\(arknights\\), arknights, 1girl</div>
  </div>
</div>
"""


class CharacterSearchTests(unittest.TestCase):
    def test_parse_downloadmost_character_cards(self):
        items = app.parse_downloadmost_characters(SAMPLE_HTML)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["character"], "amiya \\(arknights\\)")
        self.assertEqual(items[0]["prompt"], "amiya \\(arknights\\), arknights, 1girl")
        self.assertEqual(
            items[0]["preview_url"],
            "https://www.downloadmost.com/NoobAI-XL/danbooru-character/preview/amiya_(arknights).jpg",
        )

    def test_translate_character_queries_uses_cache(self):
        old_file = app.CHARACTER_SEARCH_CACHE_FILE
        old_client = app.httpx.AsyncClient
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": '["amiya (arknights)"]'}}]}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, url, json):
                calls.append((url, json))
                return FakeResponse()

        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.CHARACTER_SEARCH_CACHE_FILE = Path(tmp) / "character_search_cache.json"
                app.httpx.AsyncClient = FakeAsyncClient

                first = asyncio.run(app.translate_character_queries("阿米娅"))
                second = asyncio.run(app.translate_character_queries(" 阿米娅 "))
        finally:
            app.CHARACTER_SEARCH_CACHE_FILE = old_file
            app.httpx.AsyncClient = old_client

        self.assertEqual(first, ["amiya (arknights)"])
        self.assertEqual(second, ["amiya (arknights)"])
        self.assertEqual(len(calls), 1)

    def test_search_downloadmost_characters_uses_cache(self):
        old_file = app.CHARACTER_SEARCH_CACHE_FILE
        old_client = app.httpx.AsyncClient
        calls = []

        class FakeResponse:
            text = SAMPLE_HTML
            url = "https://www.downloadmost.com/NoobAI-XL/danbooru-character/search.asp?charactername=amiya"

            def raise_for_status(self):
                return None

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url):
                calls.append(url)
                return FakeResponse()

        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.CHARACTER_SEARCH_CACHE_FILE = Path(tmp) / "character_search_cache.json"
                app.httpx.AsyncClient = FakeAsyncClient

                first = asyncio.run(app.search_downloadmost_characters("amiya"))
                second = asyncio.run(app.search_downloadmost_characters(" AMIYA "))
        finally:
            app.CHARACTER_SEARCH_CACHE_FILE = old_file
            app.httpx.AsyncClient = old_client

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["matched_query"], "amiya")
        self.assertEqual(second[0]["matched_query"], " AMIYA ")
        self.assertEqual(len(calls), 1)

    def test_character_search_returns_ambiguous_candidates(self):
        old_translate = app.translate_character_queries
        old_search = app.search_downloadmost_characters

        async def fake_translate(query):
            return ["miku"]

        async def fake_search(query):
            return [
                {"character": "hatsune miku", "prompt": "hatsune miku, vocaloid", "preview_url": "", "exact": False},
                {"character": "nakano miku", "prompt": "nakano miku, go-toubun no hanayome", "preview_url": "", "exact": False},
            ]

        try:
            app.translate_character_queries = fake_translate
            app.search_downloadmost_characters = fake_search
            client = TestClient(app.app)

            res = client.post("/api/character/search", json={"query": "miku"})
        finally:
            app.translate_character_queries = old_translate
            app.search_downloadmost_characters = old_search

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "ambiguous")
        self.assertEqual(len(body["items"]), 2)

    def test_character_appearance_tags_endpoint_returns_llm_output(self):
        old_strip = app.strip_character_clothing_tags

        async def fake_strip(prompt):
            self.assertEqual(prompt, "amiya \\(arknights\\), arknights, 1girl, rabbit ears, black jacket")
            return "amiya \\(arknights\\), arknights, 1girl, rabbit ears"

        try:
            app.strip_character_clothing_tags = fake_strip
            client = TestClient(app.app)

            res = client.post(
                "/api/character/appearance-tags",
                json={"prompt": "amiya \\(arknights\\), arknights, 1girl, rabbit ears, black jacket"},
            )
        finally:
            app.strip_character_clothing_tags = old_strip

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["text"], "amiya \\(arknights\\), arknights, 1girl, rabbit ears")


if __name__ == "__main__":
    unittest.main()
