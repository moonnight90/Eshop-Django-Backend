from rest_framework import serializers
from .models import Products, Image, CartItem, AddressBook, Category, Reviews,Order_Item,Order,OTP, WishList
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

CustomUser = get_user_model()

class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Image
        fields = '__all__'

class CategorySerializer(serializers.ModelSerializer):
    parents = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'children', 'parents', 'products_count']

    def get_parents(self, obj):
        parents = []
        parent = obj.parent
        while parent is not None:
            parents.append({'id': parent.id, 'name': parent.name})
            parent = parent.parent
        return parents

    def get_children(self, obj):
        children = obj.children.all()
        serializer = CategorySerializer(children, many=True)
        return serializer.data
    
    def get_products_count(self, obj):
        return Products.objects.filter(category=obj).count()

class ProductSerializer(serializers.ModelSerializer):
    imgs = serializers.StringRelatedField(many=True, read_only=True)
    category = CategorySerializer()

    class Meta:
        model = Products
        # fields = "__all__"
        exclude = ['created_at', 'updated_at']

class SearchAutoCompleteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Products
        fields = ["id",'title']

class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    class Meta:
        model = CartItem
        fields = ['id','quantity', 'product']

class WishListSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)

    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Products.objects.all(),write_only=True, source="product"
    )
    class Meta:
        model = WishList
        fields = ['product',"product_id","id","user"]
        # exclude=['user']


class UserLoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField()

class UserRegistrationSerializer(serializers.ModelSerializer):
    groups = serializers.SlugRelatedField(
        many=True,
        slug_field='name',
        queryset=Group.objects.all(),
        required=False
    )
    permissions = serializers.SlugRelatedField(
        many=True,
        slug_field='codename',
        queryset=Permission.objects.all(),
        required=False
    )

    class Meta:
        model = CustomUser
        fields = ['id', 'email',  'password', 'image',  'is_staff','first_name','last_name', 'groups', 'permissions']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        groups = validated_data.pop('groups', [])
        permissions = validated_data.pop('permissions', [])
        user = CustomUser.objects.create_user(**validated_data)
        user.groups.set(groups)
        user.user_permissions.set(permissions)
        return user

class AddressBookSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddressBook
        fields = '__all__'

class UserSerializer(serializers.ModelSerializer):
    image = serializers.ImageField()

    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'image','date_joined','first_name',"last_name",'bio']

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reviews
        fields = '__all__'

class OrderItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset = Products.objects.all(), write_only=True, source='product'
    )
    class Meta:
        model = Order_Item
        fields = ['id', 'product', 'product_id', 'order', 'quantity']

class OrderSerializer(serializers.ModelSerializer):
    order_items = OrderItemSerializer(many=True, read_only=True)
    # user = UserSerializer(read_only=True)
    address = serializers.SerializerMethodField(read_only=True)
    address_id = serializers.PrimaryKeyRelatedField(
        queryset = AddressBook.objects.all(), write_only=True, source="address"
    )
    class Meta:
        model = Order
        fields = ['id','address',"address_id","status","total","created_at",'order_items','payment']
        # exclude = ['updated_at','user']
    
    def get_address(self,obj):
        return {
            "city": obj.address.city,
            "state": obj.address.state,
            "zipcode": obj.address.zipcode
        }

class OTPSerializer(serializers.ModelSerializer):
    class Meta:
        model = OTP
        fields = ['email','name',"created_at"]

class PasswordUpdateSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    
