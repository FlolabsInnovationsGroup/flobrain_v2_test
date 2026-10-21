from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class V2AnonThrottle(AnonRateThrottle):
    scope = "v2_anon"


class V2UserThrottle(UserRateThrottle):
    scope = "v2_user"
