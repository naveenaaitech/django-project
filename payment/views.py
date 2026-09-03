import hmac
import hashlib
import json
import uuid
import logging
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.db.models import Sum, Count, Q
from django.utils import timezone

import razorpay

from .models import ShippingAddress, Order, OrderItem, PaymentTransaction
from .forms import ShippingForm
from cart.cart import Cart
from addpro.models import Product

logger = logging.getLogger('payment')


def get_razorpay_client():
    """
    Initializes and returns the Razorpay client using configured credentials.
    Supports both RAZORPAY_KEY_ID=rzp_test_... and rzp_live_...
    """
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


# ==============================================================================
# 1. CHECKOUT VIEW
# ==============================================================================
@login_required(login_url='login')
def checkout(request):
    cart = Cart(request)

    if len(cart.cart) == 0:
        messages.warning(request, "Your cart is empty. Add products before checkout.")
        return redirect('cart_summary')

    shipping_user, created = ShippingAddress.objects.get_or_create(user=request.user)
    shipping_form = ShippingForm(request.POST or None, instance=shipping_user)

    if request.method == "POST":
        if shipping_form.is_valid():
            shipping_instance = shipping_form.save()

            shipping_address_text = (
                f"{shipping_instance.shipping_address1}, "
                f"{shipping_instance.shipping_address2 + ', ' if shipping_instance.shipping_address2 else ''}"
                f"{shipping_instance.shipping_city}, {shipping_instance.shipping_state or ''} "
                f"{shipping_instance.shipping_zipcode or ''}, {shipping_instance.shipping_country}"
            )

            # Server-side amount computation directly from active cart
            total_amount = Decimal(str(cart.cart_total()))

            order_id = request.session.get('active_order_id')
            order = None
            if order_id:
                order = Order.objects.filter(
                    id=order_id, 
                    user=request.user, 
                    order_status__in=['CREATED', 'PAYMENT_PENDING', 'PAYMENT_FAILED']
                ).first()

            if not order:
                order = Order.objects.create(
                    user=request.user,
                    full_name=shipping_instance.shipping_full_name,
                    email=shipping_instance.shipping_email or request.user.email,
                    shipping_address=shipping_address_text,
                    amount_paid=total_amount,
                    order_status='PAYMENT_PENDING'
                )
            else:
                order.full_name = shipping_instance.shipping_full_name
                order.email = shipping_instance.shipping_email or request.user.email
                order.shipping_address = shipping_address_text
                order.amount_paid = total_amount
                order.order_status = 'PAYMENT_PENDING'
                order.save()

            # Synchronize line items
            order.items.all().delete()
            for prod_id, qty in cart.cart.items():
                try:
                    product = Product.objects.get(id=int(prod_id))
                    price = product.sale_price if product.is_sale else product.price
                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        user=request.user,
                        quantity=qty,
                        price=price
                    )
                except Product.DoesNotExist:
                    continue

            request.session['active_order_id'] = order.id
            return redirect('billing_info')

    return render(request, 'checkout.html', {
        'cart_products': cart.get_prods,
        'quantities': cart.get_quants,
        'totals': cart.cart_total(),
        'shipping_form': shipping_form,
    })


