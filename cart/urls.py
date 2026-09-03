from django.urls import path
from . import views

urlpatterns = [
    path('', views.cart_summary, name="cart_summary"),
    path('summary/', views.cart_summary, name="cart_summary_alias"),
    path('add/<int:id>/', views.cart_add, name="cart_add"),
    path('increment/<int:id>/', views.cart_increment, name="cart_increment"),
    path('decrement/<int:id>/', views.cart_decrement, name="cart_decrement"),
    path('remove/<int:id>/', views.cart_remove, name="cart_remove"),
    path('delete/', views.cart_delete, name="cart_delete"),
    path('update/', views.cart_update, name="cart_update"),
]
