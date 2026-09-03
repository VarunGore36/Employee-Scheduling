"""The HTTP boundary: routes, status codes and refusals, over a real socket."""

from __future__ import annotations

import http.client
import json
import re
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from roster.api import ApiConfig, is_loopback, make_server, query_kwargs, sample_instance, serve
from roster.cli import DEFAULT_UI_DIR
from roster.generate import small_instance
from roster.rules import REGISTRY
from roster.service import ENDPOINTS, MAX_SECONDS_CAP, ServiceError

FAST = {"seed": 7, "max_seconds": 60.0, "max_iterations": 2000,
        "iterations_per_level": 200, "polish_iterations": 0}


def body(inst=None, **extra) -> dict:
    out = {"instance": (inst or small_instance()).to_dict(), "options": dict(FAST)}
    out.update(extra)
    return out


@dataclass
class Reply:
    status: int
    headers: dict
    raw: bytes

    @property
    def json(self) -> dict:
        return json.loads(self.raw.decode("utf-8"))


class Client:
    """One call per line: method, path, body in, status and JSON out."""

    def __init__(self, port: int, token: str = "") -> None:
        self.port = port
        self.token = token

    def __call__(self, method, path, payload=None, headers=None, raw=None,
                 timeout=90) -> Reply:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            data = raw if raw is not None else (
                json.dumps(payload).encode("utf-8") if payload is not None else None)
            head = {"Content-Type": "application/json"} if data else {}
            if self.token:
                head["Authorization"] = f"Bearer {self.token}"
            head.update(headers or {})
            conn.request(method, path, body=data, headers=head)
            resp = conn.getresponse()
            return Reply(resp.status, dict(resp.getheaders()), resp.read())
        finally:
            conn.close()


class ServedCase(unittest.TestCase):
    """Runs a real server on an ephemeral port for the lifetime of the class."""

    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True)

    @classmethod
    def setUpClass(cls):
        cls.settings = cls.config()
        cls.server = make_server(cls.settings)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.call = Client(cls.server.server_address[1], cls.settings.token)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=10)
        cls.server.server_close()


class TestReadRoutes(ServedCase):
    def test_health_reports_what_the_engine_knows(self):
        out = self.call("GET", "/health").json
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["rule_types"], len(REGISTRY))
        self.assertEqual(out["endpoints"], sorted(ENDPOINTS))
        self.assertFalse(out["authenticated"])

    def test_root_lists_the_routes_when_no_ui_is_served(self):
        out = self.call("GET", "/").json
        self.assertIn("/health", out["get"])
        self.assertEqual(out["post"], sorted("/" + n for n in ENDPOINTS))

    def test_schema_and_rules_agree_on_the_catalogue(self):
        schema = self.call("GET", "/schema").json
        rules = self.call("GET", "/rules").json
        self.assertEqual(schema["rule_type_count"], len(REGISTRY))
        self.assertEqual(rules["count"], len(REGISTRY))
        self.assertEqual([r["type"] for r in rules["rule_types"]],
                         [r["type"] for r in schema["rule_types"]])

    def test_sample_serves_an_instance_the_ui_can_post_straight_back(self):
        small = self.call("GET", "/sample?small=1").json["instance"]
        self.assertEqual(len(small["employees"]), 12)
        month = self.call("GET", "/sample?days=30&employees=20&start=2026-11-19").json
        self.assertEqual(month["instance"]["horizon"]["num_days"], 30)
        self.assertEqual(len(month["instance"]["employees"]), 20)

    def test_sample_refuses_a_horizon_nobody_asked_for(self):
        reply = self.call("GET", "/sample?days=99")
        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.json["field"], "days")

    def test_trailing_slash_is_the_same_route(self):
        self.assertEqual(self.call("GET", "/health/").status, 200)

    def test_head_returns_the_headers_and_no_body(self):
        reply = self.call("HEAD", "/health")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.raw, b"")
        self.assertNotEqual(reply.headers["Content-Length"], "0")

    def test_unknown_path_is_a_404(self):
        self.assertEqual(self.call("GET", "/nowhere").status, 404)

    def test_a_post_route_fetched_with_get_says_so(self):
        reply = self.call("GET", "/solve")
        self.assertEqual(reply.status, 405)
        self.assertEqual(reply.headers["Allow"], "POST")


