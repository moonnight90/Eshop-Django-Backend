import json
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import AddressBook, Cart, CartItem, Category, Order, Products, WishList


class CheckoutFlowTests(APITestCase):
    def setUp(self):
        self.customer = self._create_user("customer@example.com")
        self.other_customer = self._create_user("other@example.com")
        self.category = Category.objects.create(name="Shoes")
        self.product = Products.objects.create(
            title="Running Shoe",
            description="Daily trainer",
            price=Decimal("19.99"),
            rating=4.5,
            review_count=3,
            stock=5,
            sold=0,
            category=self.category,
            discount=0,
            sku="RUN-001",
            weight=1.2,
        )
        self.address = AddressBook.objects.create(
            user=self.customer,
            fullName="Test Customer",
            address="123 Market Street",
            city="Austin",
            state="TX",
            zipcode="73301",
            phone="+15125550100",
            default_address=True,
        )

    def _create_user(self, email):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(email=email, password="secret123")

    def _authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.customer)

    def _cart_item(self, quantity=1):
        cart = Cart.objects.get(user=self.customer)
        return CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=quantity,
        )

    def test_cod_order_recomputes_total_decrements_stock_and_clears_cart(self):
        cart_item = self._cart_item(quantity=2)
        self._authenticate()

        response = self.client.post(
            "/api/orders/",
            {
                "address_id": self.address.id,
                "payment": "COD",
                "total": "39.98",
                "order_items": [
                    {
                        "product_id": self.product.id,
                        "item_id": cart_item.id,
                        "quantity": 2,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(id=response.data["id"])
        self.assertEqual(order.total, Decimal("39.98"))
        self.assertFalse(order.is_paid)
        self.assertEqual(order.payment, "COD")

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(self.product.sold, 2)
        self.assertFalse(CartItem.objects.filter(id=cart_item.id).exists())

    def test_cod_order_rejects_tampered_total(self):
        self._cart_item(quantity=2)
        self._authenticate()

        response = self.client.post(
            "/api/orders/",
            {
                "address_id": self.address.id,
                "payment": "COD",
                "total": "1.00",
                "order_items": [{"product_id": self.product.id, "quantity": 2}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Order total mismatch.")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertFalse(Order.objects.exists())

    def test_wishlist_is_user_scoped_and_unique(self):
        wishlist_item = WishList.objects.create(user=self.customer, product=self.product)
        self._authenticate(self.other_customer)

        response = self.client.delete(
            "/api/wishlist/",
            {"id": wishlist_item.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(WishList.objects.filter(id=wishlist_item.id).exists())

        self._authenticate(self.customer)
        response = self.client.put(
            "/api/wishlist/",
            {"id": self.product.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            WishList.objects.filter(user=self.customer, product=self.product).count(),
            1,
        )

    @override_settings(STRIPE_SECRET_KEY="sk_test")
    def test_stripe_session_status_creates_paid_order_idempotently(self):
        cart_item = self._cart_item(quantity=2)
        self._authenticate()
        metadata = {
            "user_id": str(self.customer.id),
            "address_id": str(self.address.id),
            "total": "39.98",
            "order_items": json.dumps(
                [
                    {
                        "product_id": self.product.id,
                        "item_id": cart_item.id,
                        "quantity": 2,
                    }
                ]
            ),
        }
        session = StripeSession(
            session_id="cs_test_123",
            payment_status="paid",
            metadata=metadata,
            payment_intent={"id": "pi_test_123"},
        )

        with patch("core.views.stripe.checkout.Session.retrieve", return_value=session):
            first_response = self.client.get(
                "/api/payments/session-status/?session_id=cs_test_123"
            )
            second_response = self.client.get(
                "/api/payments/session-status/?session_id=cs_test_123"
            )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(Order.objects.count(), 1)

        order = Order.objects.get()
        self.assertTrue(order.is_paid)
        self.assertEqual(order.payment, "Online")
        self.assertEqual(order.stripe_checkout_session_id, "cs_test_123")
        self.assertEqual(order.stripe_payment_intent_id, "pi_test_123")
        self.assertEqual(order.total, Decimal("39.98"))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(self.product.sold, 2)
        self.assertFalse(CartItem.objects.filter(id=cart_item.id).exists())


class StripeSession(dict):
    def __init__(self, session_id, payment_status, metadata, payment_intent):
        super().__init__(payment_intent=payment_intent)
        self.id = session_id
        self.payment_status = payment_status
        self.metadata = metadata
