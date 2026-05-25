from django.conf import settings
from drf_yasg.renderers import SwaggerUIRenderer


class CustomSwaggerUIRenderer(SwaggerUIRenderer):
    def get_swagger_ui_settings(self):
        swagger_ui_settings = super().get_swagger_ui_settings()
        swagger_ui_settings["tryItOutEnabled"] = settings.SWAGGER_SETTINGS.get(
            "TRY_IT_OUT_ENABLED",
            False,
        )
        return swagger_ui_settings
