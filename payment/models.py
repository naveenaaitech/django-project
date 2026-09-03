from django.db import models
from django.contrib.auth.models import User
from addpro.models import Product
from django.db.models.signals import post_save
import uuid


class ShippingAddress(models.Model):
    """
    Stores customer delivery address.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    shipping_full_name = models.CharField(max_length=255)
    shipping_email = models.CharField(max_length=255)
    shipping_address1 = models.CharField(max_length=255)
    shipping_address2 = models.CharField(max_length=255, null=True, blank=True)
    shipping_city = models.CharField(max_length=255)
    shipping_state = models.CharField(max_length=255, null=True, blank=True)
    shipping_zipcode = models.CharField(max_length=255, null=True, blank=True)
    shipping_country = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "Shipping Address"

    def __str__(self):
        return f"{self.shipping_full_name} ({self.shipping_city}, {self.shipping_country})"


# Create default shipping address when a user registers
def create_shipping(sender, instance, created, **kwargs):
    if created:
        ShippingAddress.objects.create(user=instance)

post_save.connect(create_shipping, sender=User)


# ==============================================================================
# 1. ORDER LIFECYCLE MODEL (E-COMMERCE ORDER)
# ==============================================================================
class Order(models.Model):
    """
    Represents an internal e-commerce order.
    Demonstrates the separation between Order Status (fulfillment lifecycle)
    and Payment Status (financial transaction state).
    """
    ORDER_STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('PAYMENT_PENDING', 'Payment Pending'),
        ('PAID', 'Paid'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('PAYMENT_FAILED', 'Payment Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='orders')
    full_name = models.CharField(max_length=250)
    email = models.EmailField(max_length=250)
    shipping_address = models.TextField(max_length=15000)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, help_text="Total order amount in INR (Decimal)")
    
    # Order Status tracks business/shipping state
    order_status = models.CharField(max_length=30, choices=ORDER_STATUS_CHOICES, default='CREATED')
    
    # Razorpay Order ID links internal Order to external Payment Gateway Order
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    date_ordered = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when payment was successfully verified")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_ordered']

    @property
    def order_code(self):
        """Standardized formatted Order Code for student presentation (e.g., ORD1001)"""
        return f"ORD{self.id:04d}"

    @property
    def amount_in_paise(self):
        """
        Razorpay requires amount in the smallest currency unit (Paise for INR).
        ₹1 = 100 paise -> ₹1,499 = 149,900 paise.
        """
        return int(self.amount_paid * 100)

    def __str__(self):
        return f"{self.order_code} - {self.full_name} ({self.order_status})"


class OrderItem(models.Model):
    """
    Line items belonging to an Order.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveBigIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total_price(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.quantity} x {self.product.name if self.product else 'Item'} in Order #{self.order_id}"


# ==============================================================================
# 2. PAYMENT TRANSACTION MODEL (FINTECH / FINANCIAL LEDGER)
# ==============================================================================
class PaymentTransaction(models.Model):
    """
    Records immutable transaction details for every payment attempt.
    Demonstrates:
    - Gateway Order vs Internal Order
    - Cryptographic Verification Identifiers (Payment ID + Signature)
    - Financial idempotency (preventing duplicate payments)
    - Multi-status transitions: CREATED -> PENDING -> SUCCESS / FAILED -> REFUNDED
    """
    TRANSACTION_STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]

    # Application Transaction Reference (e.g. TXN10001)
    transaction_id = models.CharField(max_length=50, unique=True, db_index=True)
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='transactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions')

    # Razorpay Gateway Identifiers
    razorpay_order_id = models.CharField(max_length=100, db_index=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)

    # Financial details
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount in INR")
    currency = models.CharField(max_length=10, default='INR')
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='CREATED')
    payment_method = models.CharField(max_length=50, blank=True, default='N/A')

    # Failure / Audit details
    error_code = models.CharField(max_length=100, blank=True, null=True)
    error_description = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def amount_in_paise(self):
        return int(self.amount * 100)

    def save(self, *args, **kwargs):
        # Automatically generate readable transaction ID if not set
        if not self.transaction_id:
            last_txn = PaymentTransaction.objects.order_by('-id').first()
            next_num = (last_txn.id + 1) if last_txn else 1
            self.transaction_id = f"TXN{10000 + next_num}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} | {self.order.order_code} | {self.status} | ₹{self.amount}"
