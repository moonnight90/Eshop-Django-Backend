from django.contrib import admin
from .models import Products,Image,Cart,CartItem,Category,AddressBook,Reviews,CustomUser,Order,Order_Item,OTP
# Register your models here.
admin.site.register(Products)
admin.site.register(Image)
admin.site.register(Cart)
admin.site.register(CartItem)
admin.site.register(Category)
admin.site.register(AddressBook)
admin.site.register(Reviews)
admin.site.register(CustomUser)
admin.site.register(Order)
admin.site.register(Order_Item)
admin.site.register(OTP)