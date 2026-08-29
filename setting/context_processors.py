from core.models import Notification

#general_settings
from zoneinfo import ZoneInfo
from .models import GeneralSettings


def notifications(request):

    if not request.user.is_authenticated:
        return {
            "notifications": [],
            "unread_notifications_count": 0,
        }

    user_notifications = Notification.objects.filter(
        user=request.user
    )[:5]

    unread_count = Notification.objects.filter(
        user=request.user,
        is_read=False
    ).count()

    return {
        "notifications": user_notifications,
        "unread_notifications_count": unread_count,
    }


def general_settings(request):

    settings = GeneralSettings.get_solo()

    return {
        "general_settings": settings,
        "application_timezone": ZoneInfo(
            settings.timezone
        ),
    }