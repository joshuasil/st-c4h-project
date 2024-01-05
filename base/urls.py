from django.urls import path
from django.urls import path, reverse_lazy
from django.views.generic import RedirectView

from . import views

# urls.py
from django.urls import path

def trigger_error(request):
    division_by_zero = 1 / 0


urlpatterns = [
    path("", RedirectView.as_view(url=reverse_lazy('admin:login')), name="index"),
    path('inbound_message', views.inbound_message, name="inbound_message"),
]
