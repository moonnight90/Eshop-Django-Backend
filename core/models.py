from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token
from django.conf import settings
from phonenumber_field.modelfields import PhoneNumberField
from django.core.validators import MaxValueValidator
from cloudinary.models import CloudinaryField
# Create your models here.

class CustomUserManager(BaseUserManager):
    def create_user(self,email,password=None,**extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        user = self.model(
            email = self.normalize_email(email),
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self.db)
        return user

    def create_superuser(self,email,password=None,**extra_fields):
        extra_fields.setdefault('is_staff',True)
        extra_fields.setdefault('is_superuser',True)
        extra_fields.setdefault('is_active',True)
        return self.create_user(email,password,**extra_fields)

class CustomUser(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    image = CloudinaryField(folder='profile_images/', null=True, blank=True)
    objects = CustomUserManager()
    bio = models.TextField(null=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    

    def __str__(self):
        return self.email

class AddressBook(models.Model):
    user = models.ForeignKey(CustomUser,on_delete=models.CASCADE)
    fullName = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=50)
    state = models.CharField(max_length=50)
    zipcode = models.CharField(max_length=10)
    phone = PhoneNumberField(null=False,blank=False)
    default_address = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.address


class Products(models.Model):
    
    title = models.CharField(max_length=250)
    description = models.TextField(null=True)
    price = models.FloatField(default=0)
    rating = models.FloatField(default=0)
    review_count = models.IntegerField(default=0)
    stock = models.IntegerField(default=0)
    sold = models.IntegerField(default=0)
    category = models.ForeignKey('category',related_name="products",on_delete=models.CASCADE)
    discount = models.FloatField(default=0)
    sku = models.CharField(max_length=100)
    weight = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self) -> str:
        return self.title
    

class Image(models.Model):
    product = models.ForeignKey(Products,on_delete=models.CASCADE,related_name='imgs')
    image = CloudinaryField(folder='imgs/')
    
    def __str__(self) -> str:
        return self.image.url

class WishList(models.Model):
    user = models.ForeignKey(CustomUser,on_delete=models.CASCADE)
    product = models.ForeignKey(Products,on_delete=models.DO_NOTHING)
    created_at = models.DateTimeField(auto_now_add=True)

class Cart(models.Model):
    user = models.ForeignKey(CustomUser, on_delete = models.CASCADE)
    created_at = models.DateTimeField(auto_now_add = True)

    def __str__(self) -> str:
        return self.user.email


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete = models.CASCADE)
    product = models.ForeignKey(Products,on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default = 1)

    def total_price(self):
        return self.quantity*self.product.price


class Category(models.Model):
    name = models.CharField(max_length=55,null=False)
    parent = models.ForeignKey('self',related_name = "children",null=True,blank=True,on_delete=models.CASCADE)

    def __str__(self) -> str:
        return self.name

class Reviews(models.Model):
    product = models.ForeignKey(Products,on_delete=models.CASCADE)
    user = models.ForeignKey(CustomUser,on_delete=models.CASCADE)
    body = models.TextField()
    rating = models.PositiveIntegerField(default=0,validators=[MaxValueValidator(5)])
    created_at = models.DateField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.body[:30]}"



class Order(models.Model):
    user = models.ForeignKey(CustomUser,on_delete=models.CASCADE)
    address = models.ForeignKey(AddressBook,on_delete=models.CASCADE)
    status = models.CharField(max_length=255,choices=[('Pending','Pending'),('Shipped','Shipped'),('Delivered','Delivered'),('Cancelled','Cancelled')],default='Pending')
    payment = models.CharField(max_length=255,choices=[('COD','COD'),('Online','Online')],default='COD')
    is_paid = models.BooleanField(default=False)
    total = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user.email} - {self.address.fullName}"

class Order_Item(models.Model):
    product = models.ForeignKey(Products,on_delete=models.CASCADE)
    order = models.ForeignKey(Order,on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

class OTP(models.Model):    
    email = models.EmailField(null=False)
    name = models.CharField(max_length=255)
    otp = models.CharField(max_length=6,null=False)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self) -> str:
        return self.email

class User_Verification_Token(models.Model):
    user = models.ForeignKey(CustomUser,on_delete=models.CASCADE)
    token = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.user.email

@receiver(post_save,sender=CustomUser)
def create_cart(sender,instance=None, created=False, **kwargs):
    if created:
        Cart.objects.create(user=instance)


@receiver(post_save,sender=settings.AUTH_USER_MODEL)
def create_token(sender,instance=None,created=False, **kwargas):
    if created:
        Token.objects.create(user=instance)

