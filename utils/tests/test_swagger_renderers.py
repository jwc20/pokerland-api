from django.test import SimpleTestCase, override_settings

from utils.custom_swaggers.renderers import CustomSwaggerUIRenderer


class CustomSwaggerUIRendererTests(SimpleTestCase):
    @override_settings(SWAGGER_SETTINGS={"TRY_IT_OUT_ENABLED": True})
    def test_try_it_out_enabled_can_be_enabled(self):
        swagger_ui_settings = CustomSwaggerUIRenderer().get_swagger_ui_settings()

        self.assertTrue(swagger_ui_settings["tryItOutEnabled"])

    @override_settings(SWAGGER_SETTINGS={})
    def test_try_it_out_enabled_defaults_to_disabled_when_unset(self):
        swagger_ui_settings = CustomSwaggerUIRenderer().get_swagger_ui_settings()

        self.assertFalse(swagger_ui_settings["tryItOutEnabled"])
