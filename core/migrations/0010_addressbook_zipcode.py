# Generated by Django 5.1.3 on 2024-11-27 13:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_rename_address_addressbook_address1_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='addressbook',
            name='zipcode',
            field=models.CharField(default='62040', max_length=10),
            preserve_default=False,
        ),
    ]
