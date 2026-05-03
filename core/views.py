import random
import json
import stripe
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter,OrderingFilter
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, BasePermission, IsAdminUser
from .serializers import ProductSerializer,CartItemSerializer,UserLoginSerializer,AddressBookSerializer,UserSerializer,ReviewSerializer,UserRegistrationSerializer,OrderItemSerializer,OrderSerializer,OTPSerializer,CategorySerializer,PasswordUpdateSerializer, WishListSerializer,SearchAutoCompleteSerializer,ImageSerializer,CategoryUploadSerializer,ProductUploadSerializer
from rest_framework import generics
from rest_framework import status
from .models import Products,Image,CartItem,Cart, AddressBook,Reviews,Order,Order_Item,Category,OTP,User_Verification_Token, WishList
from rest_framework.authtoken.models import Token
from rest_framework.authentication import authenticate
from django.contrib.auth import get_user_model
from rest_framework.parsers import MultiPartParser,FormParser
from django.db.models import Case, Value, When
from django.db import transaction, IntegrityError
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .helper import genereat_otp,send_otp
from django.utils import timezone
CustomUser = get_user_model()


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


MONEY_QUANT = Decimal("0.01")


def parse_decimal(value):
    try:
        if value is None or value == "":
            return None
        return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (TypeError, ValueError, InvalidOperation):
        return None


def money_to_cents(value):
    return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_order_items(order_items):
    normalized_items = []
    for item in order_items:
        product_id = item.get("product_id")
        quantity = parse_int(item.get("quantity"))
        item_id = item.get("item_id")
        normalized_items.append({
            "product_id": product_id,
            "quantity": quantity,
            "item_id": item_id,
        })
    return normalized_items


class OrderCreationError(Exception):
    pass


