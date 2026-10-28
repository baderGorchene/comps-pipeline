from django.urls import path

from web import views

urlpatterns = [
    path("", views.new_run, name="new_run"),
    path("runs/", views.history, name="history"),
    path("runs/<str:run_id>/", views.results, name="results"),
    path("runs/<str:run_id>/files/<str:name>", views.download, name="download"),
]
