from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from note2webapp.models import (
    ModelUpload,
    ModelVersion,
    ModelComment,
    CommentReaction,
    Notification,
)

User = get_user_model()


class CommentReactionNotificationTests(TestCase):
    def setUp(self):
        # uploader = owner of model / comment
        self.uploader = User.objects.create_user(
            username="uploader", password="pass123"
        )
        self.uploader.profile.role = "uploader"
        self.uploader.profile.save()

        # reviewer = reacts to comment
        self.reviewer = User.objects.create_user(
            username="reviewer", password="pass123"
        )
        self.reviewer.profile.role = "reviewer"
        self.reviewer.profile.save()

        # model + version
        self.upload = ModelUpload.objects.create(user=self.uploader, name="Senti")
        self.version = ModelVersion.objects.create(
            upload=self.upload, tag="v1", status="PASS", is_active=True
        )

        # base comment by uploader
        self.comment = ModelComment.objects.create(
            model_version=self.version,
            user=self.uploader,
            content="Nice work",
        )

    def test_cannot_react_to_own_comment(self):
        """
        If a user tries to like their own comment:
        - status 400
        - no CommentReaction created
        - no Notification created
        """
        self.client.login(username="uploader", password="pass123")
        url = reverse("toggle_comment_reaction", args=[self.comment.id])

        resp = self.client.post(url, {"reaction_type": "like"})
        self.assertEqual(resp.status_code, 400)

        self.assertFalse(
            CommentReaction.objects.filter(
                user=self.uploader, comment=self.comment
            ).exists()
        )
        self.assertFalse(Notification.objects.exists())

    def test_like_creates_reaction_and_notification(self):
        """
        When another user likes a comment:
        - CommentReaction is created
        - response contains likes_count = 1
        - Notification is created for the comment owner
        - notification has correct fields & URL in extra
        """
        self.client.login(username="reviewer", password="pass123")
        url = reverse("toggle_comment_reaction", args=[self.comment.id])

        resp = self.client.post(url, {"reaction_type": "like"})
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["likes_count"], 1)
        self.assertEqual(data["dislikes_count"], 0)
        self.assertEqual(data["user_reaction"], "like")

        # reaction exists in DB
        self.assertTrue(
            CommentReaction.objects.filter(
                user=self.reviewer, comment=self.comment, reaction_type="like"
            ).exists()
        )

        # notification created for uploader
        notifs = Notification.objects.filter(user=self.uploader)
        self.assertEqual(notifs.count(), 1)
        n = notifs.first()
        self.assertEqual(n.actor, self.reviewer)
        self.assertIn("liked your comment", n.verb)
        self.assertEqual(n.target_type, "comment")
        self.assertEqual(n.target_id, self.comment.id)

        # URL in extra should be a path and contain the version id
        url = n.extra.get("url", "")
        self.assertTrue(url.startswith("/"))
        self.assertIn(str(self.version.id), url)

    def test_switch_like_to_dislike(self):
        """
        If reviewer first likes and then dislikes,
        reaction_type should be switched to 'dislike', not duplicated.
        """
        self.client.login(username="reviewer", password="pass123")
        url = reverse("toggle_comment_reaction", args=[self.comment.id])

        # first like
        self.client.post(url, {"reaction_type": "like"})
        # then switch to dislike
        self.client.post(url, {"reaction_type": "dislike"})

        reactions = CommentReaction.objects.filter(
            user=self.reviewer, comment=self.comment
        )
        self.assertEqual(reactions.count(), 1)
        self.assertEqual(reactions.first().reaction_type, "dislike")
