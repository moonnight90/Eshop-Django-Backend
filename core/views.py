import random
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter,OrderingFilter
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from .serializers import ProductSerializer,CartItemSerializer,UserLoginSerializer,AddressBookSerializer,UserSerializer,ReviewSerializer,UserRegistrationSerializer,OrderItemSerializer,OrderSerializer,OTPSerializer,CategorySerializer,PasswordUpdateSerializer, WishListSerializer,SearchAutoCompleteSerializer,ImageSerializer
from rest_framework import generics
from rest_framework import status
from .models import Products,Image,CartItem,Cart, AddressBook,Reviews,Order,Order_Item,Category,OTP,User_Verification_Token, WishList
from rest_framework.authtoken.models import Token
from rest_framework.authentication import authenticate
from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model
from rest_framework.parsers import MultiPartParser,FormParser
from django.db.models import Case, Value, When
from .helper import genereat_otp,send_otp
from django.utils import timezone
CustomUser = get_user_model()

class IsReviewAuthenticatedOrReadOnly(BasePermission):
    """
    Custom permission to allow unauthenticated users to read reviews
    but require authentication for other actions.
    """
    
    def has_permission(self, request, view):
        # Check if it's a safe method (GET, HEAD, OPTIONS)
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        
        # Check if the user is authenticated for other actions (POST, PUT, DELETE)
        return request.user and request.user.is_authenticated


class StandardPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'limit'
    max_page_size = 100


class SearchAutoComplete(APIView):
    def get(self, request):
        query = request.query_params.get('query')
        if not query:
            return Response([])
        products = Products.objects.filter(title__icontains=query)
        products = Products.objects.filter(title__icontains=query).annotate(
            priority=Case(
                When(title__istartswith=query, then=Value(0)),
                When(title__icontains=f" {query}", then=Value(1)),
                When(title__icontains=query, then=Value(2)),
                default=Value(3)            
            )).order_by("priority","title")
        
        ## Removing duplicates
        unique_products = {product.title: product for product in products}.values()

        ## Limiting to 10 results
        unique_products = list(unique_products)[:10]

        serializer = SearchAutoCompleteSerializer(unique_products, many=True)
        return Response(serializer.data)

class ProductsView(generics.ListAPIView):
    queryset = Products.objects.all()
    serializer_class = ProductSerializer
    pagination_class = StandardPagination
    filter_backends = [SearchFilter,OrderingFilter]
    search_fields = ['title','description']
    ordering_fields = ['price','created_at','title','rating','sold']

    def get_queryset(self):
        queryset = super().get_queryset()
        title = self.request.query_params.get('title')
        categories = self.request.query_params.getlist('category', None)
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')

        # Apply filters
        if title:
            # Filter products by title
            queryset = queryset.filter(title__icontains=title)
        if categories:
            # Filter products by categories
            queryset = queryset.filter(category__name__in=categories)
        if min_price:
            # Filter products by minimum price
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            # Filter products by maximum price
            queryset = queryset.filter(price__lte=max_price)
        
        return queryset