def create_order_from_payload(
    user,
    address_id,
    total,
    order_items,
    payment="COD",
    is_paid=False,
    stripe_checkout_session_id=None,
    stripe_payment_intent_id=None,
    validate_total=True,
):
    if payment not in ["COD", "Online"]:
        raise OrderCreationError("Invalid payment method.")

    total_amount = parse_decimal(total)
    if total_amount is None:
        raise OrderCreationError("Invalid total amount.")

    address = AddressBook.objects.filter(id=address_id, user=user).first()
    if not address:
        raise OrderCreationError("Invalid address.")

    normalized_items = normalize_order_items(order_items)
    if not normalized_items:
        raise OrderCreationError("No order items provided.")

    try:
        with transaction.atomic():
            order_lines = []
            calculated_total = Decimal("0.00")

            for order_item in normalized_items:
                product_id = order_item.get("product_id")
                quantity = order_item.get("quantity")
                product = Products.objects.select_for_update().filter(id=product_id).first()

                if not product:
                    raise OrderCreationError("Product Not Found...")
                if quantity is None or quantity < 1:
                    raise OrderCreationError("Invalid quantity.")
                if quantity > product.stock:
                    raise OrderCreationError(f"Insufficient stock for {product.title}.")

                line_total = (product.price * quantity).quantize(
                    MONEY_QUANT, rounding=ROUND_HALF_UP
                )
                calculated_total = (calculated_total + line_total).quantize(
                    MONEY_QUANT, rounding=ROUND_HALF_UP
                )
                order_lines.append((order_item, product, quantity))

            if validate_total and total_amount != calculated_total:
                raise OrderCreationError("Order total mismatch.")

            order = Order.objects.create(
                user=user,
                address=address,
                payment=payment,
                is_paid=is_paid,
                total=calculated_total if validate_total else total_amount,
                stripe_checkout_session_id=stripe_checkout_session_id,
                stripe_payment_intent_id=stripe_payment_intent_id,
            )

            for order_item, product, quantity in order_lines:
                Order_Item.objects.create(
                    product=product,
                    order=order,
                    quantity=quantity,
                )

                product.stock -= quantity
                product.sold += quantity
                product.save(update_fields=["stock", "sold"])

            # Clear requested items from cart (or fallback by product ids)
            cart = Cart.objects.filter(user=user).first()
            if cart:
                cart_item_ids = [v.get("item_id") for v in normalized_items if v.get("item_id")]
                if cart_item_ids:
                    CartItem.objects.filter(cart=cart, id__in=cart_item_ids).delete()
                else:
                    product_ids = [v.get("product_id") for v in normalized_items if v.get("product_id")]
                    CartItem.objects.filter(cart=cart, product_id__in=product_ids).delete()
    except IntegrityError:
        if stripe_checkout_session_id:
            existing = Order.objects.filter(
                stripe_checkout_session_id=stripe_checkout_session_id, user=user
            ).first()
            if existing:
                return existing
        raise OrderCreationError("Order already exists for this payment session.")

    return order

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
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        serializer = ProductUploadSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ImageUploadView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
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
        if not id:
            return Response({"msg":"Product id is required"},status=status.HTTP_400_BAD_REQUEST)
        obj = WishList.objects.filter(user=request.user, product_id=id)
        if obj.exists():
            return Response({"msg":"This product already in wishlist"},status=status.HTTP_200_OK)
        serializer = WishListSerializer(data={
            "product_id":request.data.get('id')
        })
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request):
        id = request.data.get('id')
        if not id:
            return Response({"msg":"Wishlist id is required",'status':400},status=status.HTTP_400_BAD_REQUEST)
        obj = WishList.objects.filter(id=id, user=request.user)
        if obj.exists():
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
        if not id:
            return Response({"error":"Id not provided"},status=status.HTTP_400_BAD_REQUEST)
        deleted,_ = CartItem.objects.filter(id=id, cart__user=request.user).delete()
        if deleted == 0:
            return Response({"error":"Product Not Found..."},status=status.HTTP_404_NOT_FOUND)
        return Response({"status":200,"success":"Product removed from cart..."},status=status.HTTP_200_OK)

    def put(self,request):
        id = request.data.get('id')
        quantity = parse_int(request.data.get('q'))
        if quantity is None or quantity < 1:
            return Response({"status":400,"error":"Invalid quantity."},status=status.HTTP_400_BAD_REQUEST)
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
        quantity = parse_int(request.data.get('q'))
        if quantity is None:
            return Response({"status":400,"error":"Invalid quantity."},status=status.HTTP_400_BAD_REQUEST)

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
            has_default = AddressBook.objects.filter(default_address=True, user=request.user).exists()
            is_default = serializer.validated_data.get("default_address", False)

            if not has_default:
                is_default = True

            if is_default:
                AddressBook.objects.filter(user=request.user).update(default_address=False)

            serializer.save(user=request.user, default_address=is_default)
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def put(self,request):
        id = request.data.get('id')
        if not id:
            return Response({"error":"Id not provided"},status=status.HTTP_400_BAD_REQUEST)
        obj = AddressBook.objects.filter(id=id, user=request.user).first()
        if not obj:
            return Response({"error":"Address not found"},status=status.HTTP_404_NOT_FOUND)
        serializer = AddressBookSerializer(obj,data=request.data,partial=True)
        if serializer.is_valid():
            if serializer.validated_data.get('default_address'):
                AddressBook.objects.filter(user=request.user).exclude(id=obj.id).update(default_address=False)
            serializer.save()
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
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
        address_id = request.data.get("address_id")
        payment = request.data.get("payment", "COD")
        total = request.data.get("total")
        order_items = request.data.get('order_items',[])
        if payment != "COD":
            return Response(
                {"error": "Use Stripe checkout endpoint for online payments."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            order = create_order_from_payload(
                user=request.user,
                address_id=address_id,
                total=total,
                order_items=order_items,
                payment="COD",
                is_paid=False,
            )
        except OrderCreationError as err:
            return Response({"error": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OrderSerializer(order).data,status=status.HTTP_201_CREATED)

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
            serializer.save()
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CategoryView(APIView):
    authentication_classes = [TokenAuthentication]

    def get_permissions(self):
        if self.request.method == 'GET':
            return []
        return [IsAuthenticated(), IsAdminUser()]

    def get(self,request):
        objs = Category.objects.all()
        serializer = CategorySerializer(objs,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)
    
    def post(self,request):
        serializer = CategoryUploadSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)


class StripeCheckoutSessionView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response(
                {"error": "Stripe is not configured on server."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        address_id = request.data.get("address_id")
        order_items = normalize_order_items(request.data.get("order_items", []))
        if not order_items:
            return Response({"error": "No order items provided."}, status=status.HTTP_400_BAD_REQUEST)
        if not AddressBook.objects.filter(id=address_id, user=request.user).exists():
            return Response({"error": "Invalid address."}, status=status.HTTP_400_BAD_REQUEST)

        stripe.api_key = settings.STRIPE_SECRET_KEY
        line_items = []
        calculated_total = Decimal("0.00")

        for item in order_items:
            product = Products.objects.filter(id=item.get("product_id")).first()
            quantity = item.get("quantity")
            if not product:
                return Response({"error": "Product Not Found..."}, status=status.HTTP_400_BAD_REQUEST)
            if quantity is None or quantity < 1:
                return Response({"error": "Invalid quantity."}, status=status.HTTP_400_BAD_REQUEST)
            if quantity > product.stock:
                return Response(
                    {"error": f"Insufficient stock for {product.title}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            unit_amount = money_to_cents(product.price)
            if unit_amount <= 0:
                return Response(
                    {"error": f"Invalid price for {product.title}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line_total = (product.price * quantity).quantize(
                MONEY_QUANT, rounding=ROUND_HALF_UP
            )
            calculated_total = (calculated_total + line_total).quantize(
                MONEY_QUANT, rounding=ROUND_HALF_UP
            )
            line_items.append(
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": product.title,
                        },
                    },
                    "quantity": quantity,
                }
            )

        frontend_url = request.headers.get("Origin") or settings.FRONTEND_URL
        metadata = {
            "user_id": str(request.user.id),
            "address_id": str(address_id),
            "total": str(calculated_total),
            "order_items": json.dumps(order_items),
        }

        try:
            checkout_session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=line_items,
                customer_email=request.user.email,
                success_url=f"{frontend_url}/order-confirm?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{frontend_url}/cart?payment_cancelled=1",
                metadata=metadata,
            )
        except Exception as err:
            return Response({"error": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "id": checkout_session.id,
                "url": checkout_session.url,
            },
            status=status.HTTP_200_OK,
        )


class StripeSessionStatusView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response(
                {"error": "Stripe is not configured on server."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response({"error": "session_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            checkout_session = stripe.checkout.Session.retrieve(
                session_id, expand=["payment_intent"]
            )
        except Exception:
            return Response({"error": "Invalid session id."}, status=status.HTTP_400_BAD_REQUEST)

        metadata = checkout_session.metadata or {}
        if str(metadata.get("user_id")) != str(request.user.id):
            return Response({"error": "Unauthorized session."}, status=status.HTTP_403_FORBIDDEN)

        existing_order = Order.objects.filter(
            user=request.user, stripe_checkout_session_id=checkout_session.id
        ).first()
        if existing_order:
            return Response(
                {
                    "order_id": existing_order.id,
                    "status": existing_order.status,
                    "is_paid": existing_order.is_paid,
                },
                status=status.HTTP_200_OK,
            )

        if checkout_session.payment_status != "paid":
            return Response(
                {"status": "pending", "is_paid": False},
                status=status.HTTP_202_ACCEPTED,
            )

        order_items = []
        try:
            order_items = json.loads(metadata.get("order_items", "[]"))
        except json.JSONDecodeError:
            return Response({"error": "Corrupted checkout metadata."}, status=status.HTTP_400_BAD_REQUEST)

        payment_intent = checkout_session.get("payment_intent")
        payment_intent_id = None
        if isinstance(payment_intent, dict):
            payment_intent_id = payment_intent.get("id")
        elif hasattr(payment_intent, "id"):
            payment_intent_id = payment_intent.id
        elif payment_intent:
            payment_intent_id = str(payment_intent)

        try:
            order = create_order_from_payload(
                user=request.user,
                address_id=metadata.get("address_id"),
                total=metadata.get("total"),
                order_items=order_items,
                payment="Online",
                is_paid=True,
                stripe_checkout_session_id=checkout_session.id,
                stripe_payment_intent_id=payment_intent_id,
                validate_total=False,
            )
        except OrderCreationError as err:
            return Response({"error": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "order_id": order.id,
                "status": order.status,
                "is_paid": order.is_paid,
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
            return Response(status=status.HTTP_200_OK)

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        stripe.api_key = settings.STRIPE_SECRET_KEY

        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event.get("type") == "checkout.session.completed":
            session = event["data"]["object"]
            metadata = session.get("metadata") or {}
            user_id = metadata.get("user_id")
            user = CustomUser.objects.filter(id=user_id).first()
            if not user:
                return Response(status=status.HTTP_200_OK)

            if Order.objects.filter(stripe_checkout_session_id=session.get("id")).exists():
                return Response(status=status.HTTP_200_OK)

            try:
                order_items = json.loads(metadata.get("order_items", "[]"))
            except json.JSONDecodeError:
                return Response(status=status.HTTP_200_OK)

            try:
                create_order_from_payload(
                    user=user,
                    address_id=metadata.get("address_id"),
                    total=metadata.get("total"),
                    order_items=order_items,
                    payment="Online",
                    is_paid=True,
                    stripe_checkout_session_id=session.get("id"),
                    stripe_payment_intent_id=session.get("payment_intent"),
                    validate_total=False,
                )
            except OrderCreationError:
                return Response(status=status.HTTP_200_OK)

        return Response(status=status.HTTP_200_OK)

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
