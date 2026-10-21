from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core_v2.errors import v2_exception_handler
from core_v2.throttles import V2AnonThrottle, V2UserThrottle
from organizations.permissions import IsActiveOrgMember
from users.authentication import BearerJWTAuthentication


class V2APIView(APIView):
    authentication_classes = [BearerJWTAuthentication]
    permission_classes = [IsActiveOrgMember]
    throttle_classes = [V2UserThrottle]

    def get_exception_handler(self):
        return v2_exception_handler


class V2PublicAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [V2AnonThrottle]

    def get_exception_handler(self):
        return v2_exception_handler
