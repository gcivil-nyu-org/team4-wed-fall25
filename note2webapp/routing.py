from django.urls import re_path
from . import consumer

websocket_urlpatterns = [
    re_path(
        r"ws/model/(?P<version_id>\d+)/comments/$",
        consumer.ModelCommentConsumer.as_asgi(),
    ),
]
