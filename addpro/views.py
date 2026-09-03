from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from .models import Product
# from django.contrib.auth.decorators import login_required

from django.db.models import Q


def home(request):
    products = Product.objects.all()
    return render(request, 'home.html', {'products': products})

def about(request):
    return render(request, 'about.html')

def product(request,pk):
    product = Product.objects.get(id=pk)
    return render(request, 'product.html',{'product':product})

# def category(request,foo):
#     foo = foo.replace('-',' ')
#     try:
#         category= Category.objects.get(name=foo)#name in models category
#         products = Product.objects.filter(category=category)
#         return render(request, 'category.html', {'products':products, 'category':category})
#     except:
#         messages.success(request,("The category doesn't exist.. "))
#         return redirect('home')
    
def register_user(request):
    if request.method == "POST":
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']

        # Password match check
        if password1 != password2:
            messages.error(request, "Passwords do not match")
            return redirect('register')

        # Password length check
        if len(password1) < 8:
            messages.error(request, "Password must be at least 8 characters long")
            return redirect('register')

        special_characters = "!@#$%^&*()-_=+[]{};:'\",.<>?/\\|`~"
        if not any(char in special_characters for char in password1):
            messages.error(request, "Password must contain at least 1 special character")
            return redirect('register')

        if not any(char.isalpha() for char in password1):
            messages.error(request, "Password must contain at least one letter (A-Z or a-z)")
            return redirect('register')


        # Username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken")
            return redirect('register')

        # Email already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered")
            return redirect('register')
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1
        )

        messages.success(request, "Account created successfully! Please log in.")
        return redirect('login')

    return render(request, 'register.html')

def login_user(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, "You Have Been Logged In!")
            return redirect('home')
        else:
            messages.error(request, "Invalid Username or Password")
            return redirect('login')

    return render(request, 'login.html')

def logout_user(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('home')

def search(request):
    searched = (request.GET.get('searched') or request.POST.get('searched', '')).strip()

    if searched:
        products = Product.objects.filter(
            Q(name__icontains=searched) | 
            Q(description__icontains=searched) |
            Q(category__name__icontains=searched)
        ).distinct()
        return render(request, "search.html", {
            'searched': products, 
            'query': searched, 
            'has_query': True
        })

    # If user opens /search/ without query, show all products to explore
    all_products = Product.objects.all()
    return render(request, "search.html", {
        'searched': all_products, 
        'query': '', 
        'has_query': False
    })


from .models import Product, Category

def mobiles(request):
    category = Category.objects.get(name='Mobile Phones')
    products = Product.objects.filter(category=category)
    return render(request, 'mobiles.html', {'products': products})

def shoes(request):
    category = Category.objects.get(name='Shoes')
    products = Product.objects.filter(category=category)
    return render(request, 'shoes.html', {'products': products})

def cakes(request):
    category = Category.objects.get(name='Cakes')
    products = Product.objects.filter(category=category)
    return render(request, 'cakes.html', {'products': products})

def drinks(request):
    category = Category.objects.get(name='Drinks')
    products = Product.objects.filter(category=category)
    return render(request, 'drinks.html', {'products': products})


