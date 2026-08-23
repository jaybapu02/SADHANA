from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import User
from relationships.models import ConnectionRequest
from notifications.models import Notification

from .models import (
    AccessRequest, BlacklistItem, FocusDevice, FocusDeviceCommand,
    FocusLockEvent, FocusSession, WhitelistItem,
)


class FocusTestBase(TestCase):
    """Shared fixtures: a connected parent+child pair with an active session."""

    @classmethod
    def setUpTestData(cls):
        cls.parent = User.objects.create_user(
            username='parent1', password='pass12345', role='PARENT')
        cls.child = User.objects.create_user(
            username='child1', password='pass12345', role='CHILD')
        ConnectionRequest.objects.create(
            parent=cls.parent, child=cls.child, status='ACCEPTED')
        cls.restricted_site = BlacklistItem.objects.create(
            name='YouTube', category='WEBSITE', url_pattern='youtube.com')
        cls.restricted_app = BlacklistItem.objects.create(
            name='Discord', category='APP', app_name='discord.exe')
        cls.allowed_app = WhitelistItem.objects.create(
            name='VS Code', category='APP', app_name='code.exe')

    def setUp(self):
        self.client.force_login(self.child)
        self.session = FocusSession.objects.create(
            child=self.child,
            planned_duration=25,
            status=FocusSession.Status.ACTIVE,
            session_type=FocusSession.Type.FOCUS,
            lock_enabled=True,
        )

    def approve_access(self, item=None, minutes=10, in_use=False):
        item = item or self.restricted_site
        req = AccessRequest.objects.create(
            child=self.child,
            parent=self.parent,
            session=self.session,
            blacklist_item=item,
            status=AccessRequest.Status.APPROVED,
            granted_until=timezone.now() + timedelta(minutes=minutes),
        )
        if in_use:
            req.in_use = True
            req.usage_started_at = timezone.now()
            req.save()
            self.session.paused_at = req.usage_started_at
            self.session.save(update_fields=['paused_at'])
        return req


# ─── Server-authoritative ticking ───


class SessionTickTests(FocusTestBase):
    def tick(self, kind='FOCUS', ago=None):
        if ago is not None:
            self.session.last_tick_at = timezone.now() - timedelta(seconds=ago)
            self.session.save(update_fields=['last_tick_at'])
        return self.client.post('/focus/api/session-tick/', {
            'session_id': self.session.id, 'kind': kind},
            content_type='application/json')

    def test_first_tick_records_baseline_without_accumulation(self):
        resp = self.tick()  # no prior last_tick_at -> baseline only
        self.assertEqual(resp.json()['status'], 'success')
        self.session.refresh_from_db()
        self.assertEqual(self.session.actual_focus_seconds, 0)
        self.assertIsNotNone(self.session.last_tick_at)

    def test_focus_tick_accumulates_delta(self):
        self.tick()  # baseline
        resp = self.tick(kind='FOCUS', ago=5)
        data = resp.json()
        self.assertEqual(data['focus_seconds'], 5)
        self.assertEqual(data['remaining_seconds'], 25 * 60 - 5)

    def test_distracted_tick_accumulates_distraction_only(self):
        self.tick()
        self.tick(kind='DISTRACTED', ago=7)
        self.session.refresh_from_db()
        self.assertEqual(self.session.distraction_seconds, 7)
        self.assertEqual(self.session.actual_focus_seconds, 0)

    def test_tick_ignored_while_paused_for_approved_use(self):
        self.approve_access(in_use=True)  # sets paused_at
        self.tick()
        resp = self.tick(kind='FOCUS', ago=10)
        data = resp.json()
        self.assertTrue(data['paused'])
        self.assertEqual(data['focus_seconds'], 0)
        self.session.refresh_from_db()
        self.assertEqual(self.session.actual_focus_seconds, 0)
        self.assertEqual(self.session.distraction_seconds, 0)

    def test_manual_pause_kind_accumulates_nothing(self):
        self.tick()
        self.tick(kind='PAUSED', ago=20)
        self.session.refresh_from_db()
        self.assertEqual(self.session.actual_focus_seconds, 0)
        self.assertEqual(self.session.distraction_seconds, 0)

    def test_delta_clamped_to_sixty_seconds(self):
        self.tick()
        self.tick(kind='FOCUS', ago=600)  # client was gone 10 minutes
        self.session.refresh_from_db()
        self.assertEqual(self.session.actual_focus_seconds, 60)

    def test_focus_time_capped_at_planned_duration(self):
        FocusSession.objects.filter(id=self.session.id).update(
            actual_focus_seconds=25 * 60 - 2)
        self.tick()
        self.tick(kind='FOCUS', ago=30)  # clamped to 30 > remaining 2
        self.session.refresh_from_db()
        self.assertEqual(self.session.actual_focus_seconds, 25 * 60)

    def test_other_users_session_is_rejected(self):
        other = User.objects.create_user(
            username='child2', password='pass12345', role='CHILD')
        self.client.force_login(other)
        resp = self.tick()
        self.assertEqual(resp.status_code, 404)


