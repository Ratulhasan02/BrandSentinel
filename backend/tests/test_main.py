import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import main


SAMPLE = (
    "Our app is the #1 fastest app in Bangladesh!!! "
    "We guarantee that every customer will save 90% on all purchases. "
    "Get cheap plans for everyone."
)


class BrandSentinelTests(unittest.TestCase):
    def setUp(self):
        self.original_db = main.DB
        self.temp_dir = tempfile.TemporaryDirectory()
        main.DB = Path(self.temp_dir.name) / "brand.db"
        main.TOKENS.clear()
        main.init()
        self.admin_id = main.create_user("admin-test", "admin", "admin-password-123")
        self.creator_id = main.create_user(
            "creator-test", "creator", "creator-password-123"
        )
        self.manager_id = main.create_user(
            "manager-test", "manager", "manager-password-123"
        )
        main.TOKENS.update(
            {
                "admin-token": {
                    "name": "admin-test",
                    "role": "admin",
                    "expires": 4_000_000_000,
                },
                "creator-token": {
                    "name": "creator-test",
                    "role": "creator",
                    "expires": 4_000_000_000,
                },
                "manager-token": {
                    "name": "manager-test",
                    "role": "manager",
                    "expires": 4_000_000_000,
                },
            }
        )
        self.seed_result = main.seed_demo_data()
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        self.env.stop()
        main.TOKENS.clear()
        main.DB = self.original_db
        self.temp_dir.cleanup()

    def test_init_is_repeatable_and_preserves_existing_records(self):
        source_id = main.q(
            "INSERT INTO sources(kind,title,body) VALUES('fact','Existing','Keep me')",
            write=True,
        )
        main.init()
        source = main.q("SELECT * FROM sources WHERE id=?", (source_id,), one=True)
        self.assertEqual(source["body"], "Keep me")
        self.assertEqual(main.q("SELECT count(*) AS n FROM users", one=True)["n"], 3)

    def test_seed_is_repeatable_and_does_not_overwrite_edited_sources(self):
        self.assertEqual(self.seed_result["inserted"], 3)
        first = main.seed_demo_data()
        source = main.q(
            "SELECT * FROM sources WHERE title='Brand Tone Guidelines'", one=True
        )
        self.assertEqual(first["inserted"], 0)
        self.assertEqual(source["created_by"], "admin-test")
        main.q(
            "UPDATE sources SET body='User-edited guidance' WHERE id=?",
            (source["id"],),
            write=True,
        )
        second = main.seed_demo_data()
        current = main.q(
            "SELECT body FROM sources WHERE id=?", (source["id"],), one=True
        )
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(current["body"], "User-edited guidance")

    def test_deterministic_review_flags_sample_with_real_source_references(self):
        findings = main.rule_review(SAMPLE)
        claims = [finding for finding in findings if finding["ftype"] == "claim"]
        terminology = [
            finding for finding in findings if finding["ftype"] == "terminology"
        ]
        tone = [finding for finding in findings if finding["ftype"] == "tone"]
        self.assertEqual(len(claims), 2)
        self.assertTrue(any("#1 fastest" in item["snippet"] for item in claims))
        savings = next(item for item in claims if "save 90%" in item["snippet"])
        cited = main.q(
            "SELECT title,body FROM sources WHERE id=?",
            (savings["source_id"],),
            one=True,
        )
        self.assertEqual(cited["title"], "Approved Product Facts")
        self.assertIn("do not guarantee", cited["body"])
        self.assertEqual(savings["severity"], "high")
        self.assertTrue(any(item["snippet"] == "cheap plans" for item in terminology))
        self.assertTrue(any(item["snippet"] == "!!!" for item in tone))
        for finding in findings:
            self.assertIn(finding["origin"], {"deterministic", "llm"})
            self.assertTrue(finding["why"])
            self.assertGreaterEqual(finding["confidence"], 0)
            self.assertLessEqual(finding["confidence"], 1)

    def test_full_review_keeps_tone_finding_next_to_claim(self):
        created = main.create_submission(
            main.NewSub(title="Sample", channel="social post", text=SAMPLE),
            "creator-token",
        )
        detail = main.detail(created["id"], "creator-token")
        tone = [item for item in detail["findings"] if item["ftype"] == "tone"]
        self.assertTrue(any(item["snippet"] == "!!!" for item in tone))
        self.assertEqual(len(detail["findings"]), 4)

    def test_llm_quote_and_citation_validation_rejects_fabrication(self):
        sources = [{"id": 4, "title": "Tone", "body": "Be clear."}]
        valid = {
            "quote": "be clear",
            "type": "tone",
            "why": "This wording is unclear.",
            "source_id": 4,
            "suggestion": "write clearly",
            "confidence": 0.8,
        }
        raw = json.dumps(
            [
                valid,
                {**valid, "quote": "not submitted"},
                {**valid, "source_id": 99},
                {**valid, "confidence": 2},
            ]
        )
        result = main._validated_llm_findings("Please be clear", raw, sources)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["origin"], "llm")
        self.assertEqual(result[0]["s_from"], 7)
        with self.assertRaises(json.JSONDecodeError):
            main._validated_llm_findings("text", "not json", sources)

    def test_llm_disabled_returns_clear_skipped_status(self):
        findings, status, detail = main.llm_review(SAMPLE)
        self.assertEqual(findings, [])
        self.assertEqual(status, "skipped")
        self.assertIn("ANTHROPIC_API_KEY", detail)

    def test_llm_api_failure_is_reported_without_exposing_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-secret-key"}), patch(
            "anthropic.Anthropic", side_effect=TimeoutError("request timed out")
        ):
            findings, status, detail = main.llm_review(SAMPLE)
        self.assertEqual(findings, [])
        self.assertEqual(status, "failed")
        self.assertIn("TimeoutError", detail)
        self.assertNotIn("test-secret-key", detail)

    def test_llm_review_validates_mocked_anthropic_response(self):
        answer = [
            {
                "quote": "cheap plans",
                "type": "messaging",
                "why": "Use approved terminology.",
                "source_id": main.q(
                    "SELECT id FROM sources WHERE title='Approved Terminology'",
                    one=True,
                )["id"],
                "suggestion": "affordable plans",
                "confidence": 0.9,
            },
            {
                "quote": "invented quote",
                "type": "tone",
                "why": "Not in submitted content.",
                "source_id": 1,
                "suggestion": "",
                "confidence": 0.9,
            },
        ]
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(answer))]
        )
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only-key"}), patch(
            "anthropic.Anthropic"
        ) as anthropic_client:
            anthropic_client.return_value.messages.create.return_value = response
            findings, status, detail = main.llm_review(SAMPLE)
        self.assertEqual(status, "completed")
        self.assertEqual(detail, "")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["origin"], "llm")
        anthropic_client.assert_called_once()

    def test_login_does_not_allow_role_selection_or_wrong_password(self):
        with self.assertRaises(HTTPException) as denied:
            main.login(main.Login(name="creator-test", password="wrong"))
        self.assertEqual(denied.exception.status_code, 401)
        with self.assertRaises(HTTPException) as no_user:
            main.login(main.Login(name="admin", password="admin"))
        self.assertEqual(no_user.exception.status_code, 401)
        logged_in = main.login(
            main.Login(name="creator-test", password="creator-password-123")
        )
        self.assertEqual(logged_in["role"], "creator")

    def test_registration_validates_names_and_applies_selected_role(self):
        registered = main.register(
            main.Register(name="  new.creator  ", password="new-password-123")
        )
        self.assertEqual(registered["name"], "new.creator")
        self.assertEqual(registered["role"], "creator")
        user = main.q(
            "SELECT role,approval_status FROM users WHERE name='new.creator'",
            one=True,
        )
        self.assertEqual(user["role"], "creator")
        self.assertEqual(user["approval_status"], "approved")

        reviewer = main.register(
            main.Register(
                name="new.reviewer",
                password="new-reviewer-password",
                role="reviewer",
            )
        )
        self.assertEqual(reviewer["role"], "reviewer")
        reviewer_user = main.q(
            "SELECT role,approval_status FROM users WHERE name='new.reviewer'",
            one=True,
        )
        self.assertEqual(
            reviewer_user, {"role": "reviewer", "approval_status": "approved"}
        )

        for name in ("ab", "invalid name", "creator_demo"):
            with self.subTest(name=name), self.assertRaises(HTTPException) as error:
                main.register(
                    main.Register(name=name, password="new-password-123")
                )
            self.assertEqual(error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as short_password:
            main.register(main.Register(name="another-user", password="short"))
        self.assertEqual(short_password.exception.status_code, 400)

    def test_manager_signup_requires_admin_approval_before_login(self):
        request = main.register(
            main.Register(
                name="pending.manager",
                password="pending-manager-password",
                role="manager",
            )
        )
        self.assertEqual(
            request,
            {
                "name": "pending.manager",
                "role": "manager",
                "approval_status": "pending",
            },
        )
        pending_user = main.q(
            "SELECT id,approval_status FROM users WHERE name='pending.manager'",
            one=True,
        )
        self.assertEqual(pending_user["approval_status"], "pending")
        with self.assertRaises(HTTPException) as pending_login:
            main.login(
                main.Login(
                    name="pending.manager",
                    password="pending-manager-password",
                )
            )
        self.assertEqual(pending_login.exception.status_code, 403)

        with self.assertRaises(HTTPException) as non_admin:
            main.approve_manager(pending_user["id"], "creator-token")
        self.assertEqual(non_admin.exception.status_code, 403)

        self.assertEqual(
            main.approve_manager(pending_user["id"], "admin-token"), {"ok": True}
        )
        logged_in = main.login(
            main.Login(
                name="pending.manager",
                password="pending-manager-password",
            )
        )
        self.assertEqual(logged_in["role"], "manager")
        with self.assertRaises(HTTPException) as already_approved:
            main.approve_manager(pending_user["id"], "admin-token")
        self.assertEqual(already_approved.exception.status_code, 409)

    def test_admin_role_management_updates_active_sessions(self):
        users = main.list_users("admin-token")
        self.assertTrue(any(user["name"] == "creator-test" for user in users))
        self.assertEqual(
            main.change_role(
                self.creator_id,
                main.RoleChange(role="reviewer"),
                "admin-token",
            ),
            {"ok": True},
        )
        self.assertEqual(main.TOKENS["creator-token"]["role"], "reviewer")
        self.assertEqual(
            main.q(
                "SELECT role FROM users WHERE id=?", (self.creator_id,), one=True
            )["role"],
            "reviewer",
        )

        with self.assertRaises(HTTPException) as non_admin:
            main.list_users("creator-token")
        self.assertEqual(non_admin.exception.status_code, 403)

        with self.assertRaises(HTTPException) as protected_admin:
            main.change_role(
                self.admin_id,
                main.RoleChange(role="creator"),
                "admin-token",
            )
        self.assertEqual(protected_admin.exception.status_code, 403)

    def test_demo_accounts_are_created_or_removed_by_mode(self):
        with patch.object(main, "DEMO_MODE", True), patch.object(
            main, "DEMO_PASSWORD", "demo-password-123"
        ):
            main.ensure_demo_users()
            demo_accounts = main.q(
                "SELECT name,role FROM users WHERE name IN (?,?,?,?) ORDER BY name",
                tuple(main.DEMO_NAMES),
            )
            self.assertEqual(len(demo_accounts), 4)
            self.assertEqual(len(main.q("SELECT * FROM sources")), 3)
            self.assertEqual(len(main.demo_accounts()), 4)
            samples = main.q(
                "SELECT id,title,status FROM submissions WHERE author='creator_demo' "
                "ORDER BY title"
            )
            self.assertEqual(
                [(item["title"], item["status"]) for item in samples],
                [
                    ("Sample: Draft to practise accept/reject", "draft"),
                    ("Sample: Summer Promotion Ad (in review)", "in_review"),
                ],
            )
            for sample in samples:
                detail = main.detail(sample["id"], "admin-token")
                self.assertTrue(detail["findings"])
            review_sample = next(
                item
                for item in samples
                if item["title"] == "Sample: Summer Promotion Ad (in review)"
            )
            findings = main.q(
                "SELECT ftype FROM findings WHERE submission_id=?",
                (review_sample["id"],),
            )
            finding_types = {item["ftype"] for item in findings}
            self.assertTrue({"claim", "tone", "terminology"} <= finding_types)

        with patch.object(main, "DEMO_MODE", False):
            main.ensure_demo_users()
        remaining = main.q(
            "SELECT count(*) AS n FROM users WHERE name IN (?,?,?,?)",
            tuple(main.DEMO_NAMES),
            one=True,
        )
        self.assertEqual(remaining["n"], 0)

    def test_health_reports_status_and_demo_mode_without_user_data(self):
        for demo_mode in (False, True):
            with self.subTest(demo_mode=demo_mode), patch.object(
                main, "DEMO_MODE", demo_mode
            ):
                self.assertEqual(
                    main.health(),
                    {"status": "ok", "demo_mode": demo_mode},
                )

    def test_demo_submission_seed_is_idempotent_and_skips_llm(self):
        with patch.object(main, "DEMO_MODE", True), patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "test-only-key"}
        ), patch("anthropic.Anthropic") as anthropic_client:
            main.ensure_demo_users()
            main.seed_demo_submissions()
            self.assertEqual(
                main.q(
                    "SELECT count(*) AS n FROM submissions WHERE author='creator_demo'",
                    one=True,
                )["n"],
                2,
            )
            anthropic_client.assert_not_called()
        seeded = main.q(
            "SELECT llm_status,llm_detail FROM submissions WHERE author='creator_demo'"
        )
        self.assertTrue(all(item["llm_status"] == "skipped" for item in seeded))
        self.assertTrue(
            all(
                item["llm_detail"]
                == "Sample data seeded without an LLM call."
                for item in seeded
            )
        )

    def test_demo_reset_access_and_restores_only_sample_submissions(self):
        with patch.object(main, "DEMO_MODE", False):
            with self.assertRaises(HTTPException) as disabled:
                main.reset_demo_samples("admin-token")
        self.assertEqual(disabled.exception.status_code, 404)

        with patch.object(main, "DEMO_MODE", True):
            main.ensure_demo_users()
            with self.assertRaises(HTTPException) as denied:
                main.reset_demo_samples("creator-token")
            self.assertEqual(denied.exception.status_code, 403)

            main.TOKENS["admin-demo-token"] = {
                "name": "admin_demo",
                "role": "admin",
                "expires": 4_000_000_000,
            }
            review_sample = main.q(
                "SELECT id FROM submissions WHERE author='creator_demo' "
                "AND title='Sample: Summer Promotion Ad (in review)'",
                one=True,
            )
            draft_sample = main.q(
                "SELECT id FROM submissions WHERE author='creator_demo' "
                "AND title='Sample: Draft to practise accept/reject'",
                one=True,
            )
            main.set_status(
                review_sample["id"],
                main.Status(status="approved", reason="Reviewed for the demo."),
                "admin-demo-token",
            )
            main.edit_submission(
                draft_sample["id"],
                main.EditSub(
                    title="Sample: Draft to practise accept/reject",
                    channel="social post",
                    text="Edited demo content with affordable plans.",
                ),
                "admin-demo-token",
            )

            untouched_id = main.create_submission(
                main.NewSub(title="Keep this", text="Other creator content."),
                "creator-token",
            )["id"]
            self.assertEqual(
                main.reset_demo_samples("admin-demo-token"), {"ok": True}
            )
            restored = main.q(
                "SELECT id,title,status,text,version FROM submissions "
                "WHERE author='creator_demo' ORDER BY title"
            )
            self.assertEqual(len(restored), 2)
            by_title = {item["title"]: item for item in restored}
            self.assertEqual(
                by_title["Sample: Summer Promotion Ad (in review)"]["status"],
                "in_review",
            )
            self.assertEqual(
                by_title["Sample: Draft to practise accept/reject"]["status"],
                "draft",
            )
            self.assertEqual(
                by_title["Sample: Draft to practise accept/reject"]["text"],
                "Join our community today!! Our cheap plans are built for everyone.",
            )
            for sample in restored:
                detail = main.detail(sample["id"], "admin-demo-token")
                self.assertEqual(len(detail["versions"]), 1)
                self.assertEqual(detail["comments"], [])
                self.assertEqual(detail["activity"], [])
                self.assertTrue(detail["findings"])
            self.assertEqual(
                main.q("SELECT id FROM submissions WHERE id=?", (untouched_id,), one=True)[
                    "id"
                ],
                untouched_id,
            )

    def test_demo_mode_off_removes_demo_submissions_and_accounts(self):
        with patch.object(main, "DEMO_MODE", True):
            main.ensure_demo_users()
        with patch.object(main, "DEMO_MODE", False):
            main.ensure_demo_users()
            self.assertEqual(main.demo_accounts(), [])
        self.assertEqual(
            main.q(
                "SELECT count(*) AS n FROM users WHERE name IN (?,?,?,?)",
                tuple(main.DEMO_NAMES),
                one=True,
            )["n"],
            0,
        )
        self.assertEqual(
            main.q(
                "SELECT count(*) AS n FROM submissions WHERE author='creator_demo'",
                one=True,
            )["n"],
            0,
        )

    def test_role_access_and_approval_high_risk_override(self):
        created = main.create_submission(
            main.NewSub(title="Sample", channel="social post", text=SAMPLE),
            "creator-token",
        )
        submission_id = created["id"]
        with self.assertRaises(HTTPException) as premature:
            main.set_status(
                submission_id,
                main.Status(status="approved", reason="Not in review."),
                "manager-token",
            )
        self.assertEqual(premature.exception.status_code, 409)
        main.set_status(
            submission_id, main.Status(status="in_review"), "creator-token"
        )
        finding_id = main.q(
            "SELECT id FROM findings WHERE submission_id=? AND severity='high'",
            (submission_id,),
            one=True,
        )["id"]
        with self.assertRaises(HTTPException) as review_edit:
            main.edit_submission(
                submission_id,
                main.EditSub(title="Changed", channel="social post", text="Changed."),
                "creator-token",
            )
        self.assertEqual(review_edit.exception.status_code, 409)
        with self.assertRaises(HTTPException) as review_decision:
            main.decide(
                finding_id,
                main.Decision(decision="rejected"),
                "creator-token",
            )
        self.assertEqual(review_decision.exception.status_code, 409)
        with self.assertRaises(HTTPException) as denied:
            main.add_source(
                main.Source(
                    kind="fact", title="No", body="Not allowed"
                ),
                "creator-token",
            )
        self.assertEqual(denied.exception.status_code, 403)
        source = main.add_source(
            main.Source(kind="fact", title="Admin source", body="Approved."),
            "admin-token",
        )
        self.assertEqual(
            main.q(
                "SELECT created_by FROM sources WHERE id=?",
                (source["id"],),
                one=True,
            )["created_by"],
            "admin-test",
        )
        with self.assertRaises(HTTPException) as creator_approval:
            main.set_status(
                submission_id,
                main.Status(status="approved", reason="Not authorized."),
                "creator-token",
            )
        self.assertEqual(creator_approval.exception.status_code, 403)
        with self.assertRaises(HTTPException) as hidden:
            main.detail(submission_id, "missing-token")
        self.assertEqual(hidden.exception.status_code, 401)
        with self.assertRaises(HTTPException) as no_override:
            main.set_status(
                submission_id,
                main.Status(status="approved"),
                "manager-token",
            )
        self.assertEqual(no_override.exception.status_code, 400)
        main.set_status(
            submission_id,
            main.Status(status="approved", reason="Legal review documented."),
            "manager-token",
        )
        detail = main.detail(submission_id, "manager-token")
        self.assertEqual(detail["status"], "approved")
        self.assertEqual(detail["activity"][0]["reason"], "Legal review documented.")
        self.assertEqual(len(detail["versions"]), 1)
        with self.assertRaises(HTTPException) as finalized_edit:
            main.edit_submission(
                submission_id,
                main.EditSub(title="Changed", channel="social post", text="Changed."),
                "creator-token",
            )
        self.assertEqual(finalized_edit.exception.status_code, 409)
        with self.assertRaises(HTTPException) as finalized_status:
            main.set_status(
                submission_id,
                main.Status(status="changes_requested"),
                "manager-token",
            )
        self.assertEqual(finalized_status.exception.status_code, 409)

    def test_comments_edits_suggestions_and_revisions_persist(self):
        created = main.create_submission(
            main.NewSub(title="Sample", channel="social post", text=SAMPLE),
            "creator-token",
        )
        submission_id = created["id"]
        main.comment(
            submission_id, main.Comment(body="Please revise the claim."), "manager-token"
        )
        detail = main.detail(submission_id, "creator-token")
        term = next(
            item for item in detail["findings"] if item["snippet"] == "cheap plans"
        )
        main.decide(
            term["id"], main.Decision(decision="accepted"), "creator-token"
        )
        edited = main.edit_submission(
            submission_id,
            main.EditSub(
                title="Updated",
                channel="social post",
                text="A new version with affordable plans.",
                note="Manual correction",
            ),
            "creator-token",
        )
        detail = main.detail(submission_id, "creator-token")
        self.assertEqual(detail["version"], 3)
        self.assertEqual(detail["title"], "Updated")
        self.assertEqual(len(detail["versions"]), 3)
        self.assertEqual(len(detail["comments"]), 1)
        self.assertEqual(edited["review"]["llm_status"], "skipped")

    def test_creators_cannot_read_or_edit_other_users_submissions(self):
        other_user = main.create_user(
            "other-creator", "creator", "other-creator-password"
        )
        main.TOKENS["other-token"] = {
            "name": "other-creator",
            "role": "creator",
            "expires": 4_000_000_000,
        }
        submission_id = main.create_submission(
            main.NewSub(title="Private", text="Private text"),
            "creator-token",
        )["id"]
        with self.assertRaises(HTTPException) as denied:
            main.detail(submission_id, "other-token")
        self.assertEqual(denied.exception.status_code, 403)
        self.assertTrue(other_user)


if __name__ == "__main__":
    unittest.main()
