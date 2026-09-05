import os
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from addpro.models import Category, Product


class Command(BaseCommand):
    help = 'Ensures default admin, test reviewer accounts, and sample store catalog exist.'

    def handle(self, *args, **options):
        # 1. Ensure Superuser Admin Account
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_email = os.getenv('ADMIN_EMAIL', 'admin@finpay.com')
        admin_password = os.getenv('ADMIN_PASSWORD', 'Admin@12345')

        admin_user, created = User.objects.get_or_create(username=admin_username, defaults={'email': admin_email})
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.set_password(admin_password)
        admin_user.save()
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created Admin Superuser: {admin_username}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated Admin Superuser: {admin_username}"))

        # 2. Ensure Razorpay Reviewer / Test Customer Account
        test_username = os.getenv('TEST_USER_USERNAME', 'razorpay_test')
        test_email = os.getenv('TEST_USER_EMAIL', 'reviewer@finpay.com')
        test_password = os.getenv('TEST_USER_PASSWORD', 'Test@12345')

        test_user, created = User.objects.get_or_create(username=test_username, defaults={'email': test_email})
        test_user.set_password(test_password)
        test_user.save()
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created Test Customer Account: {test_username}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated Test Customer Account: {test_username}"))

        # 3. Ensure Categories
        categories_data = [
            'Mobile Phones',
            'Shoes',
            'Cakes & Bakery',
            'Drinks & Beverages'
        ]
        cat_objs = {}
        for cat_name in categories_data:
            cat, _ = Category.objects.get_or_create(name=cat_name)
            cat_objs[cat_name] = cat

        # 4. Ensure Sample Products with Images
        products_data = [
            {
                'name': 'Samsung Galaxy S24 Ultra',
                'category': cat_objs['Mobile Phones'],
                'price': Decimal('129999.00'),
                'is_sale': True,
                'sale_price': Decimal('119999.00'),
                'image': 'uploads/product/mobile.jpg',
                'description': 'Flagship AI smartphone with 200MP camera and titanium build.'
            },
            {
                'name': 'Apple iPhone 15 Pro',
                'category': cat_objs['Mobile Phones'],
                'price': Decimal('134900.00'),
                'is_sale': False,
                'sale_price': Decimal('0.00'),
                'image': 'uploads/product/0_Qfzh9dCW6754ydZ0.jpg',
                'description': 'A17 Pro chip, Grade 5 titanium design, Action button.'
            },
            {
                'name': 'Nike Air Zoom Pegasus',
                'category': cat_objs['Shoes'],
                'price': Decimal('9995.00'),
                'is_sale': True,
                'sale_price': Decimal('7995.00'),
                'image': 'uploads/product/shoe1.jpg',
                'description': 'Responsive cushioning for daily running with engineered mesh upper.'
            },
            {
                'name': 'Adidas Ultraboost Light',
                'category': cat_objs['Shoes'],
                'price': Decimal('14999.00'),
                'is_sale': False,
                'sale_price': Decimal('0.00'),
                'image': 'uploads/product/shoe2.jpg',
                'description': 'Lightest Boost midsole ever with Continental rubber outsole.'
            },
            {
                'name': 'Belgian Chocolate Truffle Cake',
                'category': cat_objs['Cakes & Bakery'],
                'price': Decimal('850.00'),
                'is_sale': True,
                'sale_price': Decimal('699.00'),
                'image': 'uploads/product/cake1.jpg',
                'description': 'Rich dark chocolate ganache layered with moist sponge.'
            },
            {
                'name': 'Red Velvet Cream Cheese Cake',
                'category': cat_objs['Cakes & Bakery'],
                'price': Decimal('950.00'),
                'is_sale': False,
                'sale_price': Decimal('0.00'),
                'image': 'uploads/product/cake3.jpg',
                'description': 'Classic red velvet layered with premium vanilla cream cheese.'
            },
            {
                'name': 'Cold Brew Iced Coffee',
                'category': cat_objs['Drinks & Beverages'],
                'price': Decimal('250.00'),
                'is_sale': True,
                'sale_price': Decimal('199.00'),
                'image': 'uploads/product/drink1.jpg',
                'description': 'Steeped for 18 hours for a smooth, naturally sweet espresso flavor.'
            },
            {
                'name': 'Test Payment Sandbox Item',
                'category': cat_objs['Drinks & Beverages'],
                'price': Decimal('2.00'),
                'is_sale': False,
                'sale_price': Decimal('0.00'),
                'image': 'uploads/product/drink3.jpg',
                'description': 'Low-value sample item for live gateway verification (₹2 INR).'
            }
        ]

        for p_data in products_data:
            try:
                prod, created = Product.objects.get_or_create(
                    name=p_data['name'],
                    defaults=p_data
                )
                if not created and not prod.image:
                    prod.image = p_data.get('image', '')
                    prod.save()
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Product setup notice for {p_data.get('name')}: {e}"))

        self.stdout.write(self.style.SUCCESS("Demo catalog & accounts initialized successfully!"))