# ==============================================================================
# 2. BILLING & PAYMENT VIEW
# ==============================================================================
@login_required(login_url='login')
def billing_info(request):
    cart = Cart(request)
    order_id = request.session.get('active_order_id') or request.GET.get('order_id')
    
    order = None
    if order_id:
        order = Order.objects.filter(id=order_id, user=request.user).first()

    if not order:
        messages.error(request, "No active order found. Please proceed from checkout.")
        return redirect('checkout')

    if order.order_status == 'PAID':
        messages.info(request, f"Order {order.order_code} has already been paid.")
        return redirect('payment_success')

    # Convert to smallest currency unit (paise for INR)
    amount_in_paise = order.amount_in_paise

    client = get_razorpay_client()
    razorpay_order_id = ""

    try:
        razorpay_order = client.order.create(data={
            'amount': int(amount_in_paise),
            'currency': settings.RAZORPAY_CURRENCY,
            'payment_capture': 1,
            'notes': {
                'ecommerce_order_code': order.order_code,
                'customer_email': order.email,
                'customer_name': order.full_name,
            }
        })
        razorpay_order_id = razorpay_order['id']
        logger.info(f"Created Razorpay Order {razorpay_order_id} for Django Order {order.order_code}")
    except Exception as e:
        logger.error(f"Error creating Razorpay gateway order for {order.order_code}: {e}")
        razorpay_order_id = ""

    if razorpay_order_id:
        order.razorpay_order_id = razorpay_order_id
        order.save()

    transaction = PaymentTransaction.objects.filter(order=order).first()
    if not transaction:
        transaction = PaymentTransaction.objects.create(
            order=order,
            user=request.user,
            razorpay_order_id=razorpay_order_id,
            amount=order.amount_paid,
            currency=settings.RAZORPAY_CURRENCY,
            status='CREATED'
        )
    else:
        transaction.razorpay_order_id = razorpay_order_id
        transaction.amount = order.amount_paid
        transaction.save()

    context = {
        'order': order,
        'transaction': transaction,
        'cart_products': cart.get_prods,
        'quantities': cart.get_quants,
        'totals': order.amount_paid,
        'amount_in_paise': amount_in_paise,
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'razorpay_order_id': razorpay_order_id,
        'currency': settings.RAZORPAY_CURRENCY,
        'user': request.user,
    }

    return render(request, 'billing_info.html', context)


# ==============================================================================
# 2B. CASH ON DELIVERY (COD) HANDLER
# ==============================================================================
@login_required(login_url='login')
def process_cod(request):
    if request.method != "POST":
        return redirect('checkout')

    order_id = request.session.get('active_order_id') or request.POST.get('order_id')
    order = get_object_or_404(Order, id=order_id, user=request.user)

    order.order_status = 'PROCESSING'
    order.save()

    txn_id = f"TXN-COD-{uuid.uuid4().hex[:8].upper()}"
    transaction = PaymentTransaction.objects.filter(order=order).first()

    if not transaction:
        transaction = PaymentTransaction.objects.create(
            order=order,
            user=request.user,
            transaction_id=txn_id,
            razorpay_order_id=f"COD_{order.order_code}",
            amount=order.amount_paid,
            currency=settings.RAZORPAY_CURRENCY,
            status='PENDING',
            payment_method='Cash on Delivery (COD)'
        )
    else:
        transaction.payment_method = 'Cash on Delivery (COD)'
        transaction.status = 'PENDING'
        transaction.save()

    cart = Cart(request)
    cart.clear()
    if 'active_order_id' in request.session:
        del request.session['active_order_id']

    request.session['last_transaction_id'] = transaction.transaction_id
    messages.success(request, f"Order {order.order_code} placed successfully via Cash on Delivery!")
    return redirect('payment_success')