class ProductUploadView(APIView):
    # parser_classes = [MultiPartParser, FormParser]
    def post(self, request):
        serializer = ProductSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ImageUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    def post(self, request):
        serializer = ImageSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class HandleOTP(APIView):
    def post(self,request):
        serialzer = OTPSerializer(data=request.data)
        if serialzer.is_valid():
            email = serialzer.validated_data['email']
            name = serialzer.validated_data['name']
            otp = genereat_otp(6)
            response = send_otp(email,name,otp)
            if response:
                OTP.objects.filter(email=email).delete()
                OTP.objects.create(email=email,name=name,otp=otp).save()

                return Response({"status":202,"msg":"OTP sent."},status=status.HTTP_202_ACCEPTED)
            else:
                return Response({"status":422,"msg":"Failed to send OTP."},status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(serialzer.errors,status=status.HTTP_400_BAD_REQUEST)
        

class VerifyOTP(APIView):
    def post(self,request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        obj = OTP.objects.filter(email=email,otp=otp)
        if obj:
            obj = obj.first()
            if obj.created_at < (timezone.now() - timezone.timedelta(minutes=10)):
                obj.delete()
                return Response({"status":400, "msg":"OTP expired"},status=status.HTTP_400_BAD_REQUEST)
            
            obj.is_verified = True
            obj.save()
            return Response({"status":200, "msg":"OTP verified"},status=status.HTTP_200_OK)
        else:
            return Response({"status":400, "msg":"Invalid OTP"},status=status.HTTP_400_BAD_REQUEST)
        

class SingleProduct(APIView):
    def get(self,request,id):
        obj = Products.objects.filter(id=id).first()
        if obj:
            return Response(ProductSerializer(obj).data)
        else:
            return Response({})

class WishListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self,request):
        objs = WishList.objects.filter(user=request.user)
        serializer = WishListSerializer(objs,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)
    def put(self,request):
        id = request.data.get('id')
        obj = WishList.objects.filter(product=id)
        if obj.count():
            return Response({"msg":"This product already in wishlist"},status=status.HTTP_200_OK)
        serializer = WishListSerializer(data={
            "user":request.user.id,
            "product_id":request.data.get('id')
        })
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
    def delete(self,request):
        id = request.data.get('id')
        obj = WishList.objects.filter(id=id)
        if obj.count():
            obj.delete()
            return Response({"msg":"Delete Successfully...",'status':200},status=status.HTTP_200_OK)
        else:
            return Response({"msg":"Item Not Exists",'status':404},status=status.HTTP_404_NOT_FOUND)
            



class CartItemView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self,request):
        total_quantity = request.query_params.get('total_quantity')
        if total_quantity:
            cart_items = CartItem.objects.filter(cart__user=request.user)
            return Response({'total_quantity': len(cart_items)}, status=status.HTTP_200_OK)
        else:
            cart_items = CartItem.objects.filter(cart__user=request.user)
            serializer = CartItemSerializer(cart_items,many=True)
            return Response(serializer.data,status=status.HTTP_200_OK)

    def delete(self,request):
        id = request.data.get('id')
        CartItem.objects.get(id=id).delete()
        return Response({"status":200,"success":"Product removed from cart..."},status=status.HTTP_200_OK)

    def put(self,request):
        id = request.data.get('id')
        quantity = request.data.get('q')
        cart_item = CartItem.objects.filter(cart__user=request.user,product__id=id)
        if not cart_item:
            return Response({"error":"Product Not Found..."},status=status.HTTP_400_BAD_REQUEST)
        product = Products.objects.filter(id=id).first()
        cart_item = cart_item.first()
        if quantity > product.stock:
            return Response({"status":400,"error":"Sorry, we don't have enough stock for this item."},status=status.HTTP_400_BAD_REQUEST)
        elif quantity > 10:
            return Response({"status":400,"error":"You've reached the maximum quantity for this item."},status=status.HTTP_400_BAD_REQUEST)
        cart_item.quantity = quantity
        cart_item.save()
        return Response({"status":200,"success":"Product quantity updated..."},status=status.HTTP_200_OK)

    def post(self,request):
        product_id = request.data.get('id')
        quantity = request.data.get('q')

        try:
            product = Products.objects.get(id=product_id)
        except Products.DoesNotExist:
            return Response({"error":"Product Not Found..."},status=status.HTTP_400_BAD_REQUEST)
        cartItems = CartItem.objects.filter(cart__user = request.user,product=product)
        if cartItems: 
            cartItem = cartItems.first()
            if cartItem.quantity + quantity > product.stock:
                return Response({"status":400,"error":"Sorry, we don't have enough stock for this item."},status=status.HTTP_400_BAD_REQUEST)
            elif cartItem.quantity + quantity < 1  or cartItem.quantity + quantity > 10:
                return Response({"status":400,"error":"You've reached the maximum quantity for this item."},status=status.HTTP_400_BAD_REQUEST)
            cartItem.quantity += quantity
            cartItem.save()
        else:
            cartItem = CartItem()
            cartItem.product = product
            cartItem.cart = Cart.objects.get(user=request.user)
            cartItem.quantity = quantity
            cartItem.save()
            

        return Response({"status":200,"success":"Product has been added to your cart!"},status=status.HTTP_200_OK)

