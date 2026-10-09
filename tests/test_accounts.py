import re

import pytest
from django.urls import reverse

from accounts.models import DemoEmail, EmailVerification, User

from .conftest import PW, make_staff

pytestmark = pytest.mark.django_db


def register(client, email="new.student@aston.ac.uk", password="Birmingham2027!"):
    return client.post(reverse("accounts:register"),
                       {"full_name": "New Student", "email": email, "password": password, "terms": "on"})


def test_register_requires_aston_email(client):
    r = register(client, email="someone@gmail.com")
    assert r.status_code == 200
    assert "should end with @aston.ac.uk" in r.content.decode()
    assert not User.objects.filter(email="someone@gmail.com").exists()


def test_register_rejects_weak_password(client):
    r = register(client, password="password")
    assert r.status_code == 200 and not User.objects.exists()


def test_register_sends_code_to_demo_inbox_and_stores_only_hash(client):
    r = register(client)
    assert r.status_code == 302 and r.url == reverse("accounts:verify")
    user = User.objects.get(email="new.student@aston.ac.uk")
    assert not user.email_verified
    mail = DemoEmail.objects.get(to_email=user.email)
    code = re.search(r"(\d{6})", mail.subject).group(1)
    v = EmailVerification.objects.get(user=user)
    assert code not in v.code_hash  # only a hash is stored


def test_wrong_code_then_right_code_verifies_and_signs_in(client):
    register(client)
    mail = DemoEmail.objects.get()
    code = re.search(r"(\d{6})", mail.subject).group(1)
    wrong = "000000" if code != "000000" else "111111"
    r = client.post(reverse("accounts:verify"), {"code": wrong, "verify": "1"})
    assert "4 attempts left" in r.content.decode()
    r = client.post(reverse("accounts:verify"), {"code": code, "verify": "1"})
    assert r.status_code == 302
    assert User.objects.get(email="new.student@aston.ac.uk").email_verified
    assert client.get(reverse("accounts:overview")).status_code == 200


def test_code_locks_after_five_attempts(client):
    register(client)
    for _ in range(5):
        client.post(reverse("accounts:verify"), {"code": "999999", "verify": "1"})
    v = EmailVerification.objects.get()
    assert v.attempts_left == 0
    assert not v.verify(re.search(r"(\d{6})", DemoEmail.objects.get().subject).group(1))


def test_unverified_user_cannot_sign_in(client):
    User.objects.create_user("x.y@aston.ac.uk", PW, full_name="X Y")
    r = client.post(reverse("accounts:signin"), {"email": "x.y@aston.ac.uk", "password": PW})
    assert r.url == reverse("accounts:verify")
    assert "_auth_user_id" not in client.session


def test_lockout_after_five_failed_sign_ins(client, student):
    for _ in range(5):
        client.post(reverse("accounts:signin"), {"email": student.email, "password": "wrong-password1"})
    r = client.post(reverse("accounts:signin"), {"email": student.email, "password": PW})
    assert "Too many attempts" in r.content.decode()
    assert "_auth_user_id" not in client.session


def test_staff_cannot_use_customer_sign_in(client):
    make_staff("stock")
    r = client.post(reverse("accounts:signin"), {"email": "stock@astonbundle.example", "password": PW})
    assert "staff account" in r.content.decode()


def test_password_reset_via_demo_inbox(client, student):
    r = client.post(reverse("accounts:forgot"), {"email": student.email})
    assert r.status_code == 200
    body = DemoEmail.objects.get(to_email=student.email).body
    link = re.search(r"http://testserver(/account/reset/\S+)", body).group(1)
    r = client.get(link, follow=True)
    r = client.post(r.redirect_chain[-1][0], {"new_password1": "NewPassword2027!", "new_password2": "NewPassword2027!"})
    assert r.status_code == 302
    assert client.login(email=student.email, password="NewPassword2027!")


def test_forgot_password_does_not_reveal_accounts(client):
    r = client.post(reverse("accounts:forgot"), {"email": "nobody@aston.ac.uk"})
    assert "If an account exists" in r.content.decode()
    assert not DemoEmail.objects.exists()


def test_demo_inbox_is_scoped_to_session(client, student):
    DemoEmail.objects.create(to_email=student.email, subject="Secret", body="reset link")
    r = client.get(reverse("accounts:demo_inbox") + f"?to={student.email}")
    assert "Secret" not in r.content.decode()


def test_profile_update_and_delete_account(student_client, student):
    r = student_client.post(reverse("accounts:profile"), {"action": "details", "full_name": "Aylin D", "halls": "Lakeside Court",
                                                           "room": "b-12", "arrival_date": "", "phone": ""})
    assert r.status_code == 302
    student.refresh_from_db()
    assert student.room == "B-12" and student.halls == "Lakeside Court"
    student_client.post(reverse("accounts:profile"), {"action": "delete", "confirm": "DELETE"})
    student.refresh_from_db()
    assert not student.is_active and student.full_name == "Deleted user" and "deleted" in student.email


def test_sign_out_requires_post(student_client):
    assert student_client.get(reverse("accounts:signout")).status_code == 405


def test_reset_link_for_other_students_is_never_shown_in_demo_inbox(client):
    victim = User.objects.create_user("victim.s@aston.ac.uk", PW, full_name="V S", email_verified=True)
    client.post(reverse("accounts:forgot"), {"email": victim.email})
    assert DemoEmail.objects.filter(to_email=victim.email).exists()  # "sent"
    r = client.get(reverse("accounts:demo_inbox") + f"?to={victim.email}")
    assert "/account/reset/" not in r.content.decode()


def test_disabled_account_cannot_sign_in(client, student):
    student.is_active = False
    student.save()
    client.post(reverse("accounts:signin"), {"email": student.email, "password": PW})
    assert "_auth_user_id" not in client.session


def test_terms_page(client):
    assert client.get(reverse("core:page", args=["terms"])).status_code == 200