# ─── Approved app use / release / expiry ───


class ApprovedAppFlowTests(FocusTestBase):
    def use(self, req):
        return self.client.post(
            f'/focus/api/approved-app/{req.id}/use/',
            content_type='application/json')

    def release(self, req):
        return self.client.post(
            f'/focus/api/approved-app/{req.id}/release/',
            content_type='application/json')

    def test_use_pauses_focus_timer(self):
        req = self.approve_access()
        resp = self.use(req)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('paused', data['message'])
        self.session.refresh_from_db()
        req.refresh_from_db()
        self.assertIsNotNone(self.session.paused_at)
        self.assertTrue(req.in_use)
        self.assertIsNotNone(req.usage_started_at)
        self.assertTrue(FocusLockEvent.objects.filter(
            session=self.session,
            event_type=FocusLockEvent.EventType.APPROVED_APP_START).exists())

    def test_use_returns_website_url_and_remaining(self):
        req = self.approve_access(item=self.restricted_site, minutes=7)
        data = self.use(req).json()
        self.assertEqual(data['url'], 'https://youtube.com')
        self.assertLessEqual(data['remaining_seconds'], 7 * 60)
        self.assertGreater(data['remaining_seconds'], 6 * 60 + 30)

    def test_use_rejected_when_grant_expired(self):
        req = self.approve_access(minutes=-1)
        resp = self.use(req)
        self.assertEqual(resp.status_code, 400)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.paused_at)

    def test_starting_second_approval_releases_the_first(self):
        first = self.approve_access(item=self.restricted_site)
        second = self.approve_access(item=self.restricted_app)
        self.use(first)
        self.use(second)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.in_use)
        self.assertTrue(second.in_use)
        self.assertGreaterEqual(first.usage_seconds, 0)

    def test_release_finalizes_accounting_and_resumes_timer(self):
        req = self.approve_access()
        self.use(req)
        # Simulate 90 seconds of approved use.
        AccessRequest.objects.filter(id=req.id).update(
            usage_started_at=timezone.now() - timedelta(seconds=90))
        FocusSession.objects.filter(id=self.session.id).update(
            paused_at=timezone.now() - timedelta(seconds=90),
            actual_focus_seconds=300)
        resp = self.release(req)
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertGreaterEqual(data['used_seconds'], 89)
        self.session.refresh_from_db()
        req.refresh_from_db()
        self.assertIsNone(self.session.paused_at)
        self.assertFalse(req.in_use)
        self.assertIsNone(req.usage_started_at)
        self.assertEqual(req.usage_seconds, data['total_used_seconds'])
        self.assertEqual(self.session.pause_seconds_total, data['used_seconds'])

    def test_expiry_sweep_auto_releases_and_marks_expired(self):
        req = self.approve_access(in_use=True)
        # Grant ran out while the child kept using the app.
        AccessRequest.objects.filter(id=req.id).update(
            granted_until=timezone.now() - timedelta(seconds=30),
            usage_started_at=timezone.now() - timedelta(seconds=120))
        FocusSession.objects.filter(id=self.session.id).update(
            paused_at=timezone.now() - timedelta(seconds=120))

        resp = self.client.get('/focus/api/session-state/')
        data = resp.json()

        req.refresh_from_db()
        self.session.refresh_from_db()
        self.assertIsNone(self.session.paused_at,
                          'sweep must unfreeze the timer after expiry')
        self.assertFalse(req.in_use)
        self.assertEqual(req.status, AccessRequest.Status.EXPIRED)
        self.assertTrue(FocusLockEvent.objects.filter(
            session=self.session,
            event_type=FocusLockEvent.EventType.ACCESS_EXPIRED).exists())
        self.assertNotIn(
            req.id, [a['id'] for a in data['approved']],
            'expired approval must not appear as approved')

    def test_ticks_do_not_count_as_distraction_while_paused(self):
        """The whole point of approvals: hidden focus tab during approved use
        must not accrue distraction."""
        req = self.approve_access(in_use=True)
        self.client.post('/focus/api/session-tick/', {
            'session_id': self.session.id, 'kind': 'DISTRACTED'},
            content_type='application/json')
        self.session.refresh_from_db()
        self.assertEqual(self.session.distraction_seconds, 0)
        self.release(req)

    def test_session_state_payload_shape(self):
        req = self.approve_access()
        data = self.client.get('/focus/api/session-state/').json()
        self.assertTrue(data['active'])
        self.assertEqual(data['session_id'], self.session.id)
        self.assertFalse(data['paused'])
        self.assertEqual(data['remaining_seconds'], 25 * 60)
        self.assertEqual(len(data['approved']), 1)
        app = data['approved'][0]
        for key in ('id', 'app_name', 'category', 'url', 'granted_until',
                    'remaining_seconds', 'in_use', 'usage_seconds'):
            self.assertIn(key, app)
        self.assertFalse(data['agent_online'])

    def test_parent_sees_paused_state_with_approved_app(self):
        req = self.approve_access(in_use=True)
        self.client.force_login(self.parent)
        data = self.client.get('/focus/parent/api/active-sessions/').json()
        s = data['sessions'][0]
        self.assertTrue(s['paused'])
        self.assertEqual(s['approved_app'], 'YouTube')
        self.assertGreater(s['approved_app_remaining'], 0)