# ==============================================================================
# 3. SERVER-SIDE PAYMENT SIGNATURE VERIFICATION
# ==============================================================================
@login_required(login_url='login')
def payment_verify(request):
    if request.method != "POST":
        messages.error(request, "Invalid request method for payment verification.")
        return redirect('home')

    razorpay_order_id = request.POST.get('razorpay_order_id', '').strip()
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    razorpay_signature = request.POST.get('razorpay_signature', '').strip()
    selected_method = request.POST.get('payment_method', 'Razorpay Online (UPI/Cards)')

    if not razorpay_order_id or not razorpay_payment_id:
        messages.error(request, "Missing payment verification parameters.")
        return redirect('checkout')

    # Security check: Ensure order belongs to currently authenticated user
    order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id, user=request.user)
    transaction = PaymentTransaction.objects.filter(order=order).first()

    if not transaction:
        transaction = PaymentTransaction.objects.create(
            order=order,
            user=request.user,
            razorpay_order_id=razorpay_order_id,
            amount=order.amount_paid,
            currency=settings.RAZORPAY_CURRENCY,
            status='PENDING'
        )

    # Idempotency check: prevent duplicate confirmation
    if transaction.status == 'SUCCESS' and transaction.razorpay_payment_id == razorpay_payment_id:
        messages.info(request, "This payment has already been verified.")
        return redirect('payment_success')

    is_signature_valid = False
    client = get_razorpay_client()
    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }

    # Strict Server-Side Cryptographic Signature Verification
    try:
        # 1. Primary: Verify via Razorpay SDK utility
        client.utility.verify_payment_signature(params_dict)
        is_signature_valid = True
    except razorpay.errors.SignatureVerificationError:
        logger.warning(f"Razorpay SDK signature verification failed for Order {order.order_code}")
        is_signature_valid = False
    except Exception as sig_err:
        # 2. Secondary fallback: Constant-time direct HMAC comparison
        try:
            msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
            generated_sig = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
                msg,
                hashlib.sha256
            ).hexdigest()
            is_signature_valid = hmac.compare_digest(generated_sig, razorpay_signature)
        except Exception as hmac_err:
            logger.error(f"HMAC calculation error for Order {order.order_code}: {hmac_err}")
            is_signature_valid = False

    if is_signature_valid:
        transaction.razorpay_payment_id = razorpay_payment_id
        transaction.razorpay_signature = razorpay_signature
        transaction.payment_method = selected_method
        transaction.status = 'SUCCESS'
        transaction.error_code = None
        transaction.error_description = None
        transaction.save()

        order.order_status = 'PAID'
        order.paid_at = timezone.now()
        order.save()

        # Clear shopping cart on verified successful payment
        cart = Cart(request)
        cart.clear()
        if 'active_order_id' in request.session:
            del request.session['active_order_id']

        request.session['last_transaction_id'] = transaction.transaction_id
        logger.info(f"Payment SUCCESS for Order {order.order_code} (Payment ID: {razorpay_payment_id})")
        messages.success(request, "Payment verified and completed successfully!")
        return redirect('payment_success')

    else:
        transaction.razorpay_payment_id = razorpay_payment_id
        transaction.razorpay_signature = razorpay_signature
        transaction.status = 'FAILED'
        transaction.error_code = 'SIGNATURE_VERIFICATION_FAILED'
        transaction.error_description = 'Cryptographic signature mismatch. Possible payload tampering detected.'
        transaction.save()

        order.order_status = 'PAYMENT_FAILED'
        order.save()

        logger.warning(f"Payment SIGNATURE_VERIFICATION_FAILED for Order {order.order_code}")
        messages.error(request, "Payment signature verification failed. The transaction was marked as FAILED.")
        return redirect('payment_failed')


# ==============================================================================
# 4. PAYMENT FAILED VIEW
# ==============================================================================
def payment_failed(request):
    if request.method == "POST":
        razorpay_order_id = request.POST.get('razorpay_order_id')
        error_code = request.POST.get('error_code', 'BAD_REQUEST_ERROR')
        error_desc = request.POST.get('error_description', 'Payment cancelled or declined by customer.')
        razorpay_payment_id = request.POST.get('razorpay_payment_id', '')

        if razorpay_order_id:
            order = Order.objects.filter(razorpay_order_id=razorpay_order_id).first()
            if order:
                order.order_status = 'PAYMENT_FAILED'
                order.save()

                transaction = PaymentTransaction.objects.filter(order=order).first()
                if transaction:
                    transaction.status = 'FAILED'
                    transaction.razorpay_payment_id = razorpay_payment_id or transaction.razorpay_payment_id
                    transaction.error_code = error_code
                    transaction.error_description = error_desc
                    transaction.save()
                logger.info(f"Order {order.order_code} marked PAYMENT_FAILED: {error_code} - {error_desc}")

    order_id = request.session.get('active_order_id') or request.GET.get('order_id')
    order = None
    transaction = None
    if order_id and request.user.is_authenticated:
        order = Order.objects.filter(id=order_id, user=request.user).first()
        if order:
            transaction = order.transactions.first()

    return render(request, 'payment_failed.html', {
        'order': order,
        'transaction': transaction,
    })


# ==============================================================================
# 5. PAYMENT SUCCESS VIEW
# ==============================================================================
@login_required(login_url='login')
def payment_success(request):
    txn_id = request.session.get('last_transaction_id') or request.GET.get('txn_id')
    transaction = None
    order = None

    if txn_id:
        transaction = PaymentTransaction.objects.filter(transaction_id=txn_id, user=request.user).first()
        if transaction:
            order = transaction.order

    if not order:
        order = Order.objects.filter(user=request.user).order_by('-date_ordered').first()
        if order:
            transaction = order.transactions.first()

    return render(request, 'payment_success.html', {
        'order': order,
        'transaction': transaction,
    })


