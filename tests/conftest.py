from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Role, User
from catalog.models import Bundle, BundleItem, Category, Product


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.EMAIL_BACKEND = "accounts.email_backend.DemoInboxBackend"
    settings.STORAGES = {**settings.STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast tests
    # The test client speaks plain HTTP, so the tests also pass with production settings (no .env)
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture
def catalog(db):
    kitchen = Category.objects.create(name="Kitchen", slug="kitchen", sort=1)
    tech = Category.objects.create(name="Tech & Power", slug="tech-power", sort=2)

    def mk(sku, name, cat, price, stock, th=5, returnable=True):
        return Product.objects.create(sku=sku, name=name, category=cat, price=Decimal(price), stock=stock,
                                      low_stock_threshold=th, summary=name, description=name, image_alt=name,
                                      icon="box", returnable=returnable)

    p = {
        "kettle": mk("KT-1", "1.7L Kettle", kitchen, "13.99", 20),
        "pan": mk("KT-2", "Pan Set", kitchen, "22.00", 10),
        "box": mk("KT-3", "Food Containers", kitchen, "9.50", 10, returnable=False),
        "adapter": mk("TP-1", "UK Plug Adapter", tech, "7.99", 3),
        "lead": mk("TP-2", "Extension Lead", tech, "14.99", 0),
    }
    b = Bundle.objects.create(name="Kitchen Starter", slug="kitchen-starter", tagline="cook", description="d",
                              price=Decimal("30.00"), icons="pot")
    BundleItem.objects.create(bundle=b, product=p["kettle"], quantity=1)
    BundleItem.objects.create(bundle=b, product=p["pan"], quantity=1)
    BundleItem.objects.create(bundle=b, product=p["box"], quantity=1)
    p["bundle"] = b
    return p


PW = "Student2026!demo"


@pytest.fixture
def student(db):
    return User.objects.create_user("demo.student@aston.ac.uk", PW, full_name="Aylin Demir", email_verified=True,
                                    halls="Canal View Halls", room="C-214")


@pytest.fixture
def student_client(client, student):
    client.login(email=student.email, password=PW)
    return client


def make_staff(role):
    return User.objects.create_staff(f"{role}@astonbundle.example", PW, role=role, full_name=f"{role} demo")


@pytest.fixture
def owner(db):
    return make_staff(Role.OWNER)


@pytest.fixture
def delivery_data():
    d = timezone.localdate() + timedelta(days=5)
    return {"recipient_name": "Aylin Demir", "delivery_type": "halls", "halls": "Canal View Halls", "room": "C-214",
            "delivery_date": d, "delivery_slot": "09-13"}
