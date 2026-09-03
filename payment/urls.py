from django.urls import path
from . import views

urlpatterns = [
    path('', views.checkout, name='payment_home'),
    path('checkout/', views.checkout, name='checkout'),
    path('billing_info/', views.billing_info, name='billing_info'),
    path('process_cod/', views.process_cod, name='process_cod'),
    path('verify/', views.payment_verify, name='payment_verify'),
    path('failed/', views.payment_failed, name='payment_failed'),
    path('success/', views.payment_success, name='payment_success'),
    path('payment_success/', views.payment_success, name='payment_success_alias'),
    path('dashboard/', views.customer_dashboard, name='customer_dashboard'),
    path('history/', views.payment_history, name='payment_history'),
    path('transaction/<str:transaction_id>/', views.transaction_detail, name='transaction_detail'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('update-order-status/', views.update_order_status, name='update_order_status'),
    path('webhook/', views.razorpay_webhook, name='razorpay_webhook'),
    path('admin/refund/<int:transaction_id>/', views.admin_refund, name='admin_refund'),
]
