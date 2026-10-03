"""Pin one configuration snapshot through each ASGI request and background work."""
import os
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from services import runtime_settings


class RuntimeSettingsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or os.environ.get('RUNTIME_CONFIG_MODE','environment') == 'environment' or scope.get('path') in ('/healthz','/readyz','/system-status'):
            return await self.app(scope, receive, send)
        try:
            snapshot = await run_in_threadpool(runtime_settings.get_settings)
        except runtime_settings.ConfigurationUnavailable:
            return await JSONResponse({'detail':'Configuration unavailable'}, status_code=503)(scope,receive,send)
        with runtime_settings.settings_context(snapshot):
            return await self.app(scope,receive,send)