class UserLoginAPIView(APIView):
    def post(self, request):
        serializer = UserLoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            user = authenticate(email=email, password=password)
            if user:
                token, _ = Token.objects.get_or_create(user=user)
                return Response({'token': token.key}, status=status.HTTP_200_OK)
            else:
                return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




class AddressBookView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    
    def get(self,request):
        objs = AddressBook.objects.filter(user=request.user)
        serializer = AddressBookSerializer(objs,many=True,context={'request':request})

        return Response(serializer.data,status=status.HTTP_200_OK)
    
    def post(self,request):
        serializer = AddressBookSerializer(data=request.data,context={'request':request})
        if serializer.is_valid():
            if AddressBook.objects.filter(default_address=True,user=request.user).count() == 0:
                serializer.save(user=request.user,default_address=True)
            serializer.save(user=request.user)
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def put(self,request):
        id = request.data.get('id')
        if not id:
            return Response({"error":"Id not provided"},status=status.HTTP_400_BAD_REQUEST)
        obj = AddressBook.objects.get(id=id)
        if obj.user == request.user:
            serializer = AddressBookSerializer(obj,data=request.data,partial=True)
            if serializer.is_valid():
                if serializer.validated_data.get('default_address'):
                    AddressBook.objects.filter(user=request.user).update(default_address=False)
                serializer.save()
                return Response(serializer.data,status=status.HTTP_200_OK)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error":"Address not found"},status=status.HTTP_404_NOT_FOUND)
    
    def delete(self,request):
        id = request.data.get('id')
        if not id:
            return Response({"error":"Id not provided"},status=status.HTTP_400_BAD_REQUEST)
        obj = AddressBook.objects.filter(user=request.user,id=id)
        if obj:
            obj = obj.first().delete()
            return Response({"status":200,"success":"Address deleted..."},status=status.HTTP_200_OK)
        else:
            return Response({"error":"Address not found"},status=status.HTTP_404_NOT_FOUND)
    
class UserView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self,request):
        if isinstance(request.user,CustomUser):
            serializer = UserSerializer(request.user)
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response({"error":"User not found"},status=status.HTTP_404_NOT_FOUND)

    def put(self,request):
        if isinstance(request.user,CustomUser):
            serializer = UserSerializer(request.user,data=request.data,partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data,status=status.HTTP_200_OK)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"error":"User not found"},status=status.HTTP_404_NOT_FOUND)

