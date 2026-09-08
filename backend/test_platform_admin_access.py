"""Platform operations through real auth/routes and an isolated SQLite database."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from database.models import AuditLog, AuthRefreshSession, Bot, Customer, Document, Organization, OrganizationMembership, Plan, Subscription, User
from routes import billing_routes, bot_routes, knowledge_routes, organization_routes
from routes.admin_routes import lock_organizations_using_plan
from services.billing_service import DEFAULT_PLANS
import test_platform_admin_console as fixture


class PlatformAccessTests(unittest.TestCase):
    setUp = fixture.PlatformAdminConsoleTests.setUp
    tearDown = fixture.PlatformAdminConsoleTests.tearDown

    def prepare(self):
        self.app.include_router(organization_routes.router, prefix="/organizations")
        self.app.include_router(bot_routes.collection_router)
        self.app.include_router(knowledge_routes.router, prefix="/knowledge")
        self.app.include_router(billing_routes.router, prefix="/billing")
        with self.sessions() as db:
            for number, (code, settings) in enumerate(DEFAULT_PLANS.items(), 1):
                db.add(Plan(id=number, code=code, name=settings["name"], limits_json=dict(settings["limits"])))
            db.flush()
            db.add_all([Subscription(organization_id=i, plan_id=1, provider="manual") for i in (1, 2)])
            db.add(Document(id=1, organization_id=2, bot_id=2, filename="Synthetic", source_type="txt", status="ready", processing_status="completed"))
            db.commit()

    def test_admin_can_enter_all_workspaces_without_membership_writes(self):
        self.prepare()
        response = self.client.get("/organizations/", headers=self.headers[1])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({row["id"] for row in response.json()}, {1, 2})
        self.assertTrue(all(row["role"] == "owner" for row in response.json()))
        self.assertEqual({row["id"] for row in self.client.get("/bots", headers=self.headers[1]).json()}, {1, 2})
        scoped = self.client.get("/bots", headers={**self.headers[1], "X-Organization-Id": "2"})
        self.assertEqual([row["id"] for row in scoped.json()], [2])
        for url in ("/bot/2", "/knowledge/documents?bot_id=2", "/organizations/2/members", "/organizations/2/invitations", "/billing/organizations/2/usage"):
            self.assertEqual(self.client.get(url, headers=self.headers[1]).status_code, 200, url)
        self.assertEqual(self.client.patch("/organizations/2", headers=self.headers[1], json={"name": "Renamed"}).status_code, 200)
        with patch("services.bot_service.invalidate_bot_cache"):
            self.assertEqual(self.client.put("/bot/2", headers=self.headers[1], json={"name": "Managed bot"}).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.query(OrganizationMembership).filter(OrganizationMembership.user_id == 1).count(), 0)
            self.assertEqual(db.query(OrganizationMembership).count(), 2)

    def test_normal_users_keep_tenant_and_role_boundaries(self):
        self.prepare()
        for user_id in (2, 3):
            self.assertEqual([row["id"] for row in self.client.get("/organizations/", headers=self.headers[user_id]).json()], [1])
            self.assertEqual([row["id"] for row in self.client.get("/bots", headers=self.headers[user_id]).json()], [1])
            for url in ("/bot/2", "/knowledge/documents?bot_id=2", "/organizations/2/members", "/billing/organizations/2/usage"):
                self.assertEqual(self.client.get(url, headers=self.headers[user_id]).status_code, 404, url)
            self.assertEqual(self.client.put("/bot/2", headers=self.headers[user_id], json={"name": "Denied"}).status_code, 404)
            self.assertEqual(self.client.delete("/knowledge/documents/1", headers=self.headers[user_id]).status_code, 404)
        self.assertEqual(self.client.put("/bot/1", headers=self.headers[2], json={"name": "Denied"}).status_code, 403)

    def test_demotion_and_disable_block_workspace_and_admin_access(self):
        self.prepare()
        with self.sessions() as db:
            db.get(User, 1).is_admin = False
            db.commit()
        self.assertEqual(self.client.get("/bot/2", headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.get("/admin/users", headers=self.headers[1]).status_code, 403)
        with self.sessions() as db:
            db.get(User, 1).disabled = True
            db.commit()
        self.assertEqual(self.client.get("/organizations/", headers=self.headers[1]).status_code, 401)

    def test_admin_quota_checks_are_not_bypassed(self):
        self.prepare()
        with self.sessions() as db:
            db.get(Plan, 1).limits_json = {**DEFAULT_PLANS["free"]["limits"], "max_documents": 1}
            db.commit()
        with patch("routes.knowledge_routes.enforce_rate_limit"), patch("routes.knowledge_routes.create_website_document") as create:
            response = self.client.post("/knowledge/crawl", headers=self.headers[1], json={"bot_id": 2, "url": "https://example.com"})
        self.assertEqual(response.status_code, 402, response.text)
        create.assert_not_called()

    def test_manual_plan_assignment_changes_only_selected_org(self):
        self.prepare()
        response = self.client.patch("/admin/organizations/2/plan", headers=self.headers[1], json={"plan_id": 2, "expected_plan_id": 1})
        self.assertEqual(response.status_code, 200, response.text)
        usage = self.client.get("/billing/organizations/2/usage", headers=self.headers[1]).json()
        self.assertEqual(usage["limits"]["max_documents"], 500)
        self.assertEqual(usage["usage"]["documents_used"], 1)
        with self.sessions() as db:
            self.assertEqual(db.query(Subscription).filter_by(organization_id=1).one().plan_id, 1)
            self.assertEqual(db.get(Plan, 1).limits_json["max_documents"], 20)
            self.assertEqual(db.query(AuditLog).filter_by(organization_id=2).count(), 1)
        self.assertEqual(self.client.patch("/admin/organizations/2/plan", headers=self.headers[1], json={"plan_id": 1, "expected_plan_id": 1}).status_code, 409)
        self.assertEqual(self.client.get("/admin/organizations/999/plan", headers=self.headers[1]).status_code, 404)

    def test_plan_assignment_rejects_inactive_and_provider_managed(self):
        self.prepare()
        with self.sessions() as db:
            db.get(Plan, 2).active = False
            db.query(Subscription).filter_by(organization_id=1).one().provider = "external"
            db.commit()
        self.assertEqual(self.client.patch("/admin/organizations/2/plan", headers=self.headers[1], json={"plan_id": 2, "expected_plan_id": 1}).status_code, 422)
        self.assertEqual(self.client.patch("/admin/organizations/1/plan", headers=self.headers[1], json={"plan_id": 3, "expected_plan_id": 1}).status_code, 409)

    def test_plan_limit_updates_validate_merge_and_reject_stale_writes(self):
        self.prepare()
        limits = dict(DEFAULT_PLANS["free"]["limits"])
        for invalid in (0, -1, True, 1.5, "150"):
            self.assertEqual(self.client.patch("/admin/plans/1/limits", headers=self.headers[1], json={"limits": {"max_documents": invalid}, "expected_limits": limits}).status_code, 422)
        response = self.client.patch("/admin/plans/1/limits", headers=self.headers[1], json={"limits": {"max_documents": 150}, "expected_limits": limits})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["limits_json"], {**limits, "max_documents": 150})
        self.assertEqual(self.client.patch("/admin/plans/1/limits", headers=self.headers[1], json={"limits": {"max_documents": 160}, "expected_limits": limits}).status_code, 409)
        self.assertEqual(self.client.patch("/admin/plans/1/limits", headers=self.headers[1], json={"limits": {"random_bypass": 1}, "expected_limits": limits}).status_code, 422)

    def test_user_status_revokes_sessions_and_never_exposes_secrets(self):
        with self.sessions() as db:
            db.add(AuthRefreshSession(user_id=2, token_hash="synthetic-session-hash", expires_at=datetime.utcnow() + timedelta(days=1)))
            db.commit()
        response = self.client.patch("/admin/users/2/status", headers=self.headers[1], json={"disabled": True, "expected_disabled": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/bot/1", headers=self.headers[2]).status_code, 401)
        with self.sessions() as db:
            self.assertIsNotNone(db.query(AuthRefreshSession).filter_by(user_id=2).one().revoked_at)
        self.assertEqual(self.client.patch("/admin/users/2/status", headers=self.headers[1], json={"disabled": False, "expected_disabled": False}).status_code, 409)
        self.assertEqual(self.client.patch("/admin/users/2/status", headers=self.headers[1], json={"disabled": False, "expected_disabled": True}).status_code, 200)
        with self.sessions() as db:
            self.assertIsNotNone(db.query(AuthRefreshSession).filter_by(user_id=2).one().revoked_at)
        for url in ("/admin/users", "/admin/audit-logs"):
            body = self.client.get(url, headers=self.headers[1]).text
            for secret in ("synthetic-hash", "password_hash", "token_hash", "api_key", "user_agent", "ip_address"):
                self.assertNotIn(secret, body)
        self.assertEqual(self.client.patch("/admin/users/1/status", headers=self.headers[1], json={"disabled": True, "expected_disabled": False}).status_code, 409)

    def test_new_listings_are_bounded_and_forbid_privilege_mutation(self):
        self.prepare()
        for path in ("/admin/users", "/admin/audit-logs"):
            self.assertEqual(self.client.get(path + "?limit=101", headers=self.headers[1]).status_code, 422)
        response = self.client.get("/admin/users?search=Owner&limit=1", headers=self.headers[1]).json()
        self.assertEqual([row["id"] for row in response["items"]], [3])
        self.assertEqual(self.client.patch("/admin/users/2/status", headers=self.headers[1], json={"disabled": False, "expected_disabled": False, "is_admin": True}).status_code, 422)

    def test_admin_creates_bot_under_target_organization_customer(self):
        self.prepare()
        with self.sessions() as db:
            db.get(User, 1).customer_id = 1
            db.add(Organization(id=3, name="Org Gamma", slug="gamma", owner_user_id=3))
            db.commit()
        with patch("services.bot_service.allocate_key_to_bot"), patch("services.bot_service.invalidate_bot_cache"):
            response = self.client.post("/bot/create", headers=self.headers[1], json={"organization_id": 2, "name": "Cross-org bot"})
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            bot = db.query(Bot).filter(Bot.name == "Cross-org bot").one()
            self.assertEqual((bot.organization_id, bot.customer_id), (2, 2))
            self.assertEqual(db.get(User, 1).customer_id, 1)
            self.assertEqual(db.query(Customer).count(), 2)
        with patch("services.bot_service.allocate_key_to_bot"), patch("services.bot_service.invalidate_bot_cache"):
            first = self.client.post("/bot/create", headers=self.headers[1], json={"organization_id": 3, "name": "First gamma bot"})
        self.assertEqual(first.status_code, 200, first.text)
        with self.sessions() as db:
            bot = db.query(Bot).filter(Bot.name == "First gamma bot").one()
            owner = db.get(User, 3)
            self.assertEqual(bot.organization_id, 3)
            self.assertEqual(bot.customer_id, owner.customer_id)
            self.assertNotEqual(bot.customer_id, 1)
            self.assertEqual(db.get(User, 1).customer_id, 1)

    def test_plan_limit_updates_lock_only_affected_organizations(self):
        self.prepare()
        with self.sessions() as db:
            db.query(Subscription).filter_by(organization_id=2).one().plan_id = 2
            db.add(Organization(id=3, name="Org Gamma", slug="gamma"))
            db.commit()
            self.assertEqual([org.id for org in lock_organizations_using_plan(db, db.get(Plan, 2))], [2])
            self.assertEqual([org.id for org in lock_organizations_using_plan(db, db.get(Plan, 1))], [1, 3])
        limits = dict(DEFAULT_PLANS["pro"]["limits"])
        response = self.client.patch(
            "/admin/plans/2/limits",
            headers=self.headers[1],
            json={"limits": {"max_documents": 150}, "expected_limits": limits},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertEqual(db.get(Plan, 2).limits_json["max_documents"], 150)
            self.assertEqual(db.get(Plan, 1).limits_json["max_documents"], 20)

    def test_admin_organization_listings_are_paginated(self):
        self.prepare()
        with self.sessions() as db:
            db.add_all([Organization(id=100 + i, name=f"Extra {i}", slug=f"extra-{i}") for i in range(101)])
            db.commit()
        page = self.client.get("/admin/organizations?limit=25&offset=100", headers=self.headers[1]).json()
        self.assertEqual(page["total"], 103)
        self.assertEqual(len(page["items"]), 3)
        self.assertEqual(page["limit"], 25)
        workspace = self.client.get("/organizations/?limit=5&offset=0", headers=self.headers[1]).json()
        self.assertEqual(len(workspace), 5)
        next_page = self.client.get("/organizations/?limit=5&offset=5", headers=self.headers[1]).json()
        self.assertEqual(len(next_page), 5)
        self.assertTrue({row["id"] for row in workspace}.isdisjoint({row["id"] for row in next_page}))
        self.assertEqual(len(self.client.get("/organizations/", headers=self.headers[1]).json()), 100)
        self.assertEqual(self.client.get("/organizations/?limit=101", headers=self.headers[1]).status_code, 422)
        self.assertEqual(self.client.get("/admin/organizations?limit=101", headers=self.headers[1]).status_code, 422)
        self.assertEqual([row["id"] for row in self.client.get("/organizations/", headers=self.headers[3]).json()], [1])


if __name__ == "__main__":
    unittest.main()