# ─── Launching apps through Sadhana ───


class LaunchAppTests(FocusTestBase):
    def launch(self, payload):
        return self.client.post('/focus/api/launch-app/', payload,
                                content_type='application/json')

    def test_whitelist_app_queues_agent_command(self):
        resp = self.launch({'source': 'WHITELIST', 'item_id': self.allowed_app.id})
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['action'], 'LAUNCH_APP')
        cmd = FocusDeviceCommand.objects.get(id=data['command_id'])
        self.assertEqual(cmd.status, FocusDeviceCommand.Status.QUEUED)
        self.assertEqual(cmd.requested_by, self.child)
        self.assertEqual(cmd.session_id, self.session.id)

    def test_whitelist_website_returns_open_url_action(self):
        site = WhitelistItem.objects.create(
            name='Google Docs', category='WEBSITE', url_pattern='docs.google.com')
        data = self.launch({'source': 'WHITELIST', 'item_id': site.id}).json()
        self.assertEqual(data['action'], 'OPEN_URL')
        self.assertEqual(data['url'], 'https://docs.google.com')
        self.assertFalse(FocusDeviceCommand.objects.exists())

    def test_approved_app_launch_requires_active_grant(self):
        req = self.approve_access(item=self.restricted_app, minutes=-2)
        resp = self.launch({'source': 'APPROVED', 'request_id': req.id})
        self.assertEqual(resp.status_code, 400)

    def test_approved_app_launch_queues_command(self):
        req = self.approve_access(item=self.restricted_app)
        data = self.launch({'source': 'APPROVED', 'request_id': req.id}).json()
        self.assertEqual(data['status'], 'success')
        cmd = FocusDeviceCommand.objects.get(id=data['command_id'])
        self.assertEqual(cmd.app_name, 'discord.exe')

    def test_device_status_delivers_commands_to_agent(self):
        device = FocusDevice.objects.create(
            child=self.child, device_type=FocusDevice.DeviceType.AGENT,
            name='Study PC', token='agent-token-123')
        self.launch({'source': 'WHITELIST', 'item_id': self.allowed_app.id})

        self.client.logout()
        resp = self.client.get('/focus/api/device-status/',
                               HTTP_AUTHORIZATION='Bearer agent-token-123')
        data = resp.json()
        self.assertTrue(data['active'])
        self.assertTrue(data['lock_enabled'])
        self.assertEqual(len(data['commands']), 1)
        self.assertEqual(data['commands'][0]['command_type'], 'LAUNCH_APP')
        self.assertIn('code.exe', data['commands'][0]['app_name'])

    def test_command_ack_completes_and_logs_event(self):
        device = FocusDevice.objects.create(
            child=self.child, device_type=FocusDevice.DeviceType.AGENT,
            name='Study PC', token='agent-token-123')
        cmd = FocusDeviceCommand.objects.create(
            requested_by=self.child, session=self.session, app_name='code.exe')

        self.client.logout()
        resp = self.client.post('/focus/api/device/command-ack/', {
            'command_id': cmd.id, 'ok': True, 'detail': 'launched'},
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer agent-token-123')
        self.assertEqual(resp.json()['status'], 'success')

        cmd.refresh_from_db()
        self.assertEqual(cmd.status, FocusDeviceCommand.Status.DONE)
        self.assertTrue(FocusLockEvent.objects.filter(
            event_type=FocusLockEvent.EventType.APP_LAUNCHED).exists())

    def test_command_ack_requires_valid_token(self):
        cmd = FocusDeviceCommand.objects.create(
            requested_by=self.child, session=self.session, app_name='code.exe')
        resp = self.client.post('/focus/api/device/command-ack/', {
            'command_id': cmd.id, 'ok': True},
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer wrong-token')
        self.assertEqual(resp.status_code, 401)
        cmd.refresh_from_db()
        self.assertEqual(cmd.status, FocusDeviceCommand.Status.QUEUED)

    def test_completed_commands_are_not_redelivered(self):
        device = FocusDevice.objects.create(
            child=self.child, device_type=FocusDevice.DeviceType.AGENT,
            name='Study PC', token='agent-token-123')
        cmd = FocusDeviceCommand.objects.create(
            requested_by=self.child, session=self.session, app_name='code.exe')
        FocusDeviceCommand.objects.filter(id=cmd.id).update(
            status=FocusDeviceCommand.Status.DONE)

        self.client.logout()
        data = self.client.get('/focus/api/device-status/',
                               HTTP_AUTHORIZATION='Bearer agent-token-123').json()
        self.assertEqual(data['commands'], [])


# ─── End-of-session accounting (server owns the numbers) ───


class EndSessionAccountingTests(FocusTestBase):
    def end(self, claim_focus=0, claim_distraction=0):
        return self.client.post('/focus/api/end-session/', {
            'session_id': self.session.id,
            'focus_seconds': claim_focus,
            'distraction_seconds': claim_distraction,
        }, content_type='application/json')

    def seed_ticks(self, total_seconds):
        """Simulate ticks that legitimately accumulated total_seconds."""
        self.session.last_tick_at = timezone.now() - timedelta(seconds=4)
        self.session.actual_focus_seconds = total_seconds - 4
        self.session.save(update_fields=['last_tick_at', 'actual_focus_seconds'])

    def test_client_cannot_inflate_focus_time(self):
        self.seed_ticks(total_seconds=600)  # really focused 10 min
        resp = self.end(claim_focus=1500)   # client lies: 25 min
        data = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertAlmostEqual(data['actual_focus_seconds'], 600, delta=3)
        self.assertEqual(data['session_status'], 'INTERRUPTED')
        self.assertTrue(data['early_exit'])

    def test_completion_judged_on_server_totals_with_grace(self):
        # Ticks brought the child to planned-5; the trailing bank on end
        # crosses the grace threshold (planned-10) -> COMPLETED.
        self.seed_ticks(total_seconds=25 * 60 - 5)
        data = self.end().json()
        self.assertEqual(data['session_status'], 'COMPLETED')
        self.assertFalse(data['early_exit'])

    def test_approved_usage_reported_without_penalty(self):
        req = self.approve_access(item=self.restricted_site)
        self.client.post(f'/focus/api/approved-app/{req.id}/use/',
                         content_type='application/json')
        self.seed_ticks(total_seconds=500)
        FocusSession.objects.filter(id=self.session.id).update(
            paused_at=timezone.now() - timedelta(seconds=120))
        AccessRequest.objects.filter(id=req.id).update(
            usage_started_at=timezone.now() - timedelta(seconds=120))

        data = self.end().json()
        self.assertAlmostEqual(data['actual_focus_seconds'], 500, delta=3)
        self.assertIn('YouTube', data['approved_usage'])
        self.assertGreaterEqual(data['pause_seconds_total'], 118)

    def test_legacy_client_without_ticks_still_works(self):
        data = self.end(claim_focus=900, claim_distraction=30).json()
        self.assertAlmostEqual(data['actual_focus_seconds'], 900, delta=3)
        self.assertAlmostEqual(data['distraction_seconds'], 30, delta=3)

    def test_ending_twice_fails_cleanly(self):
        self.end()
        resp = self.end()
        self.assertEqual(resp.status_code, 400)


# ─── Request access still requires an active locked context ───


class RequestAccessTests(FocusTestBase):
    def test_request_creates_pending_requests_for_all_parents(self):
        resp = self.client.post('/focus/api/request-access/', {
            'blacklist_item_id': self.restricted_site.id,
            'session_id': self.session.id,
        }, content_type='application/json')
        data = resp.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(AccessRequest.objects.filter(
            child=self.child,
            status=AccessRequest.Status.PENDING).count(), 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.parent).exists())
