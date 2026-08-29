from django.urls import path

from . import views
from .views import health


urlpatterns = [

    path(
        "notifications/",
        views.notifications,
        name="notifications",
    ),

    path(
        "notifications/<int:notification_id>/",
        views.notification_read,
        name="notification_read",
    ),

    path(
        "notifications/<int:notification_id>/delete/",
        views.notification_delete,
        name="notification_delete",
    ),

    path(
        "notifications/mark-all-read/",
        views.notifications_mark_all_read,
        name="notifications_mark_all_read",
    ),

    path(
        "notifications/delete-all/",
        views.notifications_delete_all,
        name="notifications_delete_all",
    ),

    path("health/", health),

]