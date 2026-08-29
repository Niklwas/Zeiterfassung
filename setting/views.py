from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Notification

from django.http import JsonResponse

@login_required
def notifications(request):

    user_notifications = Notification.objects.filter(
        user=request.user
    )

    return render(
        request,
        "setting/notifications.html",
        {
            "notifications": user_notifications,
        },
    )


@login_required
def notification_read(
    request,
    notification_id
):

    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user,
    )

    notification.is_read = True

    notification.save(
        update_fields=["is_read"]
    )

    if notification.url:
        return redirect(notification.url)

    return redirect("notifications")


@login_required
def notification_delete(
    request,
    notification_id
):

    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user,
    )

    if request.method == "POST":
        notification.delete()

    return redirect("notifications")


@login_required
def notifications_mark_all_read(
    request
):

    if request.method == "POST":

        Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(
            is_read=True
        )

    return redirect("notifications")


@login_required
def notifications_delete_all(
    request
):

    if request.method == "POST":

        Notification.objects.filter(
            user=request.user
        ).delete()

    return redirect("notifications")


def health(request):
    return JsonResponse({
        "status": "ok"
    })