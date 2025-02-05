from django.urls import path
from .views import *
urlpatterns = [
    path('products/',view=ProductsView.as_view()),
    path('product/<int:id>',view=SingleProduct.as_view()),
    path('cart/', view=CartItemView.as_view()),
    path('login/', view=UserLoginAPIView.as_view()),
    path('addressbook/',AddressBookView.as_view()),
    path('me/',UserView.as_view()),
    path('reviews/',ReviewsView.as_view()),
    path('register/',UserRegisterView.as_view()),
    path('logout/',view=logout.as_view()),
    path('orders/',view=OrderView.as_view()),
    path('order/',view=OrderItemView.as_view()),
    path('categories/',view=CategoryView.as_view()),
    path('update-password/', UpdatePassword.as_view()),
    path('wishlist/',WishListView.as_view()),
    path('send_otp/',view=HandleOTP.as_view()),
    path('verify_otp/',view=VerifyOTP.as_view()),
    path('reset_password/',view=ForgetPassword.as_view()),
    path('reset_password_confirm/',view=ResetPassword.as_view()),
    path('autocomplete/',view=SearchAutoComplete.as_view()),

    ## Admin Panel
    path('upload/products/',view=ProductUploadView.as_view()),
    path('upload/image/',view=ImageUploadView.as_view()),
]
