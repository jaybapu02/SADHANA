from django.db import models
from django.conf import settings


class Conversation(models.Model):
    """A private chat between exactly one linked Parent and one Child.
    Existence of a Conversation implies an ACCEPTED parent-child connection."""

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_conversations_as_parent',
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_conversations_as_child',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_message_at']
        unique_together = ('parent', 'child')

    def __str__(self):
        return f"{self.parent.username} <-> {self.child.username}"

    def participants(self):
        return [self.parent, self.child]

    def is_participant(self, user):
        return user.id in (self.parent_id, self.child_id)

    def other_participant(self, user):
        if user.id == self.parent_id:
            return self.child
        if user.id == self.child_id:
            return self.parent
        return None


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_chat_messages',
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_chat_messages',
    )
    text = models.TextField(max_length=2000, blank=True)
    parent_msg = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    attachment = models.FileField(
        upload_to='chat_files/%Y/%m/',
        null=True,
        blank=True,
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    attachment_type = models.CharField(max_length=10, blank=True)  # image | pdf
    is_read = models.BooleanField(default=False)
    is_delivered = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username}: {self.text[:40]}"

    @classmethod
    def unread_count_for(cls, user):
        return cls.objects.filter(receiver=user, is_read=False).count()

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])