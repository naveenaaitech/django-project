from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import ShippingAddress, Order, OrderItem, PaymentTransaction


@admin.register(ShippingAddress)
class ShippingAddressAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'shipping_full_name', 'shipping_city', 'shipping_country')
    search_fields = ('shipping_full_name', 'shipping_email', 'shipping_city', 'shipping_country')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'price', 'total_price')
    can_delete = False


class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    extra = 0
    readonly_fields = ('transaction_id', 'payment_method', 'razorpay_order_id', 'razorpay_payment_id', 'amount', 'currency', 'status', 'created_at')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_code_display',
        'user',
        'full_name',
        'amount_paid_display',
        'payment_method_display',
        'payment_proof_display',
        'status_badge',
        'date_ordered'
    )
    list_filter = ('order_status', 'date_ordered')
    search_fields = ('id', 'full_name', 'email', 'razorpay_order_id', 'user__username')
    readonly_fields = ('order_code', 'razorpay_order_id', 'date_ordered', 'updated_at')
    inlines = [OrderItemInline, PaymentTransactionInline]

    fieldsets = (
        ('Order Identification', {
            'fields': ('order_code', 'user', 'order_status')
        }),
        ('Customer & Shipping Information', {
            'fields': ('full_name', 'email', 'shipping_address')
        }),
        ('Payment Gateway Link', {
            'fields': ('amount_paid', 'razorpay_order_id')
        }),
        ('Timestamps', {
            'fields': ('date_ordered', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def order_code_display(self, obj):
        return obj.order_code
    order_code_display.short_description = "Order ID"

    def amount_paid_display(self, obj):
        return f"₹{obj.amount_paid}"
    amount_paid_display.short_description = "Amount"

    def payment_method_display(self, obj):
        txn = obj.transactions.first()
        if txn:
            return txn.payment_method
        return "Not Selected"
    payment_method_display.short_description = "Method"

    def payment_proof_display(self, obj):
        txn = obj.transactions.first()
        if txn and txn.razorpay_payment_id:
            return format_html('<code style="color: #0369a1; font-weight: bold;">{}</code>', txn.razorpay_payment_id)
        elif txn and txn.status == 'SUCCESS':
            return format_html('<span style="color: green; font-weight: bold;">✓ Verified</span>')
        elif obj.order_status == 'PROCESSING':
            return format_html('<span style="color: #b45309;">💵 Pay on Delivery</span>')
        return format_html('<span style="color: #9ca3af;">Pending</span>')
    payment_proof_display.short_description = "Gateway Proof / Txn ID"

    def status_badge(self, obj):
        color_map = {
            'PAID': 'background-color: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'PAYMENT_PENDING': 'background-color: #ffc107; color: black; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'PAYMENT_FAILED': 'background-color: #dc3545; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'CREATED': 'background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px;',
            'PROCESSING': 'background-color: #17a2b8; color: white; padding: 4px 10px; border-radius: 4px;',
            'SHIPPED': 'background-color: #007bff; color: white; padding: 4px 10px; border-radius: 4px;',
            'DELIVERED': 'background-color: #20c997; color: white; padding: 4px 10px; border-radius: 4px;',
            'CANCELLED': 'background-color: #343a40; color: white; padding: 4px 10px; border-radius: 4px;',
        }
        style = color_map.get(obj.order_status, 'background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px;')
        return format_html('<span style="{}">{}</span>', style, obj.get_order_status_display())
    status_badge.short_description = "Order Status"


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'order_link',
        'user',
        'amount_display',
        'status_badge',
        'payment_method',
        'razorpay_payment_id',
        'created_at',
        'refund_action_button'
    )
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('transaction_id', 'order__id', 'razorpay_order_id', 'razorpay_payment_id', 'user__username')
    
    readonly_fields = (
        'transaction_id',
        'order',
        'user',
        'razorpay_order_id',
        'razorpay_payment_id',
        'razorpay_signature',
        'amount',
        'currency',
        'created_at',
        'updated_at'
    )

    def amount_display(self, obj):
        return f"₹{obj.amount}"
    amount_display.short_description = "Amount"

    def order_link(self, obj):
        url = reverse('admin:payment_order_change', args=[obj.order.id])
        return format_html('<a href="{}"><strong>{}</strong></a>', url, obj.order.order_code)
    order_link.short_description = "Order"

    def status_badge(self, obj):
        color_map = {
            'SUCCESS': 'background-color: #28a745; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'PENDING': 'background-color: #ffc107; color: black; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'FAILED': 'background-color: #dc3545; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
            'CREATED': 'background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px;',
            'REFUNDED': 'background-color: #6f42c1; color: white; padding: 4px 10px; border-radius: 4px; font-weight: bold;',
        }
        style = color_map.get(obj.status, 'background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 4px;')
        return format_html('<span style="{}">{}</span>', style, obj.status)
    status_badge.short_description = "Status"

    def refund_action_button(self, obj):
        if obj.status == 'SUCCESS':
            refund_url = reverse('admin_refund', args=[obj.id])
            return format_html(
                '<a class="button" style="background-color: #dc3545; color: white; padding: 4px 8px; border-radius: 4px; text-decoration: none;" '
                'href="{}" onclick="return confirm(\'Issue test refund for this transaction?\')">Issue Refund</a>',
                refund_url
            )
        return "-"
    refund_action_button.short_description = "Test Refund"
