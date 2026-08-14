from django.urls import path

from .views import DisagreementListView, OrgListView

urlpatterns = [
    path("orgs/", OrgListView.as_view(), name="org-list"),
    path("disagreements/", DisagreementListView.as_view(), name="disagreement-list"),
]