# ==============================================================================
# 6. CUSTOMER DASHBOARD & ORDER HISTORY
# ==============================================================================
@login_required(login_url='login')
def customer_dashboard(request):
    user_orders = Order.objects.filter(user=request.user).order_by('-date_ordered')
    user_txns = PaymentTransaction.objects.filter(user=request.user).select_related('order').order_by('-created_at')

    total_orders_count = user_orders.count()
    successful_count = user_orders.filter(order_status='PAID').count()
    pending_count = user_orders.filter(order_status__in=['CREATED', 'PAYMENT_PENDING', 'PROCESSING']).count()
    failed_count = user_orders.filter(order_status='PAYMENT_FAILED').count()
    total_spent = user_txns.filter(status='SUCCESS').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    shipping_address = ShippingAddress.objects.filter(user=request.user).first()
    wishlist = request.session.get('wishlist', [])
    wishlist_count = len(wishlist)

    context = {
        'total_orders_count': total_orders_count,
        'successful_count': successful_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'total_spent': total_spent,
        'wishlist_count': wishlist_count,
        'recent_orders': user_orders[:5],
        'all_orders': user_orders,
        'transactions': user_txns,
        'shipping_address': shipping_address,
    }
    return render(request, 'payment_history.html', context)


@login_required(login_url='login')
def payment_history(request):
    return customer_dashboard(request)


# ==============================================================================
# 7. TRANSACTION DETAIL VIEW
# ==============================================================================
@login_required(login_url='login')
def transaction_detail(request, transaction_id):
    transaction = get_object_or_404(PaymentTransaction, transaction_id=transaction_id, user=request.user)
    order = transaction.order

    return render(request, 'transaction_detail.html', {
        'transaction': transaction,
        'order': order,
        'order_items': order.items.all(),
    })