class TestWriteRoutes(ServedCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.solved = cls.call("POST", "/solve", body()).json

    def test_solve_returns_a_roster_and_a_verdict(self):
        self.assertEqual(len(self.solved["roster"]["rows"]), 12)
        self.assertEqual(self.solved["search"]["engine"], "construct+anneal")
        self.assertTrue(self.solved["score"]["feasible"])
        self.assertEqual(self.solved["score"]["hard_violations"], 0)

    def test_evaluate_scores_the_same_roster_the_same_way(self):
        out = self.call("POST", "/evaluate",
                        body(roster=self.solved["roster"])).json
        self.assertEqual(out["score"]["cost"], self.solved["score"]["cost"])

    def test_repair_reports_where_it_started(self):
        out = self.call("POST", "/repair", body(roster=self.solved["roster"])).json
        self.assertEqual(out["search"]["engine"], "repair")
        self.assertEqual(out["before"]["cost"], self.solved["score"]["cost"])

    def test_validate_passes_a_satisfiable_month(self):
        out = self.call("POST", "/validate", body()).json
        self.assertTrue(out["ok"])
        self.assertEqual(out["problems"], [])

    def test_schema_with_an_instance_fills_in_the_dropdowns(self):
        out = self.call("POST", "/schema", {"instance": small_instance().to_dict()}).json
        self.assertEqual(len(out["scope"]["employees"]), 12)
        self.assertEqual(out["scope"]["roles"], ["DSG", "LSG", "MTS"])

    def test_parse_turns_written_rules_into_drafts(self):
        text = ("Every duty must be staffed.\n"
                "Nobody may work more than 6 days in a row.\n"
                "Coffee tastes better at 3am.\n")
        reply = self.call("POST", "/parse", {"text": text,
                                            "instance": small_instance().to_dict()})
        self.assertEqual(reply.status, 200)
        out = reply.json
        self.assertEqual(out["counts"]["statements"], 3)
        self.assertEqual([r["type"] for r in out["rules"]],
                         ["coverage", "max_consecutive_working_days"])
        self.assertEqual([d["line"] for d in out["unparsed"]], [3])

    def test_parse_works_before_any_instance_exists(self):
        out = self.call("POST", "/parse",
                        {"text": "Nobody may work more than 6 days in a row."}).json
        self.assertEqual(out["counts"]["drafted"], 1)
        self.assertFalse(out["counts"]["checked_against_instance"])

    def test_parse_names_the_field_when_the_text_is_missing(self):
        reply = self.call("POST", "/parse", {"instance": small_instance().to_dict()})
        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.json["field"], "text")

    def test_a_roster_for_the_wrong_horizon_is_rejected_by_field(self):
        payload = body(roster={"rows": [{"employee": "E01", "days": ["M"]}]})
        reply = self.call("POST", "/evaluate", payload)
        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.json["field"], "roster.rows.0")

    def test_the_time_budget_is_capped(self):
        reply = self.call("POST", "/solve", body(options={"max_seconds": MAX_SECONDS_CAP + 1}))
        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.json["field"], "options.max_seconds")

    def test_an_unknown_option_is_named_back(self):
        reply = self.call("POST", "/solve", body(options={"turbo": True}))
        self.assertEqual(reply.status, 400)
        self.assertIn("turbo", reply.json["error"])


