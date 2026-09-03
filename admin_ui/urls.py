from django.contrib.auth import views as auth_views
from django.urls import path

from admin_ui import views

app_name = "admin_ui"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="admin_ui/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.collection_list, name="collection_list"),
    path("collections/new/", views.collection_create, name="collection_create"),
    path("collections/<int:pk>/", views.collection_detail, name="collection_detail"),
    path("collections/<int:pk>/mint/", views.mint_view, name="mint"),
    path("collections/<int:pk>/mint/template.csv", views.mint_template, name="mint_template"),
    path("collections/<int:pk>/bulk-bind/", views.bulk_bind, name="bulk_bind"),
    path("arks/", views.ark_list, name="ark_list"),
    path("arks/<int:pk>/", views.ark_detail, name="ark_detail"),
    path("arks/<int:pk>/purge/", views.ark_purge, name="ark_purge"),
    path("export.csv", views.export, name="export"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<int:pk>/results.csv", views.job_results, name="job_results"),
    path("users/", views.user_list, name="user_list"),
]