class UserRegisterView(APIView):
    parser_classes= [MultiPartParser,FormParser]
    def post(self,request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            otps = OTP.objects.filter(email=serializer.validated_data['email'])
            is_user_otp_verifies = False
            for otp in otps:
                if otp.is_verified:
                    is_user_otp_verifies = True

            if not is_user_otp_verifies:
                return Response({"status":400, "msg":"Please verify your email first"},status=status.HTTP_400_BAD_REQUEST)
            
            user = serializer.save()
            token,_ = Token.objects.get_or_create(user=user)
            return Response({"Token":token.key},status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
        
        

class ReviewsView(APIView,StandardPagination):
    
    permission_classes = [IsReviewAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    def get(self,request):
        
        id = request.GET.get('id',None)
        if id:
            paginator = StandardPagination()
            objects = Reviews.objects.filter(product__id=id)
            result_page = paginator.paginate_queryset(objects,request)
            serializer = ReviewSerializer(result_page, many=True)
            return paginator.get_paginated_response(serializer.data)
        else:
            return Response({"error":"Id not provided.."},status=status.HTTP_400_BAD_REQUEST)
    
    def post(self,request):
        id = request.GET.get('id') 
        product = Products.objects.filter(id=id).first()
        if product:
            user = request.user
            if not user.is_anonymous:
                if Reviews.objects.filter(user__id=user.id,product__id=product.id).first():
                    return Response({"msg":"You alrady posted a review on this product"},status=status.HTTP_208_ALREADY_REPORTED)
                request.data['product'] = product.id
                request.data['user'] = user.id
                seriliazer = ReviewSerializer(data=request.data)
                if seriliazer.is_valid():
                    seriliazer.save(user=user,product=product)
                    return Response(seriliazer.data,status=status.HTTP_200_OK)
                else:
                    return Response(seriliazer.errors)

        return Response([])

class OrderView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self,request):
        id = request.GET.get('id')
        if id:
            objs = Order.objects.filter(user=request.user,id=id)
            if objs:
                serializer = OrderSerializer(objs.first())
                return Response(serializer.data,status=status.HTTP_200_OK)
            else:
                return Response({"msg":"Not Order Found!"},status=status.HTTP_404_NOT_FOUND)
        else:
            objs = Order.objects.filter(user=request.user)
            serializer = OrderSerializer(objs,many=True)
            return Response(serializer.data,status=status.HTTP_200_OK)
    def post(self,request):
        order_data = {
            "total":request.data.get('total'),
            "address_id": request.data.get("address_id"),
            "user": request.user.id
        }
        serializer = OrderSerializer(data=order_data)
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            order_items = request.data.get('order_items',[])
            for order_item in order_items:
                order_item['order'] = order.id
                order_item_serializer = OrderItemSerializer(data=order_item)
                if order_item_serializer.is_valid():
                        order_item_serializer.save()
                else:
                    print(order_item_serializer.errors)
            # Clearing Cart
            cart = Cart.objects.get(user=request.user)
            cartItems = CartItem.objects.filter(cart=cart,id__in=[order_item.get('item_id') for order_item in order_items])
            cartItems.delete()
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OrderItemView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self,request):
        order_id = request.GET.get('order_id')
        objs = Order_Item.objects.filter(order__user=request.user,order=order_id)
        serializer = OrderItemSerializer(objs,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)
    def post(self,request):
        serializer = OrderItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CategoryView(APIView):

    def get(self,request):
        objs = Category.objects.all()
        serializer = CategorySerializer(objs,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)

class logout(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    def post(self,request):
        request.user.auth_token.delete()
        return Response({"msg":"logout Success"},status=status.HTTP_200_OK)

class UpdatePassword(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self,request):
        serialzer = PasswordUpdateSerializer(data=request.data,context={'request':request})
        if serialzer.is_valid():
            request.user.set_password(serialzer.validated_data['new_password'])
            Token.objects.filter(user=request.user).delete()
            request.user.save()
            return Response({"msg":"Password Updated"},status=status.HTTP_200_OK)
        else:
            return Response(serialzer.errors,status=status.HTTP_400_BAD_REQUEST)
class ForgetPassword(APIView):
    def post(self,request):
        email = request.data.get('email')
        user = CustomUser.objects.filter(email=email).first()
        if user:
            otp = genereat_otp(6)
            response = send_otp(email,user.first_name,otp,4)
            if response:
                OTP.objects.filter(email=email).delete()
                OTP.objects.create(email=email,name=user.first_name,otp=otp).save()
                return Response({"status":202,"msg":"OTP sent."},status=status.HTTP_202_ACCEPTED)
            else:
                return Response({"status":422,"msg":"Failed to send OTP."},status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"status":404,"msg":"Email not found."},status=status.HTTP_404_NOT_FOUND)
    
class ResetPassword(APIView):
    def post(self,request):
        email = request.data.get('email')
        otp = request.data.get('otp')
        new_password = request.data.get('new_password')
        obj = OTP.objects.filter(email=email,otp=otp)
        if obj:
            obj = obj.first()
            if obj.created_at < (timezone.now() - timezone.timedelta(minutes=10)):
                obj.delete()
                return Response({"status":400, "msg":"OTP expired"},status=status.HTTP_400_BAD_REQUEST)
            if not new_password:
                return Response({"status":400, "msg":"Invalid password"},status=status.HTTP_400_BAD_REQUEST)
            obj.is_verified = True
            obj.save()
            user = CustomUser.objects.filter(email=email).first()
            user.set_password(new_password)
            user.save()
            return Response({"status":200, "msg":"Password updated"},status=status.HTTP_200_OK)
        else:
            return Response({"status":400, "msg":"Invalid OTP"},status=status.HTTP_400_BAD_REQUEST)