class TestMalformedRequests(ServedCase):
    def test_broken_json_is_a_400_not_a_500(self):
        reply = self.call("POST", "/validate", raw=b'{"instance": ')
        self.assertEqual(reply.status, 400)
        self.assertIn("not valid JSON", reply.json["error"])

    def test_a_json_list_is_not_a_request(self):
        reply = self.call("POST", "/validate", [1, 2, 3])
        self.assertEqual(reply.status, 400)
        self.assertIn("JSON object", reply.json["error"])

    def test_an_empty_body_still_answers_in_json(self):
        reply = self.call("POST", "/validate", raw=b"")
        self.assertEqual(reply.status, 400)
        self.assertEqual(reply.json["field"], "instance")

    def test_an_unknown_endpoint_lists_the_real_ones(self):
        reply = self.call("POST", "/optimise", {})
        self.assertEqual(reply.status, 404)
        self.assertIn("/solve", reply.json["error"])

    def test_a_chunked_body_is_refused_in_words(self):
        reply = self.call("POST", "/validate", raw=b"{}",
                          headers={"Transfer-Encoding": "identity"})
        self.assertEqual(reply.status, 400)


class TestLimits(ServedCase):
    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True, max_body=2048, socket_timeout=1.0)

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        reply = self.call("POST", "/solve", {"instance": {"pad": "x" * 4000}})
        self.assertEqual(reply.status, 413)
        self.assertEqual(reply.headers["Connection"], "close")

    def test_a_promised_body_that_never_arrives_times_out(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1],
                                          timeout=20)
        try:
            conn.putrequest("POST", "/validate")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", "64")
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 408)
        finally:
            conn.close()


class TestOneSearchAtATime(ServedCase):
    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True, max_concurrent=1)

    def test_a_second_search_is_refused_rather_than_queued(self):
        held = {}

        def occupy():
            held["reply"] = self.call("POST", "/solve",
                                      body(options={"seed": 1, "max_seconds": 3.0}))

        worker = threading.Thread(target=occupy)
        worker.start()
        try:
            time.sleep(0.6)
            reply = self.call("POST", "/solve", body())
            self.assertEqual(reply.status, 429)
            self.assertEqual(reply.headers["Retry-After"], "5")
        finally:
            worker.join(timeout=30)
        self.assertEqual(held["reply"].status, 200)

    def test_a_light_route_is_not_blocked_by_a_search(self):
        self.assertEqual(self.call("POST", "/validate", body()).status, 200)


class TestToken(ServedCase):
    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True, token="a-shared-secret")

    def test_health_stays_open_for_a_supervisor(self):
        open_client = Client(self.server.server_address[1])
        out = open_client("GET", "/health")
        self.assertEqual(out.status, 200)
        self.assertTrue(out.json["authenticated"])

    def test_everything_else_needs_the_token(self):
        open_client = Client(self.server.server_address[1])
        self.assertEqual(open_client("GET", "/schema").status, 401)
        self.assertEqual(open_client("POST", "/validate", body()).status, 401)

    def test_the_bearer_header_is_accepted(self):
        self.assertEqual(self.call("GET", "/schema").status, 200)

    def test_the_plain_header_is_accepted_too(self):
        open_client = Client(self.server.server_address[1])
        reply = open_client("GET", "/schema",
                            headers={"X-Roster-Token": "a-shared-secret"})
        self.assertEqual(reply.status, 200)

    def test_a_wrong_token_is_a_401(self):
        open_client = Client(self.server.server_address[1])
        self.assertEqual(open_client("GET", "/schema",
                                     headers={"X-Roster-Token": "guess"}).status, 401)


class TestCors(ServedCase):
    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True, cors_origin="http://localhost:5173")

    def test_the_preflight_is_answered(self):
        reply = self.call("OPTIONS", "/solve")
        self.assertEqual(reply.status, 204)
        self.assertEqual(reply.headers["Access-Control-Allow-Origin"],
                         "http://localhost:5173")
        self.assertIn("X-Roster-Token", reply.headers["Access-Control-Allow-Headers"])

    def test_a_real_response_carries_the_origin_too(self):
        self.assertEqual(self.call("GET", "/health").headers["Access-Control-Allow-Origin"],
                         "http://localhost:5173")


