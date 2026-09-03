from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from addpro.models import Product
from .cart import Cart

def cart_summary(request):
    cart = Cart(request)
    cart_items = []
    total_amount = 0

    for product_id, qty in cart.cart.items():
        try:
            product = Product.objects.get(id=int(product_id))
            price = product.sale_price if product.is_sale else product.price
            line_total = price * qty
            total_amount += line_total
            cart_items.append({
                "product": product,
                "qty": qty,
                "price": price,
                "total": line_total,
            })
        except Product.DoesNotExist:
            continue

    return render(request, "cart/cart_summary.html", {
        "cart_items": cart_items,
        "totals": total_amount,
    })


def cart_add(request, id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=id)
    cart.add(product=product, qty=1)
    return redirect("cart_summary")


def cart_increment(request, id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=id)
    cart.add(product=product, qty=1)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"success": True, "qty": cart.cart.get(str(id), 1), "totals": float(cart.cart_total())})
    return redirect("cart_summary")


def cart_decrement(request, id):
    cart = Cart(request)
    product_id = str(id)
    if product_id in cart.cart:
        if cart.cart[product_id] > 1:
            cart.cart[product_id] -= 1
        else:
            del cart.cart[product_id]
        cart.session.modified = True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"success": True, "qty": cart.cart.get(product_id, 0), "totals": float(cart.cart_total())})
    return redirect("cart_summary")


def cart_remove(request, id):
    cart = Cart(request)
    product_id = str(id)
    if product_id in cart.cart:
        del cart.cart[product_id]
        cart.session.modified = True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({"success": True, "totals": float(cart.cart_total())})
    return redirect("cart_summary")


def cart_delete(request):
    cart = Cart(request)
    product_id = str(request.POST.get("product_id") or request.GET.get("product_id", ""))
    if product_id in cart.cart:
        del cart.cart[product_id]
        cart.session.modified = True
        return JsonResponse({"success": True, "totals": float(cart.cart_total())})
    return redirect("cart_summary")


def cart_update(request):
    cart = Cart(request)
    if request.method == "POST":
        product_id = str(request.POST.get("product_id", ""))
        try:
            product_qty = int(request.POST.get("product_qty", 1))
        except ValueError:
            product_qty = 1

        if product_id in cart.cart:
            if product_qty > 0:
                cart.cart[product_id] = product_qty
            else:
                del cart.cart[product_id]
            cart.session.modified = True
            return JsonResponse({"success": True, "totals": float(cart.cart_total())})

    return redirect("cart_summary")
