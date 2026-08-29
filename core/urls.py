from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("main/", views.main_view, name="main"),
    path("ein/", views.einstempeln, name="ein"),
    path("aus/", views.ausstempeln, name="aus"),

    path("monat/", views.monat_view, name="monat"),
    path("monat/<int:year>/<int:month>/", views.monat_view, name="monat"),

    path("jahr/", views.jahr_view, name="jahr"),
    path("jahr/<int:year>/", views.jahr_view, name="jahr"),
    path("logout/", views.logout_view, name="logout"), 
    path("monat/<int:year>/<int:month>/pdf/", views.monat_pdf, name="monat_pdf"),
    path("urlaub/", views.urlaub_buchen, name="urlaub_buchen"),
    path("clockin/", views.clockin_view, name="clockin"),
    path("genehmigung",views.urlaub_genehmigen, name="urlaub_genehmigen"),
    path("jahr/<int:year>/pdf/", views.jahr_pdf, name="jahr_pdf"),
]
