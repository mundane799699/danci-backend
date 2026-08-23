import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from douyin.config import DouyinSettings
from douyin.cookies import load_cookie_file, parse_cookie_text
from douyin.errors import DouyinError
from douyin.models import DouyinVideoMetadata, MediaCandidate
from douyin.resolver import DouyinCookieResolver, parse_hydration
from douyin.router import router
from douyin.security import extract_aweme_id, extract_share_url, normalize_and_validate_url, validate_public_dns


class ShareUrlTests(unittest.TestCase):
    hosts = ("v.douyin.com", "www.douyin.com", "www.iesdouyin.com")

    def test_extracts_first_url_and_strips_chinese_punctuation(self):
        value = extract_share_url("复制 https://v.douyin.com/AbC123/，打开抖音", self.hosts)
        self.assertEqual(value, "https://v.douyin.com/AbC123/")

    def test_rejects_non_douyin_and_non_standard_port(self):
        with self.assertRaises(DouyinError) as caught:
            extract_share_url("https://example.com/video/1", self.hosts)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_HOST")
        with self.assertRaises(DouyinError):
            normalize_and_validate_url("https://v.douyin.com:8443/a", self.hosts)

    def test_extract_aweme_id(self):
        self.assertEqual(extract_aweme_id("https://www.iesdouyin.com/share/video/7676828051079036666/"), "7676828051079036666")

    @patch("douyin.security.socket.getaddrinfo")
    def test_rejects_private_dns_result(self, getaddrinfo: Mock):
        getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(DouyinError) as caught:
            validate_public_dns("https://v.douyin.com/a")
        self.assertEqual(caught.exception.code, "UNSUPPORTED_HOST")


class HydrationTests(unittest.TestCase):
    @staticmethod
    def _page(aweme: dict) -> str:
        payload = {"app": {"videoDetail": aweme}}
        return f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(payload)}</script>'

    def test_parses_video_and_sorts_h264_candidates(self):
        page = self._page(
            {
                "aweme_id": "12345",
                "desc": "测试视频",
                "author": {"nickname": "作者"},
                "video": {
                    "duration": 12000,
                    "play_addr": {"url_list": ["https://v.douyinvod.com/playwm/video.mp4?watermark=1"]},
                    "bit_rate": [
                        {
                            "bit_rate": 100,
                            "codec_type": "h264",
                            "play_addr": {"width": 720, "height": 1280, "url_list": ["https://v.douyinvod.com/low.mp4"]},
                        },
                        {
                            "bit_rate": 200,
                            "codec_type": "h264",
                            "play_addr": {"width": 1080, "height": 1920, "url_list": ["https://v.douyinvod.com/high.mp4"]},
                        },
                        {
                            "codec_type": "h265",
                            "play_addr": {"url_list": ["https://v.douyinvod.com/h265.mp4"]},
                        },
                    ],
                },
            }
        )
        result = parse_hydration(page, "12345")
        self.assertEqual(result.media_candidates[0].url, "https://v.douyinvod.com/high.mp4")
        self.assertFalse(any("playwm" in candidate.url for candidate in result.media_candidates))
        self.assertNotIn("h265", [candidate.codec for candidate in result.media_candidates])

    def test_rejects_image_post(self):
        page = self._page({"aweme_id": "12345", "images": [{"url": "x"}]})
        with self.assertRaises(DouyinError) as caught:
            parse_hydration(page, "12345")
        self.assertEqual(caught.exception.code, "UNSUPPORTED_IMAGE_POST")

    def test_parses_current_router_data_assignment(self):
        aweme = {
            "awemeId": "67890",
            "title": "新版页面",
            "author": {"name": "新作者"},
            "video": {"playAddr": {"urlList": ["https://v.douyinvod.com/video.mp4"]}},
        }
        page = f"<script>window._ROUTER_DATA = {json.dumps({'loaderData': {'page': aweme}})};</script>"
        result = parse_hydration(page, "67890")
        self.assertEqual(result.title, "新版页面")
        self.assertEqual(result.media_candidates[0].url, "https://v.douyinvod.com/video.mp4")


