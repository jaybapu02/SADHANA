from django.urls import reverse

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Notification

User = get_user_model()


class NotificationAPITestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.parent = User.objects.create_user(username='parent1', password='testpass123', role='PARENT')
        cls.child = User.objects.create_user(username='child1', password='testpass123', role='CHILD')
        cls.notif_unread = Notification.objects.create(
            recipient=cls.parent,
            sender=cls.child,
            sender_name='child1',
            notification_type='TASK_ASSIGNED',
            message='Test unread notification',
        )
        cls.notif_read = Notification.objects.create(
            recipient=cls.parent,
            sender=cls.child,
            sender_name='child1',
            notification_type='TASK_ASSIGNED',
            message='Test read notification',
            is_read=True,
        )

    def login(self, user):
        self.client.force_login(user)


class DeleteNotificationAPITests(NotificationAPITestBase):
    def test_delete_via_delete_method(self):
        self.login(self.parent)
        resp = self.client.delete(reverse('api_delete_notification', args=[self.notif_unread.id]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['deleted_id'], self.notif_unread.id)
        self.assertTrue(data['was_unread'])
        self.assertEqual(data['unread_count'], 0)
        self.assertFalse(Notification.objects.filter(id=self.notif_unread.id).exists())

    def test_delete_via_post_method(self):
        self.login(self.parent)
        resp = self.client.post(reverse('api_delete_notification', args=[self.notif_read.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'ok')
        self.assertFalse(Notification.objects.filter(id=self.notif_read.id).exists())

    def test_delete_updates_unread_count(self):
        extra = Notification.objects.create(
            recipient=self.parent, sender=self.child, sender_name='child1',
            notification_type='APPRECIATION', message='Another unread',
        )
        self.login(self.parent)
        resp = self.client.post(reverse('api_delete_notification', args=[extra.id]))
        self.assertEqual(resp.json()['unread_count'], 1)  # only notif_unread remains

    def test_delete_other_users_notification_returns_404_json(self):
        self.login(self.child)
        resp = self.client.post(reverse('api_delete_notification', args=[self.notif_unread.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['status'], 'error')
        # Must NOT be deleted.
        self.assertTrue(Notification.objects.filter(id=self.notif_unread.id).exists())

    def test_delete_missing_notification_returns_404_json(self):
        self.login(self.parent)
        resp = self.client.post(reverse('api_delete_notification', args=[99999]))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['status'], 'error')

    def test_delete_requires_login(self):
        resp = self.client.post(reverse('api_delete_notification', args=[self.notif_unread.id]))
        self.assertEqual(resp.status_code, 302)

    def test_get_method_not_allowed(self):
        self.login(self.parent)
        resp = self.client.get(reverse('api_delete_notification', args=[self.notif_unread.id]))
        self.assertEqual(resp.status_code, 405)

    def test_double_delete_is_graceful(self):
        self.login(self.parent)
        first = self.client.post(reverse('api_delete_notification', args=[self.notif_unread.id]))
        second = self.client.post(reverse('api_delete_notification', args=[self.notif_unread.id]))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 404)


class MarkReadAPITests(NotificationAPITestBase):
    def test_mark_read_returns_unread_count(self):
        self.login(self.parent)
        resp = self.client.post(reverse('api_mark_read', args=[self.notif_unread.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 0)
        self.notif_unread.refresh_from_db()
        self.assertTrue(self.notif_unread.is_read)

    def test_mark_all_read(self):
        self.login(self.parent)
        resp = self.client.post(reverse('api_mark_all_read'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['unread_count'], 0)


class UnreadCountAndListTests(NotificationAPITestBase):
    def test_api_unread_count(self):
        self.login(self.parent)
        resp = self.client.get(reverse('api_unread_count'))
        self.assertEqual(resp.json()['unread_count'], 1)

    def test_api_notifications_scoped_to_recipient(self):
        self.login(self.child)
        resp = self.client.get(reverse('api_notifications'))
        self.assertEqual(resp.json()['count'], 0)

    def test_notification_list_page_renders(self):
        self.login(self.parent)
        resp = self.client.get(reverse('notification_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['unread_count'], 1)
