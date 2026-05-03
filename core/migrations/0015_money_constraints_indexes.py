from django.db import migrations, models


def deduplicate_for_constraints(apps, schema_editor):
    AddressBook = apps.get_model("core", "AddressBook")
    CartItem = apps.get_model("core", "CartItem")
    WishList = apps.get_model("core", "WishList")
    from django.db.models import Count, Min, Sum

    for row in (
        WishList.objects.values("user_id", "product_id")
        .annotate(row_count=Count("id"), keep_id=Min("id"))
        .filter(row_count__gt=1)
    ):
        WishList.objects.filter(
            user_id=row["user_id"], product_id=row["product_id"]
        ).exclude(id=row["keep_id"]).delete()

    for row in (
        CartItem.objects.values("cart_id", "product_id")
        .annotate(row_count=Count("id"), keep_id=Min("id"), total_quantity=Sum("quantity"))
        .filter(row_count__gt=1)
    ):
        CartItem.objects.filter(id=row["keep_id"]).update(
            quantity=row["total_quantity"] or 1
        )
        CartItem.objects.filter(
            cart_id=row["cart_id"], product_id=row["product_id"]
        ).exclude(id=row["keep_id"]).delete()

    for row in (
        AddressBook.objects.filter(default_address=True)
        .values("user_id")
        .annotate(row_count=Count("id"), keep_id=Min("id"))
        .filter(row_count__gt=1)
    ):
        AddressBook.objects.filter(
            user_id=row["user_id"], default_address=True
        ).exclude(id=row["keep_id"]).update(default_address=False)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_order_stripe_checkout_session_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="products",
            name="price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name="order",
            name="total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.RunPython(deduplicate_for_constraints, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="addressbook",
            constraint=models.UniqueConstraint(
                condition=models.Q(default_address=True),
                fields=("user",),
                name="uniq_default_addr_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="wishlist",
            constraint=models.UniqueConstraint(
                fields=("user", "product"),
                name="unique_wishlist_user_product",
            ),
        ),
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                fields=("cart", "product"),
                name="unique_cart_product",
            ),
        ),
        migrations.AddIndex(
            model_name="products",
            index=models.Index(fields=["title"], name="product_title_idx"),
        ),
        migrations.AddIndex(
            model_name="products",
            index=models.Index(
                fields=["category", "price"], name="product_category_price_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="products",
            index=models.Index(fields=["created_at"], name="product_created_idx"),
        ),
        migrations.AddIndex(
            model_name="products",
            index=models.Index(fields=["rating"], name="product_rating_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["user", "created_at"], name="order_user_created_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["status"], name="order_status_idx"),
        ),
    ]