class TestStaticUi(ServedCase):
    @classmethod
    def config(cls) -> ApiConfig:
        cls.tmp = TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "index.html").write_text("<h1>roster</h1>", encoding="utf-8")
        (root / "app.js").write_text("export const ok = 1;", encoding="utf-8")
        (root / "key.pem").write_text("not for the browser", encoding="utf-8")
        return ApiConfig(port=0, quiet=True, ui_dir=root)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def test_the_root_serves_the_page(self):
        reply = self.call("GET", "/")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"roster", reply.raw)

    def test_assets_come_back_with_the_right_type(self):
        reply = self.call("GET", "/app.js")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers["Content-Type"], "text/javascript; charset=utf-8")

    def test_the_api_still_wins_over_a_filename(self):
        self.assertEqual(self.call("GET", "/health").json["status"], "ok")

    def test_an_unlisted_extension_is_not_served(self):
        self.assertEqual(self.call("GET", "/key.pem").status, 415)

    def test_a_path_climbing_out_of_the_folder_is_refused(self):
        self.assertEqual(self.call("GET", "/../helpers.py").status, 403)

    def test_a_missing_file_is_a_404(self):
        self.assertEqual(self.call("GET", "/missing.html").status, 404)


class TestTheShippedPage(ServedCase):
    """The page in frontend/ is served by the same process that answers the API."""

    @classmethod
    def config(cls) -> ApiConfig:
        return ApiConfig(port=0, quiet=True, ui_dir=DEFAULT_UI_DIR)

    @classmethod
    def setUpClass(cls):
        if not (DEFAULT_UI_DIR / "index.html").exists():
            raise unittest.SkipTest("no frontend/index.html in this checkout")
        super().setUpClass()

    def test_the_page_the_admin_opens_is_there(self):
        reply = self.call("GET", "/")
        self.assertEqual(reply.status, 200)
        self.assertIn(b"Duty roster desk", reply.raw)

    def test_the_page_only_calls_routes_this_server_answers(self):
        page = self.call("GET", "/").raw.decode("utf-8")
        script = re.search(r'<script src="([^"]+)"', page)
        self.assertIsNotNone(script, "the page links no script")
        served = self.call("GET", "/" + script.group(1))
        self.assertEqual(served.status, 200)
        called = set(re.findall(r'api\("(/[a-z]+)"', served.raw.decode("utf-8")))
        self.assertTrue(called, "the page asks the engine for nothing")
        known = {"/" + name for name in ENDPOINTS} | {"/health", "/sample", "/rules"}
        self.assertLessEqual(called, known)

    def test_everything_the_page_links_is_served(self):
        page = self.call("GET", "/").raw.decode("utf-8")
        linked = re.findall(r'(?:src|href)="([^":]+)"', page)
        self.assertTrue(linked, "the page links nothing")
        for path in linked:
            with self.subTest(path):
                self.assertEqual(self.call("GET", "/" + path).status, 200)


class TestBindingRules(unittest.TestCase):
    def test_loopback_is_recognised_by_every_spelling(self):
        for host in ("127.0.0.1", "localhost", "::1", "[::1]", ""):
            self.assertTrue(is_loopback(host), host)
        for host in ("0.0.0.0", "192.168.1.10", "roster.internal"):
            self.assertFalse(is_loopback(host), host)

    def test_a_public_bind_without_a_token_is_refused(self):
        with self.assertRaises(SystemExit) as caught:
            serve(ApiConfig(host="0.0.0.0", port=0, quiet=True))
        self.assertIn("--token", str(caught.exception))


class TestSampleArguments(unittest.TestCase):
    def test_blank_values_fall_back_to_the_defaults(self):
        self.assertEqual(query_kwargs({"days": [""], "seed": ["3"]}), {"seed": 3})

    def test_the_small_flag_switches_instance(self):
        self.assertEqual(len(sample_instance(**query_kwargs({"small": ["1"]})).employees), 12)

    def test_a_number_that_is_not_a_number_names_its_field(self):
        with self.assertRaises(ServiceError) as caught:
            query_kwargs({"employees": ["lots"]})
        self.assertEqual(caught.exception.field, "employees")


if __name__ == "__main__":
    unittest.main()