class CookieResolverTests(unittest.TestCase):
    def test_parses_header_and_json_cookie_files(self):
        self.assertEqual(
            parse_cookie_text("Cookie: ttwid=first; msToken=a=b=c"),
            {"ttwid": "first", "msToken": "a=b=c"},
        )
        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookies.json"
            cookie_file.write_text('{"ttwid":"second","odin_tt":"token"}', encoding="utf-8")
            self.assertEqual(
                load_cookie_file(str(cookie_file), 1024),
                {"ttwid": "second", "odin_tt": "token"},
            )

    def test_missing_cookie_file_is_reported_as_expired(self):
        config = DouyinSettings(cookie_file="/path/that/does/not/exist", skip_dns_safety_check=True)
        with self.assertRaises(DouyinError) as caught:
            DouyinCookieResolver(config).resolve("https://www.douyin.com/video/12345")
        self.assertEqual(caught.exception.code, "COOKIE_EXPIRED")

    def test_resolves_detail_with_cookie_and_signed_http_request(self):
        requested: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(request)
            self.assertIn("ttwid=test-id", request.headers.get("cookie", ""))
            if request.url.host == "v.douyin.com":
                return httpx.Response(
                    302,
                    headers={"location": "https://www.douyin.com/video/12345"},
                )
            self.assertIn("a_bogus=", str(request.url))
            return httpx.Response(
                200,
                json={
                    "status_code": 0,
                    "aweme_detail": {
                        "aweme_id": "12345",
                        "desc": "Cookie 解析成功",
                        "author": {"nickname": "测试作者"},
                        "video": {
                            "duration": 9000,
                            "bit_rate": [
                                {
                                    "bit_rate": 200,
                                    "codec_type": "h264",
                                    "play_addr": {
                                        "width": 1080,
                                        "height": 1920,
                                        "url_list": ["https://v.douyinvod.com/video.mp4"],
                                    },
                                }
                            ],
                        },
                    },
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookie.txt"
            cookie_file.write_text("ttwid=test-id; msToken=test-token", encoding="utf-8")
            config = DouyinSettings(
                cookie_file=str(cookie_file),
                api_retries=1,
                skip_dns_safety_check=True,
            )
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = DouyinCookieResolver(config, client).resolve(
                    "https://v.douyin.com/fresh-link/"
                )

        self.assertEqual(result.author_name, "测试作者")
        self.assertEqual(result.media_candidates[0].url, "https://v.douyinvod.com/video.mp4")
        self.assertEqual(len(requested), 2)

    def test_rejected_cookie_returns_cookie_expired(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookie.txt"
            cookie_file.write_text("ttwid=expired", encoding="utf-8")
            config = DouyinSettings(
                cookie_file=str(cookie_file),
                api_retries=1,
                skip_dns_safety_check=True,
            )
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(DouyinError) as caught:
                    DouyinCookieResolver(config, client).resolve(
                        "https://www.douyin.com/video/12345"
                    )
        self.assertEqual(caught.exception.code, "COOKIE_EXPIRED")


class ApiTests(unittest.TestCase):
    @patch("douyin.router.DouyinResolver.resolve")
    def test_resolve_endpoint_returns_best_video_url(self, resolve: Mock):
        resolve.return_value = DouyinVideoMetadata(
            aweme_id="12345",
            content_type="video",
            title="测试视频",
            author_name="作者",
            cover_url=None,
            duration_ms=12000,
            media_candidates=[MediaCandidate("https://v.douyinvod.com/high.mp4", 1080, 1920, 200, "h264")],
        )
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/douyin")
        response = TestClient(app).post(
            "/api/v1/douyin/resolve",
            json={"shareText": "复制 https://v.douyin.com/abc/ 打开抖音"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["videoUrl"], "https://v.douyinvod.com/high.mp4")

    @patch("douyin.router.DouyinResolver.resolve")
    def test_cookie_expired_has_stable_error_code(self, resolve: Mock):
        resolve.side_effect = DouyinError(
            "COOKIE_EXPIRED",
            "抖音 Cookie 缺失或已失效，请更新 Cookie 文件",
        )
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/douyin")
        response = TestClient(app).post(
            "/api/v1/douyin/resolve",
            json={"shareText": "https://v.douyin.com/abc/"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "COOKIE_EXPIRED")
        self.assertFalse(response.json()["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
