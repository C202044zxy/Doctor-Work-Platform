"""T08: central role/resource/action matrix and default-protected routes."""

from copy import copy

from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute

from app.auth import CurrentUser, current_user

CLINICAL = frozenset(
    {"patient.read", "patient.write", "emr.write", "consult.write", "health.write"}
)
PERMISSIONS = {
    "junior": CLINICAL,
    "senior": CLINICAL | {"emr.review", "grant.write"},
    "admin": CLINICAL
    | {"audit.read", "audit.export", "user.manage", "template.manage", "data.all", "grant.write"},
}
# Signup and face login are reachable without a token.
#
# WARNING: /api/auth/face/login is a SIMULATION. app.face_login.match_face()
# returns True unconditionally, so any valid JPEG plus the username of an
# existing active account yields a real 2-hour token. It is listed here only so
# the demo can show the flow; never expose this route outside a local demo.
ANONYMOUS_PATHS = frozenset(
    {
        "/health",
        "/api/health",
        "/api/health/live",
        "/api/health/ready",
        "/api/auth/login",
        "/api/auth/send-code",
        "/api/auth/verify-code",
        "/api/auth/signup",
        "/api/auth/signup/verify",
        "/api/auth/face/login",
    }
)


def allows(user, permission):
    return permission in PERMISSIONS.get(user.role.name, frozenset())


def require_permission(permission):
    def dependency(user: CurrentUser):
        if not allows(user, permission):
            raise HTTPException(403, f"Missing permission: {permission}")
        return user

    return dependency


class ProtectedRoute(APIRoute):
    def __init__(self, path, endpoint, **kwargs):
        dependencies = list(kwargs.pop("dependencies", None) or [])
        if path not in ANONYMOUS_PATHS:
            permission = None
            methods = set(kwargs.get("methods") or ["GET"])
            if path.startswith(
                ("/api/patients", "/api/patient-groups", "/api/allergies", "/api/allergens")
            ):
                permission = "patient.read" if methods <= {"GET", "HEAD"} else "patient.write"
            dependencies.insert(
                0, Depends(require_permission(permission) if permission else current_user)
            )
        super().__init__(path, endpoint, dependencies=dependencies, **kwargs)


class ProtectedFastAPI(FastAPI):
    """Keep the default guard when FastAPI copies routes from included routers."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.router.route_class = ProtectedRoute

    def include_router(self, router, **kwargs):
        secured = copy(router)
        secured.routes = []
        prefix = kwargs.get("prefix", "")
        for original in router.routes:
            route = copy(original)
            if isinstance(route, APIRoute) and prefix + route.path not in ANONYMOUS_PATHS:
                route.dependencies = [Depends(current_user), *route.dependencies]
            secured.routes.append(route)
        super().include_router(secured, **kwargs)
