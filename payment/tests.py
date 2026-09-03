import hmac
import hashlib
import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.conf import settings

from addpro.models import Product, Category
from payment.models import Order, OrderItem, PaymentTransaction, ShippingAddress


class FinTechPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student_demo', email='student@example.com', password='password123')
        self.staff_user = User.objects.create_user(username='admin_staff', email='staff@example.com', password='password123', is_staff=True)
        self.category = Category.objects.create(name='Test Category')
        self.product = Product.objects.create(
            name='Test FinTech Phone',
            price=Decimal('1499.00'),
            category=self.category,
            description='Test product for payment demo'
        )
        self.client = Client()
        self.client.login(username='student_demo', password='password123')

    def test_amount_in_paise_conversion(self):
        """
        FinTech Requirement: Ensure monetary amounts are converted accurately
        to smallest currency unit (Paise for INR).
        ₹1,499.00 -> 149900 paise.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St, Bangalore, India',
            amount_paid=Decimal('1499.00'),
            order_status='PAYMENT_PENDING'
        )
        self.assertEqual(order.amount_in_paise, 149900)
        self.assertEqual(order.order_code, f"ORD{order.id:04d}")

    def test_payment_transaction_creation_and_status(self):
        """
        Verify PaymentTransaction model creation, auto-generated transaction IDs,
        and status choices.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('2499.00'),
            order_status='PAYMENT_PENDING'
        )
        txn = PaymentTransaction.objects.create(
            order=order,
            user=self.user,
            razorpay_order_id='order_test_123456',
            amount=Decimal('2499.00'),
            currency='INR',
            status='CREATED'
        )
        self.assertTrue(txn.transaction_id.startswith('TXN'))
        self.assertEqual(txn.amount_in_paise, 249900)
        self.assertEqual(txn.status, 'CREATED')

    def test_cryptographic_signature_verification_and_success_flow(self):
        """
        Simulate Razorpay payment response and verify strict server-side signature verification.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('999.00'),
            order_status='PAYMENT_PENDING',
            razorpay_order_id='order_test_999'
        )
        txn = PaymentTransaction.objects.create(
            order=order,
            user=self.user,
            razorpay_order_id='order_test_999',
            amount=Decimal('999.00'),
            currency='INR',
            status='PENDING'
        )

        # Generate valid HMAC-SHA256 signature
        razorpay_payment_id = 'pay_test_99999'
        payload = f"{order.razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
        valid_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Submit verification request
        response = self.client.post(reverse('payment_verify'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': valid_signature
        })

        self.assertRedirects(response, reverse('payment_success'))

        # Check updated database state
        order.refresh_from_db()
        txn.refresh_from_db()

        self.assertEqual(order.order_status, 'PAID')
        self.assertIsNotNone(order.paid_at)
        self.assertEqual(txn.status, 'SUCCESS')
        self.assertEqual(txn.razorpay_payment_id, razorpay_payment_id)

    def test_invalid_signature_rejection(self):
        """
        Security Test: Ensure tampered or invalid cryptographic signatures are strictly rejected.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('999.00'),
            order_status='PAYMENT_PENDING',
            razorpay_order_id='order_test_invalid_sig'
        )
        txn = PaymentTransaction.objects.create(
            order=order,
            user=self.user,
            razorpay_order_id='order_test_invalid_sig',
            amount=Decimal('999.00'),
            currency='INR',
            status='PENDING'
        )

        # Submit deliberately corrupted signature
        response = self.client.post(reverse('payment_verify'), {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': 'pay_test_tampered',
            'razorpay_signature': 'invalid_forged_signature_hex'
        })

        self.assertRedirects(response, reverse('payment_failed'))

        order.refresh_from_db()
        txn.refresh_from_db()

        self.assertEqual(order.order_status, 'PAYMENT_FAILED')
        self.assertIsNone(order.paid_at)
        self.assertEqual(txn.status, 'FAILED')
        self.assertEqual(txn.error_code, 'SIGNATURE_VERIFICATION_FAILED')

    def test_idempotent_duplicate_payment_protection(self):
        """
        Ensure duplicate payment submissions do not double-process or corrupt state.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('500.00'),
            order_status='PAID',
            razorpay_order_id='order_test_dup'
        )
        txn = PaymentTransaction.objects.create(
            order=order,
            user=self.user,
            razorpay_order_id='order_test_dup',
            razorpay_payment_id='pay_test_dup',
            amount=Decimal('500.00'),
            currency='INR',
            status='SUCCESS'
        )

        # Post again with already successful payment ID
        response = self.client.post(reverse('payment_verify'), {
            'razorpay_order_id': 'order_test_dup',
            'razorpay_payment_id': 'pay_test_dup',
            'razorpay_signature': 'dummy_sig'
        })
        self.assertRedirects(response, reverse('payment_success'))
        self.assertEqual(PaymentTransaction.objects.filter(order=order).count(), 1)

    def test_webhook_signature_and_event_handling(self):
        """
        Test secure Razorpay webhook processing with HMAC signature.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('2000.00'),
            order_status='PAYMENT_PENDING',
            razorpay_order_id='order_test_webhook'
        )
        txn = PaymentTransaction.objects.create(
            order=order,
            user=self.user,
            razorpay_order_id='order_test_webhook',
            amount=Decimal('2000.00'),
            currency='INR',
            status='PENDING'
        )

        webhook_secret = 'test_webhook_secret_key_123'
        with self.settings(RAZORPAY_WEBHOOK_SECRET=webhook_secret):
            event_body = json.dumps({
                'event': 'payment.captured',
                'payload': {
                    'payment': {
                        'entity': {
                            'id': 'pay_test_webhook_999',
                            'order_id': 'order_test_webhook',
                            'amount': 200000,
                            'status': 'captured',
                            'method': 'upi'
                        }
                    }
                }
            })

            # Calculate webhook HMAC signature
            sig = hmac.new(
                webhook_secret.encode('utf-8'),
                event_body.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            response = self.client.post(
                reverse('razorpay_webhook'),
                data=event_body,
                content_type='application/json',
                HTTP_X_RAZORPAY_SIGNATURE=sig
            )

            self.assertEqual(response.status_code, 200)

            order.refresh_from_db()
            txn.refresh_from_db()

            self.assertEqual(order.order_status, 'PAID')
            self.assertIsNotNone(order.paid_at)
            self.assertEqual(txn.status, 'SUCCESS')
            self.assertEqual(txn.razorpay_payment_id, 'pay_test_webhook_999')

    def test_process_cod_flow(self):
        """
        Verify Cash on Delivery (COD) order placement.
        """
        order = Order.objects.create(
            user=self.user,
            full_name='Test Student',
            email='student@example.com',
            shipping_address='123 Main St',
            amount_paid=Decimal('1500.00'),
            order_status='PAYMENT_PENDING'
        )
        response = self.client.post(reverse('process_cod'), {
            'order_id': order.id
        })
        self.assertRedirects(response, reverse('payment_success'))

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'PROCESSING')
        self.assertTrue(PaymentTransaction.objects.filter(order=order, payment_method='Cash on Delivery (COD)').exists())

    def test_admin_dashboard_access_control(self):
        """
        Verify staff access control on Admin Operations Dashboard.
        """
        # Non-staff client redirected
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)

        # Staff client allowed
        staff_client = Client()
        staff_client.login(username='admin_staff', password='password123')
        staff_response = staff_client.get(reverse('admin_dashboard'))
        self.assertEqual(staff_response.status_code, 200)
        self.assertContains(staff_response, 'FinPay Admin Operations Dashboard')