# ==============================================================================
# 8. ADMIN DASHBOARD & STATUS MANAGEMENT
# ==============================================================================
@user_passes_test(lambda u: u.is_staff, login_url='login')
def admin_dashboard(request):
    all_orders = Order.objects.all().select_related('user').order_by('-date_ordered')
    all_txns = PaymentTransaction.objects.all().select_related('order', 'user').order_by('-created_at')

    total_revenue = all_txns.filter(status='SUCCESS').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_orders = all_orders.count()
    successful_orders = all_txns.filter(status='SUCCESS').count()
    failed_orders = all_txns.filter(status='FAILED').count()
    pending_orders = all_txns.filter(status__in=['CREATED', 'PENDING']).count()
    refund_requests = all_txns.filter(status='REFUNDED').count()

    context = {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'successful_orders': successful_orders,
        'failed_orders': failed_orders,
        'pending_orders': pending_orders,
        'refund_requests': refund_requests,
        'orders': all_orders[:15],
        'transactions': all_txns[:15],
        'status_choices': Order.ORDER_STATUS_CHOICES,
    }
    return render(request, 'admin_dashboard.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='login')
def update_order_status(request):
    if request.method == "POST":
        order_id = request.POST.get('order_id')
        new_status = request.POST.get('order_status')

        if order_id and new_status:
            order = Order.objects.filter(id=order_id).first()
            if order:
                order.order_status = new_status
                if new_status == 'PAID' and not order.paid_at:
                    order.paid_at = timezone.now()
                order.save()

                if new_status == 'PAID':
                    PaymentTransaction.objects.filter(order=order).update(status='SUCCESS')
                elif new_status == 'CANCELLED':
                    PaymentTransaction.objects.filter(order=order).update(status='REFUNDED')

                messages.success(request, f"Order {order.order_code} status updated to {new_status}!")

        return redirect('admin_dashboard')

    return HttpResponseBadRequest("Invalid request method.")


# ==============================================================================
# 9. RAZORPAY SECURE WEBHOOK HANDLER
# ==============================================================================
@csrf_exempt
def razorpay_webhook(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST method allowed for webhooks.")

    webhook_signature = request.headers.get('X-Razorpay-Signature', '')
    webhook_body = request.body.decode('utf-8')

    if not webhook_signature:
        logger.warning("Webhook received without X-Razorpay-Signature header.")
        return JsonResponse({'status': 'missing signature'}, status=400)

    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not configured in settings.")
        return JsonResponse({'status': 'webhook secret unconfigured'}, status=500)

    client = get_razorpay_client()
    try:
        client.utility.verify_webhook_signature(webhook_body, webhook_signature, webhook_secret)
    except razorpay.errors.SignatureVerificationError:
        logger.warning("Webhook signature verification failed.")
        return JsonResponse({'status': 'invalid signature'}, status=400)
    except Exception as e:
        logger.error(f"Webhook verification error: {e}")
        return JsonResponse({'status': 'verification error'}, status=400)

    try:
        event_data = json.loads(webhook_body)
        event_type = event_data.get('event')
        payload = event_data.get('payload', {})

        if event_type in ['payment.captured', 'order.paid']:
            payment_entity = payload.get('payment', {}).get('entity', {})
            rzp_order_id = payment_entity.get('order_id')
            rzp_payment_id = payment_entity.get('id')
            payment_method = payment_entity.get('method', 'Razorpay Online')

            if rzp_order_id:
                order = Order.objects.filter(razorpay_order_id=rzp_order_id).first()
                if order:
                    if order.order_status != 'PAID':
                        order.order_status = 'PAID'
                        order.paid_at = timezone.now()
                        order.save()

                    PaymentTransaction.objects.filter(order=order).update(
                        status='SUCCESS',
                        razorpay_payment_id=rzp_payment_id,
                        payment_method=payment_method
                    )
                    logger.info(f"Webhook: Order {order.order_code} marked PAID via {event_type}")

        elif event_type == 'payment.failed':
            payment_entity = payload.get('payment', {}).get('entity', {})
            rzp_order_id = payment_entity.get('order_id')
            error_code = payment_entity.get('error_code', 'WEBHOOK_PAYMENT_FAILED')
            error_desc = payment_entity.get('error_description', 'Payment failed as per gateway webhook')

            if rzp_order_id:
                order = Order.objects.filter(razorpay_order_id=rzp_order_id).first()
                if order and order.order_status not in ['PAID', 'DELIVERED']:
                    order.order_status = 'PAYMENT_FAILED'
                    order.save()

                    PaymentTransaction.objects.filter(order=order).update(
                        status='FAILED',
                        error_code=error_code,
                        error_description=error_desc
                    )
                    logger.info(f"Webhook: Order {order.order_code} marked FAILED via payment.failed")

        elif event_type == 'refund.processed':
            refund_entity = payload.get('refund', {}).get('entity', {})
            payment_id = refund_entity.get('payment_id')
            if payment_id:
                PaymentTransaction.objects.filter(razorpay_payment_id=payment_id).update(status='REFUNDED')
                order = Order.objects.filter(transactions__razorpay_payment_id=payment_id).first()
                if order:
                    order.order_status = 'CANCELLED'
                    order.save()
                    logger.info(f"Webhook: Order {order.order_code} marked CANCELLED via refund.processed")

        return JsonResponse({'status': 'ok', 'event': event_type})
    except Exception as err:
        logger.error(f"Error processing webhook payload: {err}")
        return JsonResponse({'status': 'error', 'message': 'Internal webhook processing error'}, status=500)


# ==============================================================================
# 10. ADMIN REFUND HANDLER
# ==============================================================================
@user_passes_test(lambda u: u.is_staff, login_url='login')
def admin_refund(request, transaction_id):
    transaction = get_object_or_404(PaymentTransaction, id=transaction_id)

    if transaction.status != 'SUCCESS':
        messages.error(request, "Only SUCCESSFUL transactions can be refunded.")
        return redirect('admin_dashboard')

    if not transaction.razorpay_payment_id:
        messages.error(request, "No Razorpay Payment ID found to refund.")
        return redirect('admin_dashboard')

    client = get_razorpay_client()
    try:
        refund_data = {
            'amount': transaction.amount_in_paise,
            'notes': {
                'reason': 'Customer requested refund',
                'transaction_id': transaction.transaction_id
            }
        }
        client.payment.refund(transaction.razorpay_payment_id, refund_data)
        logger.info(f"Initiated gateway refund for payment {transaction.razorpay_payment_id}")
    except Exception as e:
        logger.error(f"Gateway refund error for {transaction.transaction_id}: {e}")

    transaction.status = 'REFUNDED'
    transaction.save()

    order = transaction.order
    order.order_status = 'CANCELLED'
    order.save()

    messages.success(request, f"Transaction {transaction.transaction_id} refunded successfully! Order status updated.")
    return redirect('admin_dashboard')
